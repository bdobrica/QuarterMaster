"""Opt-in bounded local selector stages; no promotion, retry or database access."""

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

from quartermaster.decision_training import checked_bundle, load_job, read_pack, write_new

LIMITS = {"cpu-drafts": 300, "cpu": 300, "gpu-preflight": 300, "train": 3600, "convert": 1200}


def command(stage, image, base, inputs, output, name, gpu_mode="nvidia", *, training=None):
    if stage not in LIMITS or not re.fullmatch(r"sha256:[a-f0-9]{64}", image):
        raise ValueError("DECISION_COMMAND: Use a supported stage and pinned image ID")
    if gpu_mode not in {"nvidia", "wsl"} or not re.fullmatch(r"qm-decision-[a-f0-9-]+", name):
        raise ValueError("DECISION_COMMAND: Invalid GPU mode or container name")
    paths = [Path(p) for p in (base, inputs, output)]
    if any(any(q.is_symlink() for q in (p, *p.parents)) or "," in str(p) for p in paths):
        raise ValueError("DECISION_PATH: Use controlled directories without symlinks or commas")
    args = [
        "docker",
        "run",
        "--name",
        name,
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--log-driver=none",
        "--cpus=4",
        "--memory=10g",
        "--memory-swap=10g",
        "--pids-limit=128",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--tmpfs",
        "/tmp:rw,nosuid,size=2g",
        "--env",
        "HF_HUB_OFFLINE=1",
        "--env",
        "TRANSFORMERS_OFFLINE=1",
    ]
    for path, target, readonly in zip(
        paths, ("/base", "/input", "/output"), (True, True, False), strict=True
    ):
        args += [
            "--mount",
            f"type=bind,src={path.resolve()},dst={target}" + (",readonly" if readonly else ""),
        ]
    if stage == "convert":
        if training is None or Path(training).is_symlink() or "," in str(training):
            raise ValueError("DECISION_PATH: Conversion requires the controlled training output")
        args += ["--mount", f"type=bind,src={Path(training).resolve()},dst=/training,readonly"]
    if stage in {"gpu-preflight", "train"}:
        if gpu_mode == "wsl":
            args += [
                "--device",
                "/dev/dxg",
                "--mount",
                "type=bind,src=/usr/lib/wsl,dst=/usr/lib/wsl,readonly",
                "--env",
                "LD_LIBRARY_PATH=/usr/lib/wsl/lib",
            ]
        else:
            args += ["--gpus", "all"]
    return [*args, image, stage]


def command_hash(args):
    return hashlib.sha256(json.dumps(args, separators=(",", ":")).encode()).hexdigest()


