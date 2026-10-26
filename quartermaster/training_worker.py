"""Opt-in host worker: one persisted job, one GPU, fixed commands and scoped mounts."""

import argparse
import asyncio
import fcntl
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from uuid import uuid4

from quartermaster import evaluations, teaching, training
from quartermaster.config import Settings
from quartermaster.contracts.teaching import GroundedAdvice
from quartermaster.contracts.training import AdviserVersion, CandidatePair, TrainingRun
from quartermaster.db import connect, migrate
from quartermaster.errors import DomainError
from quartermaster.generation import PARAMETERS, checked_parameters, completed_choice
from quartermaster.holdouts import require_eligible
from quartermaster.inference import model_alias, response_schema
from quartermaster.local_runtime import verify as verify_base_gguf
from quartermaster.spike.artifacts import verify_snapshot
from quartermaster.spike.spec import LLAMA_REVISION
from quartermaster.training_artifacts import portable_files, verify_adapter


class JobCanceled(Exception):
    pass


def current(settings, run):
    return training.get_run(settings, run.project_id, run.id)


def check_cancel(settings, run):
    latest = current(settings, run)
    if latest.cancel_requested:
        raise JobCanceled
    if latest.status not in training.ACTIVE:
        raise DomainError("TRAINING_STATE: Job is no longer running.")
    return latest


