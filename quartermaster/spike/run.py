"""Opt-in local vertical spike. Ordinary web startup and tests never invoke Docker/ML."""

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from quartermaster.contracts.advice import Advice
from quartermaster.spike.artifacts import (
    extract_verified,
    package,
    require_review,
    verify_adapter,
    verify_snapshot,
)
from quartermaster.spike.spec import (
    LLAMA_REVISION,
    MAX_NEW_TOKENS,
    MODEL_ID,
    MODEL_REVISION,
    RUNTIME_IMAGE,
    TRAINER_IMAGE,
    digest,
    load_pair,
    messages,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/spike"


class SpikeFailure(RuntimeError):
    pass


class Run:
    def __init__(self, directory: Path, *, wsl_gpu=False):
        directory.mkdir(parents=True, exist_ok=False)
        self.directory = directory
        self.id = uuid4().hex
        self.wsl_gpu = wsl_gpu

    def event(self, stage, status, code=None):
        # Append-only events survive a failed subprocess or a later invocation.
        with (self.directory / "events.jsonl").open("a") as stream:
            stream.write(
                json.dumps(
                    {
                        "at": datetime.now(UTC).isoformat(),
                        "stage": stage,
                        "status": status,
                        "code": code,
                        "gpu_mode": "wsl" if self.wsl_gpu else "nvidia",
                    }
                )
                + "\n"
            )

    def command(self, stage, args, timeout, *, input_text=None):
        self.event(stage, "started")
        try:
            result = subprocess.run(
                args,
                input=input_text,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=ROOT,
                check=False,
            )
            # This command path processes only the reviewed synthetic fixtures.
            (self.directory / f"{stage}.log").write_text(
                (result.stdout + result.stderr)[-1_000_000:]
            )
            if result.returncode:
                raise SpikeFailure(
                    f"{stage}: subprocess exited {result.returncode}; inspect run log"
                )
        except subprocess.TimeoutExpired as exc:
            self.event(stage, "failed", "TIMEOUT")
            raise SpikeFailure(f"{stage}: finite time limit exceeded") from exc
        except (OSError, SpikeFailure):
            self.event(stage, "failed", "COMMAND_FAILED")
            raise
        self.event(stage, "completed")
        return result.stdout.strip()

    def container(self, stage, image, arguments, mounts, *, gpu=False, online=False, timeout=1200):
        name = f"qm-spike-{self.id}-{stage}"
        args = [
            "docker",
            "run",
            "--rm",
            "--name",
            name,
            "--init",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--pids-limit=256",
            "--memory=10g",
            "--memory-swap=10g",
            "--cpus=4",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--tmpfs",
            "/tmp:rw,nosuid,size=512m",
            "--network",
            "bridge" if online else "none",
        ]
        if gpu:
            if self.wsl_gpu:
                if not Path("/dev/dxg").exists() or not Path("/usr/lib/wsl/lib").is_dir():
                    raise SpikeFailure("WSL mode requires /dev/dxg and /usr/lib/wsl/lib")
                args += [
                    "--device",
                    "/dev/dxg",
                    "--mount",
                    "type=bind,src=/usr/lib/wsl,dst=/usr/lib/wsl,readonly",
                    "-e",
                    "LD_LIBRARY_PATH=/usr/lib/wsl/lib",
                ]
            else:
                args += ["--gpus", "all"]
        for source, target, writable in mounts:
            args += [
                "--mount",
                f"type=bind,src={source.resolve()},dst={target}"
                + ("" if writable else ",readonly"),
            ]
        if not online:
            args += ["-e", "HF_HUB_OFFLINE=1", "-e", "TRANSFORMERS_OFFLINE=1"]
        try:
            self.command(stage, [*args, image, *arguments], timeout)
        finally:
            # A killed Docker client does not necessarily stop its container.
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=30)


