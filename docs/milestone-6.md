# Milestone 6 — reviewed supervision and local LoRA jobs

The Train screen turns applied corrections into separately reviewed supervised examples. It
freezes a dataset and queues one bounded local training attempt, records immutable candidates,
compares base/candidate advice on identical frozen context, and requires explicit owner selection.
Application export is described in [Milestone 7](milestone-7.md). Workflow verification does not establish adviser quality.

## Owner workflow

1. On Test, correct an answer and approve the resulting lesson for immediate context use.
2. Open Train and create a draft from the applied correction. The original situation is copied
   without its observed outcome; the approved lesson does not automatically become a target.
3. Write the desired response in the form, or prepare a separate synthetic AI draft. Preview
   the exact provider endpoint/model, system, mission, lesson and seed situation before consenting.
   No holdout cases, rubrics, source files or separate observed outcomes are attached. Free text
   may still contain sensitive content; inspect the disclosure. No external call happens on page load.
4. Inspect the full system prompt, decision-time context, target and lineage. Approve or reject
   each example. AI provenance stays `AI_DRAFT` after approval. Pending/rejected examples never
   enter SFT, change lessons or alter active weights. Approved revisions cannot be edited.
5. Freeze an unseen evaluation suite before training. Select distinct approved examples, that
   frozen suite and quick/standard. Acknowledge the small-data/overfitting warning. Five examples
   do not establish quality; a single example is permitted for workflow experiments with this warning.
6. Queue the immutable dataset. Queueing uses no GPU. An operator runs the explicitly enabled
   local worker against the same data directory, as below. Refresh Train for durable stage progress.
7. Inspect the candidate's side-by-side A (unmodified base) and B (trained weights) outputs,
   questions, citations, narrow behavior checks and written rubric. Both use the frozen suite's
   exact B context. Record preferences with unchanged rationale, separate from observed outcomes.
8. Explicitly select a verified candidate after acknowledging regressions/unreviewed cases, or
   retain the base/choose an earlier verified candidate. Structural smoke checks are not a quality
   threshold. Selection changes weights only; today's knowledge and lessons still apply in Test.

## Operator setup

The ordinary Compose web service has **no Docker socket**, GPU dependency or trainer libraries.
The optional worker is a Linux host CLI using the Docker CLI. It does not import trainer internals.
It processes one queued job and exits; rerun it explicitly for another job. A host file lock and
transactional global claim prevent concurrent workers/jobs. No distributed queue or new Python
dependency is used. This MVP supports a local Docker daemon, not a remote daemon with different paths.

The worker and web must see the same host-backed SQLite/artifact directory. For a **new** training
installation, from the repository root:

```sh
mkdir -p data/training-app
uv sync --locked
docker compose -f compose.yaml -f compose.training.yaml --profile advice --profile training up --build -d --wait
```

The override uses `./data/training-app` and UID/GID 1000 by default. Set `QM_TRAINING_DATA_DIR`,
`QM_LOCAL_UID` and `QM_LOCAL_GID` for your host if needed; ensure both the host user and configured
container UID can write it. The advice base bundle still comes from `make model-setup` and the
settings in [Milestone 4](milestone-4.md). Compose's candidate service has only read access to the
artifact volume and no published port; it loads a verified candidate lazily on the first Test request.

**Existing named-volume installations:** do not apply the override to an empty directory and
mistake it for an upgrade. Stop the web service, make an SQLite online backup and a full volume
backup, then copy the entire existing data volume into an empty host directory, including source
and artifact bytes. Verify the copy's hashes and ownership before applying the override. Keep
the original volume and backup. A normal `docker compose up --build` continues using the existing
named volume and exposes review/queueing without enabling host training; no automatic data move occurs.

Build the pinned images (ordinary image builds, no GPU job):

```sh
docker build -f trainer/Dockerfile --target trainer -t quartermaster-trainer:m6 .
docker build -f trainer/Dockerfile --target runtime -t quartermaster-runtime:m6 .
docker image inspect quartermaster-trainer:m6 --format '{{.Id}}'
docker image inspect quartermaster-runtime:m6 --format '{{.Id}}'
```

Then supply the two exact printed `sha256:...` **image IDs**, the existing verified base snapshot
and base GGUF directory to this reviewed worker command. Replace the image placeholders:

```sh
uv run --locked python -m quartermaster.training_worker \
  --run-gpu \
  --data-dir ./data/training-app \
  --base ./data/spike/base-2fc06364715b967f1860aea9cf38778875588b17 \
  --base-gguf ./data/local-model \
  --trainer-image sha256:REPLACE_WITH_TRAINER_IMAGE_ID \
  --runtime-image sha256:REPLACE_WITH_RUNTIME_IMAGE_ID
```

