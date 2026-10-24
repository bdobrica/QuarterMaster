# Milestone 7: standalone adviser packages

The project Export screen packages a completed, smoke-checked candidate from Train.
It freezes the **evaluated** adviser, knowledge selection and approved lessons, even
if the owner later changes the active project. Downloading never starts training,
conversion, a cloud job or a builder-provider request. The fixed M6 worker already
uses the verified M1 safe LoRA merge → GGUF Q8_0 conversion; export rechecks that
lineage and copies the exact portable bytes instead of converting them again.

After explicit owner approval, a real M6 GPU run completed and its newly trained
candidate was exported through the application API and served from a fresh offline
Compose extraction. Model and frozen context fingerprints matched, closing the
selected-candidate acceptance checks. The earlier M1-based runtime fixture remains
separately labeled with **mocked M6 lineage**; it is not evidence for real training.
Neither check establishes adviser quality; the tiny M6 comparison showed no gain.

## Operator setup

Use the same Docker Engine host as the builder. Build the single standard image:

```sh
docker build -f trainer/Dockerfile --target standalone-runtime -t quartermaster-standalone-runtime:m7 .
docker image inspect quartermaster-standalone-runtime:m7 --format '{{.Id}}'
```

Set `QM_EXPORT_RUNTIME_IMAGE=sha256:...` in the ignored `.env` to the exact complete
image ID printed by inspect. Recreate the web service to load the setting:

```sh
docker compose up -d --build --wait web
```

The runtime retains the digest-pinned Python 3.13 slim **Trixie** base and the same
pinned llama.cpp revision as M1/M6. It reuses the existing locked Python packages;
there are no new dependencies or Node build. Only the public contracts, shared
context/inference modules, standalone server and browser template are copied into
this image. Builder routes, database module, training orchestration and external
builder-provider client are absent. The optional image does not enlarge or add ML
packages to the normal web service.

After a real reviewed M6 run finishes, open the project's **Export a standalone
adviser** screen, inspect/select its candidate and acknowledge the exact contents.
The candidate need not replace active Test weights. Packaging can take time while
hashing/copying the model; reserve twice the model size plus 64 MB metadata and
additional runtime-image space. Packaging errors leave a partial UUID directory
without a ready archive marker; it cannot be downloaded or presented as complete.
No schema migration is needed; SQLite stays at v6. Export artifacts use controlled
UUID paths under `artifacts/exports/<project UUID>/<export UUID>/`.

The web app deliberately has no Docker socket. It can check metadata and bytes,
but cannot establish that the configured image is installed or a model can start.
The separate host smoke command verifies both before runtime success is reported.

## Package and immutable contract

```text
adviser.json                 # evaluated mission/model pointer and approved lesson text
knowledge/chunks.json        # selected source identities and exact excerpts
knowledge/sources/<UUID>.md  # unchanged selected originals, never user filenames as paths
model/model.gguf
model/LICENSE.model
manifests/export.json        # quartermaster.export/v1
reference.json              # one frozen decision-time case and context/evidence fingerprints
compose.yaml
README.md
LICENSE
```

`ExportManifest` records the candidate/run IDs and hashes, base lineage through the
adviser configuration, training manifest/job hashes, evaluated adviser revision,
frozen suite fingerprint, knowledge/lesson pointers, source hashes, engine/prompt
versions, exact runtime image ID and every payload file's SHA-256/size. Paths and
tar member order are deterministic; timestamps/IDs distinguish separate exports.
No original source, training snapshot, candidate or earlier export is rewritten.
The builder retains the archive and its fingerprint; staging copies are discarded
after successful packaging. Repeated exports create new immutable UUIDs.

The package contains only selected knowledge, approved lesson text and one disclosed
reference situation. It excludes unselected sources, spreadsheets, raw feedback,
provider disclosures/keys, training rows, rubric labels and observed outcomes.
Selected source/lesson/case text may itself be sensitive: owner review and protecting
the archive are required. This is explicit selection, not automatic secret redaction.
Frozen reference data never goes to a trainer or synthetic-data provider.

Retrieval rebuilds a small in-memory FTS5 index from the frozen excerpts, so no
builder SQLite file is shipped. Shared context assembly preserves the existing
budget, literal-term search, approved-lesson ranking and source/case untrusted-data
boundaries. All frozen evaluation cases must reproduce their exact context, evidence,
lesson selection and omission counts before packaging proceeds. Corpus-dependent
FTS ranking can differ when unrelated indexed documents are absent; this fails with
`EXPORT_CONTEXT` rather than silently claiming equivalent behavior. Re-evaluate the
desired isolated knowledge selection and train/evaluate a corresponding candidate.

## Fresh extraction and verification

After downloading, run from this repository on the operator's Docker host:

