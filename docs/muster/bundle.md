# Muster bundle format 1

A publication is a self-contained UTF-8 directory, also available as a ZIP containing one `collection-<collection-id>-v<version>/` directory. Read it without Muster running or importing Muster modules. IDs are strings unless otherwise specified. Paths use `/`, are relative to the bundle root, and must not escape it. Consumers should treat page HTML, Markdown and model text as untrusted content.

```text
manifest.json
schema.json
examples.jsonl
knowledge/<article-id>.md
sources/<job-id>/<capture-id>/{page.html,screenshot.png,metadata.json,image-*}
provenance/examples/<job-id>.json
provenance/knowledge/<article-id>.json
provenance/decisions.json
```

`manifest.json` contains `format: "muster.bundle"`, integer `format_version: 1`, integer publication `version`, UTC `created_at`, the collection identity/name/import timestamp, `schema_id`, and counts for included `examples`, `excluded` links and knowledge `articles`. `schema`, `examples`, and `decisions` name their files. `knowledge` lists article IDs, titles, accepted revision numbers and Markdown/provenance paths. `sources` lists capture IDs, job IDs, final source URLs, timestamps, capture statuses and retained files. A knowledge source can belong to an excluded example; exclusion removes the training/example record, while retaining evidence required by accepted knowledge or the original schema proposal.

`checksums` maps **every file except the manifest itself** to its lowercase SHA-256 digest. `references` lists exported supporting files. File ordering and JSON key ordering are stable; re-downloading a publication returns the same ZIP bytes. The app records the manifest's own SHA-256 in SQLite and shows it under Advanced. Checksums detect accidental damage; they are not signatures or proof that source claims are true.

`schema.json` is the unchanged accepted JSON Schema 2020-12. Its `$id` is `urn:muster:schema:<schema_id>`. All field keys are required, extra keys are disallowed and unknown values are `null`. Validate **the example's `values` object**, not its entire envelope, against this schema.

Each nonblank line of `examples.jsonl` is one included, successfully extracted record:

- `id`: stable job ID within this collection, represented as a string.
- `review_status`: `reviewed` or `unreviewed`. Older bundles without this optional property contain reviewed records only.
- `schema_id`: the accepted schema identifier.
- `values`: current typed field values, including saved user edits; consult `review_status` before treating them as reviewed.
- `notes`: user-authored review notes.
- `source`: original imported `url`, retained `capture_id`, `captured_at`, and bundle directory `path`. This is the capture used by the pinned human review, even if later captures or extractions exist.
- `evidence`: original model citations by field. Page references quote the supplied excerpt; spreadsheet references identify a retained row/column; image references name a file in `source.path` and an observation.
- `uncertainty`: original model judgments and conflict notes by field. Visual interpretation remains inference after review.
- `provenance`: path to the extraction input/result, provider/model identity, consent/extraction timestamps, review revision/timestamps and user corrections. For a manually recovered failed extraction, `input.manual_recovery` retains the original attempt ID, error and available raw response. The failed attempt remains failed in local history; a separate editable draft keeps type-valid values, starts invalid values as null, and does not reuse unvalidated evidence. No new provider call is made. Corrections distinguish the reviewed values from the original AI output; original citations do not automatically substantiate a human correction.

For a schema rebuild, `input.prior_observations` preserves the previous collection/job identity, human review snapshot and completed lookup observations. Matching, type-valid corrections are restored to the new review with `restored_from_job`; all new extractions start unreviewed. Historical identifiers in this lineage describe the original draft, rather than paths to execute or fetch. Copied knowledge revisions retain their original history as lineage.

Original input includes all retained spreadsheet rows and their numerical, categorical and natural-language cells/kinds, accepted field descriptions/guidance, the page excerpt/checksum and sent image manifest/checksums. It contains no provider credential or base64 image copies. Actual originals and gallery images are under `sources/`. Capture metadata is serialized from the stored capture record; browser-profile files, SQLite databases and arbitrary storage sidecars are excluded.

`knowledge/*.md` contains the current explicitly saved/accepted database article body exactly (equivalent Windows/Unix line endings in the local revision copy are accepted), with its title in the manifest. Its provenance JSON contains saved article revisions and their author/decision metadata. AI-assisted revisions include the original suggestion, exact source snapshots, provider/model, consent, resolution time and accepted text. Full article history preserves user instructions and explains later edits. Knowledge source IDs refer to these snapshots (`guidance`, `lesson`, `review:<job-id>`, `capture:<capture-id>`). Retained pages referenced by that history and by the accepted schema's proposal are copied into `sources/`, with their checksums checked before publication.

