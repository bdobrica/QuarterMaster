"""CPU fixtures for the generic handoff; fake model bytes never demonstrate model quality."""

import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from quartermaster import exporting, muster, predictions, training, training_worker
from quartermaster.contracts.interview import VersionedAction
from quartermaster.contracts.muster import UseKnowledge
from quartermaster.contracts.prediction import (
    ImproveSelection,
    Prediction,
    PredictionJob,
    PredictionPair,
    PredictionResult,
)
from quartermaster.contracts.training import Promote, TrainingJob
from quartermaster.db import connect, migrate
from quartermaster.errors import DomainError
from quartermaster.export_package import extract_verified, verify_package
from quartermaster.holdouts import case_fingerprint
from quartermaster.inference import LocalInference
from quartermaster.prediction_context import SYSTEM, serialize
from quartermaster.prediction_jobs import verify_job
from quartermaster.projects import get_adviser
from quartermaster.standalone_runtime import create_runtime
from tests.test_muster_integration import action
from tests.test_muster_integration import collection as collection
from tests.test_training import FakeEngine

NUMBER = {"kind": "number", "unit": "EUR"}
CATEGORY = {"kind": "category", "choices": ["Consider", "Decline"]}


def setup(settings, collection, fmt=NUMBER):
    project, _, bundle = collection
    item = muster.import_collection(settings, project, bundle.digest)
    muster.use_knowledge(settings, project, item.id, UseKnowledge(expected_revision=None))
    target = (
        {"kind": "number", "value": 72000.0, "unit": "EUR"}
        if fmt == NUMBER
        else {"kind": "category", "value": "Consider"}
    )
    muster.save_decision(settings, project, item.id, "1", action(bundle, target=target))
    return project, item, target


def selection(settings, project, fmt=NUMBER):
    return ImproveSelection(
        expected_revision=get_adviser(settings.database_path, project).revision,
        answer_format=fmt,
        acknowledge_resources=True,
    )


class Adapter:
    def __init__(self, target, fail=None):
        self.target, self.fail, self.calls = target, fail, []

    async def predict(self, **kwargs):
        self.calls.append(kwargs)
        refs = json.loads(kwargs["context"])["retrieved_evidence"]
        if self.fail == "error":
            raise RuntimeError("sensitive raw content")
        return Prediction(
            behavior="answer",
            target=self.target,
            explanation="This fits the taught preference and transport policy.",
            evidence_refs=[str(uuid4())]
            if self.fail == "citation"
            else [e["citation_id"] for e in refs[:1]],
            question=None,
            limitations=[],
        )


class PredictionEngine(FakeEngine):
    def __init__(self, settings, fail=None, cancel=False):
        super().__init__((None, None, None, None, settings), fail=fail, cancel=cancel)

    def train(self, run, job):
        super().train(run, job)
        path = training.directory(self.settings, run.id) / "output/training.json"
        data = json.loads(path.read_bytes())
        data["schema_version"] = "quartermaster.training-artifacts/v2"
        path.write_text(json.dumps(data))

    def evaluate(self, run, job, suite, files):
        self.stage("evaluating")
        pairs = []
        for entry in job.examples[:5]:
            result = PredictionResult(
                prediction=entry.target, error=None, input_sha256=entry.input.input_sha256
            )
            other = (
                result.model_copy(update={"input_sha256": "0" * 64})
                if self.fail == "context"
                else result
            )
            pairs.append(
                PredictionPair(case_id=entry.case.case_id, baseline=result, candidate=other)
            )
        return pairs


