# Milestone 1: model-to-export feasibility spike

This spike tests a model lifecycle, not adviser quality. The builder still creates/lists projects;
training, comparison and export here are explicit developer commands. The owner approved the four
synthetic supervision pairs on 2026-10-24. They retain `AI_DRAFT_SYNTHETIC` origin; the separate
[review record](../tests/fixtures/spike/review.json) grants approval for their exact SHA-256 only.
Changing the training fixture invalidates that approval. The two held-out cases are never mounted
into the training container. No business content or builder-provider API is used.

## Pinned choices

| Component | Selection |
| --- | --- |
| Base | `Qwen/Qwen3.5-0.8B` |
| Upstream revision | `2fc06364715b967f1860aea9cf38778875588b17` |
| License | Apache-2.0, copied unchanged from the pinned upstream snapshot |
| Text model class | Transformers `Qwen3_5ForCausalLM`, text configuration; no vision inputs |
| Trainer | Python 3.13 on Debian Trixie, digest pinned in `trainer/Dockerfile` |
| ML packages | PyTorch 2.11.0 (CUDA 12.6), Transformers 5.20.2, TRL 0.29.0, PEFT 0.21.2 |
| Other direct pins | Accelerate 1.15.0, Datasets 5.1.0, safetensors 0.8.0 |
| Runtime/converter | llama.cpp `1a24df163920a4744a95373d178d790b72a9bb2f` |
| Source archive SHA-256 | `495fa6f41f7c0d0a68a44e2053c663fb6291fd44a552577039822c02733b9a5c` |
| Portable representation | Safely merge PEFT into text-only weights, then GGUF Q8_0 |

The [trainer lock](../trainer/uv.lock) pins transitive distributions and hashes independently of the
lightweight web app. CUDA dependencies belong only to the trainer. Transformers loads the model,
TRL supplies completion-only SFT, PEFT supplies LoRA and checked merge, Datasets supplies the tiny
in-memory corpus, and Accelerate supplies device/trainer support. SentencePiece, protobuf and
requests support upstream conversion/tokenization. llama.cpp is built from the same verified source
archive for conversion and serving; prebuilt UI downloads are disabled. The final runtime contains
no Torch, trainer, QuarterMaster database or provider client.

