"""Offline package/runtime tests. Fake GGUF bytes prove software paths, never model quality."""

import hashlib
import io
import json
import tarfile
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from quartermaster import exporting, training, training_worker
from quartermaster.contracts.export import ExportManifest, ExportSelection, RuntimeInput
from quartermaster.errors import DomainError
from quartermaster.export_package import (
    MANIFEST,
    PackageContext,
    extract_verified,
    sha256,
    verify_package,
)
from quartermaster.export_smoke import smoke, verify_image
from quartermaster.standalone_runtime import create_runtime
from tests import test_teaching, test_training
from tests.test_foundation import select_knowledge, upload
from tests.test_teaching import ask, base, correct, draft, prepare, review, send

workshop = test_teaching.workshop
IMAGE = "sha256:" + "c" * 64


@pytest.fixture
def candidate(workshop):
    client, project, _, _, config = workshop
    config.export_runtime_image = IMAGE
    source = upload(
        client,
        project,
        b"# Safety\nInspection and damage must be checked.\n",
        "guide.md",
        "knowledge",
    ).json()
    omitted = upload(
        client,
        project,
        b"# Private\nNEVER_EXPORT_THIS_UNSELECTED_SOURCE\n",
        "secret.md",
        "knowledge",
    ).json()
    select_knowledge(client, project, [source["id"]])
    example = test_training.approve(
        workshop, test_training.set_target(workshop, test_training.new_example(workshop))
    )
    run = test_training.queue(workshop, [example])
    result = training_worker.execute_next(config, test_training.FakeEngine(workshop))
    assert result.status == "completed"
    return training.get_version(config, project, result.candidate_id), source, omitted, run


def package(workshop, candidate):
    version = candidate[0]
    response = workshop[0].post(
        base(workshop[1]) + "/exports",
        json={
            "candidate_id": str(version.id),
            "acknowledge_contents": True,
        },
    )
    assert response.status_code == 201, response.text
    manifest = ExportManifest.model_validate_json(response.content)
    archive = exporting.archive_path(workshop[4], workshop[1], manifest.id)
    return manifest, archive


def extracted(workshop, candidate, tmp_path):
    manifest, archive = package(workshop, candidate)
    root = tmp_path / "extracted"
    extract_verified(archive, root)
    return manifest, archive, root


def rehash(root, name):
    manifest = json.loads((root / MANIFEST).read_bytes())
    manifest["files"][name] = {
        "sha256": sha256(root / name),
        "size_bytes": (root / name).stat().st_size,
    }
    (root / MANIFEST).write_text(json.dumps(manifest))


def test_package_frozen_context_and_independent_runtime(workshop, candidate, tmp_path):
    client, project, inference, builder, config = workshop
    before = client.get(base(project)).json()
    manifest, archive, root = extracted(workshop, candidate, tmp_path)
    record, snapshot, material, reference = verify_package(root)
    assert record == manifest
    assert snapshot.adviser.model.adapter_artifact == candidate[0].id
    assert snapshot.adviser.lessons_revision == UUID(before["lessons_revision"])
    assert snapshot.lessons and len(material.sources) == 1
    assert material.sources[0].id == UUID(candidate[1]["id"])
    assert manifest.source_hashes == {candidate[1]["id"]: candidate[1]["sha256"]}
    assert record.files["model/model.gguf"].sha256 == candidate[0].model_sha256
    assert (root / "compose.yaml").read_text() == exporting.compose_text(IMAGE)
    assert "127.0.0.1:8081" in (root / "README.md").read_text()
    assert "api_key" not in (root / "adviser.json").read_text()
    assert "disclosure" not in (root / "adviser.json").read_text()
    assert b"NEVER_EXPORT_THIS_UNSELECTED_SOURCE" not in archive.read_bytes()
    for excluded in (
        "observed_outcome",
        "expected_behavior",
        "owner_correction",
        "training_loss",
        "provider.example",
    ):
        assert excluded.encode() not in archive.read_bytes()
    assert client.get(base(project)).json() == before
    assert len(builder.calls) == 1  # Explicit earlier lesson drafting only.
    calls_before = len(inference.calls)
    with TestClient(create_runtime(root, inference=inference, launch_engine=False)) as runtime:
        assert runtime.get("/healthz").json()["export_id"] == str(manifest.id)
        response = runtime.post("/v1/advise", json=reference.case.model_dump(mode="json"))
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["context_sha256"] == reference.context_sha256
        assert result["advice"]["clarification_question"]
        assert [UUID(e["citation_id"]) for e in result["evidence"]] == reference.evidence_ids
        assert "approved_lessons" in inference.calls[-1][1]
        assert runtime.get("/").status_code == 200
        assert len(inference.calls) == calls_before + 1
    # The extracted runtime only needs its own bytes; builder DB/artifacts are not opened.
    assert not list(root.rglob("*.sqlite3"))