@pytest.mark.parametrize("fmt", [NUMBER, CATEGORY])
@pytest.mark.parametrize("configured", [False, True])
def test_reviewed_dataset_job_ask_and_independent_export(
    client, settings, collection, tmp_path, monkeypatch, fmt, configured
):
    project, item, target = setup(settings, collection, fmt)
    if configured:
        from pydantic import TypeAdapter

        from quartermaster.contracts.answers import AnswerFormat
        from quartermaster.projects import configure_answer

        configure_answer(
            settings.database_path,
            project,
            TypeAdapter(AnswerFormat).validate_python(fmt),
            get_adviser(settings.database_path, project).revision,
        )
    previous = get_adviser(settings.database_path, project)
    endpoint = f"/api/projects/{project}/muster/{item.id}/improve"
    response = client.post(endpoint, json=selection(settings, project, fmt).model_dump(mode="json"))
    assert response.status_code == 200, response.text
    run = training.get_run(settings, project, response.json()["id"])
    job = training.read_job(settings, run)
    assert job.schema_version == "quartermaster.training-job/v2"
    assert job.adviser.outputs == "quartermaster.prediction/v1"
    assert job.baseline == previous.model
    assert job.examples[0].target.target.model_dump() == target
    assert "price" not in job.examples[0].case.situation
    assert "observed_outcome" not in job.examples[0].input.context
    with pytest.raises(ValidationError):
        TrainingJob.model_validate_json(job.model_dump_json())
    raw = (training.directory(settings, run.id) / "input/train.jsonl").read_bytes()
    assert verify_job(job, raw) == job
    from quartermaster.prediction_context import system_for

    assert json.loads(raw)["messages"][0]["content"] == system_for(job.examples[0].input.context)
    assert job.examples[0].input.prompt_version == ("context/v5" if configured else "context/v4")
    if not configured:
        assert job.examples[0].input.system == SYSTEM
    assert json.loads(raw)["messages"][1]["content"] == job.examples[0].input.context
    assert "OWNER_REVIEWED" not in raw.decode()
    assert get_adviser(settings.database_path, project) == previous
    assert client.get(f"/api/projects/{project}/training-runs/{run.id}/job").status_code == 200
    assert client.get(f"/api/projects/{project}/training-runs/{run.id}/dataset").content == raw

    # The public trainer consumer independently reconstructs rows without importing app services.
    trainer = Path(__file__).parents[1] / "trainer"
    monkeypatch.syspath_prepend(str(trainer))
    spec = importlib.util.spec_from_file_location("generic_job_worker", trainer / "job_worker.py")
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    root = training.directory(settings, run.id) / "input"
    worker.Path = lambda value: root / value.removeprefix("/input/")
    loaded, rows = worker.load_job()
    assert loaded == job and rows[0].messages[1]["content"] == job.examples[0].input.context

    adapter = Adapter(target)
    client.app.state.inference = adapter
    request = {"situation": "A new place with convenient transport.", "answer_format": fmt}
    answer = client.post(f"/api/projects/{project}/predictions", json=request)
    assert answer.status_code == 200, answer.text
    assert answer.json()["result"]["prediction"]["target"] == target
    assert adapter.calls[0]["system"] == job.examples[0].input.system
    assert adapter.calls[0]["parameters"] == job.examples[0].input.parameters

    result = training_worker.execute_next(settings, PredictionEngine(settings))
    assert result.status == "completed", result.error
    version = training.get_version(settings, project, result.candidate_id)
    assert version.comparison_kind == "taught_preference_consistency"
    assert version.baseline == previous.model
    assert client.get(f"/api/projects/{project}/adviser-versions").status_code == 200
    assert client.get(f"/projects/{project}/train").status_code == 200
    assert client.get(f"/projects/{project}/ask").status_code == 200
    assert get_adviser(settings.database_path, project).model == previous.model

    selected = training.promote(
        settings,
        project,
        version.id,
        Promote(expected_revision=previous.revision, acknowledge_regressions=True),
    )
    assert selected.knowledge_revision == previous.knowledge_revision
    assert selected.outputs == "quartermaster.prediction/v1"
    # Selected candidates go through their verified runtime alias, with the generic schema.
    payloads = []

    async def completion(self, system, context, parameters, schema):
        payloads.append((self.alias, self.base_url, system, schema))
        return (
            await adapter.predict(system=system, context=context, parameters=parameters)
        ).model_dump_json(), None

    monkeypatch.setattr(LocalInference, "_completion", completion)
    assert (
        client.post(f"/api/projects/{project}/predictions", json=request).json()["result"]["error"]
        is None
    )
    assert payloads[-1][0] == f"qm-candidate-{version.model_sha256}"

    settings.export_runtime_image = "sha256:" + "c" * 64
    response = client.post(
        f"/api/projects/{project}/exports",
        json={"candidate_id": str(version.id), "acknowledge_contents": True},
    )
    assert response.status_code == 201, response.text
    archive = exporting.archive_path(settings, project, response.json()["id"])
    root = tmp_path / "fresh-export"
    manifest, config, _, reference = extract_verified(archive, root)
    assert manifest.schema_version == "quartermaster.export/v4"
    assert manifest.teaching_sha256 == job.teaching_sha256
    assert config.answer_format == job.answer_format
    verify_package(root)
    # Empty/absent builder storage cannot affect a fresh extracted package.
    monkeypatch.setenv("QM_BUILDER_API_KEY", "must-not-use")
    monkeypatch.setenv("QM_DATA_DIR", str(tmp_path / "absent-builder"))
    with TestClient(create_runtime(root, inference=adapter, launch_engine=False)) as runtime:
        reply = runtime.post("/v1/advise", json=reference.case.model_dump(mode="json"))
        assert reply.status_code == 200, reply.text
        assert reply.json()["prediction"]["target"] == target
        assert reply.json()["context_sha256"] == reference.context_sha256
        assert adapter.calls[-1]["context"] == job.examples[0].input.context
        assert (
            runtime.post(
                "/advise", data={"situation": "A new case"}, headers={"origin": "http://testserver"}
            ).status_code
            == 200
        )
    assert not list(root.rglob("*.sqlite3"))