Default GPU passthrough needs NVIDIA Container Toolkit. The verified M1 WSL alternative is
`--gpu-mode wsl`, mounting `/dev/dxg` and `/usr/lib/wsl` read-only. See
[host setup and limitations](milestone-1.md). No implicit model download, cloud fallback or retry
occurs in this command. CPU inference and conversion do not receive GPU devices.

Preflight verifies GPU availability, at least 5.5 billion bytes VRAM (nominal 6 GB), compute
capability at least 7, 12 GB free artifact disk plus image space, base snapshot hashes, base GGUF
and license, trainer contract label and the pinned llama.cpp engine label. These are conservative
allowances, not promises that every allowed sequence fits every GPU. OOM fails durably; it never
silently changes precision, truncates targets or restarts training.

| Preset | Steps | Sequence cap | Training hard limit | LoRA |
| --- | --- | --- | --- | --- |
| quick | 12 | 2048 tokens including target | 1200 seconds | rank 4, alpha 8, q_proj/v_proj |
| standard | 48 | 2048 tokens including target | 3600 seconds | same fixed recipe |

Both use float32, completion-only NLL, LR 1e-5, seed 17, batch/accumulation 1 and gradient
checkpointing, reusing the verified pinned M1 libraries. An oversized example fails rather than
being truncated. Limits are maximums, not estimated completion times. Containers have four CPUs,
10 GiB RAM/swap limit, 256 PIDs, read-only roots, no network, no capabilities, no restart policy
and a bounded tmpfs. Only preflight/training receive GPU access. Preflight/conversion have separate
1200-second deadlines; the entire CPU comparison has a 1200-second deadline and finite requests.
The worker additionally enforces wall-clock bounds, polls cancellation and removes its containers.

Trainer mounts contain only the immutable job/dataset input (read-only), verified base
(read-only), and this job's output. Conversion receives only base, input metadata, verified
adapter (read-only), and portable output. No builder credentials, database, home directory,
Docker socket, original uploads, evaluation rubrics or evaluation targets enter the trainer.

## Contracts and lineage

[Public contracts](../quartermaster/contracts/training.py) define `training-example/v1`,
`training-job/v1`, `lora-recipe/v1`, `training-run/v1`, `training-artifacts/v1` and
`adviser-version/v1`. Existing `adviser/v1` now accepts a canonical candidate UUID in
`model.adapter_artifact`; previous null/base records remain readable. The adapter UUID identifies
a verified immutable adviser version, not an executable path. Unknown fields/pins are rejected.

SQLite schema 6 adds only `training_examples`, `training_runs` and `adviser_versions`. Example
and run revisions are append-only. Approval records reviewed → approved revisions. A job freezes
selected example revisions and full prompt/target bytes, source hashes and knowledge revisions,
lesson text/revisions, base revision, recipe, selected frozen suite/hash and all current holdout
IDs/fingerprints. JSONL is stably ordered by example UUID; each row retains example ID/revision
and system/user/assistant messages. `input/job.json` and `input/train.jsonl` live under
`artifacts/training/<job-uuid>/` and are hash-checked before dispatch. Outputs are never overwritten
by a retry; a new run gets a new UUID. Job lineage and exact dataset are inspectable via Train links.

Exact/normalized cases and conservative lexical near duplicates are blocked at selection,
before synthetic prompts, on generated-case return, at freeze and at dispatch. New evaluation
reservations also reject already taught/training situations. The lexical guard uses token-order
similarity or token-set Jaccard ≥0.9; it may reject distinct cases with similar wording and does
not detect all semantic paraphrases. Owner review remains required, including keeping entities/time
separate where relevant. No general entity/time split can be inferred from arbitrary situation text.

Jobs progress queued → preflight → training → verifying → converting → evaluating → completed.
Failure/cancel/interruption are durable terminal states. Raw trainer/library stdout can contain
examples, so Docker logging is disabled and UI logs contain at most 100 fixed stage diagnostic
events; customer prompts, raw exception messages and credentials are not logged. GPU metadata and
package versions are saved in `output/preflight.json`; partial comparison outputs are checkpointed
in the local `comparison.jsonl` artifact. Cancellation intent is persisted and checked between stages
and while containers run. A worker restart first removes orphaned containers and marks old active
jobs interrupted without retraining. Web restarts leave an independently running worker alone.
If Docker cleanup fails, `cleanup_required` keeps the global slot blocked until worker recovery
can stop the orphan; that run cannot be promoted.

