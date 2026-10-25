"""Offline review/queue/artifact checks. Synthetic fixtures are never training approval."""

import asyncio
import hashlib
import json
import struct
from uuid import uuid4

import pytest

from quartermaster import evaluations, training, training_worker
from quartermaster.candidate_runtime import verify as verify_runtime
from quartermaster.contracts.interview import VersionedAction
from quartermaster.contracts.training import CandidatePair, ExampleProposal, TrainingManifest
from quartermaster.db import SCHEMA_VERSION, connect, migrate
from quartermaster.errors import DomainError
from quartermaster.holdouts import near_duplicate
from quartermaster.training_artifacts import verify_adapter, verify_candidate
from tests import test_evaluations, test_teaching
from tests.test_evaluations import create, freeze, save
from tests.test_teaching import ask, base, correct, draft, prepare, review, send

workshop = test_teaching.workshop


def example_path(workshop, example, suffix=""):
    return base(workshop[1]) + f"/training-examples/{example['id']}" + suffix


def new_example(workshop, situation="Mixer inspection is current; damage status is unknown."):
    lesson = correct(workshop, ask(workshop, situation))
    lesson = review(workshop, send(workshop, prepare(workshop, lesson)))
    response = workshop[0].post(
        base(workshop[1]) + f"/lessons/{lesson['id']}/training-example",
        json={"expected_revision": lesson["revision"]},
    )
    assert response.status_code == 200, response.text
    return response.json()