@pytest.mark.parametrize(
    "failure", ["training", "manifest", "converting", "evaluating", "context", "cancel"]
)
def test_durable_failure_no_promotion_or_retry(client, settings, collection, failure):
    project, item, _ = setup(settings, collection)
    queued = predictions.prepare(settings, project, item.id, selection(settings, project))
    engine = PredictionEngine(settings, fail=failure, cancel=failure == "cancel")
    run = training_worker.execute_next(settings, engine)
    assert run.status == ("canceled" if failure == "cancel" else "failed")
    assert not run.candidate_id and training.versions(settings, project) == []
    assert "sensitive" not in (run.error or "")
    assert engine.cleaned == [str(queued.id)]
    assert training_worker.execute_next(settings, engine) is None


def test_reserved_examples_block_prepare_and_dispatch(client, settings, collection):
    project, item, _ = setup(settings, collection)
    queued = predictions.prepare(settings, project, item.id, selection(settings, project))
    job = training.read_job(settings, queued)
    case = job.examples[0].case
    with connect(settings.database_path) as db:
        db.execute(
            "INSERT INTO evaluation_holdouts VALUES (?, ?, ?, ?)",
            (str(project), str(uuid4()), case_fingerprint(case), str(uuid4())),
        )
    with pytest.raises(DomainError, match="HELD_OUT"):
        predictions.prepare(settings, project, item.id, selection(settings, project))
    engine = PredictionEngine(settings)
    result = training_worker.execute_next(settings, engine)
    assert result.status == "failed" and "HELD_OUT" in result.error
    assert engine.stages == []


