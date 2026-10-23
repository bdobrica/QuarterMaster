# Milestone 2 — Projects, sources and knowledge

Milestone 2 adds the local Teach foundation. Open a project from the home page, edit its name,
mission and optional business goal, and upload CSV/XLSX/Markdown. Every saved mission and
knowledge selection creates a timestamped revision. This milestone does not call a builder
provider, generate advice, approve training labels or run a GPU job.

## Owner workflow

1. Create or open a project. Save its mission and optional goal; inspect older revisions under
   **Mission history**. Saving a stale page is rejected rather than overwriting newer edits.
2. Upload one file at a time. Explicitly label it observations, examples to inspect, or knowledge.
   For CSV, select UTF-8 or Windows-1252 and a comma, semicolon, tab or pipe separator. Re-upload
   with the correct options if the preview does not match the file. Original bytes are retained.
3. Inspect sheets, field names, row counts, the first five rows, missing values, likely types,
   date candidates and formula counts. Hints do not convert ambiguous dates or infer labels.
4. Choose **Review a field mapping**. State what one primary row represents and when advice is
   requested. Choose the decision inputs, later observed outcomes and candidate target advice.
   Confirm that inputs and join keys were available before advice. Review the resulting cases and leakage
   warnings before confirming the mapping. Previewing alone saves no cases.
5. If combining tables, explicitly choose both join keys. Keys match exact, case-sensitive text
   without trimming or numeric coercion. The right key must be unique and nonempty, and every
   primary row must match. Keys mapped as outcomes or target advice are rejected; suspicious
   unmapped key names produce leakage warnings too. Ambiguous/unmatched joins fail; no rows are silently dropped. The
   form supports one additional table; the contract/API supports up to three ordered joins.
6. Select uploaded Markdown labeled knowledge and choose **Save selection and reindex**. Search
   finds ranked text excerpts with source links, heading, line positions and stable citation IDs.
   To replace a source, upload a new file, select it and deselect the earlier source. Deselecting
   all sources creates an empty current revision. Earlier selections and originals remain intact.

Source roles and parse options are part of immutable upload metadata. To correct either,
re-upload the same bytes with the intended role/options; this creates a new source ID and reuses
its content-addressed original. A source's name never selects or overwrites a file on disk.

## Contracts and persistence

- [AdviserSpec](../quartermaster/contracts/adviser.py): `quartermaster.adviser/v1`, UUID, revision,
  UTC timestamp, name/mission/goal, explicit Case/Advice contracts, pinned model and nullable
  knowledge pointer. Adapter and lesson settings remain unavailable at this stage.
- [Source and mapping contracts](../quartermaster/contracts/sources.py): strict types, unknown
  fields rejected, UUID strings accepted at the JSON boundary, explicit boolean confirmations.
  A missing/false/numeric confirmation cannot save a mapping.
- `quartermaster.derived-case/v1` wraps the existing [Case](../quartermaster/contracts/advice.py).
  The situation is stable, sorted JSON text containing grain, decision time and selected input
  fields qualified by source ID/sheet/name. Outcomes are stored only in `observed_outcome`, which
  `Case.decision_input()` excludes. Target columns are separate unreviewed candidates. Neither
  source role “examples” nor mapping approval establishes ideal advice or training supervision.
- Every derived case preserves mapping ID, source IDs/hashes, sheet and record/row numbers.
  Multiline CSV records also preserve physical start/end lines. Mapping and case IDs are
  deterministic for the same reviewed mapping and source IDs, independent of save time. Repeated
  confirmation is idempotent. Re-uploading creates a distinct source lineage even for equal bytes.
- SQLite schema v2 migrates v1 projects transactionally, preserving original IDs, creation times,
  names and missions as adviser revision 1. Unknown/malformed databases are never reset. Back up
  the full data directory/Compose volume before upgrading; older code cannot open schema v2.
- Originals live under `artifacts/sources/<hash-prefix>/<sha256>`, created exclusively, never
  overwritten, and read back with size/hash checks. SQLite holds source metadata, mapping/case
  snapshots and knowledge manifests. Keep SQLite and artifacts together in backups.
- Markdown chunk/index rows are rebuildable projections. Saving/reindexing regenerates selected
  sources from verified originals and creates a new immutable selection. Citation IDs remain
  stable for unchanged source IDs, character spans and content. Historical citations require
  their explicit revision; current lookup and search exclude deselected sources.

## Parsing and retrieval limits

| Area | Supported boundary |
| --- | --- |
| Upload | One nonempty `.csv`, `.xlsx` or `.md`, at most 8 MiB; actual request stream capped at 8 MiB + 64 KiB before multipart parsing |
| Spreadsheet | Header in first row; unique nonempty field names, at most 100 columns and 10,000 data rows per sheet; 100,000 data cells total per file |
| XLSX archive | At most 512 unique entries and 32 MiB expanded; at most 20 worksheets; unsafe/encrypted archives, macros, embedded objects and unsafe XML rejected |
| Cells | At most 8,000 characters per cell; formulas displayed literally, never evaluated, and rejected in selected XLSX mapping fields/join keys |
| Markdown | UTF-8, ATX/setext heading boundaries outside fenced code; at most 2,000 headings per source; escaped source text, no rendered HTML/scripts or followed links |
| Knowledge selection | At most 100 Markdown sources, 16 MiB total and 10,000 chunks; chunks at most 1,500 characters |
| Mapping | 1–30 inputs, at most 10 outcomes and 10 candidate targets, up to three exact keyed joins; oversized Case text rejected, never silently truncated |
| Search | SQLite FTS5/BM25, literal word terms (up to 16) from at most 200 query characters; at most 10 results; project/revision scoped |

