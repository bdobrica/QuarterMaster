"""Optional offline selector worker. CPU draft checking can never enter a GPU stage."""

import argparse
import hashlib
import json
import math
import signal
import time
from pathlib import Path
from types import SimpleNamespace

from worker import convert, load_model, save, training_args

from quartermaster.contracts.decision_training import DecisionManifest, DecisionRecipe
from quartermaster.decision_training import dataset, load_job, read_pack
from quartermaster.spike.artifacts import verify_snapshot
from quartermaster.spike.spec import MODEL_ID, MODEL_REVISION, digest


def deadline(signum, frame):
    raise TimeoutError("DECISION_DEADLINE")


def tokenizer_for(base):
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(
        base, local_files_only=True, trust_remote_code=False, padding_side="left"
    )
    if "<|im_end|>" not in tokenizer.get_vocab():
        raise ValueError("DECISION_END_TOKEN")
    tokenizer.eos_token = "<|im_end|>"
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    return tokenizer


def tokenized_rows(rows, tokenizer):
    data, diagnostics = [], []
    for row in rows:
        prompt = tokenizer.apply_chat_template(
            row["messages"][:2], tokenize=False, add_generation_prompt=True, enable_thinking=False
        )
        completion = row["messages"][2]["content"] + tokenizer.eos_token
        tokens = tokenizer(prompt + completion, add_special_tokens=False)["input_ids"]
        if not 0 < len(tokens) <= 2048:
            raise ValueError("DECISION_SEQUENCE_LENGTH")
        data.append({"prompt": prompt, "completion": completion})
        diagnostics.append(
            {
                "id": row["id"],
                "tokens": len(tokens),
                "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                "completion_token_ids": tokenizer(completion, add_special_tokens=False)[
                    "input_ids"
                ],
            }
        )
    return data, diagnostics


def cpu_recipe_check(output):
    args = training_args(output, cpu=True, recipe=DecisionRecipe())
    expected = {
        "max_steps": 120,
        "max_length": 2048,
        "per_device_train_batch_size": 1,
        "gradient_accumulation_steps": 1,
        "learning_rate": 1e-5,
        "seed": 17,
        "fp16": False,
        "bf16": False,
        "completion_only_loss": True,
        "use_cpu": True,
    }
    if any(getattr(args, field) != value for field, value in expected.items()):
        raise ValueError("DECISION_RECIPE_DRIFT")
    return expected


def train(base, output, job, rows, *, preflight=False):
    import torch
    from datasets import Dataset
    from peft import LoraConfig
    from safetensors import safe_open
    from transformers import TrainerCallback, set_seed
    from trl import SFTTrainer

    if not torch.cuda.is_available():
        raise ValueError("DECISION_GPU_UNAVAILABLE")
    props = torch.cuda.get_device_properties(0)
    if props.total_memory < 5_500_000_000 or props.major < 7:
        raise ValueError("DECISION_GPU_CAPABILITY")
    started = time.monotonic()

    class Progress(TrainerCallback):
        def on_step_end(self, args, state, control, **kwargs):
            with (output / "progress.jsonl").open("a") as stream:
                stream.write(
                    json.dumps(
                        {
                            "optimizer_step": state.global_step,
                            "elapsed_seconds": time.monotonic() - started,
                            "peak_allocated_vram_bytes": torch.cuda.max_memory_allocated(),
                        }
                    )
                    + "\n"
                )

    set_seed(job.recipe.seed)
    torch.cuda.reset_peak_memory_stats()
    data, lengths = tokenized_rows(rows, tokenizer_for(base))
    if preflight:
        # One real optimizer step at the longest reviewed sequence, with the same recipe.
        longest = max(range(len(data)), key=lambda i: lengths[i]["tokens"])
        data = [data[longest]]
    model, tokenizer = load_model(base)
    model.config.use_cache = False
    args = training_args(
        output,
        recipe=SimpleNamespace(steps=1 if preflight else job.recipe.steps, max_length=2048),
    )
    trainer = SFTTrainer(
        model=model,
        processing_class=tokenizer,
        train_dataset=Dataset.from_list(data),
        args=args,
        peft_config=LoraConfig(
            r=4,
            lora_alpha=8,
            lora_dropout=0.0,
            bias="none",
            task_type="CAUSAL_LM",
            target_modules=["q_proj", "v_proj"],
            base_model_name_or_path=MODEL_ID,
            revision=MODEL_REVISION,
        ),
        callbacks=[Progress()],
    )
    result = trainer.train()
    steps = 1 if preflight else 120
    if trainer.state.global_step != steps or not math.isfinite(result.training_loss):
        raise ValueError("DECISION_INCOMPLETE")
    if preflight:
        save(
            output / "gpu-preflight.json",
            {
                "schema_version": "quartermaster.decision-gpu-preflight/v1",
                "job_sha256": digest(Path("/input/job.json")),
                "optimizer_steps": 1,
                "longest_tokens": max(r["tokens"] for r in lengths),
                "peak_vram_bytes": torch.cuda.max_memory_allocated(),
                "total_vram_bytes": props.total_memory,
                "candidate_created": False,
            },
        )
        return
    adapter = output / "adapter"
    trainer.model.peft_config["default"].base_model_name_or_path = MODEL_ID
    trainer.model.peft_config["default"].revision = MODEL_REVISION
    trainer.model.save_pretrained(adapter, safe_serialization=True)
    with safe_open(adapter / "adapter_model.safetensors", framework="pt") as tensors:
        changed = False
        for name in tensors.keys():
            tensor = tensors.get_tensor(name)
            if not torch.isfinite(tensor).all():
                raise ValueError("DECISION_NONFINITE")
            if "lora_B" in name and torch.count_nonzero(tensor):
                changed = True
        if not changed:
            raise ValueError("DECISION_NO_UPDATE")
    manifest = DecisionManifest(
        job_id=job.id,
        job_sha256=digest(Path("/input/job.json")),
        dataset_sha256=job.dataset_sha256,
        recipe=job.recipe,
        completed_steps=120,
        training_loss=float(result.training_loss),
        peak_vram_bytes=torch.cuda.max_memory_allocated(),
        files={p.name: digest(p) for p in adapter.iterdir() if p.is_file()},
    )
    save(output / "training.json", manifest.model_dump(mode="json"))


