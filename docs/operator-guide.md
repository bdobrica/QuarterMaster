# Local operator guide

QuarterMaster is a trusted single-user application. Start with the [README](../README.md).
The [synthetic walkthrough](../quartermaster/ui/static/examples/) contains no real business data;
its scenarios are also available at `/examples` in the running application. Help is at `/help`.

Test also links to the opt-in [inference reliability development comparison](inference-reliability.md).
It compares current and compact responses with reviewed field definitions using unchanged base
weights. These experiments and separate quality reviews do not alter active advice or create SFT
examples. Back up before upgrading: database schema 7 adds append-only experiment/review tables;
older application versions require their pre-upgrade database backup.

## Installation and exposure

The ordinary application requires Docker Engine with Compose v2, initial internet access for
image/package downloads, and persistent disk. Use a current Compose supporting `!override` and
`!reset` for optional training/export configurations (the tested version is 2.40.3).
The base web service starts without a GPU, model or provider credential. It binds
`127.0.0.1:8000`; optional inference/candidate services publish no host ports. Standalone advisers
bind `127.0.0.1:8081`. Do not change these to `0.0.0.0` for ordinary use.

There is no authentication, tenancy or TLS. A reverse proxy alone does not add an authorization
boundary. Before remote access, the operator must provide authentication, HTTPS, upload/request
limits, access control and a correct trusted origin. The application rejects cross-origin form
submissions and does not trust forwarded headers by default; proxy arrangements need their own
review. Do not enable HTTP access/body/debug logs or place case text/API keys in URLs.

## Sources, cases and review

Upload `.csv`, `.xlsx` or UTF-8 `.md`, at most 8 MiB each. CSV accepts explicit separators and
UTF-8/Windows-1252. XLSX is read-only; formulas are displayed, never evaluated, and are not accepted
as decision inputs. Inspect sheets, types, missing values and source positions. Labels describe
intended use; labeling a file “examples” does not approve any supervision.

Confirm what one case represents, its decision time, input fields and separate later outcomes.
Possible target-advice columns remain unreviewed. Combining tables requires explicit join keys;
ambiguous joins fail. See [supported mappings and parser limits](milestone-2.md).

Select Markdown on Teach and save the knowledge selection. Uploading does not automatically make
a source retrievable. Replacement means uploading new original bytes and saving a new selection;
previous source bytes and knowledge revisions remain available. Citations resolve to the actual
selected source excerpts; existence and verbatim-quote checks do not prove factual entailment.

Give feedback on Test. Raw corrections are preserved; a pending manual or AI-drafted lesson has
no effect until reviewed and approved. Applied lessons change context, not weights. For LoRA,
create a separate training example, inspect its complete prompt/target and approve it explicitly.
AI_DRAFT provenance survives approval. Exact/lexical duplicates and evaluation holdouts are blocked;
semantic similarity and representative coverage still need human review. Freeze unseen evaluation
cases before teaching/training and keep entity/time overlaps out of the split yourself.

## External provider boundaries

The manual interview and lesson paths need no provider. Configure one OpenAI-compatible provider
using `.env` or a mounted secret file; never store keys in missions or uploaded documents. Remote
provider URLs require HTTPS and cannot include credentials, query strings or fragments.

Before any business-content send, inspect the exact endpoint/model, instructions, context and
response schema. Interview summaries show original source sizes; only bounded summaries and
explicitly selected excerpts are attached. Corrections/advice can themselves quote sensitive text.
A separate consent action authorizes that exact preview. No automatic paid retry occurs.

`QM_BUILDER_TIMEOUT_SECONDS` defaults to 20 (allowed 1–30 seconds).
`QM_BUILDER_MAX_INPUT_BYTES` defaults to 49152 (allowed 4096–65536), including the serialized request,
instructions and schema. Set lower bounds for your chosen provider. Both preview and transport
reject oversized inputs. The displayed token count is serialized UTF-8 bytes divided by four,
rounded up: approximate, not a tokenizer count, price or provider context-window guarantee.
Maximum requested output is 2048 tokens; responses are bounded to 64 KiB. Failures preserve saved
answers and have sanitized codes; shorten, inspect and explicitly retry. Provider retention and
charges are outside QuarterMaster's control.

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
silently switch the [optional host-worker installation](milestone-6.md). That deployment needs a
quiesced copy of its configured shared directory, including ownership and all artifacts.

## Models and local GPU

The supported model is Qwen/Qwen3.5-0.8B revision
`2fc06364715b967f1860aea9cf38778875588b17`. `make model-setup` explicitly downloads/verifies the base
and builds the optional local CPU runtime. Configure the printed hash and local URL, then start
the advice profile as described in [M4](milestone-4.md). The Q8_0 GGUF is **811843232 bytes** (about
812 MB); each candidate/export adds another model copy. Serving is limited to 4 GiB RAM/four CPU
threads in the tested setup; responses may take minutes. Reserve image/download/conversion space
in addition to model size. CPU setup/conversion can require substantially more RAM than serving.

