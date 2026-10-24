"""Dependency-free entry point for the optional local CPU service; never runs model code."""

import argparse
import hashlib
import json
import os
from pathlib import Path

# Keep these pins identical to spike/spec.py (checked by CPU tests).
MODEL_ID = "Qwen/Qwen3.5-0.8B"
MODEL_REVISION = "2fc06364715b967f1860aea9cf38778875588b17"
LLAMA_REVISION = "1a24df163920a4744a95373d178d790b72a9bb2f"


def sha256(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def verify(directory):
    manifest = directory / "manifest.json"
    if manifest.is_symlink() or manifest.stat().st_size > 4096:
        raise ValueError("Invalid local manifest")
    record = json.loads(manifest.read_bytes())
    expected = {
        "schema_version",
        "model_id",
        "revision",
        "llama_revision",
        "adapter_artifact",
        "format",
        "sha256",
        "size_bytes",
        "license_sha256",
    }
    if (
        set(record) != expected
        or record["schema_version"] != "quartermaster.local-model/v1"
        or record["model_id"] != MODEL_ID
        or record["revision"] != MODEL_REVISION
        or record["llama_revision"] != LLAMA_REVISION
        or record["adapter_artifact"] is not None
        or record["format"] != "GGUF-Q8_0"
    ):
        raise ValueError("Incompatible base model manifest")
    model, license_file = directory / "model.gguf", directory / "LICENSE.model"
    if model.is_symlink() or license_file.is_symlink():
        raise ValueError("Model links are unsupported")
    if (
        not 1_000_000 < model.stat().st_size < 3_000_000_000
        or model.stat().st_size != record["size_bytes"]
        or sha256(model) != record["sha256"]
        or not 0 < license_file.stat().st_size < 100_000
        or sha256(license_file) != record["license_sha256"]
    ):
        raise ValueError("Model or license hash/size mismatch")
    with model.open("rb") as stream:
        if stream.read(8) != b"GGUF\x03\x00\x00\x00":
            raise ValueError("Expected GGUF v3")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("/model"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        record = verify(args.directory)
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        raise SystemExit(
            "LOCAL_ARTIFACT: Recreate the pinned base bundle; verification failed."
        ) from None
    if args.check:
        print("Pinned local base model and license verified.")
        return
    alias = f"qm-base-{MODEL_REVISION}-{record['sha256']}"
    os.execvp(
        "llama-server",
        [
            "llama-server",
            "-m",
            str(args.directory / "model.gguf"),
            "--alias",
            alias,
            "--host",
            "0.0.0.0",
            "--port",
            "8080",
            "-c",
            "8192",
            "-t",
            "4",
            "-ngl",
            "0",
            "--parallel",
            "1",
            "--jinja",
            "--chat-template-kwargs",
            '{"enable_thinking":true}',
            "--reasoning-budget",
            "512",
            "--reasoning-format",
            "deepseek",
            "--no-webui",
            "--log-disable",
            "-n",
            "2048",
            "--no-context-shift",
        ],
    )


if __name__ == "__main__":
    main()