def run_stage(bundle, base, image, stage, *, run_gpu=False, authorization=None, gpu_mode="nvidia"):
    bundle = Path(bundle)
    if stage == "cpu-drafts":
        if {p.name for p in (bundle / "input").iterdir()} != {"pack.json"}:
            raise ValueError("DECISION_INPUT: Draft CPU mount must contain only the teaching pack")
        pack = read_pack(bundle / "input/pack.json")
        if pack.purpose != "teaching":
            raise ValueError("DECISION_DRAFT_PURPOSE: CPU drafts must be teaching only")
        identity = hashlib.sha256((bundle / "input/pack.json").read_bytes()).hexdigest()[:32]
        job = None
    else:
        job, _ = load_job(bundle / "input")
        checked_bundle(bundle, job)
        identity = str(job.id)
    name = "qm-decision-" + identity + "-" + hashlib.sha256(stage.encode()).hexdigest()[:6]
    output = bundle / "output" / stage
    training = bundle / "output/train"
    if job is not None:
        evaluation = (bundle / "evaluation.json").resolve()
        mounted = [Path(base), bundle / "input", output]
        if stage == "convert":
            mounted.append(training)
        if any(p.resolve() == evaluation or p.resolve() in evaluation.parents for p in mounted):
            raise ValueError("DECISION_EVALUATION_MOUNT: Evaluation must be outside every mount")
    args = command(
        stage,
        image,
        base,
        bundle / "input",
        output,
        name,
        gpu_mode,
        training=training if stage == "convert" else None,
    )
    if stage == "convert":
        from quartermaster.decision_artifacts import verify_adapter

        verify_adapter(
            training, job, hashlib.sha256((bundle / "input/job.json").read_bytes()).hexdigest()
        )
    if stage in {"gpu-preflight", "train"}:
        if run_gpu is not True or authorization is None:
            raise ValueError(
                "DECISION_GPU_AUTH: Owner-reviewed command and explicit opt-in required"
            )
        auth_path = Path(authorization)
        if auth_path.is_symlink() or auth_path.stat().st_size > 8000:
            raise ValueError("DECISION_GPU_AUTH: Invalid authorization record")
        auth = json.loads(auth_path.read_bytes())
        if (
            auth.get("approved") is not True
            or auth.get("reviewer") != "owner"
            or auth.get("job_sha256")
            != hashlib.sha256((bundle / "input/job.json").read_bytes()).hexdigest()
            or auth.get("commands", {}).get(stage) != command_hash(args)
            or auth.get("dataset_sha256") != job.dataset_sha256
            or auth.get("evaluation_sha256") != job.evaluation_sha256
        ):
            raise ValueError("DECISION_GPU_AUTH: Approval does not bind this job and command")
        snapshot = Path(base) / "snapshot.json"
        if (
            snapshot.is_symlink()
            or auth.get("base_snapshot_sha256") != hashlib.sha256(snapshot.read_bytes()).hexdigest()
        ):
            raise ValueError("DECISION_GPU_AUTH: Base snapshot commitment differs")
        prerequisite = "cpu" if stage == "gpu-preflight" else "gpu-preflight"
        result_path = bundle / "output" / prerequisite / "completed.json"
        if not result_path.is_file():
            raise ValueError("DECISION_PREFLIGHT: Complete the preceding bounded preflight")
        prior = json.loads(result_path.read_bytes())
        if (
            prior["job_sha256"]
            != hashlib.sha256((bundle / "input/job.json").read_bytes()).hexdigest()
            or prior["image"] != image
        ):
            raise ValueError("DECISION_PREFLIGHT: Preflight lineage differs")
        report_path = result_path.parent / prior["report"]
        if (
            Path(prior["report"]).name != prior["report"]
            or report_path.is_symlink()
            or hashlib.sha256(report_path.read_bytes()).hexdigest() != prior["report_sha256"]
        ):
            raise ValueError("DECISION_PREFLIGHT: Preflight report changed")
        report_data = json.loads(report_path.read_bytes())
        if stage == "gpu-preflight" and report_data.get("drafts_only") is not False:
            raise ValueError("DECISION_PREFLIGHT: Reviewed CPU checking is required")
        if stage == "train" and (
            report_data.get("optimizer_steps") != 1
            or report_data.get("candidate_created") is not False
        ):
            raise ValueError("DECISION_PREFLIGHT: Bounded one-step GPU result is required")
    # Existing stage directories are immutable attempt records, including failures.
    output.mkdir(parents=True, exist_ok=False)
    record = {
        "stage": stage,
        "image": image,
        "command_sha256": command_hash(args),
        "job_sha256": hashlib.sha256((bundle / "input/job.json").read_bytes()).hexdigest()
        if job
        else None,
        "seconds": LIMITS[stage],
        "automatic_retry": False,
    }
    write_new(output / "started.json", json.dumps(record).encode())
    success = False
    try:
        subprocess.run(
            args,
            check=True,
            timeout=LIMITS[stage] + 30,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        report = {
            "cpu-drafts": "cpu-preflight.json",
            "cpu": "cpu-preflight.json",
            "gpu-preflight": "gpu-preflight.json",
            "train": "training.json",
            "convert": "conversion.json",
        }[stage]
        path = output / report
        if path.is_symlink() or not 0 < path.stat().st_size < 200_000:
            raise ValueError("DECISION_REPORT: Missing or invalid stage result")
        data = json.loads(path.read_bytes())
        expected_input = (
            record["job_sha256"]
            if job
            else hashlib.sha256((bundle / "input/pack.json").read_bytes()).hexdigest()
        )
        if (
            stage in {"cpu-drafts", "cpu", "gpu-preflight"}
            and data.get("input_sha256", data.get("job_sha256")) != expected_input
        ):
            raise ValueError("DECISION_REPORT: Stage result lineage differs")
        if stage in {"cpu-drafts", "cpu"} and (
            data.get("training_started") is not False
            or data.get("gpu_capability_checked") is not False
        ):
            raise ValueError("DECISION_REPORT: CPU checking must not imply GPU readiness")
        if stage == "train":
            from quartermaster.decision_artifacts import verify_adapter

            verify_adapter(output, job, record["job_sha256"])
        if stage == "convert":
            from quartermaster.decision_artifacts import verify_conversion

            verify_conversion(output, training, job, record["job_sha256"], base)
        record["report"] = report
        record["report_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        success = True
    except BaseException:
        write_new(
            output / "failed.json", json.dumps({**record, "code": "DECISION_STAGE_FAILED"}).encode()
        )
        raise
    finally:
        try:
            cleanup = subprocess.run(
                ["docker", "rm", "-f", name],
                timeout=30,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            clean = cleanup.returncode == 0
        except (OSError, subprocess.SubprocessError):
            clean = False
        if not clean:
            write_new(output / "cleanup-required.json", json.dumps(record).encode())
            success = False
    if success:
        write_new(output / "completed.json", json.dumps(record).encode())
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=list(LIMITS))
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--gpu-mode", choices=["nvidia", "wsl"], default="nvidia")
    parser.add_argument("--run-gpu", action="store_true")
    parser.add_argument("--authorization", type=Path)
    args = parser.parse_args()
    try:
        run_stage(
            args.bundle,
            args.base,
            args.image,
            args.stage,
            run_gpu=args.run_gpu,
            authorization=args.authorization,
            gpu_mode=args.gpu_mode,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        raise SystemExit(
            "DECISION_STAGE_FAILED: Check review, hashes, resources and durable stage records; "
            "no automatic retry."
        ) from None


if __name__ == "__main__":
    main()
