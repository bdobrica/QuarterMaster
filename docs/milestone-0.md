# Milestone 0: local application skeleton

The runnable scope is project creation/listing, mission storage, a local HTML UI and `/healthz`. It does not provide adviser inference or complete any later milestone. No application code or services were copied from other projects.

## Bootstrap API

- `POST /api/projects`: JSON with exactly `name` (trimmed, 1–120 characters) and `mission` (trimmed, 1–4000 characters). Returns HTTP 201 with `schema_version: quartermaster.project/v1`, a stable UUID and UTC `created_at`.
- `GET /api/projects`: saved projects, newest first.
- `GET /healthz`: HTTP 200 `{"status":"ok"}` after storage initialization; checks the SQLite schema and artifact directory. Storage failures return HTTP 503 with a sanitized diagnostic code.
- `GET /`: project form and saved projects; `POST /projects` accepts the form with a matching Origin header, returning an HTMX fragment or a regular redirect. Cross-origin browser writes are rejected. There is no CORS policy permitting other sites.

The bootstrap metadata contract is separate from the adviser specification planned in Milestone 2. There are no editable missions or historical revisions yet. Forms also work without JavaScript. Jinja escapes untrusted text; SQL statements bind values. Provider configuration is reserved, masked and unused, with no business-content transmission.

## Storage and schema

`QM_DATA_DIR` defaults to `./data` for local Python runs. Startup creates that directory, `artifacts/` and `quartermaster.sqlite3`. Compose mounts its named volume at `/data` and runs the web server as UID/GID 10001. No per-project empty artifact tree is created.

SQLite uses WAL, foreign keys, bounded lock waits and transactions. `PRAGMA user_version` tracks the schema. The first migration initializes only an empty, unversioned database; newer versions, unknown preexisting tables or incompatible project columns fail startup. `make migrate` uses the same idempotent migration path. Future schema changes must add explicit sequential migrations.

Project files/model bytes will be implemented in later milestones. The skeleton initializes the artifact root and tests filesystem persistence without claiming to implement immutable source storage.

## Reproducibility and checks

Python support is limited to 3.13. Direct dependencies and all resolved packages are locked. The container uses `python:3.13-slim-trixie` pinned to the digest in [Dockerfile](../Dockerfile). HTMX is served locally with its upstream license and integrity check. Development/test packages are excluded from the web image.

`make test` selects CPU fixtures and excludes `gpu` and `live` markers. Fixtures reject IPv4/IPv6 socket connections, use temporary storage, and load a clearly synthetic [project fixture](../tests/fixtures/project.json). Tests cover contract errors, escaping, cross-origin writes, form handling, sanitized errors, schema incompatibility and project/artifact persistence across application restarts. CI runs locked setup, lint and CPU tests without credentials.

## Verification record — 2026-10-23

- `make setup`, `make fmt`, `make lint`, `make help`: passed. Local Python was 3.13.5; the pinned Trixie image ran Python 3.13.17 on linux/amd64.
- `make test`: **36 passed**, no warnings, GPU, credentials or live model calls. This workspace's sandbox prevented TestClient's local event-loop socket wakeups; execution outside the sandbox passed with the suite's external-network blocking fixture still enabled.
- `QM_DATA_DIR=/tmp/quartermaster-m0-migrate make migrate`: passed on a new directory and on a subsequent invocation. Sandboxed local commands used `UV_CACHE_DIR=/tmp/quartermaster-uv` for a writable tool cache.
- `docker compose up -d --build --wait`: built successfully and reported healthy. HTTP checks inside the container verified the landing page, local HTMX asset, health endpoint and JSON project creation. The web process ran as UID 10001. Compose reported only `127.0.0.1:8000` published.
- `docker compose down` followed by `docker compose up -d --wait`: the synthetic project retained its exact UUID, UTC timestamp and content; an artifact file retained its bytes. A final image rebuild also preserved both. Only the synthetic smoke project and marker were removed afterward; the healthy service and persistent volume were retained.
- GitHub Actions configuration was added; its equivalent setup/lint/test commands passed locally. No hosted CI run is claimed.

No real model, GPU training, model conversion or standalone adviser export was run or claimed. Those checks begin with Milestone 1.
