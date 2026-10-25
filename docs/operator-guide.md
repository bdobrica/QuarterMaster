# Local operator guide

Use the [README](../README.md) for basic startup and [TODO](../TODO.md) for unfinished product behavior. The primary activities are Collect / Teach / Ask / Review. Historical results and failed approaches are in [ADRs](adr/README.md), not additional walkthroughs.

## Current controls

- **Collect (Muster):** included source at `muster/`, running at `/collect/` in the same application. Add links or CSV/XLSX, capture pages, choose fields, consent to extraction, check details, edit/review knowledge and publish. Collection/extraction have explicit start/stop controls; startup never visits pages or calls a provider. The managed browser has a separate profile; access barriers require permitted manual intervention.
- **Teach:** open an adviser-bound collection after checking its details and choose Start teaching. Publication/import and unambiguous knowledge activation happen automatically. Legacy publications remain available under Advanced. Save the answer kind/unit/choices once per adviser, then teach personal judgments. Select only decision-time fields. Unfinished extractions cannot become teaching targets; checked asking prices are still observations. Saving your answer needs no extra approval. Changes append revisions; a newer publication is a separate snapshot. Download reviewed teaching data to freeze the latest answers for that publication and current active knowledge. Choose **Improve my adviser**, reuse the saved answer settings and acknowledge local resource limits to prepare a new generic training job. It freezes reviewed decisions and active knowledge without starting GPU work. It never converts the data into a historical version 1 job.
- **Sources and setup** (under Advanced): upload CSV/XLSX or UTF-8 Markdown, at most 8 MiB each. Inspect previews; explicitly map decision-time inputs separately from outcomes and targets. Joins need explicit keys; formulas and embedded instructions are never executed. Add saved HTML through Collect's existing pipeline; it retains exact bytes and declared provenance without executing scripts or fetching resources.
- **Knowledge:** upload/select Markdown, or propose an article edit. Review its diff and approve it to create immutable source bytes and an active revision. Rejection leaves behavior unchanged; stale proposals cannot overwrite newer knowledge. Historical citations remain accessible. This changes context, not weights.
- **Ask:** `/projects/<project-id>/ask` returns a number with units or an available choice using the local base/selected compatible candidate, active knowledge and related reviewed decisions. It reuses the adviser's saved answer format; missing decisive facts may produce clarification or abstention. Excerpts are verified before inference. Inspect prepared improvements and compare new/previous answers under Advanced before selecting a version. Replays of taught cases measure preference consistency, not unseen accuracy.
- **Review:** accept, correct, add a note or skip a typed answer in the standalone review activity. Accepted/corrected judgments become teaching evidence automatically. Notes/skips add no label. A reusable policy proposal still needs approval; training execution and model selection remain separate explicit actions.
- **Advanced advice history:** the earlier `/test` screen asks using the selected engine, inspect evidence, then record Pending/Pass/Fail and an optional correction. Failure cannot be marked Pass. Ratings currently do not automatically become teaching; eligible corrections still have a separate reviewed lesson path.
- **Improvements:** view saved check questions, reviews and earlier answers. Preview reruns before executing them. Saving a check permanently excludes its situation from teaching; its corrections remain evaluation-only. Ordinary question history needs a separate future path.
- **Advanced:** inspect training, check sets, diagnostics and exports. Historical experiments remain accessible for existing records; they are not current product examples.

Knowledge replay explicitly runs four requests: original/fresh question, each with old/new knowledge. Both arms retain the same current model, mission, prompt and settings; only knowledge changes. Hosted replay requires scoped advice consent. Inspect failed outputs as well as changed answers; a valid citation does not certify usefulness.

## Muster setup and existing data

One QuarterMaster server owns both applications; use a single Uvicorn worker. Muster uses its own SQLite state under `QM_DATA_DIR/muster` (default `data/muster`), included in a normal full-data backup. `QM_MUSTER_DATA_DIR` optionally changes that location; back it up separately if outside `QM_DATA_DIR`. Knowledge imported into an adviser is a separate exact source snapshot. It is not a live synchronized copy of a working article. Publish/import a new version to bring later changes across; review the active source selection when titles conflict. No cross-version target matching is inferred from local collection/job IDs.

For headed browser collection, run the Python application on a desktop host and install Chromium explicitly:

```sh
uv run --locked playwright install chromium
```