def test_historical_context_survives_later_builder_edits(workshop, candidate, tmp_path):
    client, project, *_ = workshop
    evaluated = client.get(base(project)).json()
    select_knowledge(client, project, [candidate[2]["id"]], evaluated["knowledge_revision"])
    lesson = correct(workshop, ask(workshop, "Completely new drill situation; inspection unknown."))
    review(workshop, send(workshop, prepare(workshop, lesson)))
    current = client.get(base(project)).json()
    assert current["lessons_revision"] != evaluated["lessons_revision"]
    manifest, _, root = extracted(workshop, candidate, tmp_path)
    _, snapshot, _, _ = verify_package(root)
    assert manifest.knowledge_revision == UUID(evaluated["knowledge_revision"])
    assert str(snapshot.adviser.lessons_revision) == evaluated["lessons_revision"]
    assert len(snapshot.lessons) == 1
    assert "NEVER_EXPORT" not in (root / "knowledge/chunks.json").read_text()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"candidate_id": "invalid", "acknowledge_contents": True},
        {"candidate_id": str(uuid4()), "acknowledge_contents": "true"},
        {"candidate_id": str(uuid4()), "acknowledge_contents": 1},
        {"candidate_id": str(uuid4()), "acknowledge_contents": False},
        {"candidate_id": str(uuid4()), "acknowledge_contents": True, "image": "arbitrary"},
    ],
)
def test_export_strict_selection(client, payload):
    project = client.post("/api/projects", json={"name": "X", "mission": "Advise."}).json()["id"]
    assert client.post(base(project) + "/exports", json=payload).status_code == 422


