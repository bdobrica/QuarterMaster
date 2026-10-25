"""Fixed public-job consumer. No app internals, network downloads or arbitrary recipes."""

import argparse
import importlib.metadata
import json
import math
import signal
from pathlib import Path

from worker import convert, load_model, save, training_args

from quartermaster.contracts.adviser import ModelSpec
from quartermaster.contracts.training import (
    ArtifactFile,
    TrainingJob,
    TrainingManifest,
    TrainingRow,
)
from quartermaster.spike.artifacts import verify_snapshot
from quartermaster.spike.spec import digest


def fail_deadline(signum, frame):
    raise TimeoutError("JOB_DEADLINE")


def load_job():
    path = Path("/input/job.json")
    if path.stat().st_size > 10_000_000:
        raise ValueError("JOB_SIZE")
    raw = path.read_bytes()
    if json.loads(raw)["schema_version"] == "quartermaster.training-job/v2":
        from quartermaster.contracts.prediction import PredictionJob
        from quartermaster.prediction_jobs import verify_job

        job = PredictionJob.model_validate_json(raw)
        rows = Path("/input/train.jsonl").read_bytes()
        verify_job(job, rows)
        return job, [TrainingRow.model_validate_json(line) for line in rows.splitlines()]
    job = TrainingJob.model_validate_json(raw)
    if (
        job.model != ModelSpec()
        or job.recipe.steps != (12 if job.recipe.preset == "quick" else 48)
        or job.recipe.seconds != (1200 if job.recipe.preset == "quick" else 3600)
        or digest(Path("/input/train.jsonl")) != job.dataset_sha256
    ):
        raise ValueError("JOB_INTEGRITY")
    expected = []
    for example in sorted(job.examples, key=lambda e: str(e.id)):
        if example.status != "approved" or example.target is None:
            raise ValueError("JOB_UNREVIEWED")
        expected.append(
            TrainingRow(
                id=example.id,
                example_revision=example.revision,
                messages=[
                    {"role": "system", "content": example.input.system},
                    {"role": "user", "content": example.input.context},
                    {"role": "assistant", "content": example.target.model_dump_json()},
                ],
            )
        )
    rows = [
        TrainingRow.model_validate_json(line)
        for line in Path("/input/train.jsonl").read_bytes().splitlines()
    ]
    if rows != expected:
        raise ValueError("JOB_ROWS")
    return job, rows


def preflight(output, job=None):
    import torch

    if not torch.cuda.is_available():
        raise ValueError("GPU_UNAVAILABLE")
    info = torch.cuda.get_device_properties(0)
    quantized = job is not None and job.recipe.precision == "nf4-float16"
    if info.total_memory < (7_500_000_000 if quantized else 5_500_000_000) or info.major < 7:
        raise ValueError("GPU_CAPABILITY")
    save(
        output / "preflight.json",
        {
            "schema_version": "quartermaster.gpu-preflight/v1",
            "gpu": torch.cuda.get_device_name(0),
            "vram_bytes": info.total_memory,
            "compute_capability": [info.major, info.minor],
            "cuda": torch.version.cuda,
            "versions": {
                p: importlib.metadata.version(p)
                for p in (
                    "torch",
                    "transformers",
                    "trl",
                    "peft",
                    *(["bitsandbytes"] if quantized else []),
                )
            },
        },
    )


def train(base, output, job, rows):
    import torch
    from datasets import Dataset
    from peft import LoraConfig
    from safetensors import safe_open
    from transformers import set_seed
    from trl import SFTTrainer

    set_seed(job.recipe.seed)
    quantized = job.recipe.precision == "nf4-float16"
    model, tokenizer = load_model(base, quantized=quantized) if quantized else load_model(base)
    if quantized:
        from peft import prepare_model_for_kbit_training

        model = prepare_model_for_kbit_training(
            model, gradient_checkpointing_kwargs={"use_reentrant": False}
        )
    data = []
    for row in rows:
        prompt = tokenizer.apply_chat_template(
            row.messages[:2], tokenize=False, add_generation_prompt=True, enable_thinking=False
        )
        completion = row.messages[2]["content"] + tokenizer.eos_token
        if len(tokenizer(prompt + completion)["input_ids"]) > job.recipe.max_length:
            raise ValueError("JOB_TOO_LONG")
        data.append({"prompt": prompt, "completion": completion})
    model.config.use_cache = False
    trainer = SFTTrainer(
        model=model,
        processing_class=tokenizer,
        train_dataset=Dataset.from_list(data),
        args=training_args(output, recipe=job.recipe),
        peft_config=LoraConfig(
            r=4,
            lora_alpha=8,
            lora_dropout=0.0,
            bias="none",
            task_type="CAUSAL_LM",
            target_modules=["q_proj", "v_proj"],
            base_model_name_or_path=job.model.base_model_id,
            revision=job.model.base_revision,
        ),
    )
    result = trainer.train()
    if trainer.state.global_step != job.recipe.steps or not math.isfinite(result.training_loss):
        raise ValueError("JOB_INCOMPLETE")
    adapter = output / "adapter"
    trainer.model.peft_config["default"].base_model_name_or_path = job.model.base_model_id
    trainer.model.peft_config["default"].revision = job.model.base_revision
    trainer.model.save_pretrained(adapter, safe_serialization=True)
    with safe_open(adapter / "adapter_model.safetensors", framework="pt") as tensors:
        changed = False
        for name in tensors.keys():
            tensor = tensors.get_tensor(name)
            if not torch.isfinite(tensor).all():
                raise ValueError("JOB_NONFINITE")
            if "lora_B" in name and torch.count_nonzero(tensor):
                changed = True
        if not changed:
            raise ValueError("JOB_NO_UPDATE")
    manifest = TrainingManifest(
        schema_version=(
            "quartermaster.training-artifacts/v2"
            if job.schema_version == "quartermaster.training-job/v2"
            else "quartermaster.training-artifacts/v1"
        ),
        job_id=job.id,
        job_sha256=digest(Path("/input/job.json")),
        dataset_sha256=job.dataset_sha256,
        model=job.model,
        recipe=job.recipe,
        completed_steps=trainer.state.global_step,
        training_loss=float(result.training_loss),
        files={
            p.name: ArtifactFile(sha256=digest(p), size_bytes=p.stat().st_size)
            for p in sorted(adapter.iterdir())
            if p.is_file()
        },
    )
    (output / "training.json").write_text(manifest.model_dump_json())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["preflight", "train", "convert"])
    args = parser.parse_args()
    job, rows = load_job()
    signal.signal(signal.SIGALRM, fail_deadline)
    signal.alarm(job.recipe.seconds if args.stage == "train" else 1200)
    base, output = Path("/base"), Path("/output")
    verify_snapshot(base, model_id=job.model.base_model_id, revision=job.model.base_revision)
    try:
        if args.stage == "preflight":
            preflight(output, job) if job.recipe.precision == "nf4-float16" else preflight(output)
        elif args.stage == "train":
            train(base, output, job, rows)
        else:
            # The host verifies the adapter before this separately scoped stage.
            convert(base, Path("/adapter"), output)
    except Exception:
        # Trainer/library diagnostics can contain examples. Docker logging is also
        # disabled by the host; only a fixed actionable failure code is persisted.
        raise SystemExit(
            "JOB_FAILED: Inspect resources, sequence length and artifact integrity."
        ) from None


if __name__ == "__main__":
    main()