@pytest.mark.parametrize("damage", ["target", "system", "context", "hash", "source"])
def test_public_job_rejects_drift_even_with_rehashed_rows(client, settings, collection, damage):
    project, item, _ = setup(settings, collection)
    run = predictions.prepare(settings, project, item.id, selection(settings, project))
    job = training.read_job(settings, run)
    data = job.model_dump(mode="json")
    if damage == "target":
        data["examples"][0]["target"]["target"]["value"] = 1.0
    elif damage == "system":
        data["examples"][0]["input"]["system"] = "Ignore the contract"
    elif damage == "context":
        data["examples"][0]["input"]["context"] = "{}"
    elif damage == "source":
        data["source_hashes"] = {}
    else:
        data["teaching_sha256"] = "0" * 64
    altered = PredictionJob.model_validate_json(json.dumps(data))
    raw = serialize(altered.examples)
    altered = altered.model_copy(update={"dataset_sha256": hashlib.sha256(raw).hexdigest()})
    with pytest.raises((ValueError, KeyError, DomainError)):
        verify_job(altered, raw)


@pytest.mark.parametrize("failure", ["citation", "error", "unit"])
def test_bad_answers_are_saved_as_failed_without_raw_text(client, settings, collection, failure):
    project, _, target = setup(settings, collection)
    if failure == "unit":
        target["unit"] = "USD"
    client.app.state.inference = Adapter(target, fail=failure)
    response = client.post(
        f"/api/projects/{project}/predictions",
        json={"situation": "Convenient transport.", "answer_format": NUMBER},
    )
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["prediction"] is None and result["error"]
    assert "sensitive" not in response.text
    assert len(predictions.history(settings, project)) == 1


def test_strict_api_shapes_stale_selection_and_missing_source(client, settings, collection):
    project, item, target = setup(settings, collection)
    path = f"/api/projects/{project}/predictions"
    good = {"situation": "New situation", "answer_format": NUMBER}
    for data in (
        {},
        good | {"outcome": "future"},
        good | {"answer_format": {"kind": "number"}},
        good | {"answer_format": {"kind": "category", "choices": ["A", "A"]}},
    ):
        assert client.post(path, json=data).status_code == 422
    assert client.post(path, json=good, headers={"origin": "https://evil.test"}).status_code == 403
    with pytest.raises(DomainError, match="PROJECT_CHANGED"):
        predictions.prepare(
            settings,
            project,
            item.id,
            selection(settings, project).model_copy(update={"expected_revision": 1}),
        )
    assert client.get(f"/projects/{project}/teach/{item.id}").status_code == 200
    assert client.get(f"/projects/{project}/ask").status_code == 200
    assert client.post(f"/projects/{project}/ask", data={"situation": "X"}).status_code == 403
    # Missing bytes fail before model content can be sent.
    client.app.state.inference = Adapter(target)
    with connect(settings.database_path) as db:
        row = db.execute("SELECT document FROM sources").fetchone()
    from quartermaster.contracts.sources import Source
    from quartermaster.sources import blob_path

    source = Source.model_validate_json(row[0])
    # Resolve the retained bytes using the established storage helper.
    path = blob_path(settings.artifact_root, source.sha256)
    path.unlink()
    assert client.post(f"/api/projects/{project}/predictions", json=good).status_code >= 400
    assert client.app.state.inference.calls == []


def test_prediction_clarify_abstain_and_estimates_are_explicit():
    base = dict(
        behavior="clarify",
        target=None,
        explanation="Missing travel time.",
        evidence_refs=[],
        question="How long is the trip?",
        limitations=[],
    )
    assert Prediction(**base).target is None
    assert Prediction(**(base | {"behavior": "abstain", "question": None})).target is None
    for data in (
        base | {"target": {"kind": "number", "value": 1.0, "unit": "EUR"}},
        base | {"question": None},
        base | {"estimated_probabilities": {"A": float("nan")}},
    ):
        with pytest.raises(ValidationError):
            Prediction(**data)


