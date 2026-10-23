import io
import json
import subprocess
import tarfile
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from quartermaster.contracts.advice import Advice, Case
from quartermaster.spike.artifacts import (
    check_gguf,
    extract_verified,
    package,
    require_review,
    verify_adapter,
    verify_snapshot,
)
from quartermaster.spike.run import FIXTURES, Run, SpikeFailure
from quartermaster.spike.spec import MODEL_ID, MODEL_REVISION, digest, load_pair, messages


def test_approved_fixture_and_held_out_cases():
    train, evaluation = load_pair(FIXTURES / "train.json", FIXTURES / "evaluation.json")
    assert len(train.examples) == 4
    assert len(evaluation.examples) == 2
    require_review(FIXTURES / "train.json", FIXTURES / "review.json")


def test_review_is_invalidated_by_any_fixture_change(tmp_path):
    changed = tmp_path / "train.json"
    changed.write_bytes((FIXTURES / "train.json").read_bytes() + b" ")
    with pytest.raises(ValueError, match="approval"):
        require_review(changed, FIXTURES / "review.json")


@pytest.mark.parametrize("field,value", [("review_state", "pending"), ("reviewer", " ")])
def test_unreviewed_fixture_cannot_train(tmp_path, field, value):
    review = json.loads((FIXTURES / "review.json").read_text())
    review[field] = value
    path = tmp_path / "review.json"
    path.write_text(json.dumps(review))
    with pytest.raises(ValueError, match="approval"):
        require_review(FIXTURES / "train.json", path)


@pytest.mark.parametrize("field", ["case_id", "situation"])
def test_evaluation_leakage_rejected(tmp_path, field):
    training = json.loads((FIXTURES / "train.json").read_text())
    evaluation = json.loads((FIXTURES / "evaluation.json").read_text())
    training["examples"][0]["case"][field] = evaluation["examples"][0]["case"][field]
    path = tmp_path / "train.json"
    path.write_text(json.dumps(training))
    with pytest.raises(ValueError, match="leaked"):
        load_pair(path, FIXTURES / "evaluation.json")


def test_outcomes_not_in_prompt():
    case = Case(case_id=uuid4(), situation="Inspection status unknown", observed_outcome="SECRET")
    prompt = messages("Ask about inspections", case)
    assert "SECRET" not in json.dumps(prompt)
    assert "observed_outcome" not in json.dumps(prompt)
    assert str(case.case_id) in prompt[1]["content"]


@pytest.mark.parametrize(
    "change",
    [
        {"recommendation": ""},
        {"recommendation": 12},
        {"confidence": 0.9},
        {"evidence_refs": "source-1"},
        {"clarification_question": False},
        {"schema_version": "quartermaster.advice/v9"},
    ],
)
def test_advice_rejects_invalid_and_extra_fields(change):
    fixture, _ = load_pair(FIXTURES / "train.json", FIXTURES / "evaluation.json")
    advice = fixture.examples[0].advice.model_dump()
    with pytest.raises(ValidationError):
        Advice.model_validate(advice | change)


def test_missing_advice_fields_rejected():
    with pytest.raises(ValidationError):
        Advice.model_validate({"recommendation": "Use it"})


@pytest.mark.parametrize(
    "data",
    [
        {"situation": "Inspection unknown"},
        {"case_id": "invalid", "situation": "Inspection unknown"},
        {"case_id": str(uuid4()), "situation": ""},
        {"case_id": str(uuid4()), "situation": "Inspection unknown", "execute": "send email"},
    ],
)
def test_case_rejects_missing_invalid_or_extra_fields(data):
    with pytest.raises(ValidationError):
        Case.model_validate_json(json.dumps(data))


def test_citations_must_exist():
    fixture, _ = load_pair(FIXTURES / "train.json", FIXTURES / "evaluation.json")
    advice = fixture.examples[0].advice.model_copy(update={"evidence_refs": ["made-up"]})
    with pytest.raises(ValueError, match="inaccessible"):
        advice.check_evidence(set())
    advice.check_evidence({"made-up"})


