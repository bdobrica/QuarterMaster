# QuarterMaster

**A no-code factory for specialized, teachable AI advisers.**

QuarterMaster helps a small-business owner turn their knowledge, historical examples, and natural-language feedback into a specialized adviser. Describe what you want advice about, upload spreadsheets and Markdown research, teach the adviser how to handle situations, evaluate its judgment, fine-tune a small language model, and export a standalone Docker-ready adviser.

**Status:** Milestones 0–3: local projects and mission history, CSV/XLSX/Markdown previews, reviewed case mappings, searchable Markdown knowledge with citations, and a guided interview with editable spec review. The interview works manually offline or through an optional provider after explicit disclosure/consent. The Milestone 1 developer LoRA/GGUF smoke test is also available. Advice/correction and application training/export screens remain planned; this is not the `0.1.0` MVP yet. The tiny synthetic spike does not establish adviser quality. QuarterMaster is a standalone project, not a KitchenSoup plugin.

## Why QuarterMaster?

A knowledgeable human adviser is useful not only because they know facts, but because they have experience: they've encountered similar situations, learned when to ask questions, and developed judgment. QuarterMaster explores whether a business owner can teach those habits to a small LLM **without becoming a data scientist**.

The defining interaction is:

> “In this situation, I don't think you handled it well. You should have asked for the menu picture before advising.”

QuarterMaster turns that correction into a reviewed lesson, applies it immediately through context, and can later include it in a LoRA fine-tuning run. The owner tests the result and decides which adviser version is worth keeping.

## The workflow

1. **Teach** — Describe the advisory job. Upload CSV/XLSX observations, Markdown knowledge, and examples. Answer a short guided interview.
2. **Test** — Ask the base-model apprentice for advice. Inspect supporting evidence and correct mistakes in plain English.
3. **Evaluate** — Save representative situations and compare advisers side by side, including cases where they should ask for more information.
4. **Train** — Review the training examples, fine-tune a curated small Qwen model with LoRA, and compare the candidate against the current adviser.
5. **Export** — Package the chosen version with its model, lessons, knowledge index, local UI and `/v1/advise` API.

The primary UI tabs are **Teach · Train · Evaluate · Test · Export**. The order above reflects how a first-time owner discovers the product: try it and teach it before committing to a training run.

## What an adviser returns

An adviser can offer:

- A concrete recommendation or an honest inability to decide.
- A concise explanation grounded in the supplied case and retrieved knowledge.
- References to the uploaded sources that support factual claims.
- A request for missing information when it should not make a call yet.
- Limitations or uncertainty stated without invented numerical confidence.

It does **not** send emails, post to social media, modify business records, or execute real-world actions.

## Example projects

| Domain | Owner's question | Potential teaching moment |
| --- | --- | --- |
| Social media | “When should I post this announcement?” | Ask whether it is part of a coordinated campaign. |
| Accounts receivable | “Which invoice should I follow up on?” | Consider a disputed invoice differently from a normal overdue invoice. |
| Customer experience | “How should I respond to this complaint?” | Ask for the relevant photo before making a definitive judgment. |

These examples illustrate **advisory behavior**, not proven causal business lift. Historical observations help ground the advice, but do not automatically identify the effect of taking the recommended action.

## Quick start

From this checkout, with Docker Engine and Docker Compose v2 installed:

```sh
cp .env.example .env
docker compose up -d --build --wait
```

Open <http://127.0.0.1:8000>. No GPU, model download, API key or other application service is needed. The build needs internet access to obtain the Python image and locked packages; the running application serves its assets locally. The Python 3.13 image uses Debian Trixie and is pinned by digest.

Compose stores SQLite and artifacts in the `quartermaster-data` named volume at `/data`. `docker compose down` retains it. To back it up, stop the web service and copy the entire volume, including SQLite sidecar files and artifacts. Restore with the service stopped. `QM_DATA_DIR` configures local Python runs; Compose deliberately fixes it to its persistent `/data` mount.

