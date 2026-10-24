"""Explicit local CPU model preparation. No GPU, LoRA, business data or cloud job."""

import argparse
import json
from pathlib import Path
from uuid import uuid4

from quartermaster.local_runtime import sha256, verify
from quartermaster.spike.artifacts import verify_snapshot
from quartermaster.spike.run import ROOT, Run
from quartermaster.spike.spec import LLAMA_REVISION, MODEL_ID, MODEL_REVISION

TRAINER = "quartermaster-local-converter:m4"
RUNTIME = "quartermaster-local-runtime:m4"


def prepare(data_dir: Path, skip_build=False):
    directory = data_dir / "local-model"
    run = Run(data_dir / "local-setup" / str(uuid4()))
    try:
        existing = verify(directory) if directory.exists() else None
        if not skip_build:
            builds = [("adviser-runtime", RUNTIME)]
            if existing is None:
                builds.insert(0, ("trainer", TRAINER))
            for target, image in builds:
                run.command(
                    f"build-{target}",
                    [
                        "docker",
                        "build",
                        "-f",
                        "trainer/Dockerfile",
                        "--target",
                        target,
                        "-t",
                        image,
                        ".",
                    ],
                    1800,
                )
        if existing is not None:
            run.event("setup", "completed")
            print(f"Existing verified bundle: {directory}")
            print(f"QM_LOCAL_MODEL_SHA256={existing['sha256']}")
            return
        image = run.command(
            "converter-image", ["docker", "image", "inspect", TRAINER, "--format", "{{.Id}}"], 30
        )
        base = data_dir / "spike" / f"base-{MODEL_REVISION}"
        if not base.exists():
            base.mkdir(parents=True)
            run.container(
                "download", image, ["download"], [(base, "/output", True)], online=True, timeout=900
            )
        verify_snapshot(base)
        output = run.directory / "bundle"
        output.mkdir()
        run.container(
            "convert-base",
            image,
            ["convert-base"],
            [(base, "/base", False), (output, "/output", True)],
            timeout=1200,
        )
        model = output / "model.gguf"
        record = {
            "schema_version": "quartermaster.local-model/v1",
            "model_id": MODEL_ID,
            "revision": MODEL_REVISION,
            "llama_revision": LLAMA_REVISION,
            "adapter_artifact": None,
            "format": "GGUF-Q8_0",
            "sha256": sha256(model),
            "size_bytes": model.stat().st_size,
            "license_sha256": sha256(output / "LICENSE.model"),
        }
        (output / "manifest.json").write_text(json.dumps(record, indent=2) + "\n")
        verify(output)
        for file in output.iterdir():
            file.chmod(0o444)
        output.rename(directory)
        run.event("setup", "completed")
        print(f"Prepared unmodified pinned base model: {directory}")
        print(f"QM_LOCAL_MODEL_SHA256={record['sha256']}")
    except Exception as exc:
        run.event("setup", "failed", type(exc).__name__)
        raise SystemExit(
            f"Local setup failed ({type(exc).__name__}); inspect {run.directory}"
        ) from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()
    prepare(args.data_dir.resolve(), args.skip_build)


if __name__ == "__main__":
    main()
