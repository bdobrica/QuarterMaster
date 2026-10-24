"""Deterministic CPU fixtures, not real training or an owner-validated model result."""

import importlib.util
import json
import struct
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_decision_training import IMAGE, pack

from quartermaster.contracts.advice import DecisionOnly
from quartermaster.contracts.decision_training import SYSTEM_SHA256, DecisionManifest
from quartermaster.decision_artifacts import conversion_record, verify_adapter, verify_conversion
from quartermaster.decision_comparison import comparison_inputs, run_comparison, runtime_command
from quartermaster.decision_runtime import payload
from quartermaster.decision_training import freeze
from quartermaster.decision_worker import command, run_stage
from quartermaster.errors import DomainError
from quartermaster.generation import PARAMETERS
from quartermaster.spike.spec import digest


def fixture(tmp_path):
    root, base = tmp_path / "bundle", tmp_path / "base"
    base.mkdir()
    (base / "LICENSE").write_text("CPU fixture only")
    job = freeze(pack(), pack("evaluation"), root, independent_owner_review=True)
    training = root / "output/train"
    adapter = training / "adapter"
    adapter.mkdir(parents=True)
    config = dict(
        base_model_name_or_path=job.model_id,
        revision=job.model_revision,
        peft_type="LORA",
        task_type="CAUSAL_LM",
        r=4,
        lora_alpha=8,
        target_modules=["q_proj", "v_proj"],
        bias="none",
        lora_dropout=0,
    )
    (adapter / "adapter_config.json").write_text(json.dumps(config))
    header = json.dumps(
        {
            "base.q_proj.lora_A.weight": {"dtype": "F32", "shape": [4, 4], "data_offsets": [0, 64]},
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
    manifest = DecisionManifest(
        job_id=job.id,
        job_sha256=digest(root / "input/job.json"),
        dataset_sha256=job.dataset_sha256,
        recipe=job.recipe,
        completed_steps=120,
        training_loss=1,
        peak_vram_bytes=1,
        files={p.name: digest(p) for p in adapter.iterdir()},
    )
    (training / "training.json").write_text(manifest.model_dump_json())
    converted = root / "output/convert"
    converted.mkdir()
    # Format fixture only, never used to claim real GGUF compatibility.
    (converted / "model.gguf").write_bytes(b"GGUF\x03\x00\x00\x00" + b"x" * 1_000_000)
    (converted / "LICENSE.model").write_bytes((base / "LICENSE").read_bytes())
    (converted / "conversion.json").write_text(
        json.dumps(
            conversion_record(converted, training, job, digest(root / "input/job.json"), base)
        )
    )
    base_gguf = tmp_path / "base.gguf"
    base_gguf.write_bytes(b"GGUF\x03\x00\x00\x00" + b"b" * 1_000_000)
    plan = {
        "job_sha256": digest(root / "input/job.json"),
        "dataset_sha256": job.dataset_sha256,
        "evaluation_sha256": job.evaluation_sha256,
        "system_sha256": SYSTEM_SHA256,
        "response_schema": DecisionOnly.model_json_schema(),
        "generation_parameters": PARAMETERS,
        "unchanged_base_model_sha256": digest(base_gguf),
    }
    (root / "comparison-plan.json").write_text(json.dumps(plan))
    return root, base, base_gguf, job


def test_conversion_keeps_decision_lineage_and_rejects_changes(tmp_path):
    root, base, _, job = fixture(tmp_path)
    training, converted = root / "output/train", root / "output/convert"
    record = verify_conversion(converted, training, job, digest(root / "input/job.json"), base)
    assert (
        record["response_contract"] == "DecisionOnly" and record["system_sha256"] == SYSTEM_SHA256
    )
    (converted / "model.gguf").write_bytes((converted / "model.gguf").read_bytes() + b"x")
    with pytest.raises(ValueError, match="DECISION_CONVERSION"):
        verify_conversion(converted, training, job, digest(root / "input/job.json"), base)
    (training / "adapter/adapter_model.safetensors").write_bytes(b"changed")
    with pytest.raises(ValueError, match="DECISION_HASH"):
        verify_adapter(training, job, digest(root / "input/job.json"))


@pytest.mark.parametrize(
    "change", ["job", "dataset", "schema", "config", "tensor", "extra", "link"]
)
def test_adapter_rejects_wrong_contract_lineage_and_structure(tmp_path, change):
    root, _, _, job = fixture(tmp_path)
    training = root / "output/train"
    manifest = json.loads((training / "training.json").read_bytes())
    if change in {"job", "dataset"}:
        manifest[change + "_sha256"] = "0" * 64
    elif change == "schema":
        manifest["schema_version"] = "quartermaster.training-artifacts/v1"
    elif change == "extra":
        (training / "adapter/unsafe.py").write_text("never execute")
    elif change == "link":
        (training / "adapter/README.md").symlink_to(training / "training.json")
        manifest["files"]["README.md"] = digest(training / "training.json")
    else:
        path = (
            training
            / "adapter"
            / ("adapter_config.json" if change == "config" else "adapter_model.safetensors")
        )
        if change == "config":
            config = json.loads(path.read_bytes())
            config["use_rslora"] = True
            path.write_text(json.dumps(config))
        else:
            path.write_bytes(b"broken safe tensor header")
        manifest["files"][path.name] = digest(path)
    (training / "training.json").write_text(json.dumps(manifest))
    with pytest.raises((ValueError, DomainError)):
        verify_adapter(training, job, digest(root / "input/job.json"))


def test_conversion_command_mounts_no_evaluation_and_never_uses_gpu(tmp_path):
    root, base, _, job = fixture(tmp_path)
    args = command(
        "convert",
        IMAGE,
        base,
        root / "input",
        root / "out",
        "qm-decision-abcd",
        training=root / "output/train",
    )
    assert "--gpus" not in args and "/dev/dxg" not in args
    assert all("evaluation" not in arg for arg in args)
    assert any("dst=/training,readonly" in arg for arg in args)
    assert {p.name for p in (root / "input").iterdir()} == {"job.json", "train.jsonl"}
    wire = (root / "input/job.json").read_text() + (root / "input/train.jsonl").read_text()
    suite, _, inputs = comparison_inputs(root, job)
    for example in suite.examples:
        assert str(example.id) not in wire and example.context not in wire
    assert set(inputs) == {"schema_version", "system", "response_schema", "parameters", "cases"}
    assert all(set(row) == {"id", "context"} for row in inputs["cases"])
    runtime = runtime_command(
        IMAGE,
        root / "model.gguf",
        root / "selected",
        root / "out",
        "qm-decision-abcd",
        "a" * 64,
        1200,
    )
    assert "--network=none" in runtime and "--memory=8g" in runtime
    assert all("training" not in arg and "evaluation" not in arg for arg in runtime)
    with pytest.raises(ValueError, match="DECISION_EVALUATION_MOUNT"):
        run_stage(root, root, IMAGE, "gpu-preflight")


@pytest.mark.parametrize(
    "failure",
    [
        None,
        "length",
        "duplicate",
        "extra",
        "identity",
        "tools",
        "refusal",
        "timeout",
        "missing",
        "truncated",
        "settings",
        "cleanup",
    ],
)
def test_paired_harness_uses_identical_inputs_and_counts_every_failure(
    tmp_path, monkeypatch, failure
):
    root, base, base_gguf, job = fixture(tmp_path)
    suite, _, inputs = comparison_inputs(root, job)
    destination = tmp_path / "comparison"
    calls = []

    def execute(args, **kwargs):
        calls.append(args)
        if args[1] == "rm":
            return SimpleNamespace(returncode=1 if failure == "cleanup" else 0)
        mounts = [args[i + 1] for i, arg in enumerate(args) if arg == "--mount"]
        output = Path(next(m.split("src=")[1].split(",")[0] for m in mounts if "dst=/output" in m))
        sha = args[args.index("--model-sha256") + 1]
        alias = "qm-decision-" + sha
        candidate = output.name == "candidate"
        for i, case in enumerate(inputs["cases"]):
            if candidate and i == 0 and failure == "missing":
                continue
            label = (
                suite.examples[i].target.model_dump_json() if candidate else '{"decision":"answer"}'
            )
            if candidate and i == 0 and failure == "duplicate":
                label = '{"decision":"answer","decision":"abstain"}'
            if candidate and i == 0 and failure == "extra":
                label = '{"decision":"answer","reason":"extra"}'
            response = {
                "model": alias,
                "choices": [{"finish_reason": "stop", "message": {"content": label}}],
                "__verbose": {
                    "truncated": False,
                    "generation_settings": {
                        "temperature": 0,
                        "seed": 17,
                        "max_tokens": 1024,
                        "n_predict": 1024,
                        "n_probs": 5,
                        "post_sampling_probs": False,
                        "lora": [],
                        "grammar": "test",
                    },
                },
            }
            if candidate and i == 0:
                if failure == "length":
                    response["choices"][0]["finish_reason"] = "length"
                if failure == "identity":
                    response["model"] = "wrong-model"
                if failure == "truncated":
                    response["__verbose"]["truncated"] = True
                if failure == "settings":
                    response["__verbose"]["generation_settings"]["seed"] = 0
                if failure in {"tools", "refusal"}:
                    response["choices"][0]["message"][
                        "tool_calls" if failure == "tools" else "refusal"
                    ] = "unsupported"
            record = {
                "id": case["id"],
                "input_sha256": digest(destination / "input/inputs.json"),
                "model_sha256": sha,
                "request": payload(inputs, case, alias),
                "response": response,
                "error": None,
            }
            (output / f"{case['id']}.json").write_text(json.dumps(record))
        if candidate and failure == "timeout":
            # Preserve already received records but still fail the execution gate.
            raise subprocess.TimeoutExpired(args, 1200)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", execute)
    result = run_comparison(root, base, base_gguf, IMAGE, destination)
    assert result["baseline"]["total"] == result["candidate"]["total"] == 30
    invalid = failure in {
        "length",
        "duplicate",
        "extra",
        "identity",
        "tools",
        "refusal",
        "missing",
        "truncated",
        "settings",
    }
    assert result["candidate"]["invalid"] == int(invalid)
    assert result["candidate"]["correct"] == 30 - int(invalid)
    assert result["all_proposed_gates_passed"] == (failure is None)
    assert result["automatic_promotion"] is False
    assert len(calls) == 4  # Two containers, two targeted cleanups, no retries.
    assert inputs == json.loads((destination / "input/inputs.json").read_bytes())
    with pytest.raises(FileExistsError):
        run_comparison(root, base, base_gguf, IMAGE, destination)


def test_contract_drift_blocks_generation_before_output_creation(tmp_path):
    root, base, base_gguf, _ = fixture(tmp_path)
    plan = json.loads((root / "comparison-plan.json").read_bytes())
    plan["response_schema"]["properties"]["decision"]["enum"].reverse()
    (root / "comparison-plan.json").write_text(json.dumps(plan))
    with pytest.raises(ValueError, match="DECISION_COMPARISON_PLAN"):
        run_comparison(root, base, base_gguf, IMAGE, tmp_path / "no")
    assert not (tmp_path / "no").exists()


def test_container_conversion_calls_safe_merge_only_after_manifest_verification(
    tmp_path, monkeypatch
):
    trainer = Path(__file__).resolve().parents[1] / "trainer"
    monkeypatch.syspath_prepend(str(trainer))
    spec = importlib.util.spec_from_file_location(
        "selector_conversion_worker", trainer / "decision_worker.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root, base, _, job = fixture(tmp_path)
    training = root / "output/train"
    # Ordinary CI intentionally uses no torch dependency. Fake only tensor math, not lineage.
    import sys

    class Tensors:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def keys(self):
            return ["base.q_proj.lora_B.weight"]

        def get_tensor(self, name):
            return object()

    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(
            isfinite=lambda x: SimpleNamespace(all=lambda: True), count_nonzero=lambda x: 1
        ),
    )
    monkeypatch.setitem(
        sys.modules, "safetensors", SimpleNamespace(safe_open=lambda *a, **kw: Tensors())
    )
    calls = []

    def convert(base_arg, adapter_arg, output):
        calls.append((base_arg, adapter_arg))
        (output / "model.gguf").write_bytes((root / "output/convert/model.gguf").read_bytes())
        (output / "LICENSE.model").write_bytes((base_arg / "LICENSE").read_bytes())

    monkeypatch.setattr(module, "convert", convert)
    output = tmp_path / "converted"
    output.mkdir()
    module.convert_decision(base, training, output, job, digest(root / "input/job.json"))
    assert calls == [(base, training / "adapter")]
    assert verify_conversion(output, training, job, digest(root / "input/job.json"), base)
    (training / "adapter/adapter_config.json").write_text("{}")
    with pytest.raises(ValueError):
        module.convert_decision(base, training, output, job, digest(root / "input/job.json"))
    assert len(calls) == 1


def test_conversion_timeout_is_durable_and_has_no_gpu_retry(tmp_path, monkeypatch):
    root, base, _, _ = fixture(tmp_path)
    # The fixture has an existing successful-looking CPU conversion; move it aside for this attempt.
    (root / "output/convert").rename(root / "output/fixture-convert")
    calls = []

    def execute(args, **kwargs):
        calls.append(args)
        if args[1] == "run":
            assert kwargs["timeout"] == 1230
            raise subprocess.TimeoutExpired(args, 1230)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", execute)
    with pytest.raises(subprocess.TimeoutExpired):
        run_stage(root, base, IMAGE, "convert")
    assert (root / "output/convert/failed.json").exists()
    assert not (root / "output/convert/completed.json").exists()
    assert len(calls) == 2