def test_v10_migration_preserves_populated_documents(client, settings, collection):
    project, item, _ = setup(settings, collection)
    run = predictions.prepare(settings, project, item.id, selection(settings, project))
    job_hash = training.hash_file(training.directory(settings, run.id) / "input/job.json")
    with connect(settings.database_path) as db:
        tables = [
            r[0]
            for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name != 'prediction_runs'"
            )
        ]
        before = {t: [tuple(r) for r in db.execute(f'SELECT * FROM "{t}"')] for t in tables}
        db.execute("DROP TABLE prediction_runs")
        db.execute("PRAGMA user_version=10")
    migrate(settings.database_path)
    with connect(settings.database_path) as db:
        assert before == {t: [tuple(r) for r in db.execute(f'SELECT * FROM "{t}"')] for t in tables}
    assert training.hash_file(training.directory(settings, run.id) / "input/job.json") == job_hash


def test_second_candidate_compares_selected_model_and_can_reselect_prior(
    client, settings, collection, monkeypatch
):
    project, item, target = setup(settings, collection)
    first = predictions.prepare(settings, project, item.id, selection(settings, project))
    completed = training_worker.execute_next(settings, PredictionEngine(settings))
    version = training.get_version(settings, project, completed.candidate_id)
    current = get_adviser(settings.database_path, project)
    current = training.promote(
        settings,
        project,
        version.id,
        Promote(expected_revision=current.revision, acknowledge_regressions=True),
    )
    second = predictions.prepare(settings, project, item.id, selection(settings, project))
    job = training.read_job(settings, second)
    assert job.baseline.adapter_artifact == version.id
    assert job.model.adapter_artifact is None  # Train from the pinned base, no implicit stacking.
    engine = training_worker.DockerEngine(
        settings, settings.data_dir, settings.data_dir, "sha256:" + "a" * 64, "sha256:" + "b" * 64
    )
    engine.base_record = {"sha256": "c" * 64}
    commands, calls = [], []

    def command(args, *rest):
        commands.append(args)
        return ""

    engine.command = command
    monkeypatch.setattr(
        training_worker.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0)
    )

    async def predict(self, **kwargs):
        calls.append((self.alias, kwargs))
        return await Adapter(target).predict(**kwargs)

    monkeypatch.setattr(training_worker.DockerInference, "predict", predict)
    with connect(settings.database_path) as db:
        active = training.update_run(db, second, status="evaluating")
    files = {"model_sha256": "d" * 64}
    pairs = asyncio.run(engine.compare(active, job, files))
    assert pairs[0].baseline.input_sha256 == pairs[0].candidate.input_sha256
    assert calls[0][0] == f"qm-candidate-{version.model_sha256}"
    assert calls[0][1] == calls[1][1]
    baseline_mount = next(c for c in commands if "run" in c and "baseline" in " ".join(c))
    assert any(
        f"training/{first.id}/output/portable,dst=/model,readonly" in part
        for part in baseline_mount
    )
    assert "--network=none" in baseline_mount and "--gpus" not in baseline_mount
    # Rejecting/retaining a candidate never changes the selected model or active knowledge.
    assert get_adviser(settings.database_path, project) == current
    base = training.retain_base(
        settings, project, VersionedAction(expected_revision=current.revision)
    )
    restored = training.promote(
        settings,
        project,
        version.id,
        Promote(expected_revision=base.revision, acknowledge_regressions=True),
    )
    assert restored.knowledge_revision == current.knowledge_revision
    assert restored.model == current.model
    assert training.read_job(settings, first).teaching == job.teaching


