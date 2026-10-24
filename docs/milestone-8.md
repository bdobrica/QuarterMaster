# Milestone 8 — usability, safety and release polish

Implemented and locally checked on **2026-10-24**. The application remains a development build.
The complete human owner-journey release acceptance is still open; **no `0.1.0` tag is created**.
Working components and synthetic software tests do not establish useful adviser judgment.

## Owner-visible changes

- Persistent Teach / Train / Evaluate / Test / Export navigation with actionable blank states.
- `/examples`: downloadable, explicitly **AI_DRAFT synthetic** missions, CSV observations,
  Markdown knowledge and scenario/interview JSON for rental tools, print-proof readiness and
  social-post timing. The third scenario supplies PLAN's numerical social-post observations and
  plainly invented research notes. All domains use the same existing public contracts/engines.
  Downloads never import, approve training labels or queue a job automatically.
- `/help`: upload/mapping/knowledge-replacement guidance, context versus weight learning,
  separate target review, holdouts, hardware/privacy limits and actionable diagnostic codes.
- Interview, correction and synthetic-example provider previews display complete serialized
  request bytes and approximate input tokens. Interview previews also show original file sizes.
  The estimate is UTF-8 bytes / 4 rounded up, including instructions/schema: not a tokenizer,
  cost quote or guarantee of a provider's context limit.
- `QM_BUILDER_MAX_INPUT_BYTES` defaults to **49152**, configurable **4096–65536**. The chosen
  provider's timeout remains configurable **1–30 seconds**, default **20**. All three preview
  paths check the serialized bound before saving a request; the transport checks again before
  sending. The existing 64 KiB response and 2048 output-token bounds, exact-context consent and
  explicit retries remain. Historical disclosure hashes/bytes are not rewritten for display.
- A concise [README](../README.md) and [operator guide](operator-guide.md) cover installation,
  backup/restore, localhost/proxy limitations, source revisions, review, GPU prerequisites,
  model footprint, license/distribution constraints and troubleshooting. Backup filenames in
  the guide are excluded by `.gitignore`.

No dependency, service, persistent schema migration, model recipe, automatic promotion or
external action was added. Images retain pinned Python 3.13 slim **Trixie**. CPU tests have no
network/model dependency; the explicit live demo does not create SFT examples or start training.

## CPU and security verification

Executed:

```sh
uv run --locked pytest tests/test_release_polish.py -q
make test
make lint
```

Results: **16 focused tests**, **435 total tests passed**, lint and formatting passed for
**97 Python files** on Python 3.13.5. Production container Python is 3.13.17 with the existing
26 locked runtime packages and no Torch.

The same public API regression runs all three domains through project creation, uploads,
reviewed mapping with outcomes excluded, manual interview review, cited Test response,
pending → reviewed → applied correction, unseen retest and a frozen evaluation comparison.
It verifies unchanged weights, no unreviewed target approval and no builder calls. Its scripted
inference adapters deliberately simulate a context response change; this is **workflow evidence**,
not a real-model improvement measurement or permission to train on these fixture targets.

New regressions also cover blank pages/download bytes, exact provider request-size estimates,
multibyte input and lowered limits before transmission, unchanged saved answers/examples on
rejection, honest missing-size display for historical previews, sanitized HTTP errors/logs, malicious Markdown/spreadsheet cells, escaped script text,
path-like upload names and refusal to extract into an existing destination. Existing archive
regressions cover traversal, absolute paths, links, duplicate/oversized entries, injected Compose
commands and corrupt hashes. Existing timeout/no-retry, unknown citations, holdout leakage,
correction rejection and failed training/export tests passed in the full gate.

Hostile text remains untrusted context, never system instructions or executable tools. Tests
establish application boundaries and provenance; they do not prove a model resists every prompt
injection. Ordinary Uvicorn access logs are disabled, provider errors omit response bodies,
trainer logs use fixed diagnostics and model servers suppress raw output. Do not enable body/debug
logging, put secrets in case text/URLs or expose private test reports publicly.

## Clean Compose, backup and ordinary installation

Started a new `qm-m8-clean` project and empty volume with `.env.example`, no real credentials,
provider or model/GPU. A tiny override used **127.0.0.1:18008** to avoid interrupting the ordinary
port 8000 application; the rest was the documented base Compose configuration:

