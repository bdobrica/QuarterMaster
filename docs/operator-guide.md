# Local operator guide

Use the [README](../README.md) for basic startup and [TODO](../TODO.md) for unfinished product behavior. This guide describes the current implementation, whose navigation still differs from the intended Collect / Teach / Ask / Review loop. Historical results and failed approaches are in [ADRs](adr/README.md), not additional walkthroughs.

## Current controls

- **Collect (Muster):** included source at `muster/`, running at `/collect/` in the same application. Add links or CSV/XLSX, capture pages, choose fields, consent to extraction, check details, edit/review knowledge and publish. Collection/extraction have explicit start/stop controls; startup never visits pages or calls a provider. The managed browser has a separate profile; access barriers require permitted manual intervention.
- **Teach:** open an adviser-bound collection after checking its details and choose Start teaching. Publication/import and unambiguous knowledge activation happen automatically. Legacy publications remain available under Advanced. Save the answer kind/unit/choices once per adviser, then teach personal judgments. Select only decision-time fields. Unfinished extractions cannot become teaching targets; checked asking prices are still observations. Saving your answer needs no extra approval. Changes append revisions; a newer publication is a separate snapshot. Download reviewed teaching data to freeze the latest answers for that publication and current active knowledge. Choose **Improve my adviser**, reuse the saved answer settings and acknowledge local resource limits to prepare a new generic training job. It freezes reviewed decisions and active knowledge without starting GPU work. It never converts the data into a historical version 1 job.
- **Sources and setup** (under Advanced): upload CSV/XLSX or UTF-8 Markdown, at most 8 MiB each. Inspect previews; explicitly map decision-time inputs separately from outcomes and targets. Joins need explicit keys; formulas and embedded instructions are never executed. Direct saved-HTML uploads are not implemented; Muster safely captures source pages.
- **Knowledge:** upload/select Markdown, or propose an article edit. Review its diff and approve it to create immutable source bytes and an active revision. Rejection leaves behavior unchanged; stale proposals cannot overwrite newer knowledge. Historical citations remain accessible. This changes context, not weights.
- **Ask:** `/projects/<project-id>/ask` returns a number with units or an available choice using the local base/selected compatible candidate and active knowledge. Choose the requested answer format; missing decisive facts may produce clarification or abstention. Excerpts are verified before inference. Inspect prepared improvements and compare new/previous answers under **Adviser improvements and versions** before selecting a version. Replays of taught cases measure preference consistency, not unseen accuracy. Typed reviews and automatic routing remain unfinished.
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

Run `make model-setup` explicitly to build/download/verify the supported base bundle; ordinary startup does not do this. It uses CPU conversion, not training. Copy the printed model fingerprint into `.env`:

```dotenv
QM_LOCAL_BASE_URL=http://inference:8080/v1
QM_LOCAL_MODEL_SHA256=<printed SHA-256>
QM_LOCAL_TIMEOUT_SECONDS=180
```

Start the advice profile with the read-only base-bundle override:

```sh
docker compose -f compose.yaml -f compose.advice.yaml --profile advice up -d --build --wait
```

The override lets the web service read the base bundle for export. Host Python deployments set `QM_LOCAL_MODEL_DIR` to their verified `data/local-model` directory and need a separately configured loopback inference endpoint. No existing artifact should be replaced to suppress a hash error.

The supported base is `Qwen/Qwen3.5-0.8B` revision `2fc06364715b967f1860aea9cf38778875588b17`; llama.cpp is pinned in [trainer/Dockerfile](../trainer/Dockerfile). The Q8_0 model is about 812 MB. In the tested setup serving uses four CPU threads and a 4 GiB limit; responses may take minutes. Setup/conversion needs additional memory and disk. Historical written advice uses bounded thinking; the typed prediction path preserves historical `context/v4`; newly configured advisers use `context/v5` and the bounded non-thinking 1,024-token profile with training, comparison and export. Historical training, checks and exports retain their captured profiles. See [generation settings](../quartermaster/generation.py).

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