def advance(settings, run, status, **changes):
    with connect(settings.database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        latest = evaluations.read_document(
            connection, "training_runs", TrainingRun, run.project_id, run.id
        )
        if latest.cancel_requested:
            raise JobCanceled
        return training.update_run(
            connection,
            latest,
            status=status,
            log=[*latest.log[-98:], f"{status}: fixed local stage."],
            **changes,
        )


def claim(settings):
    with connect(settings.database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        records = [
            TrainingRun.model_validate_json(row[0])
            for row in connection.execute(
                "SELECT document FROM training_runs r WHERE revision=(SELECT MAX(revision) "
                "FROM training_runs WHERE id=r.id) ORDER BY rowid"
            )
        ]
        if any(r.status in training.ACTIVE for r in records):
            raise DomainError(
                "TRAINING_BUSY: Recover the previous worker before starting another.", 409
            )
        queued = next((r for r in records if r.status == "queued" and not r.cancel_requested), None)
        if queued:
            return training.update_run(
                connection,
                queued,
                status="preflight",
                log=[*queued.log, "preflight: checking local resources."],
            )


def recover(settings, engine):
    # Caller holds the host flock for the entire worker lifetime. Stop orphaned
    # containers before releasing the global GPU slot. Never retry an active job.
    with connect(settings.database_path) as connection:
        records = [
            TrainingRun.model_validate_json(row[0])
            for row in connection.execute(
                "SELECT document FROM training_runs r WHERE revision=(SELECT MAX(revision) "
                "FROM training_runs WHERE id=r.id)"
            )
        ]
        for run in records:
            if run.status in training.ACTIVE:
                engine.cleanup(run)
                training.update_run(
                    connection,
                    run,
                    status="canceled" if run.cancel_requested else "interrupted",
                    error="TRAINING_INTERRUPTED: Worker restarted; no automatic retry.",
                    log=[*run.log[-99:], "Stopped orphaned containers; explicit new job required."],
                )


def execute_next(settings, engine):
    run = claim(settings)
    if run is None:
        return None
    try:
        job = training.read_job(settings, run)
        # Recheck the exclusion under a write lock at actual dispatch too.
        with connect(settings.database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            require_eligible(connection, job.project_id, [e.case for e in job.examples])
        if job.schema_version == "quartermaster.training-job/v2":
            run = execute_predictions(settings, engine, run, job)
        else:
            output = training.directory(settings, run.id) / "output"
            output.mkdir(mode=0o700)
            pins = engine.preflight(run, job)
            run = advance(settings, run, "training", **pins)
            engine.train(run, job)
            run = advance(settings, run, "verifying")
            verify_adapter(output, job, run)
            run = advance(settings, run, "converting")
            (output / "portable").mkdir(mode=0o700)
            engine.convert(run, job)
            files = portable_files(output / "portable", job.model)
            run = advance(settings, run, "evaluating")
            suite = evaluations.get_suite(
                settings, run.project_id, job.suite_id, job.suite_revision
            )
            evaluations.verify_frozen(suite)
            if suite.frozen_sha256 != job.suite_sha256:
                raise DomainError("TRAINING_SUITE: Frozen evaluation lineage changed.")
            comparisons = engine.evaluate(run, job, suite, files)
            if [p.case_id for p in comparisons] != [c.id for c in suite.cases] or any(
                p.candidate.error
                or not p.candidate.checks.schema_valid
                or not p.candidate.checks.citations_valid
                or not p.candidate.checks.supporting_facts_valid
                for p in comparisons
            ):
                raise DomainError(
                    "CANDIDATE_SMOKE: Candidate advice failed structural or evidence checks."
                )
            for pair, frozen in zip(comparisons, suite.inputs, strict=True):
                if pair.baseline.input_sha256 != frozen.b.input_sha256 or (
                    pair.candidate.input_sha256 != frozen.b.input_sha256
                ):
                    raise DomainError(
                        "CANDIDATE_CONTEXT: Comparison must use identical frozen context."
                    )
            version = AdviserVersion(
                id=uuid4(),
                project_id=run.project_id,
                training_run_id=run.id,
                created_at=training.now(),
                job_sha256=run.job_sha256,
                training_manifest_sha256=training.hash_file(output / "training.json"),
                **files,
                trainer_image_id=run.trainer_image_id,
                runtime_image_id=run.runtime_image_id,
                suite_id=suite.id,
                suite_revision=suite.revision,
                suite_sha256=suite.frozen_sha256,
                smoke_passed=True,
                comparisons=comparisons,
            )
            # Publish a runtime locator only after verification. It is an immutable
            # manifest with UUID paths, never a command or an arbitrary local path.
            registry = settings.artifact_root / "candidates"
            if registry.is_symlink():
                raise DomainError("CANDIDATE_PATH: Restore the controlled registry.")
            registry.mkdir(exist_ok=True, mode=0o700)
            with connect(settings.database_path) as connection:
                connection.execute("BEGIN IMMEDIATE")
                latest = evaluations.read_document(
                    connection, "training_runs", TrainingRun, run.project_id, run.id
                )
                if latest.cancel_requested:
                    raise JobCanceled
                with (registry / f"{version.id}.json").open("x") as stream:
                    stream.write(version.model_dump_json())
                connection.execute(
                    "INSERT INTO adviser_versions VALUES (?, ?, ?)",
                    (str(version.id), str(run.project_id), version.model_dump_json()),
                )
                run = training.update_run(
                    connection,
                    latest,
                    status="completed",
                    candidate_id=version.id,
                    log=[
                        *latest.log[-99:],
                        "Candidate verified and evaluated. Active adviser unchanged.",
                    ],
                )
    except (Exception, KeyboardInterrupt) as exc:
        status = (
            "canceled"
            if isinstance(exc, JobCanceled)
            else ("interrupted" if isinstance(exc, KeyboardInterrupt) else "failed")
        )
        message = (
            exc.message
            if isinstance(exc, DomainError)
            else (
                "TRAINING_CANCELED: Job stopped; no candidate registered."
                if status == "canceled"
                else "TRAINING_FAILED: Check local GPU, disk, sequence length and pinned files. "
                "No automatic retry or promotion."
            )
        )
        with connect(settings.database_path) as connection:
            latest = evaluations.read_document(
                connection, "training_runs", TrainingRun, run.project_id, run.id
            )
            run = training.update_run(
                connection,
                latest,
                status=status,
                error=message,
                log=[*latest.log[-99:], status + ": explicit new job required."],
            )
    finally:
        try:
            engine.cleanup(run)
        except Exception:
            with connect(settings.database_path) as connection:
                latest = evaluations.read_document(
                    connection, "training_runs", TrainingRun, run.project_id, run.id
                )
                run = training.update_run(
                    connection,
                    latest,
                    status="cleanup_required",
                    candidate_id=None,
                    error="TRAINING_CLEANUP: Restore Docker and restart the worker to stop "
                    "orphaned containers before another job can run.",
                )
    return run


def execute_predictions(settings, engine, run, job):
    """Same bounded stages/queue, explicit v2 supervision and preference replay."""
    from quartermaster.contracts.prediction import PredictionCandidate
    from quartermaster.prediction_context import validate

    output = training.directory(settings, run.id) / "output"
    output.mkdir(mode=0o700)
    pins = engine.preflight(run, job)
    run = advance(settings, run, "training", **pins)
    engine.train(run, job)
    run = advance(settings, run, "verifying")
    verify_adapter(output, job, run)
    run = advance(settings, run, "converting")
    (output / "portable").mkdir(mode=0o700)
    engine.convert(run, job)
    files = portable_files(output / "portable", job.model)
    run = advance(settings, run, "evaluating")
    pairs = engine.evaluate(run, job, job, files)
    if [p.case_id for p in pairs] != [e.case.case_id for e in job.examples[:5]]:
        raise DomainError("CANDIDATE_CONTEXT: Replay every selected case once.")
    for pair, entry in zip(pairs, job.examples[:5], strict=True):
        if pair.candidate.error or pair.candidate.prediction is None:
            raise DomainError("CANDIDATE_SMOKE: The candidate did not return a valid prediction.")
        validate(pair.candidate.prediction, entry.input)
        if (
            pair.baseline.input_sha256 != entry.input.input_sha256
            or pair.candidate.input_sha256 != entry.input.input_sha256
        ):
            raise DomainError("CANDIDATE_CONTEXT: Compare on identical captured inputs.")
        if pair.baseline.prediction is not None:
            validate(pair.baseline.prediction, entry.input)
    version = PredictionCandidate(
        id=uuid4(),
        project_id=run.project_id,
        training_run_id=run.id,
        created_at=training.now(),
        job_sha256=run.job_sha256,
        training_manifest_sha256=training.hash_file(output / "training.json"),
        **files,
        trainer_image_id=run.trainer_image_id,
        runtime_image_id=run.runtime_image_id,
        baseline=job.baseline,
        answer_format=job.answer_format,
        teaching_sha256=job.teaching_sha256,
        smoke_passed=True,
        comparisons=pairs,
    )
    registry = settings.artifact_root / "candidates"
    if registry.is_symlink():
        raise DomainError("CANDIDATE_PATH: Restore the controlled registry.")
    registry.mkdir(exist_ok=True, mode=0o700)
    with connect(settings.database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        latest = evaluations.read_document(
            connection, "training_runs", TrainingRun, run.project_id, run.id
        )
        if latest.cancel_requested:
            raise JobCanceled
        with (registry / f"{version.id}.json").open("x") as stream:
            stream.write(version.model_dump_json())
        connection.execute(
            "INSERT INTO adviser_versions VALUES (?, ?, ?)",
            (str(version.id), str(run.project_id), version.model_dump_json()),
        )
        return training.update_run(
            connection,
            latest,
            status="completed",
            candidate_id=version.id,
            log=[
                *latest.log[-99:],
                "New adviser version ready. Review the comparison before selecting it.",
            ],
        )


class DockerInference:
    def __init__(self, engine, run, name, alias):
        self.engine, self.run, self.name, self.alias = engine, run, name, alias

    async def advise(self, *, system, context, parameters=None):
        raw = await self.complete(system, context, parameters, response_schema(context))
        return GroundedAdvice.model_validate_json(raw)

    async def predict(self, *, system, context, parameters=None):
        from quartermaster.prediction_context import parse_answer, schema_for

        raw = await self.complete(system, context, parameters, schema_for(context))
        return parse_answer(raw, context)

    async def complete(self, system, context, parameters, schema):
        parameters = checked_parameters(parameters)
        check_cancel(self.engine.settings, self.run)
        payload = {
            "model": self.alias,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": context},
            ],
            **parameters,
            "stream": False,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "grounded_advice",
                    "strict": True,
                    "schema": schema,
                },
            },
        }
        script = (
            "import sys,json,urllib.request; "
            "models=json.load(urllib.request.urlopen("
            "'http://127.0.0.1:8080/v1/models',timeout=5)); "
            f"assert [m['id'] for m in models['data']]==[{self.alias!r}]; "
            "body=sys.stdin.buffer.read(); "
            "r=urllib.request.Request('http://127.0.0.1:8080/v1/chat/completions',"
            "data=body,headers={'Content-Type':'application/json'}); "
            "print(urllib.request.urlopen(r,timeout=180).read(131073).decode())"
        )
        raw = await asyncio.to_thread(
            self.engine.command,
            ["docker", "exec", "-i", self.name, "python", "-c", script],
            190,
            json.dumps(payload),
        )
        if len(raw) > 131072:
            raise DomainError("CANDIDATE_SIZE: Model response exceeded the size limit.")
        response = json.loads(raw)
        if response.get("model") != self.alias:
            raise DomainError("CANDIDATE_IDENTITY: The model returned a different identity.")
        return completed_choice(response)


class DockerEngine:
    def __init__(self, settings, base, base_gguf, trainer_image, runtime_image, gpu_mode="nvidia"):
        self.settings, self.base, self.base_gguf = settings, base.resolve(), base_gguf.resolve()
        self.trainer_image, self.runtime_image, self.gpu_mode = (
            trainer_image,
            runtime_image,
            gpu_mode,
        )
        for value in (trainer_image, runtime_image):
            if not re.fullmatch(r"sha256:[a-f0-9]{64}", value):
                raise DomainError(
                    "TRAINING_IMAGE: Supply exact local sha256 image IDs, never tags."
                )

    def command(self, args, timeout=30, input_text=None):
        try:
            result = subprocess.run(
                args, input=input_text, capture_output=True, text=True, timeout=timeout, check=False
            )
            if result.returncode:
                raise DomainError(
                    "TRAINING_CONTAINER: Local container command failed. "
                    "Check GPU support, resources and image compatibility."
                )
            return result.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            raise DomainError(
                "TRAINING_TIMEOUT: Local command failed or exceeded its time limit."
            ) from None

    def name(self, run, stage):
        return f"qm-training-{run.id}-{stage}"

    def args(self, run, stage, image, mounts, gpu=False, model=None):
        from quartermaster.model_pins import CAPABLE_REVISION

        large = model is not None and model.base_revision == CAPABLE_REVISION
        memory = "24g" if large and stage == "convert" else "10g"
        args = [
            "docker",
            "run",
            "-d",
            "--pull=never",
            "--name",
            self.name(run, stage),
            "--init",
            "--read-only",
            "--network=none",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--pids-limit=256",
            f"--memory={memory}",
            f"--memory-swap={memory}",
            "--cpus=4",
            "--log-driver=none",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--tmpfs",
            "/tmp:rw,nosuid,size=512m",
        ]
        if gpu:
            if self.gpu_mode == "wsl":
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
            resolved = source.resolve()
            if source.is_symlink() or "," in str(resolved):
                raise DomainError(
                    "TRAINING_MOUNT: Use controlled directories without links or commas."
                )
            args += [
                "--mount",
                f"type=bind,src={resolved},dst={target}" + ("" if writable else ",readonly"),
            ]
        if image == self.trainer_image:
            args += [
                "-e",
                "HF_HUB_OFFLINE=1",
                "-e",
                "TRANSFORMERS_OFFLINE=1",
                "--entrypoint",
                "python",
                image,
                "/opt/trainer/job_worker.py",
            ]
        else:
            args += ["--entrypoint", "timeout", image, "1300", "llama-server"]
        return args

    def stage(self, run, job, stage, mounts, gpu=False):
        self.command([*self.args(run, stage, self.trainer_image, mounts, gpu, job.model), stage])
        deadline = time.monotonic() + (job.recipe.seconds + 30 if stage == "train" else 1230)
        while time.monotonic() < deadline:
            check_cancel(self.settings, run)
            state = json.loads(
                self.command(
                    ["docker", "inspect", self.name(run, stage), "--format", "{{json .State}}"]
                )
            )
            if not state["Running"]:
                if state["ExitCode"] != 0 or state.get("OOMKilled"):
                    raise DomainError(
                        f"TRAINING_{stage.upper()}: Stage failed. Check GPU, RAM, "
                        "disk and the 2048-token sequence limit. No automatic retry."
                    )
                return
            time.sleep(1)
        raise DomainError("TRAINING_DEADLINE: Stage exceeded its finite time limit.")

    def preflight(self, run, job):
        if shutil.disk_usage(self.settings.data_dir).free < 12_000_000_000:
            raise DomainError("TRAINING_DISK: Free at least 12 GB plus Docker image space.")
        from quartermaster.model_pins import CAPABLE_REVISION

        if job.model.base_revision == CAPABLE_REVISION:
            if shutil.disk_usage(self.settings.data_dir).free < 32_000_000_000:
                raise DomainError("TRAINING_DISK: Free at least 32 GB for the installed model.")
            verify_snapshot(
                self.base, model_id=job.model.base_model_id, revision=job.model.base_revision
            )
        else:
            verify_snapshot(self.base)
        self.base_record = verify_base_gguf(self.base_gguf)
        if (
            self.base_record["model_id"] != job.model.base_model_id
            or self.base_record["revision"] != job.model.base_revision
        ):
            raise DomainError(
                "TRAINING_BASE: Use the original and portable files for this adviser's base."
            )
        runtime = json.loads(self.command(["docker", "image", "inspect", self.runtime_image]))[0]
        trainer = json.loads(self.command(["docker", "image", "inspect", self.trainer_image]))[0]
        if (
            runtime["Config"].get("Labels", {}).get("org.opencontainers.image.revision")
            != LLAMA_REVISION
            or trainer["Config"].get("Labels", {}).get("io.quartermaster.training-contract")
            != job.schema_version
            or (
                job.recipe.schema_version == "quartermaster.lora-recipe/v2"
                and trainer["Config"].get("Labels", {}).get("io.quartermaster.training-recipe")
                != "quartermaster.lora-recipe/v2"
            )
            or (
                job.schema_version == "quartermaster.training-job/v2"
                and any(e.input.prompt_version == "context/v6" for e in job.examples)
                and trainer["Config"].get("Labels", {}).get("io.quartermaster.prediction-context")
                != "context/v6"
            )
        ):
            raise DomainError("TRAINING_IMAGE: Build the documented pinned trainer/runtime stages.")
        folder = training.directory(self.settings, run.id)
        self.stage(
            run,
            job,
            "preflight",
            [
                (self.base, "/base", False),
                (folder / "input", "/input", False),
                (folder / "output", "/output", True),
            ],
            gpu=True,
        )
        return {
            "trainer_image_id": self.trainer_image.removeprefix("sha256:"),
            "runtime_image_id": self.runtime_image.removeprefix("sha256:"),
        }

    def train(self, run, job):
        folder = training.directory(self.settings, run.id)
        self.stage(
            run,
            job,
            "train",
            [
                (self.base, "/base", False),
                (folder / "input", "/input", False),
                (folder / "output", "/output", True),
            ],
            gpu=True,
        )

    def convert(self, run, job):
        folder = training.directory(self.settings, run.id)
        self.stage(
            run,
            job,
            "convert",
            [
                (self.base, "/base", False),
                (folder / "input", "/input", False),
                (folder / "output/adapter", "/adapter", False),
                (folder / "output/portable", "/output", True),
            ],
        )

    async def compare(self, run, suite, files):
        outputs = {}
        generic = getattr(suite, "schema_version", None) == "quartermaster.training-job/v2"
        baseline_path, baseline_sha = self.base_gguf, self.base_record["sha256"]
        baseline_alias = (
            model_alias(baseline_sha, suite.model.base_revision)
            if generic
            else model_alias(baseline_sha)
        )
        if generic and suite.baseline.adapter_artifact:
            from quartermaster.training_artifacts import verify_candidate

            version = training.get_version(
                self.settings, run.project_id, suite.baseline.adapter_artifact
            )
            if (
                version.schema_version != "quartermaster.adviser-version/v2"
                or version.answer_format != suite.answer_format
            ):
                raise DomainError(
                    "CANDIDATE_BASELINE: Selected adviser uses a different answer format."
                )
            baseline_path = verify_candidate(self.settings, version)
            baseline_sha = version.model_sha256
            baseline_alias = f"qm-candidate-{baseline_sha}"
        async with asyncio.timeout(evaluations.RUN_SECONDS):
            for variant, path, sha in (
                ("baseline", baseline_path, baseline_sha),
                (
                    "candidate",
                    training.directory(self.settings, run.id) / "output/portable",
                    files["model_sha256"],
                ),
            ):
                alias = baseline_alias if variant == "baseline" else f"qm-candidate-{sha}"
                name = self.name(run, variant)
                args = self.args(run, variant, self.runtime_image, [(path, "/model", False)])
                self.command(
                    [
                        *args,
                        "-m",
                        "/model/model.gguf",
                        "--alias",
                        alias,
                        "--host",
                        "127.0.0.1",
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
                        '{"enable_thinking":false}',
                        "--no-webui",
                        "--log-disable",
                        "-n",
                        str(PARAMETERS["max_tokens"]),
                        "--no-context-shift",
                    ]
                )
                probe = "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health',timeout=2)"
                for _ in range(60):
                    check_cancel(self.settings, run)
                    result = subprocess.run(
                        ["docker", "exec", name, "python", "-c", probe],
                        capture_output=True,
                        timeout=5,
                    )
                    if result.returncode == 0:
                        break
                    await asyncio.sleep(1)
                else:
                    raise DomainError("CANDIDATE_START: CPU runtime did not become healthy.")
                adapter = DockerInference(self, run, name, alias)
                outputs[variant] = []
                if generic:
                    from quartermaster.predictions import generate

                    for entry in suite.examples[:5]:
                        check_cancel(self.settings, run)
                        outputs[variant].append(await generate(adapter, entry.input))
                    self.command(["docker", "rm", "-f", name])
                    continue
                for entry, pair in zip(suite.cases, suite.inputs, strict=True):
                    checked_parameters(pair.b.parameters)
                    if (
                        pair.b.model_alias != model_alias(self.base_record["sha256"])
                        or pair.b.system != teaching.SYSTEM
                        or pair.b.response_schema != response_schema(pair.b.context)
                    ):
                        raise DomainError(
                            "CANDIDATE_RUNTIME: Frozen baseline model or prompt differs."
                        )
                    check_cancel(self.settings, run)
                    output = await evaluations.evaluate_output(
                        self.settings, adapter, run.project_id, entry, pair.b
                    )
                    outputs[variant].append(output)
                    with (training.directory(self.settings, run.id) / "comparison.jsonl").open(
                        "a"
                    ) as stream:
                        stream.write(
                            json.dumps(
                                {"variant": variant, "output": output.model_dump(mode="json")}
                            )
                            + "\n"
                        )
                self.command(["docker", "rm", "-f", name])
        if generic:
            from quartermaster.contracts.prediction import PredictionPair

            return [
                PredictionPair(case_id=e.case.case_id, baseline=a, candidate=b)
                for e, a, b in zip(
                    suite.examples[:5], outputs["baseline"], outputs["candidate"], strict=True
                )
            ]
        return [
            CandidatePair(case_id=entry.id, baseline=a, candidate=b)
            for entry, a, b in zip(
                suite.cases, outputs["baseline"], outputs["candidate"], strict=True
            )
        ]

    def evaluate(self, run, job, suite, files):
        return asyncio.run(self.compare(run, suite, files))

    def cleanup(self, run):
        names = set(self.command(["docker", "ps", "-a", "--format", "{{.Names}}"]).splitlines())
        for stage in ("preflight", "train", "convert", "baseline", "candidate"):
            name = self.name(run, stage)
            if name in names:
                self.command(["docker", "rm", "-f", name])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-gpu", action="store_true", required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--base-gguf", type=Path, required=True)
    parser.add_argument("--trainer-image", required=True)
    parser.add_argument("--runtime-image", required=True)
    parser.add_argument("--gpu-mode", choices=["nvidia", "wsl"], default="nvidia")
    args = parser.parse_args()
    settings = Settings(data_dir=args.data_dir.resolve(), _env_file=None)
    # Use the same bind-mounted data directory as the web app. No Docker socket
    # or training control privilege is ever mounted into the web service.
    if not settings.database_path.exists():
        parser.error("Use the existing app data directory; see docs/operator-guide.md.")
    migrate(settings.database_path)
    engine = DockerEngine(
        settings, args.base, args.base_gguf, args.trainer_image, args.runtime_image, args.gpu_mode
    )
    with (settings.data_dir / "training-worker.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("TRAINING_BUSY: Another local worker holds the queue lock.") from None
        recover(settings, engine)
        run = execute_next(settings, engine)
        print(f"Job {run.id}: {run.status}" if run else "No queued training job.")
        if run and run.status != "completed":
            raise SystemExit(1)


if __name__ == "__main__":
    main()