```sh
docker compose --env-file .env.example --project-name qm-m8-clean \
  -f compose.yaml -f /tmp/qm-m8-clean.compose.yaml up -d --build --wait
```

Health, landing/examples/help, all five blank tabs, downloads and a synthetic Markdown upload
passed over real HTTP. Inspect confirmed nonroot UID/GID 10001, loopback-only exposure, no GPU,
no Docker socket, and blank provider settings. Build required network access; this was a fresh
application data volume on the existing Docker host, **not a second clean machine**.

Executed the operator guide's exact tar backup/restore Python commands with only test project
names/configuration substituted. The source web was stopped; restore used a separate empty
`qm-m8-restore` volume and port **127.0.0.1:18009**. The restored application started healthy.
All **25 tables** and the one original uploaded Markdown hash matched; SQLite integrity was `ok`.
Backup was 204800 bytes, SHA-256
`3d3f55c90782e0627da1436c3fa246204aa3a425ce845310b110e69906794f2a`.
The ignored evidence is `data/m8-verification/backup-verification.json` and its adjacent archive.
Both disposable Compose projects/volumes were removed after checking.

The ordinary named-volume install was separately backed up online before updating web:
`/data/backups/pre-milestone-8-39415976-56fd-4c20-ba36-36c1694a74db.sqlite3`, with table/artifact
fingerprints in the adjacent JSON. All **25 preexisting tables** and **zero original artifact
files** were unchanged; it still had zero projects. No demo was inserted into that volume.
It remains schema v6, healthy on **127.0.0.1:8000**, with the existing inference service unchanged
and its new examples/help available. Its existing secrets/settings were preserved.

Final web image ID:
`sha256:d8d4abec6604d0f1db3bb59181df5c65d7f761bb88eb9e7fdec6614ba911dfa1`
(config digest `sha256:8b767f5639b193f9e9dea734ecfde146163e264ff4f1270964df4d776dc028d2`).
Only the ordinary healthy web and inference containers remain after verification.

## Real local CPU demonstrations

Ran [the opt-in smoke driver](../tests/smoke_domains.py) against the existing pinned unmodified
CPU model, in separate nonroot containers sharing only the local inference network. No GPU,
builder credential or frontier call was used. Each driver container had 2 CPUs/512 MiB, read-only
root, no capabilities, bounded tmpfs and its own ignored data directory. Inference kept its
existing 4 GiB/four-thread bounds. The driver refuses an existing nonempty directory before app
startup, writes synthetic fixture projects only, never queues training or labels SFT supervision,
and preserves unchanged active model pointers.

For reproduction with an operator-controlled local endpoint, the driver accepts:

```sh
uv run --locked python tests/smoke_domains.py --live \
  --data-dir /absolute/new-empty-demo-directory \
  --base-url http://127.0.0.1:8080/v1 \
  --model-sha256 c85ac7c9cb8ecb014270ee852dd9580cff838ad294120c6dabfb41f5be29b004
```

The shown CLI arguments are the interface; the actual checks ran inside Docker with
`http://inference:8080/v1`, read-only mounts for the driver/examples and isolated `/data`.
The default inference service deliberately publishes no host port: do not expose it just to run
this host example. `--domain social-post` restricts the check to one included fixture. Model hash
and source/version pins remain those in [M4](milestone-4.md).

Each domain uploaded both files, confirmed mapping, applied a manual interview and synthetic
software-test lesson, tried a baseline/unseen situation, froze a separate holdout and ran A/B.
Fixture lesson application in these isolated software tests is not human approval of training
supervision. The generated targets have **not** been promoted to SFT.

| Domain | Live result | Quality limitation |
| --- | --- | --- |
| Rental tools | Baseline/unseen/holdout responses valid; applied lesson appears in unseen context; frozen A/B completes | Over-asks about already supplied or irrelevant facts; full rubric relevance not established |
| Print proof | Cited baseline and holdout valid; lesson context captured; frozen A/B completes | Baseline holds without asking for unknown approval; unseen retest fails with `LOCAL_JSON`, saved as failure |
| Social post | Baseline/unseen/holdout responses valid; lesson context captured; frozen A/B completes | Baseline asks for an already provided window; later outputs still over-ask |