On Linux, missing browser system libraries need an operator-managed Playwright dependency installation. WSL requires a working display/WSLg session. The default Docker image has no browser/display: its knowledge, manual review, publication and handoff screens work; live collection requires the host setup. Missing Chromium/display errors remain visible failed jobs. See the [bundle contract](muster/bundle.md) and optional [read-only lookups](muster/connectors.md).

Muster extraction settings use `MUSTER_AI_BASE_URL`, `MUSTER_AI_MODEL`, `MUSTER_AI_API_KEY` and optional `MUSTER_AI_REASONING_EFFORT` in QuarterMaster's environment/`.env`. No provider is configured by default. Each request previews its actual content and needs consent. Adviser/builder consent does not cover collection extraction. API keys are not imported from an old checkout or a bundle.

To preserve an existing installation, stop both apps and copy its **data directory** into a new destination before deleting the old repository:

```sh
uv run --locked python -m quartermaster.migrate_muster /absolute/path/to/old/.muster
```

This targets `QM_MUSTER_DATA_DIR` or `QM_DATA_DIR/muster`, refuses an existing destination, backs up SQLite and verifies copied source/knowledge/publication bytes. It leaves the original untouched. Browser profiles/cookies, `.env`, connector configuration and credentials are excluded. Retain credentials separately and configure the new environment if extraction is wanted. It never starts collection or sends content. Existing publications stay unchanged, including unfinished examples and review provenance. Open Collect to inspect the migrated collections. Copying source code alone does not preserve these ignored local data files.

A host copy under `data/muster` is used by the host Python application. It does not populate an existing Docker named volume automatically; copy it into that deployment's stopped/backed-up data storage before expecting the container to show those collections. Do not switch an existing installation to an empty storage path.

CPU verification includes inherited Muster tests and the handoff. The integrated real-browser fixture test is opt-in: `uv run --locked pytest tests/test_muster_browser.py -m live` after installing Chromium. It makes only local requests and starts no extraction/provider/GPU work.

## Exposure and external providers

Keep ports on localhost: web `127.0.0.1:8000`, standalone `127.0.0.1:8081`. Optional inference/candidate services have no published host ports. There is no authentication, tenancy or TLS. Remote access requires an operator-supplied security boundary; a reverse proxy alone is insufficient. Do not enable request-body/debug logging or put credentials in case text or URLs.

Configure optional hosted advice and builder providers separately in [.env.example](../.env.example). Remote endpoints need HTTPS and no credentials/query/fragment in the URL. Credentials stay in the environment or mounted secret files, outside SQLite and exports. A project must consent to its exact hosted endpoint/model; `QM_ADVISER_LOCAL_ONLY=true` disables hosted advice. There is no silent external fallback.

Builder requests disclose instructions, actual context, schema, endpoint/model and byte count before consent. Interview, lesson and knowledge drafting have distinct payloads; inspect free text for sensitive content. Manual paths need no provider. The default input bound is 49,152 serialized UTF-8 bytes (configurable 4,096–65,536); the default timeout is 20 seconds (1–30 allowed). Output requests are at most 2,048 tokens and responses at most 64 KiB. Displayed token estimates are approximate, not prices or provider-window guarantees. Provider errors require an explicit fresh attempt, not an automatic paid retry.

## Local model

Run `make model-setup` explicitly to build/download/verify the supported base bundle; ordinary startup does not do this. It uses CPU conversion, not training. Default setup prepares the preferred 4B model separately from the historical bundle. Copy the printed fingerprint, revision, directory and memory limit into `.env`:

```dotenv
QM_LOCAL_BASE_URL=http://inference:8080/v1
QM_LOCAL_MODEL_SHA256=<printed SHA-256>
QM_LOCAL_MODEL_REVISION=851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a
QM_LOCAL_MODEL_DIR=./data/local-model-4b
QM_LOCAL_MEMORY_LIMIT=6g
QM_LOCAL_TIMEOUT_SECONDS=180
```

Start the advice profile with the read-only base-bundle override:

```sh
docker compose -f compose.yaml -f compose.advice.yaml --profile advice up -d --build --wait
```

The override lets the web service read the selected bundle for export. Host Python deployments use the same verified directory and a separately configured loopback inference endpoint, for example `http://127.0.0.1:8081/v1`. Inside Compose use `http://inference:8080/v1`. Never replace an existing artifact to suppress a hash error.

