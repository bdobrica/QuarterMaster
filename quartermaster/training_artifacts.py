"""Fail-closed file verification shared with the optional trainer, without ML dependencies."""

import json
from pathlib import Path

from quartermaster.contracts.training import TrainingManifest
from quartermaster.errors import DomainError
from quartermaster.spike.spec import MODEL_ID, MODEL_REVISION


def verify_adapter(output, job, run):
    from quartermaster.training import hash_file

    manifest_path = output / "training.json"
    if manifest_path.is_symlink() or manifest_path.stat().st_size > 32_000:
        raise DomainError("TRAINING_MANIFEST: Invalid artifact manifest.")
    manifest = TrainingManifest.model_validate_json(manifest_path.read_bytes())
    if (
        manifest.job_id != run.id
        or manifest.job_sha256 != run.job_sha256
        or manifest.dataset_sha256 != run.dataset_sha256
        or manifest.model != job.model
        or manifest.recipe != job.recipe
        or manifest.completed_steps != job.recipe.steps
    ):
        raise DomainError("TRAINING_LINEAGE: Adapter does not match the frozen job.")
    adapter = output / "adapter"
    names = {p.name for p in adapter.iterdir()}
    required = {"adapter_config.json", "adapter_model.safetensors"}
    if (
        not required <= names
        or not names <= required | {"README.md"}
        or names != set(manifest.files)
    ):
        raise DomainError("TRAINING_FILES: Missing or unexpected adapter files.")
    for name, record in manifest.files.items():
        path = adapter / name
        if (
            Path(name).name != name
            or path.is_symlink()
            or path.stat().st_size != record.size_bytes
            or hash_file(path) != record.sha256
        ):
            raise DomainError("TRAINING_HASH: Adapter file hash or size mismatch.")
    verify_lora_structure(adapter, job.recipe)
    return manifest


def verify_lora_structure(adapter, recipe):
    """Shared fixed-model PEFT/framing checks; callers verify their own versioned lineage."""
    if (adapter / "adapter_config.json").stat().st_size > 32_000:
        raise DomainError("TRAINING_CONFIG: Adapter configuration is too large.")
    config = json.loads((adapter / "adapter_config.json").read_bytes())
    if (
        config.get("base_model_name_or_path") != MODEL_ID
        or config.get("revision") != MODEL_REVISION
        or config.get("peft_type") != "LORA"
        or config.get("task_type") != "CAUSAL_LM"
        or config.get("r") != recipe.rank
        or config.get("lora_alpha") != recipe.alpha
        or set(config.get("target_modules", [])) != {"q_proj", "v_proj"}
        or config.get("use_dora", False)
        or config.get("modules_to_save")
        or config.get("rank_pattern")
        or config.get("alpha_pattern")
    ):
        raise DomainError("TRAINING_CONFIG: Unexpected adapter recipe or base revision.")
    # Check safetensors framing without importing Torch or accepting pickle weights.
    path = adapter / "adapter_model.safetensors"
    with path.open("rb") as stream:
        length = int.from_bytes(stream.read(8), "little")
        if not 2 < length < 1_000_000 or length + 8 >= path.stat().st_size:
            raise DomainError("TRAINING_TENSORS: Invalid safetensors header.")
        header = json.loads(stream.read(length))
    tensors = {k: v for k, v in header.items() if k != "__metadata__"}
    if not tensors or not any("lora_B" in k for k in tensors):
        raise DomainError("TRAINING_TENSORS: Adapter contains no LoRA update.")
    for name, value in tensors.items():
        offsets = value["data_offsets"]
        if (
            not ("lora_A" in name or "lora_B" in name)
            or value["dtype"] not in {"F32", "F16", "BF16"}
            or len(value["shape"]) != 2
            or recipe.rank not in value["shape"]
            or len(offsets) != 2
            or not 0 <= offsets[0] < offsets[1]
            or offsets[1] > path.stat().st_size - length - 8
        ):
            raise DomainError("TRAINING_TENSORS: Unexpected LoRA tensor structure.")


def portable_files(path):
    from quartermaster.training import hash_file

    model, license_file = path / "model.gguf", path / "LICENSE.model"
    if path.is_symlink() or model.is_symlink() or license_file.is_symlink():
        raise DomainError("CANDIDATE_PATH: Model links are not supported.")
    if not 1_000_000 < model.stat().st_size < 3_000_000_000:
        raise DomainError("CANDIDATE_FORMAT: Model size is invalid.")
    with model.open("rb") as stream:
        if stream.read(8) != b"GGUF\x03\x00\x00\x00":
            raise DomainError("CANDIDATE_FORMAT: Expected a GGUF v3 model.")
    if not 0 < license_file.stat().st_size < 100_000:
        raise DomainError("CANDIDATE_LICENSE: Missing model license.")
    return {
        "model_sha256": hash_file(model),
        "model_size_bytes": model.stat().st_size,
        "license_sha256": hash_file(license_file),
    }


def verify_candidate(settings, version):
    try:
        return verified_candidate(settings, version)
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        raise DomainError("CANDIDATE_INVALID: Restore the verified candidate files.", 409) from None


def verified_candidate(settings, version):
    from quartermaster.training import directory, get_run, hash_file, read_job

    run = get_run(settings, version.project_id, version.training_run_id)
    job = read_job(settings, run)
    output = directory(settings, run.id) / "output"
    verify_adapter(output, job, run)
    files = portable_files(output / "portable")
    if (
        version.job_sha256 != run.job_sha256
        or hash_file(output / "training.json") != version.training_manifest_sha256
        or any(getattr(version, key) != value for key, value in files.items())
    ):
        raise DomainError("CANDIDATE_HASH: Restore the verified candidate artifacts.", 409)
    return output / "portable"
