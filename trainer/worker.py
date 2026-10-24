"""Fixed, bounded synthetic spike recipe. Runs only in the optional trainer image."""

import argparse
import gc
import importlib.metadata
import json
import math
import shutil
import subprocess
import time
from pathlib import Path

from quartermaster.spike.artifacts import require_review
from quartermaster.spike.spec import (
    LEARNING_RATE,
    MAX_LENGTH,
    MAX_NEW_TOKENS,
    MAX_STEPS,
    MODEL_ID,
    MODEL_REVISION,
    digest,
    load_fixture,
    messages,
)


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def download(output):
    from huggingface_hub import snapshot_download

    snapshot_download(
        MODEL_ID,
        revision=MODEL_REVISION,
        local_dir=output,
        allow_patterns=[
            "*.json",
            "*.jinja",
            "*.safetensors",
            "merges.txt",
            "vocab.json",
            "LICENSE",
            "README.md",
        ],
        max_workers=2,
    )
    if not (output / "LICENSE").is_file():
        raise ValueError("Model license is missing")
    save(
        output / "snapshot.json",
        {
            "model_id": MODEL_ID,
            "revision": MODEL_REVISION,
            "files": {p.name: digest(p) for p in output.iterdir() if p.is_file()},
        },
    )


def load_model(base, gpu=True):
    import torch
    from transformers import AutoConfig, AutoTokenizer, Qwen3_5ForCausalLM

    if gpu and not torch.cuda.is_available():
        raise ValueError("A local NVIDIA GPU is required; no cloud fallback is used")
    if gpu and torch.cuda.get_device_properties(0).total_memory < 5_500_000_000:
        raise ValueError("This spike requires at least 6 GB VRAM")
    config = AutoConfig.from_pretrained(base, local_files_only=True, trust_remote_code=False)
    config = config.get_text_config()
    # Full upstream checkpoint -> text-only class; native Transformers maps language_model keys.
    model, info = Qwen3_5ForCausalLM.from_pretrained(
        base,
        config=config,
        dtype=torch.float32,
        attn_implementation="eager",
        local_files_only=True,
        trust_remote_code=False,
        output_loading_info=True,
    )
    if info.get("missing_keys") or info.get("mismatched_keys"):
        raise ValueError("Text-only checkpoint did not load all expected weights")
    tokenizer = AutoTokenizer.from_pretrained(
        base,
        local_files_only=True,
        trust_remote_code=False,
        padding_side="left",
    )
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    # Qwen chat turns end with im_end, rather than the tokenizer's document-end default.
    if "<|im_end|>" not in tokenizer.get_vocab():
        raise ValueError("Pinned Qwen chat end token is missing")
    tokenizer.eos_token = "<|im_end|>"
    model.config.eos_token_id = tokenizer.eos_token_id
    model.generation_config.eos_token_id = tokenizer.eos_token_id
    model.config.pad_token_id = tokenizer.pad_token_id
    if gpu:
        model.to("cuda")
    return model, tokenizer