The preferred base is `Qwen/Qwen3.5-4B` revision `851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a`; llama.cpp remains pinned in [trainer/Dockerfile](../trainer/Dockerfile). The verified Q8_0 file is 4,482,402,848 bytes. Serving was tested with four CPU threads and a 6 GiB limit; the twelve capability controls took 24–44 seconds each. Real-browser requests took up to 65 seconds. These are local development observations, not latency guarantees. Setup/merge/conversion allows 24 GiB memory and needs at least 32 GB free artifact disk plus Docker image space.

Installation affects new advisers. To move an existing adviser, open **Ask → Advanced → Use the installed local model**. It appends a version and preserves knowledge, reviewed teaching and historical models. It clears the previous adapter selection: adapters cannot transfer across these pinned bases. Requests fail clearly if the configured service and adviser base differ. Existing model/adapter records are never rewritten automatically.

The earlier `Qwen/Qwen3.5-0.8B` pin `2fc06364715b967f1860aea9cf38778875588b17` remains readable/runnable with its original files and recipes. Explicit setup is `uv run --locked python -m quartermaster.setup_local --model-size 0.8b`; use its printed settings (original revision, `data/local-model`, 4 GiB). The default setting remains that original revision for existing installations until the operator changes it. This compatibility path did not pass all current generation controls.

Historical written advice uses bounded thinking; typed predictions preserve historical `context/v4` and `context/v5`. Configured base advisers and new jobs use `context/v6`: compact facts, the complete visible response contract and explanation before target, shared with training/comparison/export. Keep the bounded non-thinking 1,024-token profile. Rebuild the prediction-trainer, candidate-runtime and standalone-runtime images before consuming the new model/recipe/packages. Selected historical adapters keep their captured prompts. See [ADR 0009](adr/0009-visible-prediction-contract.md), [ADR 0010](adr/0010-verified-local-model.md) and [generation settings](../quartermaster/generation.py).

## Training

Training is opt-in. Preparing **Improve my adviser** puts saved collection decisions into `training-job/v2` without an applied lesson or second target approval. One publication per job and at most 100 targets are supported; all targets must fit the selected unit or choices. Reasons must fit the shared short explanation contract (600 characters); longer saved reasons remain intact and need explicit editing before training. The historical version 1 workflow still requires an applied lesson and separate reviewed target. AI-draft provenance survives review. Reserved check cases and later outcomes never enter training. Exact/lexical duplicate checks do not catch every semantic overlap; inspect entity/time separation yourself.

The worker and web must share the same SQLite/artifact directory. The override below switches from a named volume to a host directory. **Existing installations must first stop services, back up and copy the complete volume into an empty host directory, then verify hashes and ownership.** Keep the original volume. Do not apply the override to an empty path and mistake it for an upgrade.

For a new host-worker installation:

```sh
mkdir -p data/training-app
uv sync --locked
docker compose -f compose.yaml -f compose.training.yaml --profile advice --profile training up --build -d --wait
```

The shared directory defaults to `./data/training-app`, UID/GID 1000. Configure `QM_TRAINING_DATA_DIR`, `QM_LOCAL_UID`, `QM_LOCAL_GID` as needed. Compose must support the override tags (`!override`, `!reset`); the historically tested version was 2.40.3.

Build and inspect the local images:

```sh
docker build -f trainer/Dockerfile --target prediction-trainer -t quartermaster-trainer:prediction .
docker build -f trainer/Dockerfile --target runtime -t quartermaster-runtime:m6 .
docker image inspect quartermaster-trainer:prediction --format '{{.Id}}'
docker image inspect quartermaster-runtime:m6 --format '{{.Id}}'
```

The `prediction-trainer` target advertises `training-job/v2`, `lora-recipe/v2` and `context/v6`; preflight rejects stale images lacking required capabilities. For a historical version 1 job, build the `trainer` target instead; the worker rejects an incompatible image label before training. It always trains from the pinned base and compares generic candidates against the captured current selection. Up to five taught cases are replayed with identical context/settings. A rejected/unselected candidate leaves the current model and knowledge unchanged.

After reviewing a queued job, hardware and the exact command, an operator can start the worker with those complete image IDs:

```sh
uv run --locked python -m quartermaster.training_worker \
  --run-gpu \
  --data-dir ./data/training-app \
  --base ./data/spike/base-851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a \
  --base-gguf ./data/local-model-4b \
  --trainer-image sha256:REPLACE_WITH_TRAINER_IMAGE_ID \
  --runtime-image sha256:REPLACE_WITH_RUNTIME_IMAGE_ID
```

