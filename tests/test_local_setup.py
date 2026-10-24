"""CPU mocks prove preparation cannot silently train, publish partial bytes or retry."""

import json

import pytest

from quartermaster import setup_local
from quartermaster.spike.spec import MODEL_REVISION


@pytest.fixture
def preparer(tmp_path, monkeypatch):
    calls = []

    class FakeRun:
        fail = False

        def __init__(self, directory):
            self.directory = directory
            directory.mkdir(parents=True)

        def command(self, stage, args, timeout):
            calls.append((stage, args, timeout))
            return "sha256:synthetic-image"

        def container(self, stage, image, arguments, mounts, **kwargs):
            calls.append((stage, arguments, kwargs))
            assert not kwargs.get("gpu")
            assert all("adapter" not in str(source) for source, _, _ in mounts)
            assert arguments == ["convert-base"]
            assert kwargs["timeout"] == 1200
            if self.fail:
                raise RuntimeError("synthetic conversion failure")
            output = next(source for source, target, _ in mounts if target == "/output")
            (output / "model.gguf").write_bytes(b"GGUF\x03\x00\x00\x00" + b"x" * 1_000_000)
            (output / "LICENSE.model").write_text("Synthetic fixture license")

        def event(self, stage, status, code=None):
            calls.append((stage, status, code))

    monkeypatch.setattr(setup_local, "Run", FakeRun)
    monkeypatch.setattr(setup_local, "verify_snapshot", lambda path: calls.append(("verify", path)))
    (tmp_path / "spike" / f"base-{MODEL_REVISION}").mkdir(parents=True)
    return tmp_path, calls, FakeRun


def test_base_setup_publishes_verified_bundle_and_rebuilds_runtime_on_reuse(preparer):
    root, calls, _ = preparer
    setup_local.prepare(root, skip_build=True)
    directory = root / "local-model"
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    manifest = json.loads(before["manifest.json"])
    assert manifest["adapter_artifact"] is None and manifest["revision"] == MODEL_REVISION
    assert [c[0] for c in calls].count("convert-base") == 1
    setup_local.prepare(root)
    assert {p.name: p.read_bytes() for p in directory.iterdir()} == before
    assert [c[0] for c in calls].count("convert-base") == 1
    assert [c[0] for c in calls].count("build-adviser-runtime") == 1
    assert not any(c[0] == "build-trainer" for c in calls)


def test_base_conversion_failure_never_publishes_or_retries(preparer):
    root, calls, fake = preparer
    fake.fail = True
    with pytest.raises(SystemExit, match="Local setup failed"):
        setup_local.prepare(root, skip_build=True)
    assert not (root / "local-model").exists()
    assert [c[0] for c in calls].count("convert-base") == 1
    assert ("setup", "failed", "RuntimeError") in calls


def test_corrupt_existing_bundle_fails_before_any_container_operation(preparer):
    root, calls, _ = preparer
    (root / "local-model").mkdir()
    (root / "local-model" / "manifest.json").write_text("not valid json")
    with pytest.raises(SystemExit, match="Local setup failed"):
        setup_local.prepare(root)
    assert calls == [("setup", "failed", "JSONDecodeError")]
    assert (root / "local-model" / "manifest.json").read_text() == "not valid json"