def set_target(workshop, example, target=None):
    response = workshop[0].post(
        example_path(workshop, example, "/target"),
        json={
            "expected_revision": example["revision"],
            "target": (
                target
                or draft(question="Is any damage reported?", missing=["reported damage status"])
            ).model_dump(mode="json"),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def approve(workshop, example):
    response = workshop[0].post(
        example_path(workshop, example, "/review"),
        json={"expected_revision": example["revision"], "action": "approve"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def queue(workshop, examples=None, suite=None, preset="quick", expected=200):
    if examples is None:
        examples = [approve(workshop, set_target(workshop, new_example(workshop)))]
    suite = suite or freeze(workshop, save(workshop, create(workshop)))
    response = workshop[0].post(
        base(workshop[1]) + "/training-runs",
        json={
            "example_ids": [e["id"] for e in examples],
            "suite_id": suite["id"],
            "suite_revision": suite["revision"],
            "preset": preset,
            "acknowledge_small_data": True,
        },
    )
    assert response.status_code == expected, response.text
    return response.json()


def job(workshop, run):
    return training.read_job(workshop[4], training.get_run(workshop[4], workshop[1], run["id"]))


class FakeEngine:
    def __init__(self, workshop, fail=None, cancel=False):
        self.workshop = workshop
        self.settings = workshop[4]
        self.fail, self.cancel = fail, cancel
        self.stages, self.cleaned = [], []

    def stage(self, name):
        self.stages.append(name)
        if self.fail == name:
            raise RuntimeError("private case and credential must not appear")

    def preflight(self, run, job):
        self.stage("preflight")
        return {"trainer_image_id": "a" * 64, "runtime_image_id": "b" * 64}

    def train(self, run, job):
        self.stage("training")
        output = training.directory(self.settings, run.id) / "output"
        adapter = output / "adapter"
        adapter.mkdir()
        config = {
            "base_model_name_or_path": job.model.base_model_id,
            "revision": job.model.base_revision,
            "peft_type": "LORA",
            "task_type": "CAUSAL_LM",
            "r": 4,
            "lora_alpha": 8,
            "target_modules": ["q_proj", "v_proj"],
        }
        (adapter / "adapter_config.json").write_text(json.dumps(config))
        header = json.dumps(
            {
                "base.q_proj.lora_A.weight": {
                    "dtype": "F32",
                    "shape": [4, 4],
                    "data_offsets": [0, 64],
                },
                "base.q_proj.lora_B.weight": {
                    "dtype": "F32",
                    "shape": [4, 4],
                    "data_offsets": [64, 128],
                },
            }
        ).encode()
        (adapter / "adapter_model.safetensors").write_bytes(
            len(header).to_bytes(8, "little") + header + struct.pack("<32f", *([0.01] * 32))
        )
        manifest = TrainingManifest(
            job_id=job.id,
            job_sha256=run.job_sha256,
            dataset_sha256=job.dataset_sha256,
            model=job.model,
            recipe=job.recipe,
            completed_steps=job.recipe.steps,
            training_loss=1.0,
            files={
                p.name: {"sha256": training.hash_file(p), "size_bytes": p.stat().st_size}
                for p in adapter.iterdir()
            },
        )
        (output / "training.json").write_text(manifest.model_dump_json())
        if self.cancel:
            latest = training.get_run(self.settings, run.project_id, run.id)
            training.cancel(
                self.settings,
                run.project_id,
                run.id,
                VersionedAction(expected_revision=latest.revision),
            )
        if self.fail == "manifest":
            (adapter / "adapter_model.safetensors").write_bytes(b"corrupt")

    def convert(self, run, job):
        self.stage("converting")
        portable = training.directory(self.settings, run.id) / "output/portable"
        # Deliberately fake format bytes for failure-path tests, never a real model.
        (portable / "model.gguf").write_bytes(b"GGUF\x03\x00\x00\x00" + b"x" * 1_000_000)
        (portable / "LICENSE.model").write_text("Synthetic test license")

    def evaluate(self, run, job, suite, files):
        self.stage("evaluating")

        async def outputs():
            pairs = []
            for entry, pair in zip(suite.cases, suite.inputs, strict=True):
                a = await evaluations.evaluate_output(
                    self.settings, self.workshop[2], run.project_id, entry, pair.b
                )
                b = await evaluations.evaluate_output(
                    self.settings, self.workshop[2], run.project_id, entry, pair.b
                )
                pairs.append(CandidatePair(case_id=entry.id, baseline=a, candidate=b))
            return pairs

        result = asyncio.run(outputs())
        if self.fail == "context":
            result[0] = CandidatePair.model_validate(
                {
                    **result[0].model_dump(),
                    "candidate": {**result[0].candidate.model_dump(), "input_sha256": "0" * 64},
                }
            )
        return result

    def cleanup(self, run):
        self.cleaned.append(str(run.id))


def test_owner_review_freeze_run_rate_promote_and_retain_base(workshop):
    client, project, inference, _, config = workshop
    example = new_example(workshop)
    assert example["origin"] == "OWNER_DRAFT" and example["target"] is None
    example = set_target(workshop, example)
    draft_revision = example.copy()
    before = client.get(base(project)).json()
    example = approve(workshop, example)
    assert example["status"] == "approved" and example["revision"] == draft_revision["revision"] + 2
    assert (
        client.get(
            example_path(workshop, example), params={"revision": draft_revision["revision"]}
        ).json()
        == draft_revision
    )
    assert client.get(base(project)).json() == before
    run = queue(workshop, [example])
    frozen = job(workshop, run)
    assert frozen.recipe.steps == 12 and frozen.recipe.seconds == 1200
    assert frozen.examples[0].lesson.status == "applied"
    assert frozen.holdout_ids and frozen.suite_sha256
    data = client.get(base(project) + f"/training-runs/{run['id']}/dataset").content
    assert hashlib.sha256(data).hexdigest() == run["dataset_sha256"]
    assert "observed_outcome" not in json.loads(data)["messages"][1]["content"]
    assert json.loads(data)["id"] == example["id"]
    inference.calls.clear()
    engine = FakeEngine(workshop)
    completed = training_worker.execute_next(config, engine)
    assert completed.status == "completed" and engine.cleaned == [run["id"]]
    assert engine.stages == ["preflight", "training", "converting", "evaluating"]
    assert inference.calls[0] == inference.calls[1]
    assert client.get(base(project)).json() == before
    candidates = client.get(base(project) + "/adviser-versions").json()
    candidate = candidates[0]
    path = base(project) + f"/adviser-versions/{candidate['id']}"
    suite_case = candidate["comparisons"][0]["case_id"]
    rating = {
        "expected_revision": 0,
        "preference": "a_better",
        "category": "should_ask",
        "rationale": "  Prefer A. No observed business outcome.\n  ",
    }
    assert (
        client.post(path + f"/ratings/{suite_case}", json=rating).json()["rationale"]
        == rating["rationale"]
    )
    assert client.post(path + f"/ratings/{suite_case}", json=rating).status_code == 409
    page = client.get(f"/projects/{project}/train")
    assert page.status_code == 200, page.text
    assert "0 improved · 1 regressed" in page.text
    assert "AI drafts require your review" not in page.text  # approved example is immutable
    assert "full written rubric" in page.text and "automatic retry" in page.text
    assert (
        client.post(path + "/promote", json={"expected_revision": before["revision"]}).status_code
        == 422
    )
    promoted = client.post(
        path + "/promote",
        json={"expected_revision": before["revision"], "acknowledge_regressions": True},
    ).json()
    assert promoted["model"]["adapter_artifact"] == candidate["id"]
    assert promoted["knowledge_revision"] == before["knowledge_revision"]
    retained = client.post(
        base(project) + "/retain-base", json={"expected_revision": promoted["revision"]}
    ).json()
    assert retained["model"]["adapter_artifact"] is None
    assert client.get(path).json() == candidate
    assert training_worker.execute_next(config, engine) is None


@pytest.mark.parametrize("status", ["draft", "prepared", "rejected"])
def test_unreviewed_examples_cannot_freeze(workshop, status):
    example = set_target(workshop, new_example(workshop))
    config = workshop[4]
    if status != "draft":
        with connect(config.database_path) as connection:
            record = training.get_example(config, workshop[1], example["id"])
            example = training.append_example(connection, record, status=status).model_dump(
                mode="json"
            )
    response = queue(workshop, [example], expected=409)
    assert "TRAINING_REVIEW" in response["detail"]
    assert training.runs(config, workshop[1]) == []


def test_target_integrity_and_rejection_leave_active_unchanged(workshop):
    client, project, *_, config = workshop
    example = new_example(workshop)
    before = client.get(base(project)).json()
    bad = draft(quotes=["Invented decisive fact"])
    response = client.post(
        example_path(workshop, example, "/target"),
        json={"expected_revision": example["revision"], "target": bad.model_dump(mode="json")},
    )
    assert response.status_code == 422 and "ADVICE_SUPPORT" in response.text
    assert training.get_example(config, project, example["id"]).revision == example["revision"]
    response = client.post(
        example_path(workshop, example, "/review"),
        json={"expected_revision": example["revision"], "action": "reject"},
    )
    assert response.json()["status"] == "rejected"
    assert client.get(base(project)).json() == before


def test_exact_and_near_duplicates_do_not_enter_same_dataset(workshop):
    first = approve(workshop, set_target(workshop, new_example(workshop)))
    second = approve(
        workshop,
        set_target(
            workshop,
            new_example(workshop, "Mixer inspection is current; damage status is unknown today."),
        ),
    )
    suite = freeze(workshop, save(workshop, create(workshop)))
    assert "TRAINING_DUPLICATE" in queue(workshop, [first, second], suite, expected=409)["detail"]
    assert "TRAINING_DUPLICATE" in queue(workshop, [first, first], suite, expected=422)["detail"]


def test_holdouts_block_selection_synthetic_disclosure_and_dispatch(workshop):
    client, project, *_, config = workshop
    example = approve(workshop, set_target(workshop, new_example(workshop)))
    run = queue(workshop, [example])
    with connect(config.database_path) as connection:
        connection.execute(
            "INSERT INTO evaluation_holdouts VALUES (?,?,?,?)",
            (project, example["case"]["case_id"], "c" * 64, str(uuid4())),
        )
    assert "EVALUATION_HELD_OUT" in queue(workshop, [example], expected=409)["detail"]
    response = client.post(
        example_path(workshop, example, "/prepare"), json={"expected_revision": example["revision"]}
    )
    assert response.status_code == 409 and "EVALUATION_HELD_OUT" in response.text
    engine = FakeEngine(workshop)
    failed = training_worker.execute_next(config, engine)
    assert failed.status == "failed" and engine.stages == []
    assert "EVALUATION_HELD_OUT" in failed.error
    assert training.get_run(config, project, run["id"]).candidate_id is None


def test_new_holdout_cannot_copy_taught_or_synthetic_training_case(workshop):
    example = new_example(workshop)
    suite = create(workshop)
    copied = ask(workshop, example["case"]["situation"] + " Today.")
    response = workshop[0].post(
        test_evaluations.suite_path(workshop, suite, "cases"),
        json={
            "expected_revision": suite["revision"],
            "test_id": copied["id"],
            "rubric": {"expected_behavior": "clarify", "expectation": "Ask for damage."},
        },
    )
    assert response.status_code == 409 and "EVALUATION_TAUGHT" in response.text


@pytest.mark.parametrize(
    "stage", ["preflight", "training", "manifest", "converting", "evaluating", "context"]
)
def test_failure_is_durable_sanitized_and_never_deployable(workshop, stage):
    client, project, *_, config = workshop
    queued = queue(workshop)
    before = client.get(base(project)).json()
    engine = FakeEngine(workshop, fail=stage)
    failed = training_worker.execute_next(config, engine)
    assert failed.status == "failed" and failed.candidate_id is None
    assert "private case" not in failed.model_dump_json()
    assert training.versions(config, project) == []
    assert engine.cleaned == [queued["id"]]
    assert client.get(base(project)).json() == before
    assert training_worker.execute_next(config, engine) is None


def test_queued_and_running_cancellation(workshop):
    client, project, *_, config = workshop
    first = queue(workshop)
    response = client.post(
        base(project) + f"/training-runs/{first['id']}/cancel",
        json={"expected_revision": first["revision"]},
    )
    assert response.json()["status"] == "canceled"
    assert training_worker.execute_next(config, FakeEngine(workshop)) is None
    second = queue(workshop)
    engine = FakeEngine(workshop, cancel=True)
    canceled = training_worker.execute_next(config, engine)
    assert str(canceled.id) == second["id"] and canceled.status == "canceled"
    assert canceled.cancel_requested and canceled.candidate_id is None
    assert "converting" not in engine.stages
    assert training.versions(config, project) == []


def test_worker_restart_stops_orphans_and_does_not_retrain(workshop):
    config = workshop[4]
    queued = queue(workshop)
    claimed = training_worker.claim(config)
    assert str(claimed.id) == queued["id"]
    with pytest.raises(DomainError, match="TRAINING_BUSY"):
        training_worker.claim(config)
    training.recover_examples(config)  # a web restart must leave worker job alone
    assert training.get_run(config, workshop[1], queued["id"]).status == "preflight"
    engine = FakeEngine(workshop)
    training_worker.recover(config, engine)
    training_worker.recover(config, engine)
    recovered = training.get_run(config, workshop[1], queued["id"])
    assert recovered.status == "interrupted" and recovered.revision == claimed.revision + 1
    assert engine.cleaned == [queued["id"]] and engine.stages == []
    assert training_worker.execute_next(config, engine) is None


def test_snapshot_corruption_fails_before_gpu(workshop):
    queued = queue(workshop)
    path = training.directory(workshop[4], queued["id"]) / "input/train.jsonl"
    path.write_bytes(path.read_bytes() + b"\n")
    engine = FakeEngine(workshop)
    failed = training_worker.execute_next(workshop[4], engine)
    assert failed.status == "failed" and "TRAINING_INTEGRITY" in failed.error
    assert engine.stages == []


def test_ai_draft_disclosure_consent_review_and_outcome_separation(workshop):
    client, project, _, builder, config = workshop
    seed = new_example(workshop)
    calls = len(builder.calls)
    response = client.post(
        example_path(workshop, seed, "/prepare"), json={"expected_revision": seed["revision"]}
    )
    assert response.status_code == 200, response.text
    prepared = response.json()
    assert prepared["id"] != seed["id"] and prepared["origin"] == "AI_DRAFT"
    assert len(builder.calls) == calls
    disclosure = prepared["disclosure"]
    assert "observed_outcome" not in disclosure["context"] and "rubric" not in disclosure["context"]
    proposal = ExampleProposal.model_validate_json(
        json.dumps(
            {
                "case": {
                    "case_id": str(uuid4()),
                    "situation": "Compressor safety guard condition is unknown.",
                },
                "target": draft(
                    question="Is the safety guard intact?", missing=["safety guard condition"]
                ).model_dump(mode="json"),
            }
        )
    )

    async def structured(**kwargs):
        builder.calls.append(kwargs)
        return proposal

    builder.structured = structured
    consent = {
        "expected_revision": prepared["revision"],
        "turn_id": prepared["id"],
        "disclosure_sha256": disclosure["disclosure_sha256"],
        "consent": True,
    }
    assert (
        client.post(
            example_path(workshop, prepared, "/send"), json={**consent, "consent": 1}
        ).status_code
        == 422
    )
    assert len(builder.calls) == calls
    response = client.post(example_path(workshop, prepared, "/send"), json=consent)
    assert response.status_code == 200, response.text
    drafted = response.json()
    assert drafted["origin"] == "AI_DRAFT" and drafted["status"] == "draft"
    assert drafted["case"] == proposal.case.model_dump(mode="json")
    assert queue(workshop, [drafted], expected=409)["detail"].startswith("TRAINING_REVIEW")
    approved = approve(workshop, drafted)
    run = queue(workshop, [approved])
    assert job(workshop, run).examples[0].origin == "AI_DRAFT"
    assert training.get_example(config, project, seed["id"]).status == "draft"


@pytest.mark.parametrize(
    "field,value",
    [("consent", False), ("consent", "true"), ("expected_revision", True), ("extra", "bad")],
)
def test_invalid_example_actions_are_rejected(workshop, field, value):
    example = new_example(workshop)
    body = {"expected_revision": example["revision"], "action": "approve"}
    body[field] = value
    response = workshop[0].post(example_path(workshop, example, "/review"), json=body)
    assert response.status_code == 422


def test_scope_csrf_escaping_forms_and_queue_warning(workshop):
    client, project, *_, config = workshop
    example = new_example(workshop, "<script>test</script> Compressor pressure is unknown.")
    path = example_path(workshop, example, "/target")
    assert client.post(path, json={}, headers={"Origin": "https://evil.example"}).status_code == 422
    response = client.post(f"/projects/{project}/training-examples/{example['id']}/target", data={})
    assert response.status_code == 403
    other = client.post("/api/projects", json={"name": "Other", "mission": "Other mission"}).json()[
        "id"
    ]
    assert client.get(base(other) + f"/training-examples/{example['id']}").status_code == 404
    page = client.get(f"/projects/{project}/train")
    assert page.status_code == 200
    assert (
        "&lt;script&gt;test&lt;/script&gt;" in page.text
        and "<script>test</script>" not in page.text
    )
    assert "Five examples do not ensure quality" in page.text
    assert (
        client.get(base(project) + "/training-resources").json()["minimum_free_bytes"]
        == 12_000_000_000
    )
    target = {
        "expected_revision": example["revision"],
        "behavior": "clarify",
        "recommendation": "Withhold a decision.",
        "explanation": "Pressure is unknown.",
        "question": "What pressure is reported?",
        "missing": "pressure",
        "quotes": "",
        "refs": "",
        "limitations": "Pressure missing.",
    }
    response = client.post(
        f"/projects/{project}/training-examples/{example['id']}/target",
        data=target,
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    assert training.get_example(config, project, example["id"]).target.advice.clarification_question


def test_runtime_manifest_hash_links_and_candidate_tampering(workshop):
    queue(workshop)
    completed = training_worker.execute_next(workshop[4], FakeEngine(workshop))
    version = training.get_version(workshop[4], workshop[1], completed.candidate_id)
    path = verify_candidate(workshop[4], version)
    model, alias = verify_runtime(workshop[4].artifact_root, str(version.id))
    assert model == path / "model.gguf" and alias == f"qm-candidate-{version.model_sha256}"
    model.write_bytes(b"GGUF\x03\x00\x00\x00" + b"y" * 1_000_000)
    with pytest.raises(ValueError, match="CANDIDATE_HASH"):
        verify_runtime(workshop[4].artifact_root, str(version.id))
    with pytest.raises(DomainError, match="CANDIDATE_HASH"):
        verify_candidate(workshop[4], version)


def test_populated_v5_migration_preserves_all_old_tables_and_artifacts(workshop):
    client, project, *_, config = workshop
    suite = freeze(workshop, save(workshop, create(workshop)))
    test_evaluations.run_suite(workshop, suite)
    correct(workshop)
    artifact = config.artifact_root / "original.bin"
    artifact.write_bytes(b"original source bytes")
    with connect(config.database_path) as connection:
        for table in (
            "knowledge_proposals",
            "answer_reviews",
            "reliability_runs",
            "reliability_reviews",
            "training_examples",
            "training_runs",
            "adviser_versions",
        ):
            connection.execute(f"DROP TABLE {table}")
        tables = [
            r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        ]
        before = {t: [tuple(r) for r in connection.execute(f'SELECT * FROM "{t}"')] for t in tables}
        connection.execute("DROP TABLE owner_decisions")
        connection.execute("DROP TABLE muster_imports")
        connection.execute("PRAGMA user_version=5")
    migrate(config.database_path)
    migrate(config.database_path)
    with connect(config.database_path) as connection:
        assert before == {
            t: [tuple(r) for r in connection.execute(f'SELECT * FROM "{t}"')] for t in tables
        }
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 10
    assert artifact.read_bytes() == b"original source bytes"
    assert client.get(base(project)).status_code == 200


def test_docker_command_scoping_pins_and_gpu_mode(workshop, tmp_path):
    queued = queue(workshop)
    run = training.get_run(workshop[4], workshop[1], queued["id"])
    engine = training_worker.DockerEngine(
        workshop[4], tmp_path, tmp_path, "sha256:" + "a" * 64, "sha256:" + "b" * 64
    )
    args = engine.args(run, "train", engine.trainer_image, [(tmp_path, "/input", False)], gpu=True)
    assert "--network=none" in args and "--log-driver=none" in args and "--gpus" in args
    assert "--privileged" not in args and "docker.sock" not in " ".join(args)
    assert "HF_HUB_OFFLINE=1" in args and "TRANSFORMERS_OFFLINE=1" in args
    assert ",readonly" in args[args.index("--mount") + 1]
    with pytest.raises(DomainError, match="TRAINING_IMAGE"):
        training_worker.DockerEngine(workshop[4], tmp_path, tmp_path, "latest", "runtime:latest")


def test_near_duplicate_is_lexical_and_does_not_use_outcomes():
    from quartermaster.contracts.advice import Case

    a = Case(case_id=uuid4(), situation="The current inspection report has no damage reported.")
    b = Case(
        case_id=uuid4(),
        situation="The current inspection report has no damage reported today.",
        observed_outcome="Separate future outcome",
    )
    assert near_duplicate(a, b)
    assert not near_duplicate(a, Case(case_id=uuid4(), situation="Guard needs replacement."))


def test_live_fixture_setup_is_held_out_stable_and_bounded(settings):
    from quartermaster.config import initialize_storage
    from quartermaster.inference import model_alias
    from quartermaster.training_smoke import FIXTURE, seed

    settings = settings.model_copy(
        update={"local_base_url": "http://127.0.0.1:8080/v1", "local_model_sha256": "a" * 64}
    )
    initialize_storage(settings)
    migrate(settings.database_path)
    run = seed(settings, json.loads(FIXTURE.read_bytes()), model_alias("a" * 64))
    frozen = training.read_job(settings, run)
    assert len(frozen.examples) == 4 and len(frozen.holdout_ids) == 2
    assert frozen.recipe.steps == 12 and all(e.origin == "AI_DRAFT" for e in frozen.examples)
    suite = evaluations.get_suite(settings, run.project_id, frozen.suite_id)
    assert suite.frozen_at < run.created_at
    serialized = training.serialize(frozen.examples)
    assert serialized == training.serialize(list(reversed(frozen.examples)))
    situations = [c.case.situation for c in suite.cases]
    assert all(text not in serialized.decode() for text in situations)
    assert all(c.rubric.expectation not in serialized.decode() for c in suite.cases)


def test_cleanup_failure_keeps_global_slot_blocked(workshop):
    queue(workshop)
    engine = FakeEngine(workshop, fail="training")

    def unavailable(run):
        raise OSError("Docker unavailable")

    engine.cleanup = unavailable
    run = training_worker.execute_next(workshop[4], engine)
    assert run.status == "cleanup_required" and run.candidate_id is None
    with pytest.raises(DomainError, match="TRAINING_BUSY"):
        training_worker.claim(workshop[4])
    recovered_engine = FakeEngine(workshop)
    training_worker.recover(workshop[4], recovered_engine)
    assert training.get_run(workshop[4], workshop[1], run.id).status == "interrupted"


def test_active_candidate_test_uses_candidate_identity_and_return_to_base(workshop, monkeypatch):
    queue(workshop)
    completed = training_worker.execute_next(workshop[4], FakeEngine(workshop))
    version = training.get_version(workshop[4], workshop[1], completed.candidate_id)
    client, project, inference, *_ = workshop
    before = client.get(base(project)).json()
    path = base(project) + f"/adviser-versions/{version.id}/promote"
    assert (
        client.post(
            path, json={"expected_revision": before["revision"], "acknowledge_regressions": True}
        ).status_code
        == 200
    )
    selected = []

    def candidate_adapter(settings, **kwargs):
        selected.append(kwargs)
        return inference

    monkeypatch.setattr("quartermaster.inference.LocalInference", candidate_adapter)
    response = ask(workshop, "A new air purifier has no filter inspection record.")
    assert response["model_alias"] == f"qm-candidate-{version.model_sha256}"
    assert selected[0]["base_url"].endswith(f"/{version.id}/v1")
    assert response["adviser"]["model"]["adapter_artifact"] == str(version.id)


@pytest.mark.parametrize("change", ["missing", "extra", "base", "recipe", "nonfinite", "truncated"])
def test_adapter_verification_rejects_invalid_files_and_lineage(workshop, change):
    queued = queue(workshop)
    run = training_worker.claim(workshop[4])
    frozen = training.read_job(workshop[4], run)
    output = training.directory(workshop[4], run.id) / "output"
    output.mkdir()
    FakeEngine(workshop).train(run, frozen)
    if change == "missing":
        (output / "adapter/adapter_config.json").unlink()
    elif change == "extra":
        (output / "adapter/weights.bin").write_bytes(b"untrusted pickle")
    else:
        record = json.loads((output / "training.json").read_bytes())
        if change == "base":
            record["model"]["base_revision"] = "unverified"
        elif change == "recipe":
            record["completed_steps"] = 1
        elif change == "nonfinite":
            record["training_loss"] = float("nan")
        else:
            (output / "adapter/adapter_model.safetensors").write_bytes(b"truncated")
        (output / "training.json").write_text(json.dumps(record))
    with pytest.raises((DomainError, ValueError, OSError)):
        verify_adapter(output, frozen, run)
    assert training.versions(workshop[4], workshop[1]) == []
    assert queued["candidate_id"] is None


def test_missing_job_and_candidate_files_have_actionable_errors(workshop):
    run = queue(workshop)
    completed = training_worker.execute_next(workshop[4], FakeEngine(workshop))
    version = training.get_version(workshop[4], workshop[1], completed.candidate_id)
    folder = training.directory(workshop[4], run["id"])
    (folder / "output/training.json").unlink()
    response = workshop[0].post(
        base(workshop[1]) + f"/adviser-versions/{version.id}/promote",
        json={
            "expected_revision": workshop[0].get(base(workshop[1])).json()["revision"],
            "acknowledge_regressions": True,
        },
    )
    assert response.status_code == 409 and "CANDIDATE_INVALID" in response.text
    (folder / "input/job.json").unlink()
    response = workshop[0].get(base(workshop[1]) + f"/training-runs/{run['id']}/job")
    assert response.status_code == 422 and "TRAINING_INTEGRITY" in response.text


def test_ai_response_cannot_promote_a_holdout_or_invent_outcome(workshop):
    client, project, _, builder, config = workshop
    suite = freeze(workshop, save(workshop, create(workshop)))
    seed = new_example(workshop)
    prepared = client.post(
        example_path(workshop, seed, "/prepare"), json={"expected_revision": seed["revision"]}
    ).json()
    proposal = {
        "case": suite["cases"][0]["case"],
        "target": draft(question="Is there damage?", missing=["damage"]).model_dump(mode="json"),
    }

    async def structured(**kwargs):
        return ExampleProposal.model_validate_json(json.dumps(proposal))

    builder.structured = structured
    response = client.post(
        example_path(workshop, prepared, "/send"),
        json={
            "expected_revision": prepared["revision"],
            "turn_id": prepared["id"],
            "consent": True,
            "disclosure_sha256": prepared["disclosure"]["disclosure_sha256"],
        },
    )
    assert (
        response.json()["status"] == "failed" and "EVALUATION_HELD_OUT" in response.json()["error"]
    )
    assert training.get_example(config, project, prepared["id"]).target is None


def test_training_selection_strict_invalid_and_stale_fields(workshop):
    example = approve(workshop, set_target(workshop, new_example(workshop)))
    suite = freeze(workshop, save(workshop, create(workshop)))
    body = {
        "example_ids": [example["id"]],
        "suite_id": suite["id"],
        "suite_revision": suite["revision"],
        "preset": "quick",
        "acknowledge_small_data": True,
    }
    for extra in (
        {"acknowledge_small_data": 1},
        {"example_ids": []},
        {"preset": "unbounded"},
        {"suite_revision": True},
        {"unknown": 1},
    ):
        response = workshop[0].post(base(workshop[1]) + "/training-runs", json={**body, **extra})
        assert response.status_code == 422
    response = workshop[0].post(
        base(workshop[1]) + "/training-runs", json={**body, "suite_revision": 1}
    )
    assert response.status_code == 409 and "TRAINING_SUITE_CHANGED" in response.text


def test_owner_forms_review_and_freeze_the_exact_selected_dataset(workshop):
    client, project, *_, config = workshop
    example = set_target(workshop, new_example(workshop))
    response = client.post(
        f"/projects/{project}/training-examples/{example['id']}/review",
        data={"expected_revision": example["revision"], "action": "approve"},
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    suite = freeze(workshop, save(workshop, create(workshop)))
    response = client.post(
        f"/projects/{project}/training-runs",
        data={
            "example_ids": [example["id"]],
            "suite": f"{suite['id']}:{suite['revision']}",
            "preset": "standard",
            "acknowledge_small_data": "yes",
        },
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    queued = training.runs(config, project)[0]
    frozen = training.read_job(config, queued)
    assert frozen.recipe.steps == 48 and frozen.recipe.seconds == 3600
    assert [str(e.id) for e in frozen.examples] == [example["id"]]
    assert (
        client.post(
            f"/projects/{project}/training-runs/{queued.id}/cancel",
            data={"expected_revision": queued.revision},
            headers={"Origin": "http://testserver"},
            follow_redirects=False,
        ).status_code
        == 303
    )
    assert training.get_run(config, project, queued.id).status == "canceled"


def test_full_selected_source_hashes_are_frozen_even_if_not_retrieved(workshop):
    from tests.test_foundation import select_knowledge, upload

    client, project, *_, config = workshop
    source = upload(
        client,
        project,
        b"# Remote policy\nUnrelated zebra archival rule.",
        "unrelated.md",
        "knowledge",
    ).json()
    select_knowledge(client, project, [source["id"]])
    example = approve(workshop, set_target(workshop, new_example(workshop)))
    queued = queue(workshop, [example])
    frozen = job(workshop, queued)
    assert frozen.source_hashes == {source["id"]: source["sha256"]}
    assert training.get_run(config, project, queued["id"]).status == "queued"


def test_gpu_smoke_requires_human_review_matching_exact_fixture_hash(tmp_path):
    from quartermaster.training_smoke import fixture_review

    fixture, review_path = tmp_path / "fixture.json", tmp_path / "review.json"
    fixture.write_text('{"synthetic": true}')
    record = {
        "schema_version": "quartermaster.training-fixture-review/v1",
        "fixture_sha256": training.hash_file(fixture),
        "review_state": "pending",
        "reviewer": None,
    }
    review_path.write_text(json.dumps(record))
    with pytest.raises(SystemExit, match="TRAINING_REVIEW"):
        fixture_review(fixture, review_path)
    record.update(review_state="approved", reviewer="CPU test fixture, not actual owner review")
    review_path.write_text(json.dumps(record))
    assert fixture_review(fixture, review_path) == {"synthetic": True}
    fixture.write_text('{"synthetic": false}')
    with pytest.raises(SystemExit, match="TRAINING_REVIEW"):
        fixture_review(fixture, review_path)