def test_corrupt_snapshot_rejected(tmp_path):
    (tmp_path / "LICENSE").write_text("Apache-2.0")
    record = {
        "model_id": MODEL_ID,
        "revision": MODEL_REVISION,
        "files": {"LICENSE": digest(tmp_path / "LICENSE")},
    }
    (tmp_path / "snapshot.json").write_text(json.dumps(record))
    verify_snapshot(tmp_path)
    (tmp_path / "LICENSE").write_text("changed")
    with pytest.raises(ValueError, match="hash"):
        verify_snapshot(tmp_path)


def test_adapter_lineage_and_hashes(tmp_path):
    adapter = tmp_path / "adapter"
    adapter.mkdir()
    config = {
        "base_model_name_or_path": MODEL_ID,
        "revision": MODEL_REVISION,
        "peft_type": "LORA",
        "task_type": "CAUSAL_LM",
        "r": 4,
        "lora_alpha": 8,
        "target_modules": ["q_proj", "v_proj"],
    }
    (adapter / "adapter_config.json").write_text(json.dumps(config))
    (adapter / "adapter_model.safetensors").write_bytes(b"synthetic-test-bytes" * 10)
    manifest = {
        "schema_version": "quartermaster.spike-training/v1",
        "model_id": MODEL_ID,
        "revision": MODEL_REVISION,
        "steps": 12,
        "train_sha256": "reviewed-hash",
        "adapter_hashes": {p.name: digest(p) for p in adapter.iterdir()},
    }
    (tmp_path / "training.json").write_text(json.dumps(manifest))
    assert verify_adapter(tmp_path, "reviewed-hash") == manifest
    with pytest.raises(ValueError, match="lineage"):
        verify_adapter(tmp_path, "other-hash")
    (adapter / "adapter_model.safetensors").write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="hash"):
        verify_adapter(tmp_path, "reviewed-hash")


@pytest.mark.parametrize("content", [b"", b"not-a-model", b"GGUF\x02\x00\x00\x00"])
def test_failed_conversion_is_not_success(tmp_path, content):
    path = tmp_path / "model.gguf"
    # Nonempty failures exceed the size gate, so this also exercises magic/version rejection.
    path.write_bytes(content + (b"\0" * 1_000_001 if content else b""))
    with pytest.raises(ValueError):
        check_gguf(path)


def test_portable_package_fresh_extraction_and_corruption(tmp_path):
    source, target = tmp_path / "source", tmp_path / "extracted"
    source.mkdir()
    target.mkdir()
    (source / "model.gguf").write_bytes(b"GGUF\x03\x00\x00\x00" + b"\0" * 1_000_000)
    (source / "LICENSE.model").write_text("Synthetic fixture only, not real model bytes")
    archive = tmp_path / "adviser.tar"
    manifest = package(source, archive, {"model_id": MODEL_ID, "revision": MODEL_REVISION})
    assert extract_verified(archive, target) == manifest
    (source / "model.gguf").write_bytes(b"corruption")
    with tarfile.open(archive, "w") as tar:
        for name in ("model.gguf", "LICENSE.model", "manifest.json"):
            tar.add(source / name, arcname=name)
    with pytest.raises(ValueError, match="hash or size"):
        extract_verified(archive, target)


@pytest.mark.parametrize(
    "name,kind",
    [
        ("../escape", tarfile.REGTYPE),
        ("/absolute", tarfile.REGTYPE),
        ("model.gguf", tarfile.SYMTYPE),
        ("worker.py", tarfile.REGTYPE),
    ],
)
def test_export_rejects_unsafe_archives(tmp_path, name, kind):
    archive = tmp_path / "evil.tar"
    with tarfile.open(archive, "w") as tar:
        for entry in (name, "LICENSE.model", "manifest.json"):
            info = tarfile.TarInfo(entry)
            info.type = kind if entry == name else tarfile.REGTYPE
            info.linkname = "/etc/passwd" if info.issym() else ""
            info.size = 0
            tar.addfile(info, io.BytesIO())
    with pytest.raises(ValueError, match="archive"):
        extract_verified(archive, tmp_path / "destination")
    assert not (tmp_path / "escape").exists()


