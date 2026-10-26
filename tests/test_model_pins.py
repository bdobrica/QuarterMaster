"""Model changes preserve teaching; adapters and exports retain their exact base."""

import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from quartermaster import exporting, muster, predictions, training, training_worker
from quartermaster.contracts.adviser import ModelSpec
from quartermaster.contracts.answers import CategoryAnswer, NumberAnswer
from quartermaster.contracts.interview import VersionedAction
from quartermaster.contracts.training import Promote, Recipe
from quartermaster.errors import DomainError
from quartermaster.inference import identity
from quartermaster.local_runtime import LLAMA_REVISION, sha256, verify
from quartermaster.model_pins import CAPABLE_ID, CAPABLE_REVISION, ORIGINAL_REVISION
from quartermaster.prediction_context import serialize
from quartermaster.prediction_jobs import recipe_for, verify_job
from quartermaster.projects import adviser_history, configure_answer, get_adviser, use_local_base
from tests.test_muster_integration import collection as collection
from tests.test_predictions import CATEGORY, NUMBER, Adapter, PredictionEngine, selection, setup


def installed(settings):
    settings.local_model_revision = CAPABLE_REVISION
    settings.local_model_sha256 = "a" * 64
    settings.local_base_url = "http://127.0.0.1:18082/v1"


def configure(settings, project, fmt):
    spec = get_adviser(settings.database_path, project)
    return configure_answer(
        settings.database_path,
        project,
        NumberAnswer(**fmt) if fmt["kind"] == "number" else CategoryAnswer(**fmt),
        spec.revision,
    )


def test_model_pairs_and_recipe_versions_are_closed_and_historical_defaults_unchanged():
    old = ModelSpec()
    assert json.loads(old.model_dump_json()) == {
        "base_model_id": "Qwen/Qwen3.5-0.8B",
        "base_revision": ORIGINAL_REVISION,
        "adapter_artifact": None,
    }
    new = ModelSpec.for_revision(CAPABLE_REVISION)
    assert new.base_model_id == CAPABLE_ID
    for fields in (
        {"base_model_id": CAPABLE_ID},
        {"base_revision": CAPABLE_REVISION},
        {"base_model_id": "Qwen/Qwen3.5-2B"},
        {"base_revision": "latest"},
    ):
        with pytest.raises(ValidationError):
            ModelSpec(**fields)
    assert recipe_for(old, "quick") == training.recipe("quick")
    # The stronger experiment overfit real owner cases; never make it the default.
    assert recipe_for(new, "quick").schema_version == "quartermaster.lora-recipe/v2"
    new_recipe = recipe_for(new, "quick", version="quartermaster.lora-recipe/v3")
    assert new_recipe.schema_version == "quartermaster.lora-recipe/v3"
    assert new_recipe.precision == "nf4-float16"
    assert new_recipe.learning_rate == 0.0002
    previous = recipe_for(new, "quick", version="quartermaster.lora-recipe/v2")
    assert previous.learning_rate == 0.00001
    assert Recipe.model_validate_json(previous.model_dump_json()) == previous
    for recipe in (previous, new_recipe):
        with pytest.raises(ValidationError):
            Recipe(**{**recipe.model_dump(), "learning_rate": 0.001})
    with pytest.raises(ValidationError):
        Recipe(**{**new_recipe.model_dump(), "learning_rate": 0.00001})
    with pytest.raises(ValueError):
        recipe_for(old, "quick", version="quartermaster.lora-recipe/v3")
    with pytest.raises(ValidationError):
        Recipe(**{**new_recipe.model_dump(), "schema_version": "quartermaster.lora-recipe/v1"})
    with pytest.raises(ValidationError):
        Recipe(**{**new_recipe.model_dump(), "precision": "float32"})


def test_runtime_manifest_requires_the_exact_model_revision_and_original_bytes(tmp_path):
    model, license_file = tmp_path / "model.gguf", tmp_path / "LICENSE.model"
    model.write_bytes(b"GGUF\x03\x00\x00\x00" + b"x" * 1_000_000)
    license_file.write_text("Synthetic license fixture; no real model.")
    record = {
        "schema_version": "quartermaster.local-model/v1",
        "model_id": CAPABLE_ID,
        "revision": CAPABLE_REVISION,
        "llama_revision": LLAMA_REVISION,
        "adapter_artifact": None,
        "format": "GGUF-Q8_0",
        "sha256": sha256(model),
        "size_bytes": model.stat().st_size,
        "license_sha256": sha256(license_file),
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(record))
    assert verify(tmp_path) == record
    for change in (
        {"revision": ORIGINAL_REVISION},
        {"model_id": None, "revision": "unknown"},
        {"adapter_artifact": str(uuid4())},
        {"sha256": "0" * 64},
    ):
        path.write_text(json.dumps({**record, **change}))
        with pytest.raises(ValueError):
            verify(tmp_path)