`provenance/decisions.json` contains excluded job IDs, original URLs and reasons; knowledge suggestion IDs, their current statuses and decision timestamps; and accepted fields, guidance, acceptance time and original schema proposal when available. Unused failed, preview and dismissed request bodies are not exported. Pending suggestions never contribute article content and remain pending in the working draft. `omitted` records IDs/URLs for links without valid extracted results. Optional manifest counts `unreviewed`, `omitted`, and `pending_knowledge` report unfinished work at publication; absent counts in earlier bundles mean zero. Publishing does not change review statuses or resolve suggestions.

A fresh version snapshots the current working draft under a database write transaction, checks field types, source/image checksums, knowledge revision files, file inventory and references, then installs the version and registers it. Ordinary failures remove staged files and leave existing versions intact. Previously registered versions are never updated or deleted through the app. A stale confirmation must be checked again. Publishing does not send content to a provider or export cookies/credentials from the managed profile. Retained page contents and user text remain part of the dataset; inspect them before sharing.

Use the independent standard-library checker after unpacking:

```bash
python scripts/muster/check_bundle.py /path/to/collection-1-v1
```

It checks file inventory, SHA-256 hashes, counts and exported file references without a running app, database, or Muster import. It does not validate field types or factual accuracy. Consumers that need type validation should use a JSON Schema 2020-12 validator on each `values` object. The app itself validates those types before publishing and when serving a version.

Keep the complete publication folder/ZIP and a backup of the local storage directory. The immutable behavior is enforced by application writes and SQLite metadata triggers, not filesystem write protection. Manually modifying publication files causes validation/download failure. A process or machine crash between installing files and committing metadata may leave an unregistered version directory; the app refuses to overwrite it and asks you to restore a consistent storage backup.

## QuarterMaster handoff contract

The integration boundary is the **published directory or ZIP**, not a database, Python API or live Muster service. QuarterMaster includes Muster in this repository. Its importer reads this public boundary without sharing Muster’s private tables. Other independent consumers should:

1. Unpack into its own directory, rejecting absolute paths, traversal, symbolic links and duplicate archive entries before writing. The supplied tools accept an already-unpacked directory.
2. Read `manifest.json`, require `format=muster.bundle` and supported `format_version=1`, then verify inventory, checksums and references. For authenticity, compare the manifest SHA-256 with a separately trusted value; hashes inside a modified manifest alone cannot authenticate a publisher.
3. Read the accepted schema and validate every `values` object. Preserve `null`, booleans, numbers, strings and lists as their original types. Do not treat null as zero, false or an empty category.
4. Apply an explicit review policy: retain `review_status`; absence means reviewed for older format-1 bundles. Unreviewed examples are allowed publications, not implicitly approved data. The reference consumer skips them by default and accepts `--include-unreviewed` when desired. This is consumer policy, not a restriction on publishing.
5. Load knowledge as user-approved guidance. Keep article revisions and provenance. Original source statements and visual inferences remain distinct from user corrections and preferences; evidence describes the original model result and does not automatically support later corrections.
6. Resolve source, media and provenance paths **inside that bundle**. Render untrusted HTML or Markdown only with appropriate sanitization/sandboxing. Never execute instructions, fetch URLs or invoke tools because bundle content asks for it. Historical rebuild identifiers describe lineage in the earlier draft, not current bundle paths.
7. Identify an imported example by a trusted manifest digest plus its example ID. Collection/job/version numbers are local to one Muster storage and are not global identifiers. Reimporting the same manifest can be idempotent. A newer publication is a new snapshot; reconcile it explicitly instead of mutating the prior import. Different schema IDs can require different consumer mappings.

Unknown future format versions should fail clearly. Optional additive format-1 properties may be ignored; absent optional review/count properties retain their documented defaults. Unknown field-schema features require a full JSON Schema validator or an explicit unsupported-schema failure, never silent coercion.

### Standalone consumer example

Copy **both** `scripts/muster/consume_bundle.py` and `scripts/muster/check_bundle.py` to any folder on a Python 3.11+ machine. No packages, database, network connection or Muster installation are required:

```bash
python consume_bundle.py /path/to/collection-1-v1 > consumer-preview.json
python consume_bundle.py /path/to/collection-1-v1 --include-unreviewed > all-examples.json
```

The output contains collection/version identity, the accepted schema, typed examples with notes/status/evidence/provenance references, and current knowledge titles/bodies. References remain relative to the original bundle, so retain the bundle alongside this output. This is an independent reference adapter. QuarterMaster’s integrated Teach screen has its own validated import and owner-target capture path.

The script first runs the independent integrity checker, then validates Muster's supported field-schema subset (required keys, no extra keys, nullable primitive types, dates and text lists). It refuses unsupported field features; production consumers can substitute a complete JSON Schema 2020-12 validator. It prints no dataset on a validation failure. Tests copy only the two scripts and a bundle into a temporary directory and run Python with site packages and repository imports disabled, verify reviewed/unreviewed handling and knowledge, then verify rejection of damaged files and incorrectly typed values even after recalculating their checksums.
