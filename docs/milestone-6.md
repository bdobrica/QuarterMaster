# Milestone 6 — reviewed supervision and local LoRA jobs

The Train screen turns applied corrections into separately reviewed supervised examples. It
freezes a dataset and queues one bounded local training attempt, records immutable candidates,
compares base/candidate advice on identical frozen context, and requires explicit owner selection.
Application export remains Milestone 7. Workflow verification does not establish adviser quality.

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

The live M6 GPU workflow remains **unrun**, awaiting explicit owner fixture review and GPU opt-in.
The M1 GPU result is separate and does not prove this new application path. No new training,
real candidate-model inference, model-quality improvement, cloud job, external builder request,
application export or visual browser check is claimed by the CPU checks above.

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
