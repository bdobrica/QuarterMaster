"""Fail-closed checks for the spike's deliberately small artifact set."""

import json
import tarfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from quartermaster.spike.spec import MODEL_ID, MODEL_REVISION, digest


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: str
    train_sha256: str
    review_state: str
    reviewer: str
    reviewed_on: str
    scope: str


def require_review(train: Path, review: Path) -> None:
    record = Review.model_validate_json(review.read_bytes())
    if (
        record.schema_version != "quartermaster.spike-review/v1"
        or record.review_state != "approved"
        or not record.reviewer.strip()
        or record.train_sha256 != digest(train)
    ):
        raise ValueError("Training fixture lacks matching explicit human approval")


def verify_snapshot(base: Path) -> None:
    record = json.loads((base / "snapshot.json").read_text())
    if record["model_id"] != MODEL_ID or record["revision"] != MODEL_REVISION:
        raise ValueError("Wrong base model snapshot")
    if not record["files"] or "LICENSE" not in record["files"]:
        raise ValueError("Missing base model files/license")
    for name, expected in record["files"].items():
        if Path(name).name != name or (base / name).is_symlink():
            raise ValueError("Unsafe snapshot file")
        if digest(base / name) != expected:
            raise ValueError("Base model snapshot hash mismatch")


def verify_adapter(directory: Path, train_sha: str) -> dict:
    manifest = json.loads((directory / "training.json").read_text())
    if (
        manifest["schema_version"] != "quartermaster.spike-training/v1"
        or manifest["model_id"] != MODEL_ID
        or manifest["revision"] != MODEL_REVISION
        or manifest["train_sha256"] != train_sha
        or manifest["steps"] != 12
    ):
        raise ValueError("Adapter lineage or completed steps mismatch")
    adapter = directory / "adapter"
    config = json.loads((adapter / "adapter_config.json").read_text())
    if (
        config["base_model_name_or_path"] != MODEL_ID
        or config["revision"] != MODEL_REVISION
        or config["peft_type"] != "LORA"
        or config["task_type"] != "CAUSAL_LM"
        or config["r"] != 4
        or config["lora_alpha"] != 8
        or set(config["target_modules"]) != {"q_proj", "v_proj"}
    ):
        raise ValueError("Unexpected adapter recipe")
    names = {p.name for p in adapter.iterdir()}
    if not {"adapter_config.json", "adapter_model.safetensors"} <= names:
        raise ValueError("Adapter is missing required files")
    if not names <= {"adapter_config.json", "adapter_model.safetensors", "README.md"}:
        raise ValueError("Unexpected adapter file")
    if set(manifest["adapter_hashes"]) != names:
        raise ValueError("Incomplete adapter hashes")
    for name in names:
        if (adapter / name).is_symlink() or digest(adapter / name) != manifest["adapter_hashes"][
            name
        ]:
            raise ValueError("Adapter hash mismatch")
    weights = adapter / "adapter_model.safetensors"
    if weights.stat().st_size < 100 or weights.stat().st_size > 20_000_000:
        raise ValueError("Adapter size outside this fixed recipe's bounds")
    return manifest


def check_gguf(path: Path) -> None:
    if path.is_symlink() or not 1_000_000 < path.stat().st_size < 3_000_000_000:
        raise ValueError("Missing or implausibly sized portable model")
    with path.open("rb") as stream:
        if stream.read(8) != b"GGUF\x03\x00\x00\x00":
            raise ValueError("Expected GGUF version 3")


PACKAGE_FILES = {"model.gguf", "LICENSE.model", "manifest.json"}


def package(directory: Path, archive: Path, lineage: dict) -> dict:
    check_gguf(directory / "model.gguf")
    if not (directory / "LICENSE.model").read_text().strip():
        raise ValueError("Missing model license")
    manifest = {
        "schema_version": "quartermaster.spike-export/v1",
        **lineage,
        "files": {
            name: {"sha256": digest(directory / name), "bytes": (directory / name).stat().st_size}
            for name in ("model.gguf", "LICENSE.model")
        },
    }
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    with tarfile.open(archive, "w") as tar:
        for name in sorted(PACKAGE_FILES):
            tar.add(directory / name, arcname=name, recursive=False)
    return manifest


def extract_verified(archive: Path, destination: Path) -> dict:
    # Extract only the fixed data files: no scripts, links, directories or arbitrary paths.
    with tarfile.open(archive) as tar:
        members = tar.getmembers()
        if len(members) != 3 or {m.name for m in members} != PACKAGE_FILES:
            raise ValueError("Unexpected export archive paths")
        if any(not m.isfile() or m.size > 3_000_000_000 for m in members):
            raise ValueError("Unsupported export archive entry")
        tar.extractall(destination, filter="data")
    manifest = json.loads((destination / "manifest.json").read_text())
    if (
        manifest["schema_version"] != "quartermaster.spike-export/v1"
        or manifest["model_id"] != MODEL_ID
        or manifest["revision"] != MODEL_REVISION
        or set(manifest["files"]) != {"model.gguf", "LICENSE.model"}
    ):
        raise ValueError("Incompatible export manifest")
    for name, expected in manifest["files"].items():
        path = destination / name
        if digest(path) != expected["sha256"] or path.stat().st_size != expected["bytes"]:
            raise ValueError("Export hash or size mismatch")
    check_gguf(destination / "model.gguf")
    return manifest
