"""Decision-only artifact verification. Never reinterpret these as full-advice artifacts."""

import json
from pathlib import Path

from quartermaster.contracts.decision_training import SYSTEM_SHA256, DecisionManifest
from quartermaster.spike.artifacts import check_gguf
from quartermaster.spike.spec import digest
from quartermaster.training_artifacts import verify_lora_structure


def bounded(path, maximum):
    path = Path(path)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("DECISION_LINK: Use regular artifact paths")
    if not path.is_file() or not 0 < path.stat().st_size <= maximum:
        raise ValueError("DECISION_FILE: Missing or oversized artifact")
    return path


def verify_adapter(output, job, job_sha256):
    output = Path(output)
    path = bounded(output / "training.json", 32_000)
    manifest = DecisionManifest.model_validate_json(path.read_bytes())
    if (
        manifest.job_id != job.id
        or manifest.job_sha256 != job_sha256
        or manifest.dataset_sha256 != job.dataset_sha256
        or manifest.recipe != job.recipe
        or manifest.completed_steps != job.recipe.steps
    ):
        raise ValueError("DECISION_LINEAGE: Adapter differs from the frozen decision job")
    adapter = output / "adapter"
    required = {"adapter_config.json", "adapter_model.safetensors"}
    if (
        adapter.is_symlink()
        or not required <= set(manifest.files) <= required | {"README.md"}
        or {p.name for p in adapter.iterdir()} != set(manifest.files)
    ):
        raise ValueError("DECISION_ADAPTER: Unexpected adapter files")
    for name, expected in manifest.files.items():
        if Path(name).name != name or digest(bounded(adapter / name, 20_000_000)) != expected:
            raise ValueError("DECISION_HASH: Adapter hash differs")
    verify_lora_structure(adapter, job.recipe)
    config = json.loads((adapter / "adapter_config.json").read_bytes())
    if (
        config.get("bias") != "none"
        or config.get("lora_dropout") != 0
        or config.get("use_rslora", False)
        or config.get("fan_in_fan_out", False)
        or config.get("lora_bias", False)
    ):
        raise ValueError("DECISION_CONFIG: Unsupported LoRA variant")
    return manifest


def conversion_record(output, training, job, job_sha256, base):
    """Called after safe CPU merge/conversion; records lineage without inventing a new model job."""
    model = bounded(output / "model.gguf", 3_000_000_000)
    check_gguf(model)
    license_file = bounded(output / "LICENSE.model", 100_000)
    if digest(license_file) != digest(base / "LICENSE"):
        raise ValueError("DECISION_LICENSE: Conversion changed the model license")
    return {
        "schema_version": "quartermaster.decision-conversion/v1",
        "job_sha256": job_sha256,
        "dataset_sha256": job.dataset_sha256,
        "training_manifest_sha256": digest(training / "training.json"),
        "model_revision": job.model_revision,
        "system_sha256": SYSTEM_SHA256,
        "response_contract": "DecisionOnly",
        "quantization": "q8_0",
        "files": {p.name: digest(p) for p in (model, license_file)},
        "automatic_promotion": False,
    }


def verify_conversion(output, training, job, job_sha256, base):
    verify_adapter(training, job, job_sha256)
    record = json.loads(bounded(output / "conversion.json", 32_000).read_bytes())
    expected = conversion_record(Path(output), Path(training), job, job_sha256, Path(base))
    if record != expected:
        raise ValueError("DECISION_CONVERSION: Portable model lineage or bytes changed")
    return record