These are operator templates: substitute verified paths and image IDs for the exact frozen base. Queueing does not run the worker. Do not start it during ordinary documentation or CPU verification.

Standard passthrough requires a working NVIDIA Container Toolkit. The explicitly tested WSL alternative adds `--gpu-mode wsl`, exposing `/dev/dxg` and read-only `/usr/lib/wsl` driver files without a privileged container or daemon change. The 4B NF4 run completed on an NVIDIA RTX 2070 SUPER with 8 GB video memory (compute 7.5); other GPU families remain unverified. See the [compatibility lesson](adr/0002-local-model-and-portable-runtime.md).

For 4B, preflight requires compute capability ≥7, at least 7.5 billion VRAM bytes and 32 GB free artifact disk plus images. The fixed `lora-recipe/v2` uses bitsandbytes 0.49.2 NF4 base weights, float16 compute and non-reentrant gradient checkpointing. LoRA targets, completion-only supervision and final JSON format remain aligned with inference; merge reloads the exact original base in float32 before Q8_0 conversion. The original 0.8B `lora-recipe/v1` remains float32 with its original 5.5-billion-byte VRAM and 12 GB disk checks.

Training has four CPUs and a 10 GiB memory/swap bound; 4B conversion allows 24 GiB. Quick is 12 steps/20 minutes; standard is 48 steps/60 minutes. Only quick has been live-tested. These are hard bounds, not runtime or memory guarantees. Oversized targets fail instead of truncating. Separate preflight/conversion/comparison stages are bounded; cancellation/failure is durable with no cloud fallback or automatic retry. `cleanup_required` blocks further jobs until the recorded orphan is recovered.

The real 4B run completed all twelve steps, nonzero-weight verification, safe merge, conversion and four taught-case replays. Its candidate abstained on all four without learning useful targets; it remains unselected. The controlled base and browser successes use approved policies/retrieved earlier decisions. They are separate evidence from weight personalization. A completed run or decreasing loss does not establish improvement.

The trainer receives only its frozen input, verified base and output mounts, not the database, credentials, live source storage or held-out labels. A generic job includes its reviewed teaching/knowledge snapshot and excerpt lineage as data. Never bypass the global job lock or edit frozen manifests to recover a run.

## Standalone export

Build the current standard runtime and inspect its exact local image ID:

```sh
docker build -f trainer/Dockerfile --target standalone-runtime -t quartermaster-standalone-runtime:local .
docker image inspect quartermaster-standalone-runtime:local --format '{{.Id}}'
```

Set `QM_EXPORT_RUNTIME_IMAGE` to that full ID in `.env`, then recreate the appropriate web Compose service with the same storage/profiles. A base export binds to a successful saved answer; a historical candidate export binds to its frozen evaluation. A generic `export/v4` (original base) or `export/v5` (4B) binds to its reviewed dataset and taught-case comparison, carries its fixed answer format and responds with `prediction` at `/v1/advise`. All preserve their original context and model bytes, not later active edits. Old export versions keep their original semantics and size limits. Version 5 requires the new labelled image and 6 GiB serving limit. The 4B path currently exports a completed generic candidate; the historical written-advice base export remains limited to the original base.

Packages include the model/license, selected original knowledge, approved lessons and one disclosed reference situation. They exclude the builder database, raw reviews, training rows, rubric labels and provider credentials. Included free text may still be sensitive or subject to redistribution restrictions. An export is not a project backup. Reserve space for model copies and the runtime image; an archive alone does not install that image.

Run the independent check before claiming runtime success:

```sh
make test-export EXPORT=/absolute/path/adviser.tar
```

The checker extracts a fresh package and serves it in isolated CPU Compose with no external network, builder, database, GPU or frontier key. It validates reference-context identity, schema and citations. Keep its sanitized report. Packaging alone, mocked tests and historical checks do not prove that a new package starts or gives useful advice. The real 4B candidate passed this fresh-container check with no builder database, external network or provider. Its valid abstention verifies runtime compatibility, not useful personalization. A second-machine check and bundled offline images are not provided.

## Backup and restore

An adviser export is **not a project backup**: it excludes project history, raw corrections,
training records and other sources. Back up the entire data directory, not SQLite alone. It contains
original uploads, database/sidecars, immutable datasets, adapters, models and exports. It may be large
and sensitive. Store backups privately/offline or encrypted, with retention appropriate to your data.
Back up `.env`/secret files separately in a protected location; they are outside the data volume.

