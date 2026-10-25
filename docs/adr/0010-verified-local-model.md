# ADR 0010: Use a verified local base with a compatible bounded LoRA path

Status: Accepted · 2026-10-26

Supersedes ADR 0002's original-base-only choice for new installations. Preserve the original
model, jobs, adapters, recipes and exports. Retains ADR 0009's context-v6 and non-thinking profile.

## Decision

Use `Qwen/Qwen3.5-4B` revision `851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a` as the preferred
setup, with the same pinned llama.cpp engine. Verify the exact upstream snapshot, original
license and converted Q8_0 bytes. This is a second fixed supported pin, not a model catalogue.
The [upstream model](https://huggingface.co/Qwen/Qwen3.5-4B/tree/851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a)
retains its Apache-2.0 terms. The tested GGUF hash is
`78ea1056e3bd63c91968dc28a5cc6bca9cd582584689a67dae49b5d028570cc3` (4,482,402,848 bytes).

Setup uses a separate directory and prints revision, fingerprint and memory settings. New
advisers capture the configured pin; an existing adviser changes through an explicit versioned
Advanced action. Preserve knowledge, teaching and historical selections. Never attach an adapter
to a different base or silently serve a different configured model. Original configuration
defaults still deserialize to the original 0.8B pin; no data migration changes old model identities.

For the 4B model use the fixed `lora-recipe/v2`: NF4 frozen base, float16 compute, double
quantization, non-reentrant gradient checkpointing and the existing q_proj/v_proj LoRA targets.
The optional trainer alone adds [bitsandbytes 0.49.2](https://pypi.org/project/bitsandbytes/0.49.2/).
This follows the [official PEFT quantization path](https://huggingface.co/docs/peft/developer_guides/quantization).
The selected hardware could not hold the larger base in the original float32 training recipe.
Merge reloads the exact original base in float32; Q8_0 portable conversion uses the original
engine. Serving/export require neither bitsandbytes nor a GPU. Historical recipe-v1 remains
float32. Keep 12/48-step and 20/60-minute training bounds, explicit execution and promotion.

Preflight checks model pairs and image capabilities before GPU work. 4B training requires at
least 7.5 billion VRAM bytes and 32 GB free artifact disk plus images. Training allows 10 GiB
host memory; conversion allows 24 GiB. CPU serving allows 6 GiB and four threads. The candidate gateway uses a finite 90-second
cold-start window for larger files, retaining the original 30-second window for the old model. The larger
portable model uses `export/v5`, explicitly requiring a new labelled runtime. Historical export
versions retain their 3 GB limit; per-pin verification bounds new files to 6 GB. No historical
model/source bytes or manifests are rewritten.

## Evidence and limits

The pinned 4B base with context-v6 passed **12/12** synthetic development controls: two prices,
Visit/Pass, required missing facts, irrelevant unknowns, short-circuit conditions, an impossible
future outcome and non-apartment time/count examples. With the supported verification entrypoint,
controls took 24–44 seconds each. Expected results remained outside prompts and training.

Real Chromium checked an uploaded/cited owner policy yielding **55,000 EUR**, a corrected
**54,000 EUR** becoming teaching evidence automatically, a new unknown repair condition yielding
clarification without a target, **Visit** for a supported category case and a new **72,200 EUR**
proposal informed by related reviewed judgments. The latter still requires the owner's review;
these are synthetic development cases, not an uncoached user trial or unseen accuracy benchmark.

On three identical saved browser inputs, 512-token bounded thinking returned the same typed
number/category and clarification states. Its missing-condition explanation incorrectly carried
54,000 from the previous owner's case into the new case's possible prices; non-thinking correctly
explained 60,000 versus 55,000. Thinking took 93–131 seconds; one request overlapped another
CPU verification job, so these timings are observations, not a controlled speed ratio. No
output-quality advantage justifies changing the shared non-thinking training/inference profile.
Only final explanations were inspected; hidden reasoning was neither exposed nor used as labels.

A real 12-step 4B NF4 LoRA run completed on an RTX 2070 SUPER (8 GB, compute 7.5, WSL/CUDA
12.6), including nonzero adapter verification, safe merge, portable conversion and four identical-
context taught-case replays. Base replay gave three abstentions/one clarification; candidate
replay gave four abstentions. Those frozen cases had no explicit price rule or retrieved previous
decisions. This run **did not establish useful weight personalization**. Candidate
`bec557db-d716-4f85-b6a7-68a1fc4d69cd` remains unselected. Do not report the policy/retrieval
successes as LoRA gains. Standard/longer training and other GPU families remain unverified.

The real version-5 candidate export passed fresh isolated CPU Compose: no builder database,
provider, external network or GPU; schema, frozen context and accessible citations verified.
Its abstention establishes runtime compatibility, not personalized advice quality. The read-only candidate gateway also served the real 4B artifact without
promotion after a cold-start timing regression was fixed. CPU tests
also cover number/category lineage, explicit base switching, incompatible adapters, reserved
cases, historical serialization and the portable package dependency boundary.

Local evidence remains under ignored `data/reliability-20261025/`: original diagnostic snapshots,
`installed-4b-v6.json`, `4b-thinking-comparison.json`, browser report/screenshots and the isolated
`adviser-4b` clone with job, comparison and export reports. Original stabilization evidence is
unchanged. No weights, uploaded sources or credentials belong in Git. Owner-material rehearsal,
genuinely new personal judgments and a nontechnical trial remain acceptance gates in TODO.