Training is opt-in and separate from web startup. The tested host is WSL2 Debian with an Intel
i5-9300H, 16 GiB RAM and NVIDIA GTX 1660 Ti with approximately 6 GiB VRAM. Standard NVIDIA Docker
passthrough requires a compatible driver and NVIDIA Container Toolkit. The explicit WSL alternative
passes `/dev/dxg` and installed `/usr/lib/wsl` driver files read-only. Follow the exact
[host GPU setup](milestone-1.md#host-gpu-setup) and [worker setup](milestone-6.md); do not install host
packages or restart Docker as a side effect of opening Train.

Preflight requires compute capability at least 7, 5.5 billion VRAM bytes, 12 GB free artifact disk
plus image space and verified base bytes. The trainer has a 10 GiB RAM/swap bound and finite stage
limits. Quick is 12 steps/20 minutes; standard is 48 steps/60 minutes; those are hard bounds, not
promised durations. Only quick was live tested here. Other NVIDIA GPUs/configurations, AMD,
Apple GPU, CPU-only training, remote/cloud GPUs and other model families are unverified or unsupported.
There is no implicit precision change, cloud fallback or job retry. OOM/cancellation/interruption
fails durably; inspect the code and create an explicit new run when appropriate.

## Standalone export and distribution

Build the standard runtime and set its exact image ID using [M7 setup](milestone-7.md). Package a
completed evaluated candidate. The archived mission/knowledge/lessons match that candidate's frozen
evaluation, even after later project edits. Missing/inconsistent historical bytes fail packaging.
Downloaded archives contain selected original Markdown, approved lesson text and one decision-time
reference situation. Inspect sensitive content and your right to distribute it before sharing.
No automatic secret detection can make arbitrary uploaded text safe to publish.

Run `make test-export EXPORT=/absolute/adviser.tar`. It extracts to a fresh directory, checks the
fixed Compose recipe, serves the real model with network disabled, no builder/database/GPU, and
checks schema, citation IDs and reference-context fingerprint. Retain the sanitized report with
the archive. Packaging/download alone does not prove runtime startup or useful advice. The package
needs its exact preobtained image; an offline image bundle and a second-machine check are not provided.

LoRA training, merge and quantization retain upstream model provenance and license obligations.
The repository code and selected Qwen revision use Apache-2.0; model, runtime and uploaded content
keep their separate notices/terms. Exports copy the model license and project license; runtime
images retain llama.cpp/Python/Debian/dependency notices. CUDA/host-driver bytes are not part of
the CPU export. Do not treat model/lesson approval as permission to redistribute others' documents.
See [third-party notices](third-party-licenses.md) and review applicable terms before distribution.

## Troubleshooting

| Code or symptom | Next step |
| --- | --- |
| Web unhealthy / `STORAGE_INIT` / `STORAGE_UNAVAILABLE` | Check configured directory, ownership, free disk and backup integrity. Never delete SQLite to suppress an error. |
| `BUILDER_CONFIG` / `BUILDER_AUTH` / `BUILDER_HTTP` | Check environment/secret reference, endpoint/model and JSON-schema support; use the manual path. |
| `BUILDER_INPUT` / `BUILDER_TIMEOUT` / `BUILDER_RATE_LIMIT` | Shorten context, review provider bounds, wait when rate-limited and explicitly prepare/retry. |
| `LOCAL_MODEL` / `LOCAL_CONNECTION` / `LOCAL_TIMEOUT` | Check pinned model hash/license, advice profile health and CPU/RAM; inspect failed saved tests. |
| `LOCAL_TOKEN_LIMIT` | The answer exhausted its finite output budget. Request a concise answer or shorten the situation and retry explicitly. A frozen evaluation retains its captured budget; create a new suite to assess a changed profile. |
| `TRAINING_*` / `EXAMPLE_*` | Inspect reviewed targets, frozen suite, preflight/diagnostic code and hardware bounds. Queueing does not start a worker. |
| `cleanup_required` | Stop/recover the recorded orphan training container before starting another job; never bypass the global job lock. |
| `EXPORT_IMAGE` / `EXPORT_CONTEXT` / `EXPORT_ARTIFACT` | Verify exact local image ID and historical model/context bytes. Do not edit manifests; evaluate/train a new candidate for changed context. |
| `EXPORT_*` smoke failure | Retain the original archive and failure report; check image/model compatibility and isolated Compose cleanup. No automatic retry/training. |

Report diagnostic codes and record IDs rather than raw cases, keys or whole data directories.
Open `/help` in the running UI for owner actions. Verification
and remaining release checks are in [M8](milestone-8.md).