def test_export_form_scope_and_missing_image(workshop, candidate):
    client, project, _, _, config = workshop
    page = client.get(f"/projects/{project}/export")
    assert page.status_code == 200 and "separate operator check" in page.text
    payload = {"candidate_id": str(candidate[0].id), "acknowledge_contents": True}
    assert (
        client.post(
            base(project) + "/exports", json=payload, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    other = client.post("/api/projects", json={"name": "Y", "mission": "Other."}).json()["id"]
    assert client.post(base(other) + "/exports", json=payload).status_code == 404
    config.export_runtime_image = None
    response = client.post(base(project) + "/exports", json=payload)
    assert response.status_code == 409 and "EXPORT_IMAGE" in response.text
    config.export_runtime_image = IMAGE
    action = f"/projects/{project}/export"
    form = {"candidate_id": str(candidate[0].id), "acknowledge_contents": "on"}
    assert client.post(action, data=form).status_code == 403
    assert (
        client.post(action, data=form, headers={"Origin": "http://testserver"}).status_code == 200
    )
    records = client.get(base(project) + "/exports").json()
    assert len(records) == 1
    download = client.get(base(project) + f"/exports/{records[0]['id']}/download")
    assert download.status_code == 200 and download.content.startswith(b"LICENSE")


@pytest.mark.parametrize(
    "name",
    [
        "model/model.gguf",
        "model/LICENSE.model",
        "adviser.json",
        "knowledge/chunks.json",
        "reference.json",
    ],
)
def test_hash_corruption_fails_closed(workshop, candidate, tmp_path, name):
    _, _, root = extracted(workshop, candidate, tmp_path)
    (root / name).write_bytes(b"corrupt")
    with pytest.raises(DomainError, match="EXPORT_INVALID"):
        verify_package(root)


def test_excerpt_provenance_checked_even_with_updated_manifest(workshop, candidate, tmp_path):
    _, _, root = extracted(workshop, candidate, tmp_path)
    path = root / "knowledge/chunks.json"
    document = json.loads(path.read_bytes())
    document["chunks"][0]["text"] = "Invented provenance"
    document["chunks"][0]["sha256"] = hashlib.sha256(b"Invented provenance").hexdigest()
    path.write_text(json.dumps(document))
    rehash(root, "knowledge/chunks.json")
    with pytest.raises(DomainError, match="EXPORT_INVALID"):
        verify_package(root)


@pytest.mark.parametrize(
    "mutation", ["model_format", "source_selection", "candidate", "extra_field"]
)
def test_incompatible_manifest(workshop, candidate, tmp_path, mutation):
    _, _, root = extracted(workshop, candidate, tmp_path)
    path = root / MANIFEST
    record = json.loads(path.read_bytes())
    if mutation == "model_format":
        record["model_format"] = "pickle"
    elif mutation == "source_selection":
        record["source_hashes"] = {}
    elif mutation == "candidate":
        record["candidate_id"] = str(uuid4())
    else:
        record["script"] = "run me"
    path.write_text(json.dumps(record))
    with pytest.raises(DomainError, match="EXPORT_INVALID"):
        verify_package(root)


@pytest.mark.parametrize(
    "kind",
    [
        "traversal",
        "absolute",
        "symlink",
        "hardlink",
        "directory",
        "duplicate",
        "oversized",
        "script",
    ],
)
def test_archive_rejects_hostile_entries(tmp_path, kind):
    archive = tmp_path / "hostile.tar"
    with tarfile.open(archive, "w") as tar:
        name = {"traversal": "../escape", "absolute": "/tmp/escape", "script": "run.sh"}.get(
            kind, "README.md"
        )
        item = tarfile.TarInfo(name)
        item.size = 32_000_001 if kind == "oversized" else 0
        if kind in {"symlink", "hardlink", "directory"}:
            item.type = {
                "symlink": tarfile.SYMTYPE,
                "hardlink": tarfile.LNKTYPE,
                "directory": tarfile.DIRTYPE,
            }[kind]
            item.linkname = "/etc/passwd"
        if kind == "oversized":
            tar.fileobj.write(item.tobuf())  # Fail before reading declared oversized content.
        else:
            tar.addfile(item, io.BytesIO())
        if kind == "duplicate":
            tar.addfile(item, io.BytesIO())
    with pytest.raises(DomainError, match="EXPORT_ARCHIVE|EXPORT_INVALID"):
        extract_verified(archive, tmp_path / "new")
    assert not (tmp_path / "escape").exists()


def test_runtime_schema_citations_clarification_errors_and_html(
    workshop, candidate, tmp_path, monkeypatch
):
    _, _, root = extracted(workshop, candidate, tmp_path)
    inference = test_teaching.FakeInference()
    # Standalone execution ignores builder env, including invalid provider settings.
    monkeypatch.setenv("QM_BUILDER_BASE_URL", "invalid and secret")
    with TestClient(create_runtime(root, inference=inference, launch_engine=False)) as client:
        for payload in (
            {},
            {"situation": "x", "observed_outcome": "later"},
            {"situation": 3},
            {"situation": "x", "choices": "bad"},
        ):
            assert client.post("/v1/advise", json=payload).status_code == 422
        assert client.post("/v1/advise", content=b"x" * 32_001).status_code == 413
        assert (
            client.post(
                "/v1/advise", json={"situation": "x"}, headers={"Origin": "https://evil.example"}
            ).status_code
            == 403
        )
        inference.response = draft(quotes=["Drill current."], refs=[str(uuid4())])
        response = client.post("/v1/advise", json={"situation": "Drill current."})
        assert response.status_code == 422 and "ADVICE_CITATION" in response.text
        inference.response = draft(quotes=["invented quote"])
        assert (
            "ADVICE_SUPPORT" in client.post("/v1/advise", json={"situation": "Drill current."}).text
        )
        inference.response = draft(question="<script>alert(1)</script>", missing=["inspection"])
        assert client.post("/advise", data={"situation": "x"}).status_code == 403
        response = client.post(
            "/advise",
            data={"situation": "<script>case</script>"},
            headers={"Origin": "http://testserver"},
        )
        assert response.status_code == 200 and "&lt;script&gt;" in response.text
        assert "<script>case" not in response.text
        inference.error, inference.response = "LOCAL_TIMEOUT: Retry explicitly.", None
        assert "LOCAL_TIMEOUT" in client.post("/v1/advise", json={"situation": "x"}).text


def test_download_hash_and_candidate_corruption(workshop, candidate):
    manifest, archive = package(workshop, candidate)
    archive.write_bytes(b"x" * archive.stat().st_size)
    with pytest.raises(DomainError, match="EXPORT_HASH"):
        exporting.archive_path(workshop[4], workshop[1], manifest.id)
    portable = (
        training.directory(workshop[4], candidate[0].training_run_id) / "output/portable/model.gguf"
    )
    portable.write_bytes(b"corrupt")
    with pytest.raises(DomainError, match="CANDIDATE"):
        exporting.create_export(
            workshop[4],
            workshop[1],
            ExportSelection(candidate_id=candidate[0].id, acknowledge_contents=True),
        )


def test_missing_image_and_failed_smoke_record(workshop, candidate, tmp_path, monkeypatch):
    _, archive = package(workshop, candidate)
    from quartermaster import export_smoke

    def unavailable(*args, **kwargs):
        raise DomainError("EXPORT_DOCKER: private stdout must not appear.")

    monkeypatch.setattr(export_smoke, "command", unavailable)
    with pytest.raises(DomainError, match="EXPORT_IMAGE"):
        verify_image(IMAGE)
    report = tmp_path / "report.json"
    with pytest.raises(DomainError, match="EXPORT_IMAGE"):
        smoke(archive, report)
    record = json.loads(report.read_bytes())
    assert record["status"] == "failed" and record["error"] == "EXPORT_IMAGE"
    assert "private" not in report.read_text()


def test_runtime_import_boundary_and_image_recipe():
    source = Path("quartermaster/standalone_runtime.py").read_text()
    assert "quartermaster.db" not in source and "quartermaster.builder" not in source
    recipe = (
        Path("trainer/Dockerfile")
        .read_text()
        .split("FROM runtime AS standalone-runtime")[1]
        .split("FROM ")[0]
    )
    assert "--no-install-project" in recipe and "./quartermaster/contracts" in recipe
    assert "quartermaster/app.py" not in recipe and "quartermaster/db" not in recipe
    assert "sha256:" in exporting.compose_text(IMAGE)
    with pytest.raises(ValidationError):
        RuntimeInput(situation="x", script="run")


def test_incompatible_gguf_with_updated_hash_is_rejected(workshop, candidate, tmp_path):
    _, _, root = extracted(workshop, candidate, tmp_path)
    model = root / "model/model.gguf"
    with model.open("r+b") as stream:
        stream.write(b"PK\x00\x00\x00\x00\x00\x00")
    rehash(root, "model/model.gguf")
    with pytest.raises(DomainError, match="EXPORT_INVALID"):
        verify_package(root)


def test_package_and_builder_metadata_links_rejected(workshop, candidate, tmp_path):
    manifest, _, root = extracted(workshop, candidate, tmp_path)
    target = tmp_path / "elsewhere"
    (root / "adviser.json").rename(target)
    (root / "adviser.json").symlink_to(target)
    with pytest.raises(DomainError, match="EXPORT_INVALID"):
        verify_package(root)
    builder_root = exporting.directory(workshop[4], workshop[1], manifest.id)
    fingerprint = builder_root / "archive.json"
    fingerprint.rename(tmp_path / "fingerprint.json")
    fingerprint.symlink_to(tmp_path / "fingerprint.json")
    with pytest.raises(DomainError, match="EXPORT_MISSING"):
        exporting.get_export(workshop[4], workshop[1], manifest.id)


def test_export_rejects_context_change_and_low_disk(workshop, candidate, monkeypatch):
    original = PackageContext.assemble

    def changed(self, case):
        result = list(original(self, case))
        result[1] += " "
        return result

    selection = ExportSelection(candidate_id=candidate[0].id, acknowledge_contents=True)
    monkeypatch.setattr(PackageContext, "assemble", changed)
    with pytest.raises(DomainError, match="EXPORT_CONTEXT"):
        exporting.create_export(workshop[4], workshop[1], selection)
    monkeypatch.setattr(PackageContext, "assemble", original)
    from types import SimpleNamespace

    monkeypatch.setattr(exporting.shutil, "disk_usage", lambda _: SimpleNamespace(free=0))
    with pytest.raises(DomainError, match="EXPORT_DISK"):
        exporting.create_export(workshop[4], workshop[1], selection)


def test_smoke_rejects_modified_compose_without_docker(workshop, candidate, tmp_path, monkeypatch):
    _, archive, root = extracted(workshop, candidate, tmp_path)
    (root / "compose.yaml").write_text("services: {danger: {privileged: true}}\n")
    rehash(root, "compose.yaml")
    modified = tmp_path / "modified.tar"
    with tarfile.open(archive, "r:") as source, tarfile.open(modified, "w") as destination:
        for item in source:
            if item.name in {"compose.yaml", MANIFEST}:
                data = (root / item.name).read_bytes()
                item.size = len(data)
                destination.addfile(item, io.BytesIO(data))
            else:
                destination.addfile(item, source.extractfile(item))
    from quartermaster import export_smoke

    def must_not_run(*args, **kwargs):
        raise AssertionError("Untrusted Compose must never execute")

    monkeypatch.setattr(export_smoke, "command", must_not_run)
    with pytest.raises(DomainError, match="EXPORT_COMPOSE"):
        smoke(modified, tmp_path / "failed.json")


def test_startup_failure_cleans_compose_and_records_code(
    workshop, candidate, tmp_path, monkeypatch
):
    _, archive = package(workshop, candidate)
    from quartermaster import export_smoke

    commands = []

    def unavailable(args, **kwargs):
        commands.append(args)
        if "up" in args:
            raise DomainError("EXPORT_DOCKER: raw private logs")
        return ""

    monkeypatch.setattr(export_smoke, "verify_image", lambda image: None)
    monkeypatch.setattr(export_smoke, "command", unavailable)
    report = tmp_path / "failed.json"
    with pytest.raises(DomainError, match="EXPORT_STARTUP"):
        smoke(archive, report)
    assert "down" in commands[-1]
    assert json.loads(report.read_bytes())["error"] == "EXPORT_STARTUP"
    assert "raw private logs" not in report.read_text()


def test_engine_exit_becomes_unhealthy_and_shutdown_cleans(
    workshop, candidate, tmp_path, monkeypatch
):
    _, _, root = extracted(workshop, candidate, tmp_path)
    from quartermaster import standalone_runtime

    class Process:
        code = None

        def poll(self):
            return self.code

    process = Process()
    cleaned = []
    monkeypatch.setattr(standalone_runtime, "start_engine", lambda *args: process)
    monkeypatch.setattr(standalone_runtime, "stop_engine", lambda value: cleaned.append(value))
    with TestClient(create_runtime(root, inference=test_teaching.FakeInference())) as client:
        assert client.get("/healthz").status_code == 200
        process.code = 1
        response = client.get("/healthz")
        assert response.status_code == 503 and "EXPORT_ENGINE" in response.text
    assert cleaned == [process]


def test_missing_engine_and_bounded_cpu_recipe(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from quartermaster import standalone_runtime

    def missing(*args, **kwargs):
        raise OSError("private path must not be reflected")

    monkeypatch.setattr(standalone_runtime.subprocess, "Popen", missing)
    manifest = SimpleNamespace(files={"model/model.gguf": SimpleNamespace(sha256="a" * 64)})
    with pytest.raises(DomainError, match="EXPORT_ENGINE") as exc:
        standalone_runtime.start_engine(tmp_path, manifest)
    assert "private path" not in str(exc.value)
    commands = []
    process = SimpleNamespace(poll=lambda: 1)

    def failed(command, **kwargs):
        commands.append((command, kwargs))
        return process

    monkeypatch.setattr(standalone_runtime.subprocess, "Popen", failed)
    with pytest.raises(DomainError, match="EXPORT_ENGINE"):
        standalone_runtime.start_engine(tmp_path, manifest)
    args, options = commands[0]
    assert args[args.index("--host") + 1] == "127.0.0.1"
    assert args[args.index("-ngl") + 1] == "0"
    assert args[args.index("-c") + 1] == "8192"
    assert args[args.index("-n") + 1] == "512"
    assert "--log-disable" in args and "--no-context-shift" in args
    assert options["stdout"] == standalone_runtime.subprocess.DEVNULL
    assert options["stderr"] == standalone_runtime.subprocess.DEVNULL