@pytest.mark.parametrize(
    "failure", [None, "model", "length", "duplicate", "extra", "choice", "citation"]
)
def test_local_prediction_wire_validation_is_shared_and_bounded(
    client, settings, collection, failure
):
    project, item, target = setup(settings, collection, CATEGORY)
    run = predictions.prepare(settings, project, item.id, selection(settings, project, CATEGORY))
    snapshot = training.read_job(settings, run).examples[0].input
    draft = asyncio.run(
        Adapter(target).predict(
            system=snapshot.system, context=snapshot.context, parameters=snapshot.parameters
        )
    )
    calls = []

    def serve(request):
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": "alias"}]})
        body = json.loads(request.content)
        calls.append(body)
        data = draft.model_dump(mode="json")
        if failure == "extra":
            data["raw_reasoning"] = "hidden"
        elif failure == "choice":
            data["target"]["value"] = "Not an available choice"
        elif failure == "citation":
            data["evidence_refs"] = [str(uuid4())]
        text = json.dumps(data)
        if failure == "duplicate":
            text = '{"behavior":"abstain",' + text[1:]
        return httpx.Response(
            200,
            json={
                "model": "wrong" if failure == "model" else "alias",
                "choices": [
                    {
                        "finish_reason": "length" if failure == "length" else "stop",
                        "message": {"content": text},
                    }
                ],
            },
        )

    adapter = LocalInference(
        settings,
        alias="alias",
        base_url="http://127.0.0.1:8080/v1",
        transport=httpx.MockTransport(serve),
    )
    result = asyncio.run(predictions.generate(adapter, snapshot))
    assert (result.error is None) == (failure is None)
    assert len(calls) == 1
    assert calls[0]["response_format"]["json_schema"]["schema"] == snapshot.response_schema
    assert calls[0]["max_tokens"] == snapshot.parameters["max_tokens"]
    assert calls[0]["chat_template_kwargs"] == {"enable_thinking": False}


def test_generic_export_runtime_has_no_builder_imports(tmp_path):
    # Run the dependency closure with only the files copied by standalone-runtime.
    import shutil
    import subprocess
    import sys

    root = Path(__file__).parents[1]
    package = tmp_path / "quartermaster"
    package.mkdir()
    names = (
        "__init__.py",
        "advice_context.py",
        "config.py",
        "errors.py",
        "export_package.py",
        "inference.py",
        "generation.py",
        "prediction_context.py",
        "standalone_runtime.py",
    )
    for name in names:
        shutil.copyfile(root / "quartermaster" / name, package / name)
    shutil.copytree(
        root / "quartermaster/contracts",
        package / "contracts",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    (package / "spike").mkdir()
    for name in ("__init__.py", "spec.py"):
        shutil.copyfile(root / "quartermaster/spike" / name, package / "spike" / name)
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]); "
        "import quartermaster.standalone_runtime; import importlib.util; "
        "assert all(importlib.util.find_spec('quartermaster.'+n) is None "
        "for n in ('db','builder','training','app','muster'))"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", code, str(tmp_path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr


def test_small_taught_replay_and_knowledge_version_separation(client, settings, project_fixture):
    from muster.knowledge import save_article
    from muster.publication import get_publication, overview, publish
    from muster.review import get_review, save_review
    from quartermaster.contracts.muster import DecisionInput
    from quartermaster.contracts.sources import KnowledgeSelection, ParseOptions
    from quartermaster.knowledge import revise_knowledge
    from quartermaster.muster_bundle import load_bundle
    from quartermaster.sources import upload_source
    from tests.muster.test_publication import reviewed

    project = client.post("/api/projects", json=project_fixture).json()["id"]
    root = settings.muster_storage
    cid = reviewed(root, 3)
    for index in range(1, 4):
        review = get_review(root, cid, index)
        save_review(
            root,
            cid,
            index,
            review["revision"],
            review["values"] | {"year": 1980 + index * 10},
            "Checked year",
            "review_next",
        )
    save_article(root, cid, None, 0, "Policy", "Prefer convenient transport.")
    pid = publish(root, cid, overview(root, cid)["fingerprint"])
    bundle = load_bundle(root / get_publication(root, cid, pid)["path"])
    item = muster.import_collection(settings, project, bundle.digest)
    muster.use_knowledge(settings, project, item.id, UseKnowledge(expected_revision=None))
    for index, record in enumerate(bundle.examples):
        muster.save_decision(
            settings,
            project,
            item.id,
            record["id"],
            DecisionInput(
                expected_revision=0,
                input_fields=[key for key in record["values"] if key != "price"],
                inputs_available_at_decision=True,
                target={"kind": "number", "value": float(70000 + index * 1000), "unit": "EUR"},
                reasoning=f"Personal judgment for example {index + 1}.",
            ),
        )
    queued = predictions.prepare(settings, project, item.id, selection(settings, project))
    frozen = training.read_job(settings, queued)
    old_knowledge = get_adviser(settings.database_path, project).knowledge_revision
    new_source = upload_source(
        settings, project, "new.md", b"Prefer quiet surroundings.", "knowledge", ParseOptions()
    )
    revise_knowledge(
        settings,
        project,
        KnowledgeSelection(source_ids=[new_source.id], expected_revision=old_knowledge),
    )
    completed = training_worker.execute_next(settings, PredictionEngine(settings))
    assert completed.status == "completed", completed.error
    version = training.get_version(settings, project, completed.candidate_id)
    assert len(version.comparisons) == 3
    assert [p.candidate.prediction.target for p in version.comparisons] == [
        e.target.target for e in frozen.examples
    ]
    assert all("convenient transport" in e.input.context for e in frozen.examples)
    assert training.read_job(settings, queued) == frozen
    adapter = Adapter({"kind": "number", "value": 73000.0, "unit": "EUR"})
    client.app.state.inference = adapter
    reply = client.post(
        f"/api/projects/{project}/predictions",
        json={"situation": "New place", "answer_format": NUMBER},
    )
    assert reply.json()["result"]["error"] is None
    assert "quiet surroundings" in adapter.calls[0]["context"]
    assert "convenient transport" not in adapter.calls[0]["context"]
    assert get_adviser(settings.database_path, project).model.adapter_artifact is None
    assert len(training.runs(settings, project)) == 1
    # Identical selected situations must be resolved explicitly, not trained as conflicting targets.
    for record in bundle.examples[:2]:
        muster.save_decision(
            settings,
            project,
            item.id,
            record["id"],
            DecisionInput(
                expected_revision=1,
                input_fields=["currency"],
                inputs_available_at_decision=True,
                target={"kind": "number", "value": 50000.0, "unit": "EUR"},
                reasoning="Same visible details.",
            ),
        )
    with pytest.raises(DomainError, match="TEACHING_DUPLICATE"):
        predictions.prepare(settings, project, item.id, selection(settings, project))


def test_cleanup_failure_blocks_promotion(client, settings, collection):
    project, item, _ = setup(settings, collection)
    predictions.prepare(settings, project, item.id, selection(settings, project))
    engine = PredictionEngine(settings)

    def fail(run):
        raise RuntimeError("cleanup unavailable")

    engine.cleanup = fail
    result = training_worker.execute_next(settings, engine)
    assert result.status == "cleanup_required" and result.candidate_id is None
    version = training.versions(settings, project)[0]
    with pytest.raises(DomainError, match="CANDIDATE_UNSAFE"):
        training.promote(
            settings,
            project,
            version.id,
            Promote(
                expected_revision=get_adviser(settings.database_path, project).revision,
                acknowledge_regressions=True,
            ),
        )


def test_oversized_teaching_dataset_is_actionable_and_never_queued(
    client, settings, collection, monkeypatch, tmp_path
):
    project, item, _ = setup(settings, collection)
    sha, path = muster.freeze_teaching(settings, project, item.id)
    data = json.loads(path.read_bytes())
    data["examples"] *= 101
    oversized = tmp_path / "oversized.json"
    oversized.write_text(json.dumps(data))
    monkeypatch.setattr(muster, "freeze_teaching", lambda *args: (sha, oversized))
    reply = client.post(
        f"/api/projects/{project}/muster/{item.id}/improve",
        json=selection(settings, project).model_dump(mode="json"),
    )
    assert reply.status_code == 409 and "100 reviewed answers" in reply.text
    assert "owner_decision" not in reply.text
    assert training.runs(settings, project) == []