Completion requires manifest/job/dataset/base/recipe agreement, exact adapter file set and
hashes/sizes, LoRA metadata and safetensors framing, completed steps and finite loss. The trainer
also checks finite tensors and a nonzero LoRA update. Only the fixed safe merge/quantization path
produces the candidate GGUF; GGUF v3 bytes, size, license and hashes are checked. A verified candidate
is registered only after smoke and frozen-suite inference. Candidate UUID, adapter, merged GGUF,
training image ID, runtime image ID, suite hash, identical input hashes and outputs remain distinct
from the original base. Selection re-verifies artifacts. Runtime verifies model/license hashes
before loading; unavailable/corrupt candidates fail visibly rather than falling back to base.

The same pinned CPU llama.cpp image serves both comparison arms. Frozen B system/context,
schema/parameters and base alias must match; only model bytes/alias change. Both arms recheck
accessible evidence and run the existing schema/citation/support validators. A candidate error
fails the job; failed baseline outputs remain visible in comparisons. A wrong/irrelevant question
can pass a narrow clarification check. Rubric misses and preferences never establish causal lift.
This comparison is relative to the unmodified base, not a claim of improvement over every earlier
candidate or over a changing current context.

Active Test inference uses the selected candidate gateway, current knowledge and lessons.
Returning to base or selecting an earlier verified candidate creates another adviser revision.
The candidate gateway requires no ML Python packages, builder API or database: it verifies the
UUID-addressed local manifest and model, then runs the pinned CPU server. It serializes loads and
requests, and reports busy/unavailable errors. This is an application inference service; a portable
user export package is still Milestone 7.

## Verification

Executed locally on 2026-10-24:

- `uv run --locked pytest tests/test_training.py -q`: **42 passed**, with mocked GPU/container
  stages, real SQLite/filesystem transitions and real HTTP request/schema handling.
- `make test`: **381 passed** on Python 3.13.5, without external network, GPU or provider calls.
- `make lint`: all checks and formatting passed for **79 Python files**.
- Built the production web, pinned trainer and candidate-runtime images. The trainer imported
  the public job contract and its new entry point in an isolated CPU-only container.
- `docker compose -f compose.yaml -f compose.training.yaml --profile training config --quiet`
  passed. The optional candidate gateway booted with no model/GPU, returned healthy status, and
  rejected a missing candidate artifact with a sanitized 503 response.
- `tests/smoke_training.py` passed through real HTTP in a fresh production container: approved
  manual correction → separately reviewed target → frozen holdout suite → frozen JSONL/queued
  job → cancellation, with no builder/GPU calls and unchanged active adviser. The container used
  network none, a read-only root, nonroot UID, temporary data, two CPUs and 512 MiB RAM.
- Populated schema-v5 fixtures preserve all old table rows and original bytes through the v6
  migration; earlier v2/v3/v4 migration regression fixtures also pass.
- Upgraded the actual Compose web service to schema 6 after creating the online backup
  `/data/backups/pre-milestone-6-b0bc379a-47a6-4c80-a0ff-1993645b55f5.sqlite3` and its table/artifact
  fingerprint record. All **22 preexisting SQLite tables** were unchanged after upgrade. The
  actual volume had zero projects/artifacts; populated preservation is covered by fixtures.
  Production health and OpenAPI training routes passed, with no Torch dependency. The default
  named-volume storage, localhost port and existing base inference service were retained.
- Temporary smoke containers were removed. No data-volume migration to host storage or
  optional training-profile activation was performed on the existing installation.

The CPU checks above do not establish real GPU training or candidate-model inference.
The repository owner subsequently approved the exact fixture and one bounded local run;
the live result below verifies this new application path separately from M1. No model-quality
improvement, cloud job, external builder request or visual browser check is claimed.

The opt-in end-to-end command and exact synthetic review are in
[the fixture review](milestone-6-fixture-review.md):

```sh
make test-gpu GPU_WORKFLOW=training GPU_MODE=wsl
```

The original `make test-gpu` continues to run the separate M1 portability spike. The M6 variant
requires the exact fixture hash to have a separate human approval record, creates an isolated
synthetic project under `data/training-smoke/<uuid>`, and never promotes the candidate or changes
the ordinary Compose data volume. CPU mock-generated tensors/GGUF headers are software fixtures,
not real model artifacts or evidence of training success.

## Live GPU workflow verification — 2026-10-24

After explicit owner approval, the following command completed successfully once, with
no training retry or recipe change:

```sh
make test-gpu GPU_WORKFLOW=training GPU_MODE=wsl
```

