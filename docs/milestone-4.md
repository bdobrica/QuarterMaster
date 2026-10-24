# Milestone 4 — Local advice and reviewed context lessons

The Test screen connects a plain-language situation to a local base model, selected Markdown
knowledge and approved lessons. Feedback becomes a draft; explicit approval makes a reusable
lesson available to the next request. This changes context, not model weights. No training or
external business action runs in this flow.

## Owner flow

1. Create a project, define its mission, and optionally review the guided decision definition.
2. Upload Markdown as **knowledge**, then select it in the knowledge revision form.
3. Open **Test advice and teach a lesson**, enter decision-time facts and ask for advice.
4. Inspect the recommendation, supporting explanation, citations, limitations and question.
5. Choose good, wrong call, missing knowledge, should ask, or weak explanation. Write a correction.
   The comment is stored unchanged, including leading/trailing whitespace and newlines.
6. Write a manual reusable lesson, or preview an optional builder request. The latter discloses
   the endpoint/model, exact instructions, context, response schema and UTF-8 byte count. Only
   after explicit consent is the mission, original decision-time case, advice and correction sent.
   Source files, retrieved evidence blocks, spreadsheet records, other cases and other lessons are
   not attached. Advice/corrections may quote business content: inspect the exact disclosure.
   The separate `Case.observed_outcome` field is excluded.
7. Review/edit the applicability and instruction, then approve or reject. AI drafts say `AI_DRAFT`.
   Pending/rejected lessons have no effect. Approval appends reviewed → applied revisions and a
   new adviser revision atomically. Applied/rejected records cannot be rewritten.
8. Enter a similar new situation. Saved context shows the exact approved lessons selected. A rating
   is owner preference, not evidence of factual correctness or business lift.

Builder settings and credential handling reuse the [Milestone 3 configuration](milestone-3.md).
A failed request keeps feedback and disclosure; prepare a new preview to retry explicitly.
Restart recovery marks interrupted builder calls failed and never resends them automatically.
Manual drafting and review need no builder account or API key.

## Local CPU model setup

Ordinary web startup still requires no model, GPU, provider key or model download. Advice requires
an explicit preparation step. Docker is required for conversion and the local inference service;
Python development commands need the locked environment from `make setup`.

```sh
make model-setup
```

This builds a separate converter and CPU runtime from the pinned Trixie recipe. It downloads the
pinned base snapshot if absent, verifies snapshot hashes, extracts its text model, and converts
**without an adapter** to GGUF Q8_0. The existing Milestone 1 snapshot is reused when available.
No teaching/evaluation fixture is mounted, no training executes, and no GPU is requested.
Conversion uses at most 4 CPUs / 10 GiB RAM / 1,200 seconds; the model download is bounded to
900 seconds. Allow several GiB of disk for the upstream snapshot, temporary text weights and GGUF.
Failure leaves diagnostic events in ignored `data/local-setup/<id>`; an incomplete bundle is never
published. A verified existing `data/local-model` is reused without overwriting it.

Copy the printed SHA-256 into your ignored `.env`, alongside:

```dotenv
QM_LOCAL_BASE_URL=http://inference:8080/v1
QM_LOCAL_MODEL_SHA256=<SHA-256 printed by make model-setup>
QM_LOCAL_TIMEOUT_SECONDS=120
```

Start both services:

```sh
docker compose --profile advice up -d --build --wait
```

The profile uses `quartermaster-local-runtime:m4`, built locally by `model-setup` with no automatic
image pull. The inference service has no published port. It mounts only `./data/local-model` read
only, runs as UID 10001, drops capabilities, and is bounded to 4 CPUs / 4 GiB RAM / 128 processes.
The web app has no Docker socket and does not start jobs. To stop the optional service too, use
`docker compose --profile advice down`; the web data volume remains.

The service verifies the GGUF/version, model/revision/engine/format, null adapter, byte size, SHA-256
and license before starting llama.cpp. It serves a model alias containing the base revision and
GGUF hash. The adapter checks `/v1/models` before transmitting a situation, rejects a different
alias, and never forwards builder credentials. This is an operator-controlled local service,
not cryptographic attestation of an arbitrary remote endpoint. Only HTTP loopback addresses or
the `inference` Compose hostname are accepted. For a host Python web process, separately expose
the runtime on a loopback port and use `http://127.0.0.1:<port>/v1`.