def smoke_export(run: Run, archive: Path, evaluation: Path):
    _, fixture = load_pair(FIXTURES / "train.json", evaluation)
    with tempfile.TemporaryDirectory(prefix="isolated-", dir=run.directory) as temporary:
        extracted = Path(temporary)
        manifest = extract_verified(archive, extracted)
        if manifest["evaluation_sha256"] != digest(evaluation):
            raise ValueError("Export check must use the original frozen evaluation fixture")
        runtime_id = run.command(
            "runtime-image",
            ["docker", "image", "inspect", RUNTIME_IMAGE, "--format", "{{.Id}}"],
            30,
        )
        if runtime_id != manifest["runtime_image_id"]:
            raise ValueError("Runtime image differs from the pinned export build")
        name = f"qm-spike-{run.id}-runtime"
        try:
            run.command(
                "runtime-start",
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    name,
                    "--network=none",
                    "--read-only",
                    "--cap-drop=ALL",
                    "--security-opt=no-new-privileges",
                    "--pids-limit=128",
                    "--memory=4g",
                    "--memory-swap=4g",
                    "--cpus=4",
                    "--user",
                    f"{os.getuid()}:{os.getgid()}",
                    "--tmpfs",
                    "/tmp:rw,nosuid,size=64m",
                    "--mount",
                    f"type=bind,src={extracted.resolve()},dst=/model,readonly",
                    runtime_id,
                    "-m",
                    "/model/model.gguf",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "8080",
                    "-c",
                    "2048",
                    "-t",
                    "4",
                    "-ngl",
                    "0",
                    "--parallel",
                    "1",
                    "--jinja",
                    "--chat-template-kwargs",
                    '{"enable_thinking":false}',
                    "--no-webui",
                ],
                60,
            )
            probe = (
                "import urllib.request; "
                "print(urllib.request.urlopen('http://127.0.0.1:8080/health',timeout=2).read().decode())"
            )
            # One finite readiness wait, never an automatic retraining retry.
            for _ in range(60):
                result = subprocess.run(
                    ["docker", "exec", name, "python", "-c", probe],
                    capture_output=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    break
                time.sleep(1)
            else:
                raise SpikeFailure("Isolated runtime did not become healthy within 60 probes")
            outputs = []
            request_script = (
                "import sys,urllib.request; "
                "data=sys.stdin.buffer.read(); "
                "request=urllib.request.Request('http://127.0.0.1:8080/v1/chat/completions',"
                "data=data,headers={'Content-Type':'application/json'}); "
                "print(urllib.request.urlopen(request,timeout=180).read().decode())"
            )
            for i, example in enumerate(fixture.examples):
                payload = {
                    "messages": messages(fixture.mission, example.case),
                    "temperature": 0,
                    "seed": 17,
                    "max_tokens": MAX_NEW_TOKENS,
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "advice",
                            "strict": True,
                            "schema": Advice.model_json_schema(),
                        },
                    },
                }
                started = time.monotonic()
                response = json.loads(
                    run.command(
                        f"runtime-case-{i}",
                        ["docker", "exec", "-i", name, "python", "-c", request_script],
                        200,
                        input_text=json.dumps(payload),
                    )
                )
                content = response["choices"][0]["message"]["content"]
                advice = Advice.model_validate_json(content)
                advice.check_evidence(set())
                if bool(advice.clarification_question) != bool(
                    example.advice.clarification_question
                ):
                    raise SpikeFailure(
                        "Runtime clarification behavior differs from the held-out rubric"
                    )
                outputs.append(
                    {
                        "case_id": str(example.case.case_id),
                        "advice": advice.model_dump(mode="json"),
                        "elapsed_seconds": time.monotonic() - started,
                        "usage": response.get("usage"),
                    }
                )
            report = {
                "schema_version": "quartermaster.spike-runtime-check/v1",
                "network": "none",
                "gpu_layers": 0,
                "cpus": 4,
                "memory_limit": "4g",
                "archive_sha256": digest(archive),
                "evaluation_sha256": digest(evaluation),
                "runtime_image_id": runtime_id,
                "outputs": outputs,
            }
            (run.directory / "runtime.json").write_text(json.dumps(report, indent=2) + "\n")
            return report
        finally:
            logs = subprocess.run(
                ["docker", "logs", name], capture_output=True, text=True, timeout=15
            )
            (run.directory / "runtime.log").write_text((logs.stdout + logs.stderr)[-1_000_000:])
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=30)