The `prediction-trainer` target advertises only `training-job/v2`. For a historical version 1 job, build the `trainer` target instead; the worker rejects an incompatible image label before training. It always trains from the pinned base and compares generic candidates against the captured current selection. Up to five taught cases are replayed with identical context/settings. A rejected/unselected candidate leaves the current model and knowledge unchanged.

After reviewing a queued job, hardware and the exact command, an operator can start the worker with those complete image IDs:

```sh
uv run --locked python -m quartermaster.training_worker \
  --run-gpu \
  --data-dir ./data/training-app \
  --base ./data/spike/base-2fc06364715b967f1860aea9cf38778875588b17 \
  --base-gguf ./data/local-model \
  --trainer-image sha256:REPLACE_WITH_TRAINER_IMAGE_ID \
  --runtime-image sha256:REPLACE_WITH_RUNTIME_IMAGE_ID
```

These are operator instructions, not commands executed while implementing the generic connection. Queueing does not run the worker. Do not start it during ordinary documentation or CPU verification.

Standard passthrough requires a working NVIDIA Container Toolkit. The explicitly tested WSL alternative adds `--gpu-mode wsl`, exposing `/dev/dxg` and read-only `/usr/lib/wsl` driver files. It needs no privileged container, host install or daemon change. The tested host had a GTX 1660 Ti with 6 GiB VRAM; other GPU families/configurations remain unverified. See the [compatibility lesson](adr/0002-local-model-and-portable-runtime.md) before changing libraries, precision or kernels.

Preflight requires compute capability ≥7, 5.5 billion VRAM bytes and 12 GB free artifact disk plus image space. Training has four CPUs and a 10 GiB RAM/swap bound. Quick is 12 steps/20 minutes; standard is 48 steps/60 minutes. Only the historical quick workflow was live-tested; a new generic four-example 12-step run completed on an RTX 2070 with 8 GiB using WSL passthrough, but its numerical outputs were unusable and the candidate was not promoted. These are hard bounds, not promised runtimes or memory guarantees. Oversized targets fail instead of truncating. There are separate bounded preflight/conversion/comparison stages, durable cancellation/failure and no cloud fallback or automatic retry. `cleanup_required` blocks further jobs until the recorded orphan is stopped/recovered.

The trainer receives only its frozen input, verified base and output mounts, not the database, credentials, live source storage or held-out labels. A generic job includes its reviewed teaching/knowledge snapshot and excerpt lineage as data. Never bypass the global job lock or edit frozen manifests to recover a run.

## Standalone export

Build the current standard runtime and inspect its exact local image ID:

```sh
docker build -f trainer/Dockerfile --target standalone-runtime -t quartermaster-standalone-runtime:local .
docker image inspect quartermaster-standalone-runtime:local --format '{{.Id}}'
```

Set `QM_EXPORT_RUNTIME_IMAGE` to that full ID in `.env`, then recreate the appropriate web Compose service with the same storage/profiles. A base export binds to a successful saved answer; a historical candidate export binds to its frozen evaluation. A generic `export/v4` binds to its reviewed dataset and taught-case comparison, carries its fixed answer format and responds with `prediction` at `/v1/advise`. All preserve their original context and model bytes, not later active edits. Old export versions keep their original semantics.

Packages include the model/license, selected original knowledge, approved lessons and one disclosed reference situation. They exclude the builder database, raw reviews, training rows, rubric labels and provider credentials. Included free text may still be sensitive or subject to redistribution restrictions. An export is not a project backup. Reserve space for model copies and the runtime image; an archive alone does not install that image.

Run the independent check before claiming runtime success:

```sh
make test-export EXPORT=/absolute/path/adviser.tar
```

The checker extracts a fresh package and serves it in isolated CPU Compose with no external network, builder, database, GPU or frontier key. It validates reference-context identity, schema and citations. Keep its sanitized report. Packaging alone, mocked tests and historical checks do not prove that a new package starts or gives useful advice. A second-machine check and bundled offline images are not provided.

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

The stabilization rehearsal's base and trained candidate returned an absurd numerical price. The software workflow and actual GPU execution were verified; useful personalization was not. Treat base previews and candidate replays accordingly. A useful unseen-case demonstration and uncoached owner trial remain open in TODO.