Pins remain Qwen/Qwen3.5-0.8B at `2fc06364715b967f1860aea9cf38778875588b17` and llama.cpp at
`1a24df163920a4744a95373d178d790b72a9bb2f`; the Python 3.13 base image is the same digest-pinned
Debian Trixie image as earlier milestones. The new `adviser-runtime` target wraps that verified
engine, rather than changing the Milestone 1 runtime target. See the pinned upstream
[llama.cpp server contract](https://github.com/ggml-org/llama.cpp/blob/1a24df163920a4744a95373d178d790b72a9bb2f/tools/server/README.md).

## Contracts, bounds and evidence

- Existing `quartermaster.case/v1` and `quartermaster.advice/v1` stay compatible.
  [Teaching contracts](../quartermaster/contracts/teaching.py) add `quartermaster.test/v1`,
  `quartermaster.feedback/v1` and `quartermaster.lesson/v1`. Strict models reject extra fields and
  incorrect types. `AdviserSpec.lessons_revision` can now hold the last applied lesson UUID;
  each test also freezes every included lesson ID/revision/text, so selection is unambiguous.
- A test saves a fresh case UUID, UTC timestamp, full adviser revision (including knowledge and
  lesson pointers), verified evidence snapshots/hashes/positions, model alias, engine pin, inference
  parameters (including thinking disabled), response schema, prompt version, exact system/context,
  validated draft/output or sanitized failure.
  Subsequent mission/knowledge/lesson changes do not rewrite the response.
- One SQLite read snapshot captures adviser and lesson state. Knowledge uses the captured revision
  and verifies actual original bytes/excerpt positions before any local model call.
- Context is bounded to 24,000 UTF-8 bytes. The original situation/choices and mission/definition
  are never silently truncated. FTS retrieval searches the first 200 situation characters; up to
  four whole verified chunks are included. Up to eight whole approved lessons are ranked by
  applicability word overlap, then recency and UUID; broad lessons remain eligible. A limitations
  message reports omitted retrieved excerpts/approved lessons. Lexical selection has limited
  semantic relevance; inspect the saved context and test related situations.
- The local request is limited to 48,000 bytes and response to 64 KiB, one in-flight request, a
  configurable 1–180 second timeout, 512 output tokens, temperature 0 and seed 17. The server uses
  8,192 context tokens, no context shifting, CPU only and thinking disabled. Oversized token
  contexts fail visibly instead of discarding input. Fixed parameters do not guarantee identical
  outputs across hardware/engine versions. Redirects, environment proxies and automatic retries
  are disabled; tool calls, refusals and truncated/invalid JSON are rejected.
- The internal structured draft declares recommend/clarify/abstain, exact supporting quotes and
  missing decisive information alongside `Advice`. Generation uses behavior-specific JSON-schema
  branches: recommendations/abstentions have a null
  question, clarification has a question, and citation IDs are constrained to retrieved evidence
  (an empty array when none exists). Post-validation also rejects nonexistent citations,
  fabricated supporting quotes in decisive recommendations and recommendations without supporting
  quotes. Missing information
  or a clarification question replaces a decisive draft with a withholding response and question.
  Clarification/abstention generation uses empty support arrays. The withholding response discards
  unused draft support text; it never displays those quotes as evidence. Abstention is valid.
  Rejected drafts are retained for inspection but never displayed as advice.
- These checks establish provenance and enforce declared missing-information behavior. They cannot
  prove that a quoted fact entails a recommendation or detect every omitted fact, hallucination,
  conflicting document or prompt injection. Small-model judgment still needs human review.
  Source excerpts/cases are explicitly untrusted data; explanations describe supporting facts,
  not hidden reasoning. Approved lessons are owner instructions, not observed factual evidence.
- No source history, target candidate, separate observed-outcome field or held-out evaluation
  target is retrieved into advice or lesson drafting. Free-text situations are owner-authored decision inputs; the UI
  explicitly asks owners to omit later outcomes. This flow creates no SFT examples or evaluations.

API routes use `/api/projects/{id}/tests` (POST, recent GET), `/tests/{test_id}` (GET),
`/tests/{test_id}/feedback` (POST), `/feedback/{feedback_id}` (GET), `/lessons` and
`/lessons/revisions` (GET), and `/lessons/{lesson_id}/{prepare,send,manual,review}` (POST).
Every mutation checks same-origin; HTML forms also require Origin. Send requires explicit Boolean
consent, matching lesson UUID, disclosure digest and expected revision. All lookups are project
scoped. SQLite schema v4 adds three metadata tables transactionally; existing source bytes and
historical documents are preserved. The UI lists the latest 50 tests; saved-test links can open older originals directly.

## Verification record

Verified on 2026-10-24 (local time):

- `make test`: **311 passed**, Python 3.13.5. CPU fixtures block outbound network connections.
  Coverage includes the complete baseline → correction → consented builder draft → edited
  approval → unseen retest loop; pending/rejected exclusion; all feedback categories; unchanged
  correction text; source/citation integrity and history; invented citations/quotes; unsupported
  recommendations; safe clarification/abstention; input/schema/type/extra-field rejection;
  consent replay/staleness/provider changes; project isolation/CSRF; local HTTP failures,
  timeouts/size/truncation/model mismatch; context bounds; interrupted builder recovery;
  base conversion failure/no retry; bundle reuse; populated v3 migration preservation.
- `make lint`: Ruff check and format check passed (60 Python files).
- `uv run --locked python -m quartermaster.setup_local --skip-build`: real **CPU-only** conversion
  of the previously downloaded, hash-verified upstream base snapshot; no adapter, training fixture,
  GPU device or provider credentials. `make model-setup` subsequently reused the verified bundle
  and built the licensed runtime image. Published model: **811,843,232 bytes**, SHA-256
  `c85ac7c9cb8ecb014270ee852dd9580cff838ad294120c6dabfb41f5be29b004`.
- Fresh isolated real-model container: network `none`, read-only, nonroot, 4 CPUs / 4 GiB limit,
  no GPU. A separate temporary web container shared its network namespace and used the actual
  HTTP adapter. [Real CPU smoke](../tests/smoke_local.py) produced valid structured responses for
  two synthetic cases. The missing-damage case asked for damage status and withheld a decision.
  The complete-information case **over-asked** for tool type/location: its clarification rubric
  **failed**. The script records schema/transport and rubric results separately (`[False, True]`).
  Observed request times were 7.96 and 11.63 seconds on this Intel i5-9300H WSL2 host with four
  container CPUs; these two requests are not a latency benchmark or a quality evaluation.
- Earlier real probes exposed an invented citation, a string saying no question was required,
  and a missed unknown fact. Citation validation rejected the invented reference. The final
  implementation constrains evidence IDs/questions during generation and assesses missing inputs
  before advice. Clarification uses no factual support quotes; displayed withholding text discards
  unused draft support. These narrow fixes do not establish general factual accuracy.
- Fresh production web image (Python 3.13.17 Trixie, 26 installed packages, no Torch/Node/SDK):
  [teaching HTTP smoke](../tests/smoke_teaching.py) passed all forms, consent, draft exclusion,
  approval, unseen retest, manual rejection, escaped hostile text and immutable snapshots.
  [Interview](../tests/smoke_interview.py) and
  [foundation](../tests/smoke_foundation.py) HTTP smokes also passed. These ran with network `none`,
  a read-only filesystem, nonroot user and temporary data; model providers were synthetic
  loopback HTTP fakes. They prove request/state/context wiring, **not real-model generalization**.
- `docker compose --profile advice up -d --build --wait`: web and CPU inference healthy, web
  published only at `127.0.0.1:8000`, inference with no host port. The web service's configured
  model identity matches the local server. The two local settings were added to this checkout's
  ignored `.env`, preserving other settings. No API key was added.
- Before upgrading, SQLite's online backup wrote
  `/data/backups/pre-milestone-4-0f0f95db-bae7-47f6-83ed-c51f6590ecab.sqlite3` and a companion JSON
  of table counts/hashes. After schema v3 → v4, all **10** previous metadata/index tables matched.
  This live volume had zero projects; populated preservation is covered by the automated fixture,
  including mappings, cases, knowledge, interview revisions and unchanged original source bytes.
- `git diff --check` passed. Model bytes, setup logs and `.env` remain ignored. Temporary smoke
  containers were removed; only the application and optional inference service remain running.

The baseline/correction/unseen fixture is explicitly AI-drafted synthetic **software test data**,
not reviewed SFT supervision. No external builder call, live GPU training, cloud job, new export
run or manual browser visual inspection was performed for this milestone. Weights are unchanged.
The small base model's judgment, unnecessary questions and real lesson generalization require
further owner evaluation; no factual-correctness or business-lift improvement is claimed.

To repeat the deterministic HTTP checks after building the web image:

```sh
docker run -d --name quartermaster-m4-http-check --network none --read-only \
  --cap-drop ALL --security-opt no-new-privileges --memory 512m --cpus 2 \
  --tmpfs /tmp:rw,nosuid,nodev,size=32m \
  --tmpfs /data:rw,nosuid,nodev,size=64m,uid=10001,gid=10001 \
  -e QM_LOCAL_BASE_URL=http://127.0.0.1:8092/v1 \
  -e QM_LOCAL_MODEL_SHA256=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
  -e QM_BUILDER_BASE_URL=http://127.0.0.1:8091/v1 \
  -e QM_BUILDER_MODEL=synthetic-smoke quartermaster-web
docker exec -i quartermaster-m4-http-check python - < tests/smoke_teaching.py
docker exec -i quartermaster-m4-http-check python - < tests/smoke_interview.py
docker exec -i quartermaster-m4-http-check python - < tests/smoke_foundation.py
docker rm -f quartermaster-m4-http-check
```

For the opt-in real CPU script, use a fresh temporary web/data container configured with the
verified model hash and a loopback connection to the real runtime, then pipe
`tests/smoke_local.py` into that web container. It creates synthetic projects in that container's
data; do not run it against a business volume. Record its rubric misses as well as successful
schema/transport checks. If model preparation rejects an existing invalid `data/local-model`,
move that directory aside before rerunning setup; it is never silently overwritten. Do not
substitute a merged Milestone 1 spike model for the unmodified base bundle.