def convert_decision(base, training, output, job, job_sha256):
    import torch
    from safetensors import safe_open

    from quartermaster.decision_artifacts import conversion_record, verify_adapter

    verify_adapter(training, job, job_sha256)
    with safe_open(training / "adapter/adapter_model.safetensors", framework="pt") as tensors:
        changed = False
        for name in tensors.keys():
            tensor = tensors.get_tensor(name)
            if not torch.isfinite(tensor).all():
                raise ValueError("DECISION_NONFINITE")
            if "lora_B" in name and torch.count_nonzero(tensor):
                changed = True
        if not changed:
            raise ValueError("DECISION_NO_UPDATE")
    # Reuse the verified text-only safe_merge + q8_0 converter, never the advice job parser.
    convert(base, training / "adapter", output)
    verify_adapter(training, job, job_sha256)
    save(output / "conversion.json", conversion_record(output, training, job, job_sha256, base))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["cpu-drafts", "cpu", "gpu-preflight", "train", "convert"])
    args = parser.parse_args()
    signal.signal(signal.SIGALRM, deadline)
    signal.alarm({"train": 3600, "convert": 1200}.get(args.stage, 300))
    base, output = Path("/base"), Path("/output")
    try:
        verify_snapshot(base)
        if args.stage == "cpu-drafts":
            pack = read_pack("/input/pack.json")
            if pack.purpose != "teaching":
                raise ValueError("DECISION_DRAFT_PURPOSE")
            rows = [json.loads(line) for line in dataset(pack).splitlines()]
            job = None
        else:
            job, rows = load_job("/input")
        if args.stage in {"cpu-drafts", "cpu"}:
            _, lengths = tokenized_rows(rows, tokenizer_for(base))
            save(
                output / "cpu-preflight.json",
                {
                    "schema_version": "quartermaster.decision-cpu-preflight/v1",
                    "drafts_only": job is None,
                    "input_sha256": digest(
                        Path("/input/pack.json" if job is None else "/input/job.json")
                    ),
                    "rows": lengths,
                    "maximum_tokens": max(r["tokens"] for r in lengths),
                    "model_revision": MODEL_REVISION,
                    "recipe_cpu_check": cpu_recipe_check(output),
                    "gpu_capability_checked": False,
                    "training_started": False,
                },
            )
        elif args.stage == "convert":
            convert_decision(base, Path("/training"), output, job, digest(Path("/input/job.json")))
        else:
            train(base, output, job, rows, preflight=args.stage == "gpu-preflight")
    except Exception as exc:
        code = (
            "DECISION_DEADLINE"
            if isinstance(exc, TimeoutError)
            else "DECISION_GPU_OOM"
            if type(exc).__name__ == "OutOfMemoryError"
            else "DECISION_STAGE_FAILED"
        )
        save(
            output / "failure.json",
            {
                "code": code,
                "stage": args.stage,
                "exception_type": type(exc).__name__[:80],
                "automatic_retry": False,
            },
        )
        raise SystemExit(
            "DECISION_STAGE_FAILED: Check review, hashes, sequence lengths and resources."
        ) from None


if __name__ == "__main__":
    main()
