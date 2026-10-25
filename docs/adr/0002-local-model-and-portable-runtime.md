# ADR 0002: Reuse the verified LoRA and portable CPU runtime

Status: Accepted · 2026-10-25

## Context

The local model lifecycle was exercised successfully before the product reset. Rebuilding it would discard working training, artifact validation, conversion and isolated export boundaries. Hardware compatibility required actual checks, not assumptions from package versions.

## Decision

Keep FastAPI/Jinja2/HTMX, SQLite and local immutable artifacts. Keep GPU dependencies out of the web application and CPU runtime. Use public, versioned contracts between the app, separately operated trainer and exporter.

Reuse the pinned Qwen text model → reviewed LoRA → verified safe merge → GGUF Q8_0 → llama.cpp CPU path. Exact pins live in [model constants](../../quartermaster/spike/spec.py), [trainer Dockerfile](../../trainer/Dockerfile) and [trainer lock](../../trainer/uv.lock). Knowledge and reviewed decisions remain portable; adapters require a compatible pinned base.

Use finite resource/time bounds and explicit GPU authorization. Failure is durable, with no automatic retry or cloud fallback. An export is usable only after a fresh extracted-package check proves it runs without the builder, its database or a frontier API.

## Evidence and lessons

- The original spike and later application workflow each completed real local training, checked adapter files, merged and converted the result, and served it from an isolated CPU package. The application run used four reviewed synthetic targets and 12 training steps. This is lifecycle evidence, not personalized prediction quality.
- The application candidate and base produced identical displayed answers on the two-case check and both missed parts of the rubrics. Different model bytes did not mean better advice.
- On the tested GTX 1660 Ti (compute capability 7.5), a forced fused-loss path reached unsupported Triton/compiler requirements. The working path used ordinary PyTorch NLL, float32 and gradient checkpointing. Do not silently reintroduce optional fused kernels or assume BF16 support.
- Default NVIDIA Docker passthrough initially failed because its toolkit was absent. Explicit WSL device/read-only driver mounts worked without privileged containers or host package changes. That success does not verify other GPUs.

## Consequences

Verify the new generic target at every existing boundary instead of replacing the lifecycle. Historical training/export success does not establish the new contract, other hardware, unseen accuracy or successful distribution to another machine. See the [operator guide](../operator-guide.md).

Historical sources at `32590b0`: `docs/milestone-1.md`, `docs/milestone-6.md`, `docs/milestone-7.md`. Implementation commits: `45a01a3` and `2f412fc`. Exact legacy fixture approvals remain in [spike review](../../tests/fixtures/spike/review.json) and [training review](../../tests/fixtures/training/review.json); they authorize no new GPU run.