For the default named-volume installation, use the following from the checkout. Stop any host
training worker and optional candidate service first and wait for work to stop. The backup command
uses the already built web image and writes a tar stream to a new host file; it does not need a
second utility image or the Docker socket inside the web app.

```sh
docker compose stop
umask 077
docker compose run --rm --no-deps -T web python -c 'import sys, tarfile; t = tarfile.open(fileobj=sys.stdout.buffer, mode="w|"); t.add("/data", arcname="data"); t.close()' > quartermaster-backup.tar
# Check this command succeeded and the backup is nonempty before restarting.
docker compose up -d --wait
```

Choose a new backup filename each time; shell redirection overwrites an existing file. Keep all
services stopped until copying finishes. Do not copy a live database plus artifacts independently.
`docker compose down` keeps the volume; **`docker compose down -v` deletes it**.

Restore a backup you created and trust into a **new, empty** named volume/project first, while
keeping the existing installation stopped and preserved. Set a unique project name (shown below)
and use the same code/image version. The command refuses nonempty storage, links and entries outside
`data/`, then checks SQLite integrity. It restores data only, never executes archived content.

```sh
docker compose --project-name quartermaster-restore run --rm --no-deps -T web python -c 'import pathlib, sqlite3, sys, tarfile; p = pathlib.Path("/data"); assert not any(p.iterdir()), "Restore needs empty storage"; t = tarfile.open(fileobj=sys.stdin.buffer, mode="r|*")
for m in t:
    assert (m.name == "data" or m.name.startswith("data/")) and ".." not in pathlib.PurePosixPath(m.name).parts and (m.isfile() or m.isdir()), "Invalid backup entry"
    t.extract(m, path="/", filter="data")
c = sqlite3.connect("/data/quartermaster.sqlite3"); assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"; c.close()' < quartermaster-backup.tar
```