CSV values remain strings, including formula-like text. XLSX dates/numbers/booleans receive
explicit text representations in the preview/cases (ISO dates, decimal text, `true`/`false`),
while original bytes remain unchanged. Empty/blank spreadsheet rows are not silently discarded.
Missing/type/date and outcome/target hints are heuristics; temporal availability remains an owner
judgment. Source labels do not prove factual correctness. There is no arbitrary preprocessing,
fuzzy join, aggregation, semantic search or automatic ground-truth label generation.

XLSX uses [openpyxl's read-only mode](https://openpyxl.readthedocs.io/en/stable/optimized.html)
with `data_only=False`, external links disabled and a bounded ZIP/XML inspection first.
[openpyxl recommends defusedxml](https://openpyxl.readthedocs.io/en/stable/#security) for XML
protection; it is pinned and verified active. No workbook code or generated scripts are executed.
The dependencies stay in the web image and add no runtime service, model or Node build.

## API

See local `/docs` for request schemas. JSON mutations require `application/json`; cross-origin
requests are rejected. All browser forms and multipart uploads require an exact same-origin
`Origin` header, including multipart API calls. There is no permissive CORS configuration.

| Route under `/api/projects/{project_id}` | Operation |
| --- | --- |
| `GET` / `PATCH` project root | Read adviser spec / save name, mission, optional goal with `expected_revision` |
| `GET /revisions` | Immutable adviser history |
| `GET /sources`, `GET /sources/{id}` | List/read source metadata and previews |
| `POST /sources` | Multipart: `file`, `label`, `encoding`, `delimiter` |
| `POST /mappings/preview` | Validate a proposed mapping; return warnings and first five derived cases |
| `POST /mappings` | Confirm and persist a strict `CaseMapping` |
| `GET /mappings`, `GET /mappings/{id}/cases` | Saved mappings and provenance-linked cases |
| `GET /knowledge`, `GET /knowledge/revisions` | Active knowledge manifest / history |
| `POST /knowledge` | Explicit `source_ids` selection and `expected_revision` (null initially) |
| `GET /knowledge/search?q=...` | Ranked accessible excerpts; optional explicit `revision` UUID |
| `GET /citations/{id}` | Verified excerpt and original-source metadata; optional `revision` UUID |

Original downloads are project-scoped `/projects/{project_id}/sources/{id}/original`, returned
as attachments with an inert content type and `nosniff`. Human-facing errors show actionable,
sanitized codes without reflecting parser exceptions or sensitive validation values.

## Verification

Locally verified on 2026-10-24 (Europe/Bucharest):

- `make test`: **175 passed**, offline CPU suite on Python 3.13.5. Includes v1 migration and
  rollback, mission history, invalid/missing/extra fields, explicit review, deterministic case
  IDs/serialization, outcome/target exclusion, exact joins and post-decision join-key protection,
  parser/resource failures, hostile names/XML/archives, CSRF, actual streamed request size,
  source hash integrity, revision isolation, stable citations and rebuilding a deleted index.
- `make lint`: Ruff and formatting passed for 42 Python files.
- `docker compose build web`: pinned Python 3.13 Trixie image built with the locked parser
  dependencies; its Python version is 3.13.17. No Torch, provider SDK, Node build or model download.
- Fresh web container: **passed**, network disabled, read-only root, non-root user, temporary
  data, two CPUs and 512 MiB memory. The [HTTP smoke script](../tests/smoke_foundation.py)
  created/renamed a synthetic project, uploaded CSV/XLSX/Markdown, checked previews and original
  bytes, previewed/confirmed deterministic cases with provenance and separated outcomes,
  exercised the human-readable case-review form, indexed/searched Markdown, verified an exact
  citation, and confirmed removal from current search/citation lookup while retaining the
  explicit historical citation. Result: three sources, two derived cases, two knowledge revisions.
- `docker compose up -d --build --wait`: healthy service on localhost. A SQLite backup was made
  before upgrading the existing volume from schema v1 to v2. That volume contained zero projects;
  project-data preservation and rollback with populated databases are covered by the CPU tests.
  Post-upgrade checks confirmed schema v2, `/healthz`, home-page HTTP 200 and no Torch dependency.
- Temporary smoke container removed. No GPU, live model/provider, training or model-export job
  was run for this milestone; the existing Milestone 1 CPU regression checks passed.

The isolated HTTP check can be repeated from the checkout (it creates temporary synthetic data):

```sh
docker compose build web
docker run -d --name quartermaster-m2-smoke-20261024 --network none --read-only \
  --cap-drop ALL --security-opt no-new-privileges --memory 512m --cpus 2 \
  --tmpfs /tmp:rw,nosuid,nodev,size=32m \
  --tmpfs /data:rw,nosuid,nodev,size=64m,uid=10001,gid=10001 quartermaster-web
docker exec -i quartermaster-m2-smoke-20261024 python - < tests/smoke_foundation.py
docker rm -f quartermaster-m2-smoke-20261024
```

The CPU test/lint gates ran outside the workspace sandbox because its loopback and uv-cache
restrictions prevent ordinary TestClient/cache access. They used no external model service.
Browser appearance was not manually inspected. This verification establishes local ingestion,
review and evidence behavior, not adviser quality or business benefit.