def execute(run: Run, skip_build=False, cpu_only=False):
    train, evaluation = FIXTURES / "train.json", FIXTURES / "evaluation.json"
    require_review(train, FIXTURES / "review.json")
    _, held_out = load_pair(train, evaluation)
    if shutil.disk_usage(run.directory).free < 12_000_000_000:
        raise SpikeFailure("At least 12 GB free disk is required (plus Docker image space)")
    if not skip_build:
        builds = [("trainer", TRAINER_IMAGE)]
        if not cpu_only:
            builds.append(("runtime", RUNTIME_IMAGE))
        for stage, image in builds:
            run.command(
                f"build-{stage}",
                [
                    "docker",
                    "build",
                    "-f",
                    "trainer/Dockerfile",
                    "--target",
                    stage,
                    "-t",
                    image,
                    ".",
                ],
                1800,
            )
    images = [("trainer-image", TRAINER_IMAGE)]
    if not cpu_only:
        images.append(("runtime-image", RUNTIME_IMAGE))
    image_ids = {
        label: run.command(label, ["docker", "image", "inspect", image, "--format", "{{.Id}}"], 30)
        for label, image in images
    }
    # A shared immutable snapshot saves downloads; a partial/corrupt one fails closed.
    base = run.directory.parent / f"base-{MODEL_REVISION}"
    if not base.exists():
        base.mkdir()
        run.container(
            "download",
            image_ids["trainer-image"],
            ["download"],
            [
                (base, "/output", True),
            ],
            online=True,
            timeout=900,
        )
    verify_snapshot(base)
    train_input, infer_input = run.directory / "train-input", run.directory / "infer-input"
    train_input.mkdir()
    infer_input.mkdir()
    shutil.copyfile(train, train_input / "train.json")
    shutil.copyfile(FIXTURES / "review.json", train_input / "review.json")
    shutil.copyfile(FIXTURES / "review.json", run.directory / "review.json")
    # Freeze the held-out targets on the host; only stripped decision inputs reach comparison.
    frozen_evaluation = run.directory / "evaluation.json"
    shutil.copyfile(evaluation, frozen_evaluation)
    evaluation = frozen_evaluation
    preflight_output = run.directory / "preflight"
    preflight_output.mkdir()
    run.container(
        "preflight",
        image_ids["trainer-image"],
        ["preflight"],
        [
            (base, "/base", False),
            (train_input, "/input", False),
            (preflight_output, "/output", True),
        ],
        timeout=600,
    )
    if cpu_only:
        return
    (infer_input / "cases.json").write_text(
        json.dumps(
            [
                {"case_id": str(e.case.case_id), "messages": messages(held_out.mission, e.case)}
                for e in held_out.examples
            ]
        )
    )
    training, comparison, portable = (
        run.directory / name for name in ("training", "comparison", "portable")
    )
    for path in (training, comparison, portable):
        path.mkdir()
    run.container(
        "train",
        image_ids["trainer-image"],
        ["train"],
        [
            (base, "/base", False),
            (train_input, "/input", False),
            (training, "/output", True),
        ],
        gpu=True,
    )
    verify_adapter(training, digest(train))
    run.container(
        "compare",
        image_ids["trainer-image"],
        ["compare"],
        [
            (base, "/base", False),
            (infer_input, "/input", False),
            (training / "adapter", "/adapter", False),
            (comparison, "/output", True),
        ],
        gpu=True,
        timeout=900,
    )
    summary = {}
    for variant in ("base", "adapter"):
        rows = json.loads((comparison / f"{variant}.json").read_text())
        if [r["case_id"] for r in rows] != [str(e.case.case_id) for e in held_out.examples]:
            raise ValueError("Comparison does not cover the frozen evaluation inputs")
        checks = []
        for row, expected in zip(rows, held_out.examples, strict=True):
            try:
                advice = Advice.model_validate_json(row["content"])
                advice.check_evidence(set())
                checks.append(
                    {
                        "schema_valid": True,
                        "clarification_matches": bool(advice.clarification_question)
                        == bool(expected.advice.clarification_question),
                    }
                )
            except ValueError:
                checks.append({"schema_valid": False, "clarification_matches": False})
        summary[variant] = checks
    (comparison / "checks.json").write_text(json.dumps(summary, indent=2) + "\n")
    run.container(
        "convert",
        image_ids["trainer-image"],
        ["convert"],
        [
            (base, "/base", False),
            (training / "adapter", "/adapter", False),
            (portable, "/output", True),
        ],
        timeout=1200,
    )
    archive = run.directory / "adviser.tar"
    package(
        portable,
        archive,
        {
            "model_id": MODEL_ID,
            "revision": MODEL_REVISION,
            "llama_revision": LLAMA_REVISION,
            "format": "GGUF-Q8_0",
            "train_sha256": digest(train),
            "evaluation_sha256": digest(evaluation),
            "training_manifest_sha256": digest(training / "training.json"),
            "trainer_image_id": image_ids["trainer-image"],
            "runtime_image_id": image_ids["runtime-image"],
            "gpu_mode": "wsl" if run.wsl_gpu else "nvidia",
        },
    )
    smoke_export(run, archive, evaluation)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--run-gpu", action="store_true", help="Opt in to the fixed local GPU job")
    choice.add_argument(
        "--check-cpu", action="store_true", help="Only verify real base text inference"
    )
    choice.add_argument("--export", type=Path, help="Check an existing spike archive; no training")
    parser.add_argument("--skip-build", action="store_true", help="Use already-built local images")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data/spike")
    parser.add_argument(
        "--gpu-mode",
        choices=["nvidia", "wsl"],
        default="nvidia",
        help="Use standard NVIDIA Toolkit passthrough or explicit read-only WSL driver mounts",
    )
    args = parser.parse_args()
    run = Run(args.data_dir.resolve() / str(uuid4()), wsl_gpu=args.gpu_mode == "wsl")
    print(f"Verification artifacts: {run.directory}", flush=True)
    run.event("run", "started")
    try:
        if args.run_gpu or args.check_cpu:
            execute(run, args.skip_build, cpu_only=args.check_cpu)
        else:
            smoke_export(run, args.export.resolve(), FIXTURES / "evaluation.json")
    except KeyboardInterrupt:
        run.event("run", "interrupted", "CANCELED")
        raise SystemExit("Spike interrupted; no automatic retry") from None
    except Exception as exc:
        run.event("run", "failed", type(exc).__name__)
        # No raw model inputs, host environment or credentials are echoed.
        raise SystemExit(f"Spike failed ({type(exc).__name__}); inspect {run.directory}") from None
    run.event("run", "completed")
    if args.check_cpu:
        print("CPU text preflight passed; LoRA and export remain unverified by this command.")
    else:
        print("Spike passed; this proves format/runtime feasibility, not model quality.")


if __name__ == "__main__":
    main()
