"""One bounded paired frozen comparison. Invalid and missing attempts remain in denominators."""

import argparse
import json
import math
import os
import re
import subprocess
import time
from pathlib import Path

from quartermaster.contracts.advice import DecisionOnly
from quartermaster.contracts.decision_training import SYSTEM_SHA256, unique_keys
from quartermaster.decision_artifacts import bounded, verify_conversion
from quartermaster.decision_runtime import payload
from quartermaster.decision_training import checked_bundle, load_job, read_pack, score, write_new
from quartermaster.decision_worker import command_hash
from quartermaster.errors import DomainError
from quartermaster.generation import PARAMETERS, completed_choice
from quartermaster.spike.artifacts import check_gguf
from quartermaster.spike.spec import digest

SECONDS = 1200


def comparison_inputs(bundle, job):
    checked_bundle(bundle, job)
    plan = json.loads(bounded(bundle / "comparison-plan.json", 32_000).read_bytes())
    if (
        plan["job_sha256"] != digest(bundle / "input/job.json")
        or plan["dataset_sha256"] != job.dataset_sha256
        or plan["evaluation_sha256"] != job.evaluation_sha256
        or plan["system_sha256"] != SYSTEM_SHA256
        or plan["response_schema"] != DecisionOnly.model_json_schema()
        or plan["generation_parameters"] != PARAMETERS
    ):
        raise ValueError("DECISION_COMPARISON_PLAN: Frozen contract or lineage differs")
    suite = read_pack(bundle / "evaluation.json")
    if suite.system != job.supervision.system:
        raise ValueError("DECISION_SYSTEM: Teaching and evaluation contracts must match exactly")
    return (
        suite,
        plan,
        {
            "schema_version": "quartermaster.decision-generation-inputs/v1",
            "system": suite.system,
            "response_schema": plan["response_schema"],
            "parameters": plan["generation_parameters"],
            "cases": [{"id": str(e.id), "context": e.context} for e in suite.examples],
        },
    )


def runtime_command(image, model, inputs, output, name, model_sha256, seconds):
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", image):
        raise ValueError("DECISION_IMAGE: Pin the runtime image")
    if not re.fullmatch(r"qm-decision-[a-f0-9-]+", name) or not 1 <= seconds <= SECONDS:
        raise ValueError("DECISION_COMMAND: Invalid runtime name or deadline")
    paths = [Path(p) for p in (model, inputs, output)]
    if any(
        any(p.is_symlink() for p in (path, *path.parents)) or "," in str(path) for path in paths
    ):
        raise ValueError("DECISION_PATH: Use controlled regular paths")
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
        "--memory=8g",
        "--memory-swap=8g",
        "--pids-limit=128",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--tmpfs",
        "/tmp:rw,nosuid,size=256m",
    ]
    for path, target, readonly in zip(
        paths, ("/model/model.gguf", "/input", "/output"), (True, True, False), strict=True
    ):
        args += [
            "--mount",
            f"type=bind,src={path.resolve()},dst={target}" + (",readonly" if readonly else ""),
        ]
    return [*args, image, "--model-sha256", model_sha256, "--seconds", str(seconds)]


def outputs_from_records(directory, inputs, model_sha256):
    """Only complete, identity-matched responses reach the strict scorer; keep raw failures."""
    outputs, errors = {}, {}
    alias = "qm-decision-" + model_sha256
    input_sha256 = digest(directory.parent / "input/inputs.json")
    for case in inputs["cases"]:
        key = case["id"]
        outputs[key] = None
        try:
            record = json.loads(bounded(directory / f"{key}.json", 100_000).read_bytes())
            if (
                record["id"] != key
                or record["input_sha256"] != input_sha256
                or record["model_sha256"] != model_sha256
                or record["request"] != payload(inputs, case, alias)
                or record["error"] is not None
                or record["response"]["model"] != alias
            ):
                raise ValueError("DECISION_RESPONSE_IDENTITY")
            raw = completed_choice(record["response"])
            diagnostic = record["response"]["__verbose"]
            actual = diagnostic["generation_settings"]
            expected = {
                "temperature": 0,
                "seed": 17,
                "max_tokens": 1024,
                "n_predict": 1024,
                "n_probs": 5,
                "post_sampling_probs": False,
                "lora": [],
            }
            if (
                diagnostic["truncated"] is not False
                or any(actual.get(key) != value for key, value in expected.items())
                or not actual.get("grammar")
            ):
                raise ValueError("DECISION_RUNTIME_SETTINGS")
            # Unlike model_validate_json, this rejects repeated decision keys.
            DecisionOnly.model_validate(json.loads(raw, object_pairs_hook=unique_keys))
            outputs[key] = raw
        except (OSError, ValueError, KeyError, TypeError, IndexError, DomainError):
            errors[key] = "DECISION_OUTPUT_INVALID_OR_MISSING"
    return outputs, errors