All six frozen evaluation outputs pass schema/citation and narrow “clarify” checks. Several ask
the wrong question or repeat known facts, so these counts **do not show quality gain**. No human
preference ratings, factual labels, business outcomes or causal improvement are inferred. The
print failure is not hidden or silently retried. All three domains have accessible genuine
uploaded citations in at least their baseline response.

Ignored evidence:

- `data/m8-verification/live-domains/verification.json`: print and rental projects and complete
  saved responses/contexts/evaluation outputs.
- `data/m8-verification/social-post/verification.json`: social-post project and same records.
- Print project `dd730322-6aa4-44f4-b758-9d2b3304e011`, suite
  `a623bfa5-b53d-4077-aa23-8388e4b541e0`, frozen SHA
  `bb8d5a182d03928da2956455723120269c500e36f7fd511a76c706d3e5bf814c`.
- Rental project `a3346859-d976-4c5c-b0b3-e784ebf5b158`, suite
  `4a061188-b8ec-4d8e-a321-54c7379fffe1`, frozen SHA
  `53ff8e7ce861f05dd6a00dd47f7eb0ed4959c3e97d0fc7abf6eca5f33198f774`.
- Social project `25a17711-332c-4aef-bdf2-bd4213d806f4`, suite
  `53c1c814-15ff-4a43-8e49-df475293998b`, frozen SHA
  `ebd21ef9abb05ba2728a9c01f7d15eccc4beb03f83b609db7e3027bf11b8a8ed`.

## Real GPU evidence and fresh independent export

**No new GPU job was run for M8.** The model/trainer/recipe/contracts did not change. The explicitly
owner-approved one-run M6 record remains the real hardware validation: a 12-step quick LoRA job on
WSL2 Debian/NVIDIA GTX 1660 Ti (~6 GiB), i5-9300H and 16 GiB RAM completed training, adapter
verification, conversion and frozen comparison. Run `55a81cec-48f7-45dc-bad7-212d97629458`, candidate
`fcafe3ff-139f-4b6b-9f0f-2ba81b3a1409`; [exact hardware/versions/results](milestone-6.md).
That approval is not reused for another GPU run or new targets. Standard preset and other hardware
remain unverified. The candidate remains unpromoted and its evaluation showed no quality gain.

Freshly executed during M8:

```sh
make test-export EXPORT=/absolute/path/to/the/previously-trained-candidate/adviser.tar
```

Actual archive:
`data/training-smoke/1c147c6c-8987-4886-8b66-573437fb589a/artifacts/exports/dcfbb238-e827-4fd2-9b28-d0bb213995c7/60fe2247-3eaf-4800-a6ea-60fc57bb7d41/adviser.tar`.
Archive SHA stays `09574fd7a73a3d395438b9b2c04253e62dc65b86ac0afb92bd48567d73ff4571`.
Report `export-check-ad6a02f4-c2f2-4e62-8930-253e59bd24e6.json` is adjacent to it.
Fresh extraction/Compose inference passed with network `none`, no GPU, builder/database/provider,
read-only package mount and exact runtime image
`sha256:b52a7944803f845a661a0cfe998d35ef21a786a85cbb68aadeff6289d34c3e31`.
Schema, citations, model/IDs and reference context fingerprint matched. The candidate's historical
empty knowledge/lesson context was preserved, so this check does not prove positive retrieval
or useful advice. The earlier [M7 citation-bearing runtime fixture](milestone-7.md) covers positive
citation retrieval separately. The fresh test container/network was removed.

## Remaining release acceptance

README, PLAN, TODO and AGENTS were reviewed together; development status and product boundaries
remain aligned. No user data, models, checkpoints, backups, secrets or generated smoke outputs are
tracked. The repo still uses `0.1.0.dev0` and no MVP tag is added.

Clean startup, separate component/GPU/export records and scripted workflows do **not** complete
one human owner journey from a clean installation. A nontechnical owner still needs to follow
that full journey, review useful/irrelevant questions and failures, approve adequate representative
SFT targets, inspect gains/regressions and explicitly select a version. Then check the exported
adviser and second domain as part of that session. A new GPU run needs its own authorization and
reviewed command/targets. Existing tiny-fixture results cannot stand in for useful domain judgment.

No visual-browser usability review, second-machine/offline image-bundle validation, real external
provider call, cloud run or measured business improvement is claimed. The owner-journey acceptance
and conditional MVP tag remain unchecked in [TODO](../TODO.md) until their evidence exists.