@pytest.mark.parametrize("failure,code", [("exit", "COMMAND_FAILED"), ("timeout", "TIMEOUT")])
def test_failed_commands_have_durable_states(tmp_path, monkeypatch, failure, code):
    run = Run(tmp_path / "run")

    def failed(*args, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired("fixed-command", 1)
        return subprocess.CompletedProcess([], 1, "", "synthetic conversion failure")

    monkeypatch.setattr(subprocess, "run", failed)
    with pytest.raises(SpikeFailure):
        run.command("convert", ["fixed-command"], 1)
    events = [
        json.loads(line) for line in (run.directory / "events.jsonl").read_text().splitlines()
    ]
    assert [e["status"] for e in events] == ["started", "failed"]
    assert events[-1]["code"] == code


def test_training_mount_excludes_evaluation_and_cleanup_on_timeout(tmp_path, monkeypatch):
    run = Run(tmp_path / "run")
    commands = []

    def fake(*args, **kwargs):
        commands.append(args[0])
        if args[0][:2] == ["docker", "run"]:
            raise subprocess.TimeoutExpired("docker", 1)
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake)
    with pytest.raises(SpikeFailure):
        run.container(
            "train", "immutable-image", ["train"], [(tmp_path, "/input", False)], gpu=True
        )
    command = commands[0]
    assert "none" in command
    assert "--gpus" in command
    assert "--read-only" in command
    assert "--memory=10g" in command
    assert command[-2:] == ["immutable-image", "train"]
    assert commands[-1][:3] == ["docker", "rm", "-f"]


def test_wsl_gpu_mode_uses_only_explicit_device_and_readonly_drivers(tmp_path, monkeypatch):
    run = Run(tmp_path / "run", wsl_gpu=True)
    commands = []

    def fake(args, **kwargs):
        commands.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake)
    with monkeypatch.context() as paths:
        paths.setattr(Path, "exists", lambda path: True)
        paths.setattr(Path, "is_dir", lambda path: True)
        run.container("train", "immutable-image", ["train"], [], gpu=True)
    command = commands[0]
    assert "--gpus" not in command
    assert "--privileged" not in command
    assert command[command.index("--device") + 1] == "/dev/dxg"
    assert "type=bind,src=/usr/lib/wsl,dst=/usr/lib/wsl,readonly" in command
    assert "LD_LIBRARY_PATH=/usr/lib/wsl/lib" in command


def test_spike_does_not_add_web_ml_dependencies():
    project = (Path(__file__).parents[1] / "pyproject.toml").read_text()
    assert "torch" not in project
    assert "transformers" not in project


def test_cpu_preflight_never_submits_training(tmp_path, monkeypatch):
    from quartermaster.spike import run as runner

    run = Run(tmp_path / "run")
    (tmp_path / f"base-{MODEL_REVISION}").mkdir()
    commands, containers = [], []

    def command(stage, args, timeout):
        commands.append(args)
        return "sha256:synthetic-image"

    def container(stage, image, arguments, mounts, **kwargs):
        containers.append((stage, kwargs))

    monkeypatch.setattr(run, "command", command)
    monkeypatch.setattr(run, "container", container)
    monkeypatch.setattr(runner, "verify_snapshot", lambda base: None)
    monkeypatch.setattr(
        runner.shutil, "disk_usage", lambda path: SimpleNamespace(free=20_000_000_000)
    )
    runner.execute(run, skip_build=True, cpu_only=True)
    assert containers == [("preflight", {"timeout": 600})]
    assert all("quartermaster-spike-runtime:m1" not in command for command in commands)
    assert json.loads((run.directory / "evaluation.json").read_text())["split"] == "evaluation"


def test_validation_failure_does_not_mark_run_complete(tmp_path, monkeypatch):
    from quartermaster.spike import run as runner

    def invalid(*args, **kwargs):
        raise ValueError("Synthetic artifact corruption")

    monkeypatch.setattr(runner, "execute", invalid)
    monkeypatch.setattr("sys.argv", ["spike", "--run-gpu", "--data-dir", str(tmp_path)])
    with pytest.raises(SystemExit, match="Spike failed"):
        runner.main()
    events_path = next(tmp_path.glob("*/events.jsonl"))
    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    assert events[-1]["status"] == "failed"
    assert events[-1]["code"] == "ValueError"
    assert not any(event["status"] == "completed" for event in events)