The four targets retain AI-drafted synthetic provenance and the review SHA-256
`37372a59a51d08134c5f2f284c22c334a194a38f118dfd1d740565963286cbb8`.
The helper created a separate synthetic project, used the public correction/lesson/example
review and dataset-freezing services, then ran the real Docker trainer, adapter verifier,
merge/converter and identical-input CPU comparison. Fixture setup Test records are explicitly
labeled placeholders; the four comparison outputs are real model inferences. The existing
Compose project data was not migrated or modified. The candidate remains unpromoted.

| Check | Observed result |
| --- | --- |
| Hardware | NVIDIA GeForce GTX 1660 Ti, 6,442,123,264 VRAM bytes, compute capability 7.5, WSL passthrough |
| Libraries | PyTorch 2.11.0+cu126 / CUDA 12.6, Transformers 5.20.2, TRL 0.29.0, PEFT 0.21.2 |
| Preset | quick, 12 completed steps, float32, completion-only, rank 4 / alpha 8, LR 1e-5, seed 17 |
| Bounds | Four CPUs, 10 GiB RAM/swap limit, offline stages, 1200-second training deadline |
| GPU observation | 100% utilization and 5953 MiB used at one sampled instant; not a measured peak |
| Training stage | About 107 seconds including loading/setup/saving; finite training loss 2.3105412324269614 |
| Adapter | safetensors checked, finite tensors, nonzero LoRA update, exact files/config/hashes |
| Conversion | Real safe merge and GGUF Q8_0 conversion; 811,843,232-byte model and unchanged model license |
| Comparison | Both cases/arms passed JSON, accessible-citation and supporting-fact checks on identical frozen B inputs |
| Registration | Completed candidate stored immutably; original base and active project selection unchanged |

The tiny evaluation **does not show improved advice**. Both the base and candidate abstained
on the complete polisher case, failing its expected-recommendation check. Both asked about
inspection on the incomplete router case, passing the narrow clarification check, but also
asked about damage already supplied as absent. That extra question misses the full written
rubric. Rendered base/candidate advice was identical on these two cases. No owner preference
rating, factual correctness, useful generalization or business lift follows from this run.
The candidate's distinct model hash proves different bytes, not better judgment.

The suite was frozen **before** the four teaching lessons were applied, deliberately keeping
comparison inputs constant. Its adviser snapshot has no knowledge selection or applied lessons.
The training examples separately retain their applied-lesson context; holdout cases and rubrics
never entered trainer inputs. Export must preserve the evaluated empty knowledge/lesson
snapshot rather than silently adding the later teaching lessons.

Exact local artifacts, under ignored data storage:

```text
data root: data/training-smoke/1c147c6c-8987-4886-8b66-573437fb589a
project: dcfbb238-e827-4fd2-9b28-d0bb213995c7
training run: 55a81cec-48f7-45dc-bad7-212d97629458
candidate: fcafe3ff-139f-4b6b-9f0f-2ba81b3a1409
suite: 51afacfa-7353-4cb4-b958-3cd58e9486e2 revision 4
suite SHA-256: 8e4d0bbec685f583e3610ceec4ac6a5b6593beef91a9bd404321ee1ee49f6466
job SHA-256: eb60a68b86b01697ccecd77c9895bb4a1ae9522f0b461041689ae50604f36cf2
training manifest SHA-256: df8d88f3b8187a40df62b080890af4632538c00a826f6dde2cc74165049c1c89
adapter SHA-256: 4ca4e66ea1d1ba3a5445fb8ef1743c2c30f45361769a3e25d239156618cf7beb
model SHA-256: 8774d0caa5e571f55eb97f2fe3853b67e1377bb444077496fa23f39b67199188
trainer image: sha256:e9c014a9a20dcae4a2ef0bad9554922808ef093ebff25dcdcf2ac2745e4f6ed8
comparison runtime image: sha256:52af5dc170f9b43344961c994c82e637f0c2d04df10c80a10f4201b736d08690
```

Run status progressed queued → preflight → training → verifying → converting → evaluating →
completed between 06:52:34 and 06:57:53 UTC. `verification.json`, the append-only SQLite run
revisions, `output/preflight.json`, `output/training.json` and `comparison.jsonl` retain the
details. No mock adapter, conversion or inference was used for this run. Standard-preset
training, other GPUs and a full manual visual-browser demo remain untested.

After this live run, `make test` passed **419 CPU tests** and `make lint` passed for
**89 Python files**. The original base GGUF and model-license hashes were rechecked
unchanged. All temporary training/export containers were removed; the ordinary
builder and base inference services remained healthy. The real candidate's independent
export verification is recorded in [Milestone 7](milestone-7.md).
