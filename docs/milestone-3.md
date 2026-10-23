# Milestone 3 — Guided adviser definition

Open a project and choose **Define the adviser through a guided interview**. A short, fixed
sequence asks about mission, optional business goal, available choices, target behavior,
historical case grain, what is known before advice, and how success or harm could be observed.
Existing mission/goal prefill the answers. Each answer saves locally; earlier answers remain
editable. This milestone defines the adviser; generating advice and teaching lessons are M4.

## Owner workflow

1. Answer each question. Say “not applicable” for a goal or outcome measure that does not apply.
   Changes create timestamped interview revisions and invalidate earlier request previews/drafts.
2. Choose **Review a draft from my answers** to work entirely offline. This creates an
   `OWNER_DRAFT` without changing the active adviser. A provider is optional.
3. With a provider configured, optionally select up to three Markdown knowledge excerpts and
   prepare an exact request preview. Preparing sends nothing. Inspect the destination, model,
   business context, system instruction and response schema. Check the consent box and send
   once only if the displayed content may be transmitted.
4. Provider interpretation creates an `AI_DRAFT`. Inspect the complete proposed `AdviserSpec`,
   edit its plain-language fields, then **Apply reviewed specification** or **Reject**.
   Applying atomically appends an adviser revision; rejection leaves active behavior unchanged.
   The full model pin and knowledge pointer remain controlled by existing project configuration.
5. Timeouts, connection/rate/authentication errors and invalid JSON show sanitized codes. Answers
   remain saved. Use a new preview and consent to retry, or use the manual draft. There are no
   automatic HTTP retries, repair calls or paid background jobs. Restarted in-flight requests
   become failed revisions; restarting never retransmits them.

The visible `needs_examples` state remains throughout this milestone. No product training-example
review store exists yet. Source role “examples”, mapped target columns, owner preference and
interview approval do **not** establish ground-truth ideal advice or factual/business improvement.
No historical rows become supervised examples, and no model weights change.

## Provider configuration and disclosure

Set these in the environment or ignored `.env`, then restart the app/Compose service:

```dotenv
QM_BUILDER_BASE_URL=https://your-provider.example/v1
QM_BUILDER_MODEL=your-compatible-model
QM_BUILDER_API_KEY=your-key
QM_BUILDER_TIMEOUT_SECONDS=20
```