After successful restore, start `docker compose --project-name quartermaster-restore up -d --wait`
with the original web stopped so port 8000 is free. Open it, inspect project/source history and
verify required artifact hashes and model operation before using it. Do not merge two directories
or overwrite a working volume. A schema upgrade may be one-way: retain the pre-upgrade backup.
A project-name change may affect relative bind mounts; do not use this default-volume recipe to
silently switch the [optional host-worker installation](#training). That deployment needs a
quiesced copy of its configured shared directory, including ownership and all artifacts.

## Failure recovery

Report sanitized codes and record IDs, not private cases or credentials. `BUILDER_*`/`ADVISER_*` errors require checking provider configuration/consent; use manual or local paths where available. `LOCAL_*` errors require checking model fingerprints, service health and CPU/RAM. `LOCAL_TOKEN_LIMIT` means a finite budget was exhausted; retry explicitly or create a new check profile without editing historical records.

For `TRAINING_*`/`EXAMPLE_*`, inspect reviewed targets, check exclusions, hardware bounds and saved failure state. For `EXPORT_*`, preserve the archive/report and inspect exact image/model/context bytes and isolated cleanup. For `STORAGE_*`, check permissions, disk and complete backups; never delete SQLite to suppress an error. See [third-party notices](third-party-licenses.md) before redistributing models or knowledge.


## MVP stabilization rehearsal

Create an adviser, configure its answer once, open Collect from its navigation and add saved HTML or links. Saved HTML is retained byte-for-byte, parsed only as text, and has no screenshot or fetched resources. Check extracted details before choosing Start teaching. All unfinished examples and knowledge reviews must be resolved, or explicitly excluded through Advanced publication controls. Article-title conflicts require choosing active knowledge; no imported version silently replaces an earlier policy.

Review accepts/corrects typed answers or records a note/skip. Explicit judgments appear automatically in Teach and the next bounded improvement snapshot. Notes/skips add no target and retain earlier explicit judgments. A newer correction replaces that answer's target in future snapshots, preserving older jobs and history. Ask can use up to three relevant eligible judgments, labelled as owner preferences separately from source excerpts. Missing-source failures remain actionable errors. Neither review capture nor the manual policy proposal path requires an external provider.

The opt-in full Chromium rehearsal is `uv run --locked python -m tests.smoke_stabilization --run-live --data-dir /absolute/new/directory --use-adviser-for-collection`. It uses synthetic development pages, explicitly reuses the configured adviser provider for collection, and still goes through extraction consent screens. Omit that flag for separately configured collection credentials; `--use-builder-for-collection` is available when the builder endpoint/model/key are all configured. The local model must already be serving at the loopback address passed through `--local-url` (default port 18080). This script queues an improvement but does not execute or promote it. It writes real browser screenshots and a report inside the isolated data directory. Do not run it on an existing directory.

The original 0.8B rehearsal's base and trained candidate returned an absurd numerical price. The newer 4B base passes the controlled generation checks, but its twelve-step candidate abstained on all four taught-case replays. Useful weight personalization remains unverified. Preserve both historical runs and keep the candidate unselected.

### Investigating the failed preference replay

An offline, read-only GPU probe on 2026-10-26 loaded the exact frozen 4B job and its saved adapter. The installed trainer's actual tokenization and loss collator masked every prompt and supervised the complete owner response, including the price and end token. All four sequences fit the 2,048-token bound (566–580 tokens); none was truncated. No optimizer ran and no replacement candidate was created.

With each expected response supplied as the preceding token sequence, the adapter reduced completion loss by 0.8–1.3% and price-token loss by 1.1–2.8% relative to the same NF4 base. These are teacher-forced diagnostics, not successful free predictions or unseen-case quality. The four original free replays still abstained. Twelve steps give three exposures per example; the adapter has 458,752 parameters across the eight full-attention layers' query/value projections. The remaining 24 linear-attention layers are unadapted. Limited optimization is a plausible next hypothesis, not an isolated causal result; the probe does not establish whether conversion also affects quality.

Evidence remains private under `data/rehearsal-20261026/lora-investigation/`: the finite probe script, `teacher-forced-probe.json` and `investigation-summary.json`. Original job `9d0ab146-03be-4b95-9318-6610712130c6`, its bytes and candidate `bec557db-d716-4f85-b6a7-68a1fc4d69cd` are unchanged. The summary corrects a diagnostic metadata label: the original report's `adapter_tensor_pairs` counts loaded adapters, not tensor pairs.

Before another bounded run, capture actual owner prices and reasons. Keep identical case/policy context in the current-model and candidate arms, show exact price errors against those owner targets, and keep genuinely new cases separate. Do not insert a taught target into its own prompt. Check personal policy tradeoffs and missing-information behavior as well as JSON validity. Policy retrieval and related decisions can improve an answer immediately; report that separately from weight changes. The generic owner workflow currently prepares the fixed quick recipe. Any stronger recipe experiment must remain bounded, use the public job boundary and preserve historical recipes. Require explicit selection after reviewing the result.

### Owner material and a simulated trial

Use a verified copy of the owner's collection for rehearsal; preserve original captures, checked extraction, publications and historical jobs. The [apartment policies](../examples/apartments/owner-policies.md) include the owner's explicit directional biases. These need no external benchmark. Three reviewed personal EUR prices and reasons are still needed to establish numerical teaching targets; listing prices and AI-generated prices cannot substitute for them. Retain a different listing for a new-case question. Missing weights or a seller's unknown credibility must not silently become fabricated discounts.

The owner requested an agent-simulated workflow check for this pass and will inspect the UI later. Record it as a simulation, not an uncoached human trial. Exercise Collect → Teach → Ask → Review, confirm the correction is reusable automatically, and inspect a bounded improvement request. If personal targets are still pending, record that stage as pending rather than inventing them. Run no external extraction on the owner's content without the application's consent preview.

For a later human trial, give a separate nontechnical participant only the goal and material: “Make an adviser that reflects your apartment price judgments. Teach three examples, ask about a different apartment, correct its answer, and request an improvement.” Do not supply click instructions. Record completion, requests for help, confusing messages and the first blocking action. A facilitator intervention makes that step coached; it is not an unassisted pass. Keep participant details and raw material out of Git. The owner judges whether prices and explanations fit their preferences and explicitly selects or retains a model after comparison.

For a bounded local generation check, run `uv run --locked python -m tests.smoke_prediction_reliability --run-live --report /absolute/new-report.json` with the local service already configured and accessible. The report path must be new. This uses twelve synthetic arithmetic/choice/missing-data controls, including a non-apartment time allowance. It sends no provider requests, opens no builder database, creates no training labels and never selects a model. It saves final answers, sanitized failures and timings; a wrong value or an inappropriate clarification fails the check. `--thinking` compares the existing bounded-thinking parameters diagnostically; it does not change production or training defaults. Passing a small development check would not establish general accuracy or LoRA improvement.