def preflight(base, fixture_path, output):
    import torch

    require_review(fixture_path, fixture_path.with_name("review.json"))
    fixture = load_fixture(fixture_path)
    training_args(output, cpu=True)
    model, tokenizer = load_model(base, gpu=False)
    model.eval()
    lengths = []
    for example in fixture.examples:
        prompt = tokenizer.apply_chat_template(
            messages(fixture.mission, example.case),
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        completion = example.advice.model_dump_json() + tokenizer.eos_token
        lengths.append(len(tokenizer(prompt + completion)["input_ids"]))
    if max(lengths) > MAX_LENGTH:
        raise ValueError("Fixture would be truncated; refusing incomplete supervision")
    inputs = tokenizer.apply_chat_template(
        messages(fixture.mission, fixture.examples[0].case),
        tokenize=True,
        add_generation_prompt=True,
        enable_thinking=False,
        return_tensors="pt",
        return_dict=True,
    )
    started = time.monotonic()
    with torch.inference_mode():
        tokens = model.generate(
            **inputs,
            max_new_tokens=16,
            do_sample=False,
            pad_token_id=tokenizer.pad_token_id,
        )
    content = tokenizer.decode(tokens[0, inputs.input_ids.shape[1] :], skip_special_tokens=True)
    if not content.strip():
        raise ValueError("Text-only model produced no text")
    save(
        output / "preflight.json",
        {
            "schema_version": "quartermaster.spike-preflight/v1",
            "model_id": MODEL_ID,
            "revision": MODEL_REVISION,
            "device": "cpu",
            "train_sha256": digest(fixture_path),
            "sequence_lengths": lengths,
            "generated_text_prefix": content,
            "elapsed_seconds": time.monotonic() - started,
            "torch": torch.__version__,
        },
    )


def training_args(output, *, cpu=False):
    from trl import SFTConfig

    return SFTConfig(
        output_dir=str(output / "scratch"),
        max_steps=MAX_STEPS,
        max_length=MAX_LENGTH,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=1,
        learning_rate=LEARNING_RATE,
        lr_scheduler_type="constant",
        warmup_steps=0,
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        fp16=False,
        bf16=False,
        optim="adamw_torch",
        max_grad_norm=1.0,
        save_strategy="no",
        logging_steps=1,
        report_to="none",
        seed=17,
        data_seed=17,
        completion_only_loss=True,
        loss_type="nll",
        use_liger_kernel=False,
        packing=False,
        dataloader_num_workers=0,
        use_cpu=cpu,
    )


def train(base, fixture_path, output):
    import torch
    from datasets import Dataset
    from peft import LoraConfig
    from safetensors import safe_open
    from transformers import TrainerCallback, set_seed
    from trl import SFTTrainer

    class Deadline(TrainerCallback):
        def on_train_begin(self, args, state, control, **kwargs):
            self.deadline = time.monotonic() + 900

        def on_step_end(self, args, state, control, **kwargs):
            if time.monotonic() > self.deadline:
                raise TimeoutError("Training exceeded its 900-second deadline")

    require_review(fixture_path, fixture_path.with_name("review.json"))
    fixture = load_fixture(fixture_path)
    if fixture.split != "train":
        raise ValueError("Only the training split may enter the trainer")
    set_seed(17)
    model, tokenizer = load_model(base)
    rows = []
    for example in fixture.examples:
        prompt = tokenizer.apply_chat_template(
            messages(fixture.mission, example.case),
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        completion = example.advice.model_dump_json() + tokenizer.eos_token
        if len(tokenizer(prompt + completion)["input_ids"]) > MAX_LENGTH:
            raise ValueError("Fixture would be truncated; refusing incomplete supervision")
        rows.append({"prompt": prompt, "completion": completion})
    model.config.use_cache = False
    trainer = SFTTrainer(
        model=model,
        processing_class=tokenizer,
        train_dataset=Dataset.from_list(rows),
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
        args=training_args(output),
        callbacks=[Deadline()],
    )
    result = trainer.train()
    if trainer.state.global_step != MAX_STEPS or not math.isfinite(result.training_loss):
        raise ValueError("Training stopped early or produced a non-finite loss")
    adapter = output / "adapter"
    trainer.model.peft_config["default"].base_model_name_or_path = MODEL_ID
    trainer.model.peft_config["default"].revision = MODEL_REVISION
    trainer.model.save_pretrained(adapter, safe_serialization=True)
    with safe_open(adapter / "adapter_model.safetensors", framework="pt") as tensors:
        if not tensors.keys():
            raise ValueError("Empty adapter")
        b_changed = False
        for key in tensors.keys():
            tensor = tensors.get_tensor(key)
            if not torch.isfinite(tensor).all():
                raise ValueError("Non-finite adapter tensor")
            if "lora_B" in key and torch.count_nonzero(tensor):
                b_changed = True
        if not b_changed:
            raise ValueError("Adapter has no learned update")
    save(
        output / "training.json",
        {
            "schema_version": "quartermaster.spike-training/v1",
            "model_id": MODEL_ID,
            "revision": MODEL_REVISION,
            "train_sha256": digest(fixture_path),
            "steps": trainer.state.global_step,
            "recipe": {
                "learning_rate": LEARNING_RATE,
                "max_length": MAX_LENGTH,
                "rank": 4,
                "alpha": 8,
                "seed": 17,
                "precision": "float32",
                "loss": "nll",
                "completion_only_loss": True,
            },
            "training_loss": result.training_loss,
            "gpu": torch.cuda.get_device_name(0),
            "cuda": torch.version.cuda,
            "peak_vram_bytes": torch.cuda.max_memory_allocated(),
            "versions": {
                p: importlib.metadata.version(p)
                for p in (
                    "torch",
                    "transformers",
                    "trl",
                    "peft",
                    "accelerate",
                    "datasets",
                    "safetensors",
                )
            },
            "adapter_hashes": {p.name: digest(p) for p in sorted(adapter.iterdir()) if p.is_file()},
        },
    )
    shutil.rmtree(output / "scratch", ignore_errors=True)


def compare(base, inputs, adapter, output):
    import torch
    from peft import PeftModel

    model, tokenizer = load_model(base)
    model.eval()
    rows = json.loads(inputs.read_text())

    def generate(variant):
        results = []
        for row in rows:
            tokens = tokenizer.apply_chat_template(
                row["messages"],
                tokenize=True,
                add_generation_prompt=True,
                enable_thinking=False,
                return_tensors="pt",
                return_dict=True,
            ).to("cuda")
            started = time.monotonic()
            with torch.inference_mode():
                ids = model.generate(
                    **tokens,
                    max_new_tokens=MAX_NEW_TOKENS,
                    do_sample=False,
                    pad_token_id=tokenizer.pad_token_id,
                )
            results.append(
                {
                    "case_id": row["case_id"],
                    "content": tokenizer.decode(
                        ids[0, tokens.input_ids.shape[1] :], skip_special_tokens=True
                    ),
                    "elapsed_seconds": time.monotonic() - started,
                }
            )
        save(output / f"{variant}.json", results)

    generate("base")
    model = PeftModel.from_pretrained(model, adapter, local_files_only=True).eval()
    generate("adapter")


def convert(base, adapter, output):
    model, tokenizer = load_model(base, gpu=False)
    if adapter is not None:
        from peft import PeftModel

        model = PeftModel.from_pretrained(model, adapter, local_files_only=True)
        merged = model.merge_and_unload(safe_merge=True)
    else:
        merged = model  # Explicit M4 base-only conversion; no adapter or training fixture.
    merged.save_pretrained(output / "merged", safe_serialization=True)
    tokenizer.save_pretrained(output / "merged")
    del model, merged
    gc.collect()
    subprocess.run(
        [
            "python",
            "/llama/convert_hf_to_gguf.py",
            str(output / "merged"),
            "--outfile",
            str(output / "model.gguf"),
            "--outtype",
            "q8_0",
        ],
        check=True,
        timeout=600,
    )
    with (output / "model.gguf").open("rb") as stream:
        if stream.read(4) != b"GGUF":
            raise ValueError("Converter did not produce GGUF")
    shutil.copyfile(base / "LICENSE", output / "LICENSE.model")
    # Only the portable file is retained; the immutable base and adapter remain separate.
    shutil.rmtree(output / "merged")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "stage", choices=["download", "preflight", "train", "compare", "convert", "convert-base"]
    )
    parser.add_argument("--base", type=Path, default=Path("/base"))
    parser.add_argument("--output", type=Path, default=Path("/output"))
    args = parser.parse_args()
    args.output.mkdir(exist_ok=True, parents=True)
    match args.stage:
        case "download":
            download(args.output)
        case "train":
            train(args.base, Path("/input/train.json"), args.output)
        case "preflight":
            preflight(args.base, Path("/input/train.json"), args.output)
        case "compare":
            compare(args.base, Path("/input/cases.json"), Path("/adapter"), args.output)
        case "convert":
            convert(args.base, Path("/adapter"), args.output)
        case "convert-base":
            convert(args.base, None, args.output)


if __name__ == "__main__":
    main()