def run_comparison(bundle, base, base_gguf, image, destination):
    bundle, base, base_gguf, destination = map(Path, (bundle, base, base_gguf, destination))
    job, _ = load_job(bundle / "input")
    suite, plan, inputs = comparison_inputs(bundle, job)
    converted, training = bundle / "output/convert", bundle / "output/train"
    conversion = verify_conversion(
        converted, training, job, digest(bundle / "input/job.json"), base
    )
    check_gguf(base_gguf)
    if digest(base_gguf) != plan["unchanged_base_model_sha256"]:
        raise ValueError("DECISION_BASE: Use the frozen unchanged base GGUF")
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "input").mkdir()
    write_new(destination / "input/inputs.json", json.dumps(inputs, ensure_ascii=False).encode())
    started = {
        "schema_version": "quartermaster.decision-comparison-attempt/v1",
        "job_sha256": digest(bundle / "input/job.json"),
        "evaluation_sha256": job.evaluation_sha256,
        "input_sha256": digest(destination / "input/inputs.json"),
        "image": image,
        "conversion_sha256": digest(converted / "conversion.json"),
        "seconds": SECONDS,
        "maximum_generations": 60,
        "automatic_retry": False,
        "automatic_promotion": False,
    }
    write_new(destination / "started.json", json.dumps(started).encode())
    end = time.monotonic() + SECONDS
    all_outputs, failures = {}, {}
    for arm, model, sha in (
        ("base", base_gguf, plan["unchanged_base_model_sha256"]),
        ("candidate", converted / "model.gguf", conversion["files"]["model.gguf"]),
    ):
        output = destination / arm
        output.mkdir()
        name = "qm-decision-" + str(job.id) + ("-ba" if arm == "base" else "-ca")
        remaining = max(1, min(SECONDS, math.floor(end - time.monotonic())))
        args = runtime_command(image, model, destination / "input", output, name, sha, remaining)
        record = {"command": args, "command_sha256": command_hash(args), "seconds": remaining}
        write_new(output / "started.json", json.dumps(record).encode())
        try:
            if end <= time.monotonic():
                raise TimeoutError("DECISION_COMPARISON_DEADLINE")
            subprocess.run(
                args,
                check=True,
                timeout=remaining + 30,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.SubprocessError):
            failures[arm] = "DECISION_RUNTIME_FAILED"
            write_new(
                output / "failed.json", json.dumps({**record, "code": failures[arm]}).encode()
            )
        finally:
            try:
                clean = (
                    subprocess.run(
                        ["docker", "rm", "-f", name],
                        timeout=30,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    ).returncode
                    == 0
                )
            except (OSError, subprocess.SubprocessError):
                clean = False
            if not clean:
                failures[arm] = "DECISION_CLEANUP_REQUIRED"
                write_new(output / "cleanup-required.json", json.dumps(record).encode())
        all_outputs[arm], errors = outputs_from_records(output, inputs, sha)
        write_new(
            output / "validation.json",
            json.dumps({"errors": errors, "total": len(inputs["cases"])}).encode(),
        )
    result = score(suite, all_outputs["base"], all_outputs["candidate"])
    result["execution_failures"] = failures
    result["execution_succeeded"] = not failures
    result["all_proposed_gates_passed"] &= not failures
    write_new(destination / "comparison.json", json.dumps({**started, **result}, indent=2).encode())
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("bundle", "base", "base-gguf", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--image", required=True)
    args = parser.parse_args()
    run_comparison(args.bundle, args.base, args.base_gguf, args.image, args.output)


if __name__ == "__main__":
    main()