Upstream references: [pinned model and license](https://huggingface.co/Qwen/Qwen3.5-0.8B/tree/2fc06364715b967f1860aea9cf38778875588b17),
[Transformers text-only interface](https://huggingface.co/docs/transformers/v5.20.2/model_doc/qwen3_5),
[PyTorch CUDA distributions](https://pytorch.org/get-started/previous-versions/),
[pinned llama.cpp source](https://github.com/ggml-org/llama.cpp/tree/1a24df163920a4744a95373d178d790b72a9bb2f).

## Reproduction

Prerequisites: Docker Engine with local NVIDIA GPU passthrough, Python 3.13/uv, at least 6 GB VRAM,
12 GB free artifact disk plus Docker image/build space, and enough host RAM for a 10 GiB trainer
container. Ordinary `make test` never builds images, downloads weights or starts GPU work.

### Host GPU setup when Docker cannot select a GPU driver

The first local attempt found a working WSL GPU driver but no NVIDIA Container Toolkit. Docker
returned `could not select device driver "" with capabilities: [[gpu]]` before executing the worker.
Administrator setup is separate from the application; the agent cannot perform it when `sudo`
requires an interactive password. Do not share that password with the application or agent.

On this WSL host, a narrower route was verified: use `make test-gpu GPU_MODE=wsl`. This explicit
mode passes `/dev/dxg` and mounts `/usr/lib/wsl` read-only, with `LD_LIBRARY_PATH` pointing at its
driver libraries. It uses no privileged container, host package install, daemon change or service
restart. Both the library and driver subdirectories are necessary. This setting affects only GPU
training/comparison containers; the exported CPU runtime receives neither device nor driver mount.
The ordinary default remains NVIDIA Container Toolkit (`GPU_MODE=nvidia`).

For this Debian Trixie host, follow the [official NVIDIA installation guide](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html).
These administrator commands install the stable toolkit and configure Docker. Restarting Docker
can briefly interrupt running containers; restart the QuarterMaster web service afterward.
They are an alternative for standard NVIDIA passthrough, not required for the explicit WSL mode.

```sh
sudo apt-get update
sudo apt-get install -y --no-install-recommends ca-certificates curl gnupg2
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey -o /tmp/nvidia-container-toolkit.asc
sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg /tmp/nvidia-container-toolkit.asc
curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit=1.20.1-1 nvidia-container-toolkit-base=1.20.1-1 \
  libnvidia-container-tools=1.20.1-1 libnvidia-container1=1.20.1-1
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
docker compose up -d --wait
```

The pinned toolkit version follows the official guide at implementation time. No Linux display
driver is installed by these commands; this WSL host already exposes its Windows NVIDIA driver.
If using Docker Desktop instead of this host's native Docker daemon, configure its WSL GPU support
rather than modifying an unrelated daemon.

### Run the spike

```sh
make setup
make test
make lint
make test-gpu
```

`make test-gpu` explicitly starts one local training attempt. It builds two images, downloads only
the pinned public model snapshot, verifies hashes and review, trains, compares on held-out inputs,
merges/converts, archives and verifies the portable files, then serves a fresh extraction with no
network or GPU. Existing complete base snapshots are reused only after hash validation. A partial
snapshot fails; inspect it and explicitly move it aside before retrying a download. No automatic
training retry or cloud fallback exists.

For a real model check without GPU training or export:

```sh
uv run --locked python -m quartermaster.spike.run --check-cpu
```

This checks the pinned text-only loader, verifies fixture token lengths and generates a short
16-token prefix on CPU. It does not claim complete Advice JSON, LoRA compatibility or export.

The recipe is deliberately small: seed 17, rank 4/alpha 8, `q_proj`/`v_proj` targets, 12 steps,
batch size 1, sequence limit 512, learning rate 0.00001, completion-only loss, FP32 with gradient
checkpointing. Samples that would be truncated are rejected. FP32 avoids assuming BF16 support on
older cards. No optional FlashAttention, remote kernels or bitsandbytes path is enabled.
TRL uses ordinary `nll` loss with Liger disabled. TRL 1.16.0 was rejected for this GPU: its forced
fused loss reached Triton and failed without a compiler; Triton 3.6's documented support starts at
compute capability 8.0, whereas the GTX 1660 Ti is 7.5. The narrower alternative is the pinned
standard PyTorch loss path, not a model substitution or an untested kernel patch.

Training has a 900-second deadline callback and a 1,200-second container deadline. Generation is capped
at 256 new tokens. Merge/conversion and every other subprocess also have finite deadlines.
Containers have explicit memory, CPU and process limits; a timed-out/canceled job is removed and
cannot become a completed export. The trainer receives only the selected input and output paths,
no Docker socket, credentials, home directory or builder volume. Training, comparison, conversion
and runtime networking are disabled; only image building and the public model download are online.

Each invocation writes a new UUID directory under ignored `data/spike/`. Inspect:

- `events.jsonl`: append-only timestamps, stages, failure codes; absence of final completion means
  the attempt did not finish. A host kill may leave a started event; it is never inferred successful.
- `training/training.json` and `training/adapter/`: steps/loss, tested device, package versions,
  peak allocated VRAM, exact base/data lineage and adapter file hashes.
- `comparison/{base,adapter,checks}.json`: identical held-out prompts, actual unconstrained model
  outputs and schema/clarification checks. These checks do not establish factual or business lift.
- `portable/manifest.json`, `adviser.tar`: model/license bytes, hashes, pinned lineage and actual
  trainer/runtime image IDs. This is a spike bundle, not the Milestone 7 application export.
- `runtime.json`: isolated CPU advice outputs, elapsed wall time, token usage and archive hash.

To recheck an existing bundle without training:

```sh
make test-export EXPORT=/absolute/path/to/data/spike/RUN_ID/adviser.tar
```

The local runtime tag must still resolve to the archived image ID, and the frozen evaluation
fixture must match. This spike deliberately rejects a replaced runtime tag. The check extracts
only three fixed data filenames, rejects links/traversal/corruption, starts a fresh `--network=none`
container with only the extracted directory mounted, and requests constrained Advice JSON through
llama.cpp's loopback API. It validates both normal and missing-inspection behavior, empty citations
and the public [Case/Advice contracts](../quartermaster/contracts/advice.py). No port is published.

## Verification and limits

CPU text preflight passed on 2026-10-24 (local time), run
`a9b1743c-3ed7-4329-8a41-8f29c9d08fde`. The pinned Qwen text weights loaded without missing or
mismatched keys. The four training sequences were 331, 328, 333 and 336 tokens, below the fixed
512-token bound. A 16-token JSON prefix took 5.36 seconds excluding loading (approximately 25.7
seconds for container startup, loading, checks and generation together). This is an FP32 prefix
check, not a complete exported-response latency measurement.

Tested host: WSL2 Debian 13.2, Intel Core i5-9300H at 2.40 GHz, 16 GiB host RAM, NVIDIA GTX 1660 Ti
6 GiB VRAM; host NVIDIA-SMI 580.102.01 reports Windows driver 581.57. Containers receive at most
four CPUs and 10 GiB host RAM for preflight/training/conversion. Lower memory limits were not
benchmarked. Standard `--gpus all` failed because the toolkit is absent; explicit WSL passthrough
successfully ran a CUDA tensor operation with the pinned PyTorch wheel. No administrator host
changes were made by the implementation.

The complete real path passed using `make test-gpu GPU_MODE=wsl`, final run
`e2b3c10d-aaa8-42e1-b3a2-83a4177a49cb`, completed at 2026-10-23 21:58:45 UTC
(2026-10-24 local time):

| Check | Observed result |
| --- | --- |
| LoRA | 12 completed optimizer steps; finite training loss 1.67998 |
| GPU allocation | Peak PyTorch allocation 4,115,387,392 bytes (3.83 GiB); tested on the 6 GiB card |
| Artifact verification | Expected PEFT files, pinned base/revision, nonzero finite learned update and SHA-256 checks passed |
| Held-out comparison | Base and final adapter both produced valid JSON and matched clarification presence on both cases |
| Merge/conversion | PEFT checked merge, text-only safetensors → real GGUF v3 Q8_0 |
| Portable model size | 811,843,232 bytes (774.23 MiB) |
| Isolated runtime | Fresh archive extraction; CPU only, four CPUs, 4 GiB limit, no network, provider key or builder/trainer mount |
| Normal case | Recommended use; clarification question was null; 99 completion tokens in 6.49 seconds |
| Missing-information case | Asked for pre-use inspection status; 115 completion tokens in 5.74 seconds |

Runtime times are measured per HTTP request including Docker exec overhead, after loading. The
second request reused 175 prompt tokens. These two examples are an approximate latency check on
this host, not a throughput benchmark. No smaller memory/CPU/GPU configuration was tested.

Fingerprints for this local run (the large artifacts remain ignored):

```text
adapter_model.safetensors sha256 89a6b74f075cfb214c97e733a47f8ebe6dcc2eada59a83024ddbc25e6523311b
model.gguf               sha256 a0f50c0d3f46e34d90d462fee58a3049ef52e9d73473196a6faa390f8ee370c6
adviser.tar              sha256 bedccdf827d17527ce5f51b963b44fc03b135daa88d1f61777be3e75ecc131cc
trainer image           sha256:9f2af8de0a4b4ed7b0385801a856548eafeb6501120463b200c407959aa0a300
runtime image           sha256:3ed7454ab3575c1169841c83f5ef3e530d23d0582d0fec8d0be7945380f3dc98
```

An earlier 0.0002 learning-rate run (`dc7875f9-d4b1-421b-91b2-72aa2edf196e`) exposed a real
regression: unconstrained adapter responses repeated/truncated JSON, and constrained output made
the wrong normal-case recommendation despite passing schema/clarification-presence checks.
The selected 0.00001 recipe preserved baseline behavior on the two cases. This establishes no
quality improvement. Schema validity and a question's presence cannot establish correctness;
human review and broader frozen evaluations remain required in later milestones.

The first standard GPU launch failed with Docker exit 125 (missing NVIDIA runtime); it saved a
failed state and no adapter/export. An initial trainer configuration used an unsupported
`max_time` keyword; the final recipe uses a deadline callback. TRL 1.16.0 failed on its first
fused-loss forward pass; the supported standard-loss version is documented above. All failed and
canceled attempts remain separate in `data/spike/`; no automatic training retries were performed.

CPU checks cover rejected review changes, train/evaluation leakage, outcome exclusion, malformed
contracts, invented citations, bad GGUF magic/version, corrupt hashes, unsafe archives, subprocess
failure/timeouts and durable failure status. `make test` passed all 72 tests; `make lint` passed.
The default builder also rebuilt and reached healthy state with `docker compose up -d --build --wait`.
No cloud GPU, frontier API, live business corpus or hosted CI run was used.

`make test-export EXPORT=.../e2b3c10d-aaa8-42e1-b3a2-83a4177a49cb/adviser.tar` passed separately,
run `c3148ad7-c236-4f95-86ed-6bb22f1eba5e`, completed at 22:00:35 UTC. A second fresh extraction
and CPU container returned the same advice, with request times 6.25 and 5.89 seconds. The
archive SHA-256 matched the original run. The rebuilt web image served `/healthz` and `/` and
contained no Torch installation; no spike containers were left running after validation.

A final trainer rebuild added `/licenses/QuarterMaster-LICENSE`. Its dependency and worker layers
were cache hits; container checks confirmed the license, unchanged ML package versions and
worker/spec hashes matching the tested source tree. The historical trainer fingerprint above
identifies the actual live run. This notice-only layer received targeted checks without another
GPU job; the tested runtime image ID stayed unchanged.

Unsupported until separately tested: other model revisions, vision, other GPUs, BF16/FP16 training,
CPU training, cloud training, arbitrary LoRA targets, direct-adapter GGUF loading, other quantization
formats, other CPU architectures and production adviser quality. Four synthetic pairs do not prove
generalization; the two held-out cases are a feasibility rubric only. The schema is validated but
does not by itself make a recommendation correct.

Model fallback decision: retain Qwen3.5-0.8B; the merged text-only Q8_0 path worked, so no alternate
model was needed. Direct-adapter GGUF serving remains unverified. A future incompatible revision
must stop the gate and record its error before testing a narrowly chosen alternative and repeating
the complete spike. The app training workflow, candidate promotion and full adviser export UI/API
remain Milestones 6–7.