```sh
make test-export EXPORT=/absolute/path/to/adviser-EXPORT_UUID.tar
```

This extracts into a new temporary directory, verifies strict manifests, allowed
paths, file sizes/hashes and exact original-byte excerpt provenance, and rejects
links, duplicates, traversal, executables and oversized entries. Before executing
Compose it checks the file against the fixed trusted recipe; modifying archive
hashes cannot turn uploaded Compose instructions into executable configuration.
The exact image must exist and identify the pinned engine and export contract.

The fresh Compose project uses `network_mode: none`, removes host port publication,
mounts only the extracted package read-only, runs as the runtime's non-root user,
drops capabilities and limits RAM to 4 GiB, CPU to four threads and processes to 128.
No GPU is requested. Only the runtime's internal loopback inference is reachable.
It checks health, makes a real `/v1/advise` reference request, checks advice schema,
accessible citation IDs, export/candidate identity and exact frozen context hash.
It also asserts builder/database/training modules are absent. Cleanup removes this
Compose project only, including on failure. It does not stop the owner's builder.

A separate `export-check-<UUID>.json` beside the archive records passed/failed status,
archive/image/context fingerprints and sanitized check results. It contains no raw
case/model text and never changes the archive. Startup is bounded to 360 seconds
and inference to 180 seconds; no automatic retry or image pull occurs. Missing
Docker/image, corrupt artifacts, incompatible model startup and invalid advice have
separate actionable error codes. Fix the cause and explicitly rerun the command.

For the old **M1 spike** archive format, use the original developer check:

```sh
uv run --locked python -m quartermaster.spike.run --export /absolute/M1_RUN/adviser.tar
```

`make test-export` now checks `quartermaster.export/v1` application packages only.

## Independent startup and interface

With the exact runtime image already available, extract a verified archive into a
new directory and run the commands in its README:

```sh
docker compose up -d --wait --wait-timeout 360
```

Open `http://127.0.0.1:8081`. The local form accepts a situation and optional choices
and shows the recommendation, supporting explanation, clarification, limitations
and original uploaded evidence excerpts separately. HTML is escaped and forms
require a matching origin. JSON clients use:

```sh
curl -H 'Content-Type: application/json' \
  -d '{"situation":"Describe decision-time facts", "choices":[]}' \
  http://127.0.0.1:8081/v1/advise
```

`RuntimeInput` accepts only `situation`, optional `choices` and optional canonical
`case_id`. Missing/extra/wrong-type fields and outcomes are rejected. The response
contains validated `quartermaster.advice/v1` under `advice`, accessible `evidence`,
the export/candidate IDs and a context fingerprint. It validates supporting quotes
and citations and withholds decisive recommendations when missing facts are declared.
`GET /healthz` succeeds only after package/reference verification and engine startup;
it becomes unhealthy if the child engine exits. Advice uses a fixed loopback URL,
ignores ambient builder credentials/settings, has one-request concurrency, 32 KB
request and bounded model-response limits, and never executes external actions.

`docker compose down` stops the package without deleting files. On a second machine,
obtain the exact image from the operator and verify its ID before starting; image
distribution and other CPU architectures have not been tested here. No image is
silently pulled by this package. Once image/model bytes are present, routine advice
needs no builder, frontier API or internet connection. Public hosting/authentication,
GPU serving and offline image-bundle distribution remain deferred.

## Verification record

- `make test`: 419 CPU tests passed, including 38 focused export tests.
- `make lint`: Ruff lint and formatting passed for 89 Python files.
- Standard standalone image built from the pinned Trixie/llama.cpp recipe.
- `make test-export` passed after fresh extraction with the real M1 fine-tuned model
  and explicitly mocked M6 lineage. Its `/v1/advise` response was schema-valid, asked
  for missing information, matched the exact frozen context and retrieved one valid
  source excerpt. The container had no builder/database/provider modules, no network
  and no GPU. This verifies runtime integration, not a real new M6 training candidate.
- The generated package's documented `docker compose up -d --wait --wait-timeout 360`
  startup also passed in the separate `qm-m7-operator-check` project. Health and the
  standalone HTML form worked; the temporary service/network were removed afterward.
- The local builder was backed up and rebuilt successfully. All 25 existing SQLite
  tables were unchanged; this installation contained zero projects/source artifacts.
  Schema remains v6. Backup: `/data/backups/pre-milestone-7-081c2c92-905a-4b37-91b9-70f34e24684b.sqlite3`.
  The export runtime pin was added to the ignored local `.env`; other settings stayed
  unchanged. The web service remains healthy at localhost port 8000 with no Torch.
- After owner approval, the real M6 GPU workflow completed once and its candidate
  passed a separate real M7 export check, detailed below. No cloud job or external
  builder call occurred. No visual browser verification or quality gain is claimed.

Exact artifacts for the earlier M1-based CPU fixture check (generated files stay ignored):

