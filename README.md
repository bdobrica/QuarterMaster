# QuarterMaster

A self-hosted workshop for teaching a personal AI adviser: **Collect → Teach → Ask → optional Review**. The intended loop turns accepted answers and corrections into reusable teaching evidence automatically. Approved knowledge changes affect context immediately; model behavior changes through separately authorized LoRA training.

**Status:** development prototype. Muster is included in this repository and runs inside QuarterMaster as **Collect**: capture pages, check extracted details, manage knowledge and publish collections. **Teach** imports those publications, activates saved knowledge and records personal number/category targets. Immutable reviewed datasets are available; connecting these generic targets to training/Ask and automatic feedback routing remains unfinished. Historical local training/export success does not establish personalized advice quality.

The current example is personal apartment valuation. Its [starting policies](examples/apartments/owner-policies.md) distinguish owner preferences and unverified assumptions. Core schemas stay generic.

## Start the current application

With Docker Engine and Compose v2:

```sh
cp .env.example .env
docker compose up -d --build --wait
```

Open [localhost:8000](http://127.0.0.1:8000). Basic startup needs no GPU or API key; initial builds need internet. This is a trusted, single-user localhost application without authentication or TLS.

For Python development, use Python 3.13 and `uv`:

```sh
make setup
make migrate
make test
make lint
uv run --locked uvicorn quartermaster.app:app --host 127.0.0.1 --port 8000 --no-access-log
```

CPU tests use deterministic fixtures, not real model calls. Model downloads, provider calls, GPU jobs and fresh-container export checks are separate opt-in operations. See the [operator guide](docs/operator-guide.md) and [.env.example](.env.example).

Open **Collect** at `/collect/`, then choose a project → **Teach** to use a publication. Live collection needs a desktop and Chromium installed with `uv run --locked playwright install chromium` on the host; the default container supports the management/handoff screens without a desktop browser. The old Muster checkout is not a runtime dependency. See the operator guide to copy existing Muster data before deleting it.

## Design and limits

Python/FastAPI, Jinja2/HTMX, SQLite and local artifacts; no Node build. One local inference adapter and a separately operated GPU trainer. Standalone local packages must run without the builder database or a frontier API; hosted advice is not an offline export.

QuarterMaster advises; it does not buy, negotiate, message or modify external accounts. Keep source observations, owner judgments and later outcomes separate. An asking price is not an approved valuation. Explanations cite accessible evidence and policies; they do not expose internal reasoning or prove factual correctness. Model confidence is not automatically calibrated. Small datasets can overfit or fail to improve.

External transmission requires scoped consent. Back up the complete data volume before upgrades; `docker compose down -v` deletes it. Models, dependencies and uploaded documents retain their own licenses. QuarterMaster is a development codename; repository code is [Apache-2.0](LICENSE).

| Document | Purpose |
| --- | --- |
| [PLAN](PLAN.md) | Product behavior and architecture |
| [TODO](TODO.md) | Ordered implementation and acceptance criteria |
| [ADRs](docs/adr/README.md) | Durable decisions, positive results and failed approaches |
| [Operator guide](docs/operator-guide.md) | Current controls, models, training, export and recovery |
| [Third-party notices](docs/third-party-licenses.md) | Redistribution and model/dependency provenance |
| [AGENTS](AGENTS.md) | Engineering instructions |