These are configuration placeholders, not a tested live provider/model combination. The endpoint
appends `/chat/completions`. Remote providers require HTTPS; plain HTTP is allowed for literal
loopback hosts. URLs containing user info, query parameters or fragments are rejected. The model
must support `response_format: json_schema` with `strict: true`, `max_completion_tokens`, and
`store: false`. There is no paid default and no silent fallback to another model or weaker format.
The implementation follows the [official structured-output format](https://developers.openai.com/api/docs/guides/structured-outputs);
responses are also validated locally for required fields, types, length limits and unknown fields.

Instead of `QM_BUILDER_API_KEY`, set `QM_BUILDER_API_KEY_FILE` to a readable UTF-8 regular file
of at most 4 KiB. Do not configure both. In Docker the file must be mounted separately at that
container path (for example a Compose secret at `/run/secrets/builder_api_key`); setting the
environment reference alone does not mount a host file. Keep secret files outside tracked files
or under ignored `secrets/`. A local compatible server may omit authentication. Credentials are
read only by the adapter and never stored in interview/spec documents, response previews or logs.
Environment proxy settings are ignored and redirects are not followed.

**Send generic provider test** makes exactly one structured request without project/source data;
it requires its own explicit click and may incur a charge. `/healthz`, startup, opening a page,
saving answers and uploads never call a provider.

Every business request needs explicit consent, including mission/answers/schema summaries even
when no excerpt is selected. The disclosure identifies the full endpoint and model, shows exact
system/context/schema text, and records a SHA-256 fingerprint, turn UUID and consent timestamp.
Changing an answer, provider/model or active adviser revision invalidates the old request.
Consent does not authorize a later retry. The server sends the frozen preview, not a newly
retrieved context. Provider storage/retention remains subject to the provider's own policy;
`store: false` is not a promise of zero retention.

## Minimization, bounds and contracts

- Ordinary context includes the owner answers/project name and metadata for the first 10 sources,
  at most four sheets/source and 30 fields/sheet. Metadata includes source IDs/hashes, roles,
  row counts, field names, likely types, missing counts and candidate role hints. Names are
  clipped to 120 characters, and the truncation limits/totals appear in the preview.
- It never serializes spreadsheet samples, cell values, derived case situations, observed
  outcomes or target-advice candidates. No evaluation cases are queried. The interview is not
  a synthetic-example generation prompt. Owner-entered answers and explicitly selected excerpts
  can contain sensitive information; inspect the preview before consenting.
- Optional excerpts are the first 1,000 decoded characters of up to three project-scoped Markdown
  sources labeled knowledge. Each includes verified original SHA-256 and exact character span.
  No automatic source selection, retrieval or attachment of whole files occurs. Excerpts and
  schemas are marked untrusted data; generated text has no execution/tool capability.
- Disclosure snapshots are capped at 48,000 UTF-8 bytes; actual JSON HTTP bodies and decoded
  responses at 64 KiB. The configured total timeout is 1–30 seconds (20 default). Requests set
  a 2,048 completion-token ceiling, one non-streamed completion and no automatic retries.
- [Interview contracts](../quartermaster/contracts/interview.py) define
  `quartermaster.interview/v1`, strict answer/prepare/consent/review requests and restricted
  provider interpretation fields. Explicit consent must be boolean `true`, not `1` or a string.
  AI proposals cannot set model/adapter pins, knowledge membership, labels or training examples.
- [AdviserSpec](../quartermaster/contracts/adviser.py) retains `quartermaster.adviser/v1` with
  an optional backward-compatible `decision_definition`: choices, target behavior, grain,
  decision inputs and success/harm. Existing documents load with null; historical JSON is not
  rewritten. Manual field mapping remains a separate explicit M2 review; interview descriptions
  do not automatically map/join fields or relabel source roles.
- SQLite schema v3 adds only `interview_revisions`. The v2→v3 migration is transactional and
  leaves earlier documents/source bytes intact. Answer, preview, sending, failure, proposal,
  rejection and application states append snapshots. Stale revisions return 409; concurrent
  sends/edits on one interview are blocked. Back up before upgrading; older releases cannot
  open schema v3. This continues the trusted, single-process/single-user deployment model.

The [BuilderLLM protocol and adapter](../quartermaster/builder.py) use the already pinned HTTPX2
client, promoted from development to runtime dependency. No SDK, Node build, GPU/model package,
additional service or generated application code is introduced.

## API

The local `/docs` describes strict JSON schemas. JSON mutations enforce the existing same-origin
rules; browser forms require Origin. Public JSON routes under `/api/projects/{project_id}/interview`:

| Method / suffix | Operation |
| --- | --- |
| `GET` root / `GET /revisions` | Current interview / append-only history |
| `POST /answers` | `expected_revision`, `topic`, `answer`; save or edit one answer |
| `POST /manual` | `expected_revision`; propose spec from completed owner answers |
| `POST /prepare` | `expected_revision`, optional `excerpt_source_ids`; create disclosure |
| `POST /send` | `expected_revision`, `turn_id`, `disclosure_sha256`, boolean `consent: true` |
| `POST /review` | `expected_revision`, `action: apply/reject`, optional restricted `edited` interpretation |

`POST /api/builder/test` accepts only `{"consent": true}`. Business-call failures return a saved
interview with `status: failed` and actionable `error`; failed consent, validation and stale-state
checks use 4xx responses without provider transmission. No endpoint accepts an API key.

## Verification

Locally verified on 2026-10-24:

- `make test`: **242 passed**, Python 3.13.5, offline CPU suite. Includes manual and mocked
  interviews, editable/rejected drafts, target/outcome exclusion, excerpt provenance, source
  corruption, byte/schema limits, literal consent, CSRF, stale/busy/replayed requests, provider
  changes, invalid/truncated/refused JSON, auth/rate/HTTP/timeout errors, no implicit retry,
  credential sanitization, restart recovery and v1/v2 migration preservation.
- `make lint`: Ruff and formatting passed for 49 Python files.
- `docker compose build web`: production Python 3.13.17 Trixie image built, 26 installed runtime
  packages, no Torch/provider SDK/model download.
- [Interview HTTP smoke](../tests/smoke_interview.py): **passed** in a disposable non-root web
  container with read-only root, 512 MiB RAM, two CPUs, temporary data and `--network none`.
  A loopback-only synthetic HTTP fake exercised the actual adapter, generic provider test,
  consent, manual rejection, malformed JSON, explicit retry and edited spec application.
  Exactly three synthetic HTTP provider requests; no external provider traffic.
- [Existing foundation HTTP smoke](../tests/smoke_foundation.py): **passed** in that same image,
  covering CSV/XLSX/Markdown, case provenance/outcome isolation, knowledge revisions and citations.
- `docker compose up -d --build --wait`: local application healthy at `127.0.0.1:8000` on schema
  v3. An online SQLite backup was retained under `/data/backups/pre-milestone-3-*.sqlite3` before
  upgrading. All earlier metadata table counts/hashes were unchanged afterward. That volume had
  zero projects; populated migration preservation is covered by the CPU tests, not claimed as
  a live-data migration demonstration.

No real frontier-provider request, GPU job, training, advice generation or export was run for M3.
The mocked/fake results establish workflow behavior, not model interpretation quality. Browser
forms/rendering were checked over HTTP; visual appearance was not manually inspected.

Repeat the isolated checks after building the image:

```sh
docker run -d --name quartermaster-m3-smoke --network none --read-only \
  --cap-drop ALL --security-opt no-new-privileges --memory 512m --cpus 2 \
  --tmpfs /tmp:rw,nosuid,nodev,size=32m \
  --tmpfs /data:rw,nosuid,nodev,size=64m,uid=10001,gid=10001 \
  -e QM_BUILDER_BASE_URL=http://127.0.0.1:8091/v1 \
  -e QM_BUILDER_MODEL=synthetic-smoke quartermaster-web
docker exec -i quartermaster-m3-smoke python - < tests/smoke_interview.py
docker exec -i quartermaster-m3-smoke python - < tests/smoke_foundation.py
docker rm -f quartermaster-m3-smoke
```

Run the scripts once each after `/healthz` is ready. The snippets use a disposable container and
temporary data, not the owner's Compose volume or credentials.