For development, install Python 3.13 and [uv](https://docs.astral.sh/uv/), then run:

```sh
make setup
make migrate
make test
make lint
uv run --locked uvicorn quartermaster.app:app --host 127.0.0.1 --port 8000 --no-access-log
```

Open a project to edit its mission, upload sources, preview and confirm case mappings, and select Markdown for knowledge search. Each upload is limited to 8 MiB; formulas are never evaluated. Outcomes stay separate from decision inputs. See the [Milestone 2 guide and verification](docs/milestone-2.md) for supported mappings, limits and API routes.

Choose **Define the adviser through a guided interview** to describe choices, desired behavior, case grain, decision-time information and observable success/harm. Review, edit or reject the resulting spec before saving it. The manual path needs no provider. Optional provider setup, exact-context consent and failure recovery are described in the [Milestone 3 guide](docs/milestone-3.md). Historical rows remain unreviewed; the interview visibly reports `needs_examples`.

`make help` lists formatting and Compose commands. Startup initializes/checks schema v3 and transactionally migrates v1/v2 databases, preserving existing missions and source metadata. Back up the data volume before upgrading. Incompatible or unversioned existing databases fail with an actionable error instead of being reset.

## Model feasibility spike and planned workflow

The opt-in [Milestone 1 spike](docs/milestone-1.md) pins Qwen3.5-0.8B, trains a small reviewed synthetic fixture, compares held-out outputs, merges a LoRA adapter into GGUF Q8_0, and tests a fresh extraction in a network-isolated llama.cpp CPU container. It uses separate Trixie-based trainer/runtime images; ordinary web startup and CPU tests do not install ML dependencies or download weights.

```sh
make test-gpu                 # Requires NVIDIA Container Toolkit
make test-gpu GPU_MODE=wsl    # Explicit WSL device/read-only driver passthrough
make test-export EXPORT=/absolute/path/to/data/spike/RUN_ID/adviser.tar
```

These are explicit, bounded local developer checks, not the future no-code training/export UI. See the verification record for exact hardware, package revisions, latency, artifacts and observed regressions. No cloud GPU or builder API is used by the spike.

A supported GPU is required for this LoRA spike. Projects, uploads, case preparation and knowledge search work on CPU without a model. The explicit base-model text preflight also runs on CPU, subject to available memory. Ordinary adviser testing remains a later milestone. Training uses explicitly selected local hardware.

Exported advisers use a separate standard runtime package and run without the QuarterMaster builder or frontier-model API for core advice. The first launch may need to download its prebuilt runtime image; thereafter the model and knowledge are local.

## Architecture at a glance

| Part | Initial implementation |
| --- | --- |
| Builder UI/API | Python, FastAPI, Jinja2, HTMX |
| Durable metadata | SQLite |
| File and model artifacts | Persistent local directory with hashes |
| Research/knowledge | Markdown chunks + SQLite full-text search |
| Builder intelligence | Configurable OpenAI-compatible LLM provider |
| Adviser model | Curated small open-weight Qwen model |
| Consolidated learning | Supervised fine-tuning using PEFT LoRA on supported GPU |
| Runtime inference | Small local serving engine, initially targeting llama.cpp/GGUF |
| Packaging | Generated Docker Compose bundle with a standard runtime image |

This intentionally avoids Kubernetes, Redis, object storage, agents with tools, general-purpose code generation, and automatic retraining in the first release.

## Trust and limitations

- QuarterMaster is a **trusted single-user local application**, not an internet-exposed or multi-tenant service. Compose publishes only on localhost. Internet exposure requires authentication and a secure reverse proxy, which are not included.
- The builder must ask permission before transmitting uploaded business information to an external model provider. The exported adviser does not need that provider for core inference.
- Uploads and generated examples must be inspected; Markdown and spreadsheets may contain malicious instructions or misleading facts.
- User preferences, factual correctness, and eventual business outcomes are different signals. Fine-tuning on corrections does not guarantee business benefit.
- An LLM-generated explanation is a grounded account of supporting evidence, **not a transparent view into the model's hidden reasoning**.
- Numerical predictions and causal effect estimates are not guaranteed just because the input contains numbers.

## Project documents

- [PLAN.md](PLAN.md) — product scope, architecture, contracts, risk spikes, milestones, release gate and future extension seams.
- [TODO.md](TODO.md) — atomic implementation checklist and acceptance criteria.
- [AGENTS.md](AGENTS.md) — coding-agent instructions and verification requirements.

## Name and licensing

**QuarterMaster is a development codename.** No exclusive claim to the name is implied, and a public-facing brand should be cleared separately.

The project code is licensed under [Apache-2.0](LICENSE). Base models, source materials and third-party runtimes retain their own licenses and distribution terms; see [third-party notes](docs/third-party-licenses.md).