```text
runtime image: sha256:b52a7944803f845a661a0cfe998d35ef21a786a85cbb68aadeff6289d34c3e31
model SHA-256: a0f50c0d3f46e34d90d462fee58a3049ef52e9d73473196a6faa390f8ee370c6
model bytes:   811843232
fixture tar:   69a22e057f3e2ceaea2eed91a63db13d3910f0176f2a256fcb74a8cfc79f2009
context hash:  4b71fbb3186106ba9d7922d9bf092c7f01f68b8376f2ad5414282755c0d5612a
report: data/export-smoke-fixtures/m7-cpu-check/export-check-b2a0c81a-0531-4a00-8b46-023e4414b235.json
```

The report and `final-fixture-record.json` identify the exact scope and original M1
model/archive. The package README labels its mocked lineage before the ordinary
operator instructions. To reproduce this **test-only** check with an existing M1
archive, build/inspect the standard image, then prepare a new fixture directory:

```sh
uv run --locked python -m tests.smoke_export_fixture \
  --source-spike data/spike/e2b3c10d-aaa8-42e1-b3a2-83a4177a49cb/adviser.tar \
  --runtime-image sha256:YOUR_COMPLETE_LOCAL_IMAGE_ID
make test-export EXPORT=/absolute/path/printed/by/the/fixture/command.tar
```

This helper uses deterministic fake training/adapter/evaluation records and copies
the already-trained M1 portable bytes. It does not run a trainer or authorize new
supervision. Never import its mock project into the ordinary builder data directory
or use it to claim M6 acceptance. Release verification must use an actual reviewed
M6 candidate and retain its independent export-check report, as in the real run below.

## Real M6 candidate → standalone export — 2026-10-24

Following the owner's explicit approval, the [M6 GPU run](milestone-6.md) produced a real,
verified adapter, converted GGUF and two-case frozen comparison. The Train and Export pages
were rendered against that isolated project, then `POST /api/projects/{project_id}/exports`
created this candidate's immutable package. No mock training, adapter, conversion, model
or comparison lineage was used. The ordinary project data volume was unchanged and the
candidate was not promoted. `export-verification-setup.json` records the API/page checks,
unchanged active adviser and equality of candidate/job/training-manifest/suite/model hashes.

The actual command completed successfully:

```sh
make test-export EXPORT=/mnt/c/Users/bdobr/OneDrive/Documents/GitHub/QuarterMaster/data/training-smoke/1c147c6c-8987-4886-8b66-573437fb589a/artifacts/exports/dcfbb238-e827-4fd2-9b28-d0bb213995c7/60fe2247-3eaf-4800-a6ea-60fc57bb7d41/adviser.tar
```

The checker extracted the package into a fresh temporary directory and started the exact
standard image in an isolated CPU Compose project: read-only package, no external network,
no GPU, four CPU threads and 4 GiB RAM. The builder/database/training/provider modules were
absent. `/healthz` passed; real `/v1/advise` output validated and matched the frozen reference
context and candidate identity. Cleanup removed the temporary service after the check.

The reference is the complete polisher situation. The real candidate abstained, as in the
builder's frozen comparison: valid structure, but a **missed recommendation rubric**, not an
improved answer. The frozen suite predates the teaching lessons and has no selected knowledge,
so the exported knowledge/lesson pointers are both null, the applied-lesson list is empty and
the reference has no evidence IDs. Those empty versions match the evaluated candidate exactly;
export did not attach later lessons or invent citations. Positive uploaded-excerpt retrieval
is covered separately by the earlier M1-based runtime fixture and the CPU tests.

```text
data root: data/training-smoke/1c147c6c-8987-4886-8b66-573437fb589a
candidate: fcafe3ff-139f-4b6b-9f0f-2ba81b3a1409
export: 60fe2247-3eaf-4800-a6ea-60fc57bb7d41
model SHA-256: 8774d0caa5e571f55eb97f2fe3853b67e1377bb444077496fa23f39b67199188
model bytes: 811843232
archive SHA-256: 09574fd7a73a3d395438b9b2c04253e62dc65b86ac0afb92bd48567d73ff4571
reference context SHA-256: fd6fff9faf79273fa24152db49a0bc6c8a8e6d66cec000e9c57b3ef8373ec975
runtime image: sha256:b52a7944803f845a661a0cfe998d35ef21a786a85cbb68aadeff6289d34c3e31
report beside archive: export-check-8859be93-b24f-4591-88b1-570a70bef271.json
```

The immutable export and independent report remain under the isolated synthetic project's
artifact directory. This completes the local M6–M7 workflow acceptance on this hardware;
it does not establish useful adviser quality, a second-domain demo, standard-preset training,
visual browser behavior, other architectures or the remaining Milestone 8 release checks.