@pytest.mark.parametrize("fmt", [NUMBER, CATEGORY])
def test_explicit_base_switch_preserves_teaching_and_versions_and_prevents_silent_fallback(
    client, settings, collection, fmt
):
    project, item, target = setup(settings, collection, fmt)
    old = configure(settings, project, fmt)
    decisions = muster.decisions(settings, project)
    before, _ = muster.freeze_teaching(settings, project, item.id)
    installed(settings)
    endpoint = f"/api/projects/{project}/local-base"
    response = client.post(endpoint, json={"expected_revision": old.revision})
    assert response.status_code == 200, response.text
    current = get_adviser(settings.database_path, project)
    assert current.model == ModelSpec.for_revision(CAPABLE_REVISION)
    assert current.knowledge_revision == old.knowledge_revision
    assert current.answer_format == old.answer_format
    assert adviser_history(settings.database_path, project)[-2] == old
    assert muster.decisions(settings, project) == decisions
    assert muster.freeze_teaching(settings, project, item.id)[0] == before
    assert client.post(endpoint, json={"expected_revision": old.revision}).status_code == 409
    assert identity(settings) == f"qm-base-{CAPABLE_REVISION}-{'a' * 64}"
    created = client.post(
        "/api/projects", json={"name": "Installed base", "mission": "Help me choose."}
    )
    assert created.status_code == 201
    assert get_adviser(settings.database_path, created.json()["id"]).model == current.model

    adapter = Adapter(target)
    client.app.state.inference = adapter
    payload = {"situation": "A new situation", "answer_format": fmt}
    assert client.post(f"/api/projects/{project}/predictions", json=payload).status_code == 200
    settings.local_model_revision = ORIGINAL_REVISION
    blocked = client.post(f"/api/projects/{project}/predictions", json=payload)
    assert blocked.status_code == 409 and "LOCAL_MODEL_CHANGED" in blocked.text
    assert len(adapter.calls) == 1
    # The browser recovery form is versioned and rejects extra/duplicate fields too.
    response = client.post(
        f"/projects/{project}/local-base",
        data={"expected_revision": str(current.revision)},
        headers={"origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert get_adviser(settings.database_path, project).model.base_revision == ORIGINAL_REVISION


@pytest.mark.parametrize("fmt", [NUMBER, CATEGORY])
def test_new_base_training_candidate_and_export_keep_pinned_lineage(
    client, settings, collection, tmp_path, fmt
):
    project, item, _ = setup(settings, collection, fmt)
    old = configure(settings, project, fmt)
    installed(settings)
    use_local_base(settings, project, VersionedAction(expected_revision=old.revision))
    current = get_adviser(settings.database_path, project)
    queued = predictions.prepare(settings, project, item.id, selection(settings, project, fmt))
    job = training.read_job(settings, queued)
    assert job.model == ModelSpec.for_revision(CAPABLE_REVISION)
    assert job.baseline == current.model and job.recipe == recipe_for(job.model, "quick")
    raw = serialize(job.examples)
    assert verify_job(job, raw) == job
    with pytest.raises(ValueError):
        verify_job(job.model_copy(update={"recipe": training.recipe("quick")}), raw)
    with pytest.raises(ValueError):
        verify_job(job.model_copy(update={"model": ModelSpec()}), raw)

    completed = training_worker.execute_next(settings, PredictionEngine(settings))
    assert completed.status == "completed", completed.error
    assert get_adviser(settings.database_path, project).model == current.model
    selected = training.promote(
        settings,
        project,
        completed.candidate_id,
        Promote(expected_revision=current.revision, acknowledge_regressions=True),
    )
    assert selected.model.base_revision == CAPABLE_REVISION
    assert selected.model.adapter_artifact == completed.candidate_id
    retained = training.retain_base(
        settings, project, VersionedAction(expected_revision=selected.revision)
    )
    assert retained.model == job.model
    settings.export_runtime_image = "sha256:" + "c" * 64
    from quartermaster.contracts.export import ExportSelection
    from quartermaster.export_package import extract_verified

    record = exporting.create_export(
        settings,
        project,
        ExportSelection(candidate_id=completed.candidate_id, acknowledge_contents=True),
    )
    archive = exporting.archive_path(settings, project, record.id)
    manifest, config, _, _ = extract_verified(archive, tmp_path / "new-model-export")
    assert manifest.schema_version == "quartermaster.export/v5"
    assert config.adviser.model.base_revision == CAPABLE_REVISION
    assert config.answer_format == job.answer_format


def test_large_model_conversion_has_finite_resources_and_portable_runtime_budget(
    settings, tmp_path
):
    from quartermaster.training_worker import DockerEngine

    trainer_image, runtime_image = "sha256:" + "a" * 64, "sha256:" + "b" * 64
    engine = DockerEngine(settings, tmp_path, tmp_path, trainer_image, runtime_image, "wsl")
    from types import SimpleNamespace

    run = SimpleNamespace(id=uuid4())
    model = ModelSpec.for_revision(CAPABLE_REVISION)
    args = engine.args(run, "convert", trainer_image, [], model=model)
    assert "--memory=24g" in args and "--network=none" in args
    assert "--memory=10g" in engine.args(run, "train", trainer_image, [], model=model)
    assert "mem_limit: 6g" in exporting.compose_text("sha256:" + "a" * 64, 4_500_000_000)
    assert "mem_limit: 4g" in exporting.compose_text("sha256:" + "a" * 64)
    settings.data_dir.mkdir()
    limits = training.resource_warning(settings, model)
    assert limits["minimum_free_bytes"] == 32_000_000_000
    assert limits["minimum_vram_bytes"] == 7_500_000_000
    assert "8 GB video memory" in limits["message"]


def test_new_job_rejects_stale_trainer_capabilities_before_gpu_work(
    settings, collection, tmp_path, monkeypatch
):
    project, item, _ = setup(settings, collection, NUMBER)
    old = configure(settings, project, NUMBER)
    installed(settings)
    use_local_base(settings, project, VersionedAction(expected_revision=old.revision))
    queued = predictions.prepare(settings, project, item.id, selection(settings, project, NUMBER))
    job = training.read_job(settings, queued)
    engine = training_worker.DockerEngine(
        settings, tmp_path, tmp_path, "sha256:" + "a" * 64, "sha256:" + "b" * 64
    )
    monkeypatch.setattr(training_worker, "verify_snapshot", lambda *a, **kw: None)
    from types import SimpleNamespace

    monkeypatch.setattr(
        training_worker.shutil, "disk_usage", lambda p: SimpleNamespace(free=40_000_000_000)
    )
    monkeypatch.setattr(
        training_worker,
        "verify_base_gguf",
        lambda p: {"model_id": CAPABLE_ID, "revision": CAPABLE_REVISION},
    )
    labels = {
        "org.opencontainers.image.revision": LLAMA_REVISION,
        "io.quartermaster.training-contract": job.schema_version,
    }
    monkeypatch.setattr(
        engine, "command", lambda args: json.dumps([{"Config": {"Labels": labels}}])
    )
    stages = []
    monkeypatch.setattr(engine, "stage", lambda *a, **kw: stages.append(a))
    # Matching job version alone cannot authorize an image that lacks NF4/v6 support.
    with pytest.raises(DomainError, match="TRAINING_IMAGE"):
        engine.preflight(queued, job)
    labels["io.quartermaster.training-recipe"] = "quartermaster.lora-recipe/v2"
    with pytest.raises(DomainError, match="TRAINING_IMAGE"):
        engine.preflight(queued, job)
    assert stages == []
    labels["io.quartermaster.prediction-context"] = "context/v6"
    engine.preflight(queued, job)
    assert len(stages) == 1
    job = job.model_copy(
        update={"recipe": recipe_for(job.model, "quick", version="quartermaster.lora-recipe/v3")}
    )
    # A previous quantized image cannot execute a new learning-rate version.
    with pytest.raises(DomainError, match="TRAINING_IMAGE"):
        engine.preflight(queued, job)
    labels["io.quartermaster.training-recipe"] = "quartermaster.lora-recipe/v3"
    engine.preflight(queued, job)
    assert len(stages) == 2
    legacy = job.model_copy(
        update={"recipe": recipe_for(job.model, "quick", version="quartermaster.lora-recipe/v2")}
    )
    for label in ("quartermaster.lora-recipe/v2", "quartermaster.lora-recipe/v3"):
        labels["io.quartermaster.training-recipe"] = label
        engine.preflight(queued, legacy)


@pytest.mark.parametrize("fmt", [NUMBER, CATEGORY])
def test_frozen_quantized_recipe_keeps_its_original_rate_and_public_validation(
    settings, collection, fmt
):
    installed(settings)
    project, item, _ = setup(settings, collection, fmt)
    configure(settings, project, fmt)
    use_local_base(
        settings,
        project,
        VersionedAction(expected_revision=get_adviser(settings.database_path, project).revision),
    )
    queued = predictions.prepare(settings, project, item.id, selection(settings, project, fmt))
    job = training.read_job(settings, queued)
    raw = serialize(job.examples)
    frozen = job.model_dump_json()
    assert verify_job(job, raw).model_dump_json() == frozen
    assert job.recipe.learning_rate == 0.00001
    experiment = job.model_copy(
        update={"recipe": recipe_for(job.model, "quick", version="quartermaster.lora-recipe/v3")}
    )
    assert verify_job(experiment, raw).recipe.learning_rate == 0.0002
    assert (training.directory(settings, queued.id) / "input/job.json").read_text() == (
        job.model_dump_json()
    )


def test_trainer_uses_the_frozen_learning_rate_and_retains_legacy_defaults(tmp_path, monkeypatch):
    import importlib.util
    import sys
    from pathlib import Path
    from types import SimpleNamespace

    spec = importlib.util.spec_from_file_location(
        "rate_checked_worker", Path(__file__).parents[1] / "trainer/worker.py"
    )
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    monkeypatch.setitem(sys.modules, "trl", SimpleNamespace(SFTConfig=lambda **kw: kw))
    model = ModelSpec.for_revision(CAPABLE_REVISION)
    for version, rate in (
        ("quartermaster.lora-recipe/v2", 0.00001),
        ("quartermaster.lora-recipe/v3", 0.0002),
    ):
        recipe = recipe_for(model, "standard", version=version)
        config = worker.training_args(tmp_path, recipe=recipe)
        assert config["learning_rate"] == rate
        assert config["max_steps"] == 48 and config["max_length"] == 2048
        assert config["completion_only_loss"] and not config["packing"]
    assert worker.training_args(tmp_path)["learning_rate"] == 0.00001


def test_portable_size_limit_is_bound_to_the_pinned_model(settings, tmp_path, monkeypatch):
    from quartermaster.contracts.training import ArtifactFile
    from quartermaster.training_artifacts import portable_files

    # Sparse framing fixture: exercise the real 4B size boundary without allocating
    # model bytes or claiming these fake weights can run. Hashing is deliberately mocked.
    path = tmp_path / "portable"
    path.mkdir()
    model = path / "model.gguf"
    with model.open("wb") as stream:
        stream.write(b"GGUF\x03\x00\x00\x00")
        stream.seek(4_500_000_000 - 1)
        stream.write(b"\x00")
    (path / "LICENSE.model").write_text("Synthetic fixture")
    monkeypatch.setattr(training, "hash_file", lambda _: "a" * 64)
    with pytest.raises(DomainError, match="CANDIDATE_FORMAT"):
        portable_files(path, ModelSpec())
    record = portable_files(path, ModelSpec.for_revision(CAPABLE_REVISION))
    assert record["model_size_bytes"] == 4_500_000_000
    assert ArtifactFile(sha256="a" * 64, size_bytes=4_500_000_000).size_bytes == 4_500_000_000
    with pytest.raises(ValidationError):
        ArtifactFile(sha256="a" * 64, size_bytes=6_000_000_001)


def test_larger_export_rejects_older_runtime_image_contract(monkeypatch):
    from quartermaster import export_smoke

    image = "sha256:" + "c" * 64
    label = "quartermaster.export/v4"
    monkeypatch.setattr(
        export_smoke,
        "command",
        lambda args: json.dumps(
            [
                {
                    "Id": image,
                    "Config": {
                        "Labels": {
                            "org.opencontainers.image.revision": LLAMA_REVISION,
                            "io.quartermaster.export-contract": label,
                        }
                    },
                }
            ]
        ),
    )
    with pytest.raises(DomainError, match="EXPORT_IMAGE"):
        export_smoke.verify_image(image, "quartermaster.export/v5")
    label = "quartermaster.export/v5"
    export_smoke.verify_image(image, "quartermaster.export/v5")
    export_smoke.verify_image(image, "quartermaster.export/v4")


@pytest.mark.parametrize("size", [800_000_000, 4_500_000_000])
def test_candidate_gateway_bounded_cold_start_preserves_original_timeout(
    size, tmp_path, monkeypatch
):
    from contextlib import nullcontext
    from types import SimpleNamespace

    from quartermaster import candidate_runtime as runtime

    model = SimpleNamespace(stat=lambda: SimpleNamespace(st_size=size))
    monkeypatch.setattr(runtime, "verify", lambda *a: (model, "verified-alias"))
    process = SimpleNamespace(poll=lambda: None, terminate=lambda: None, wait=lambda **kw: None)
    monkeypatch.setattr(runtime.subprocess, "Popen", lambda *a, **kw: process)
    monkeypatch.setattr(runtime.time, "sleep", lambda seconds: None)
    calls = []

    def health(*args, **kwargs):
        calls.append(1)
        if len(calls) < 65:
            raise OSError("Still loading")
        return nullcontext()

    monkeypatch.setattr(runtime.urllib.request, "urlopen", health)
    gateway = runtime.Gateway(tmp_path)
    if size > 3_000_000_000:
        assert gateway.select("candidate") == "verified-alias"
        assert len(calls) == 65
    else:
        with pytest.raises(ValueError, match="CANDIDATE_START"):
            gateway.select("candidate")
        assert len(calls) == 60
