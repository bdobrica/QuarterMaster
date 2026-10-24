# QuarterMaster

The fresh print-proof demo and its live hosted-model evidence are documented in [P0 print demo](docs/print-demo.md).
Use the primary **Knowledge** tab to draft article changes, review a diff, approve policy revisions
and compare retrieved evidence before/after. See [reviewed knowledge workflow](docs/knowledge-workflow.md).


**A local factory for teachable AI advisers.** Describe a recurring decision, upload reference
material, test the adviser, review corrections, evaluate frozen situations, explicitly train a
small model when explicitly requested, and export it with an independent browser interface and advice API.

**Status:** Milestones 0–7 are implemented and locally verified; Milestone 8 adds onboarding,
three synthetic domains, provider limits and operating guidance. This is a development build,
not a tagged `0.1.0` release. A real laptop GPU run and offline standalone inference passed,
but the tiny synthetic evaluation showed **no quality gain**. The candidate remains unpromoted.
See [M8 verification and release checks](docs/milestone-8.md), [training results](docs/milestone-6.md)
and [export verification](docs/milestone-7.md).
The [working adviser follow-up](docs/working-adviser.md) enables bounded thinking,
project knowledge/rules and export of a tested base adviser without training.
The live bank comparison still fails the advice-quality gate; useful advice is not yet established.

## Quick start

Install Docker Engine and Docker Compose v2, then run from this checkout:

```sh
cp .env.example .env
docker compose up -d --build --wait
```

Open <http://127.0.0.1:8000>. The project/teaching UI needs no GPU, model download, API key or
other application. Initial image/package builds need internet access. Assets are served locally;
there is no Node build. Images use digest-pinned Python 3.13 slim **Trixie**.

Start at **Synthetic examples** for small, explicitly AI-drafted rental-tool, print-proof and social-post
CSV/Markdown files and sample missions. Create a project, upload the files, inspect their previews,
confirm decision-time inputs and select the Markdown as searchable knowledge. The manual guided
interview needs no provider. History and later outcomes never automatically become ideal advice.

For actual advice, run `make model-setup`, set the printed `QM_LOCAL_MODEL_SHA256` and
`QM_LOCAL_BASE_URL=http://inference:8080/v1` in `.env`, then start:

```sh
docker compose -f compose.yaml -f compose.advice.yaml --profile advice up -d --build --wait
```

This explicitly prepares the pinned unmodified Qwen3.5-0.8B model; it does not train it. The GGUF
is approximately 812 MB; the tested CPU service uses a 4 GiB memory limit/four threads and can take
minutes per response. See [model setup](docs/milestone-4.md) for resources and limitations.

## Teach → Test → Correct → Export

- **Teach:** describe the mission; upload CSV/XLSX observations and Markdown knowledge, up to
  8 MiB per file. Inspect mappings, confirm any joins and keep outcomes separate from inputs.
- **Test:** enter a situation, inspect advice/citations/questions and give a plain-language
  correction. Review and approve the reusable lesson, then try a related unseen situation.
  Lessons change **context immediately**; weights stay unchanged.
- **Export:** select a successful base test and review the included knowledge, lessons and
  reference situation. Build/pin the standard runtime first; no LoRA or GPU is required.
  Run `make test-export EXPORT=/absolute/adviser.tar`, then follow the archive's Compose instructions.
  See [setup and current quality limits](docs/working-adviser.md).
- **Evaluate:** save separate unseen cases with owner rubrics and freeze the suite. Compare
  saved outputs, inspect mistakes and rate preferences. Holdouts are blocked from teaching/SFT.
- **Train:** separately review complete prompts/desired responses, including AI drafts. Queue
  a bounded LoRA job; an operator explicitly starts the local GPU worker. Compare the candidate
  with base weights on identical frozen inputs. Active weights change only by explicit selection.
- Evaluated training candidates retain their existing export path under **Advanced**.
  Both export paths run independently of QuarterMaster's database, training GPU and builder API.

Optional builder interpretation/drafting uses a configured OpenAI-compatible provider. Every
business-content request has an exact preview and explicit consent. Preview shows file/request
size and a rough token estimate. Timeout and input bounds are configurable; failures never silently
retry. Use the manual path without credentials. See [provider setup](docs/milestone-3.md) and
[limits, privacy and troubleshooting](docs/operator-guide.md).

## Storage and operation

Compose keeps SQLite and artifacts in the `quartermaster-data` named volume at `/data`.
`docker compose down` retains it; `down -v` deletes it. Back up the **whole volume with writers
stopped**, plus secrets separately, before upgrading. An adviser archive is not a project backup.
See the [operator guide](docs/operator-guide.md) for tested backup/restore steps, optional host-worker
storage, GPU prerequisites, unsupported hardware, licensing and failure recovery. Startup checks
schema compatibility and preserves versioned records; incompatible databases fail instead of being reset.

The web app has no Docker socket, ML dependencies or automatic cloud fallback. Local CPU inference,
explicit GPU training and independent export serving use separate pinned images. Application code
is Python/FastAPI, Jinja2/HTMX, SQLite FTS5 and local immutable artifacts with versioned contracts.

## Capabilities and limits

- Single trusted local owner; **no login, tenancy or TLS**. Ports bind to localhost. Remote exposure
  needs operator-provided authentication, HTTPS and reviewed proxy/origin controls.
- Adviser only: no posting, payments, messages, scheduling or changes to business records.
- Uploaded data and model completions are untrusted. Scripts/formulas are never executed.
  Prompt instructions and structural checks do not guarantee resistance to every injection.
- Citations identify accessible uploaded excerpts; exact quotes do not prove factual entailment.
  Explanations describe support, not hidden internal reasoning. Missing evidence can lead to
  clarification or abstention; the small model can still misunderstand or ask irrelevant questions.
- Reviewed examples, immutable snapshots and held-out comparisons make changes inspectable.
  Small datasets can overfit/regress. Owner preference is not factual truth or causal business lift.
- One pinned text-only Qwen model and a tested NVIDIA/WSL quick-training path. Other model families,
  CPU-only/AMD/Apple GPU training and the standard preset have not been live verified.
- Standalone use requires its exact runtime image to be obtained first. Archives contain selected
  business content; inspect privacy and redistribution rights. No offline image bundle is included.

## Development and verification

With Python 3.13 and [uv](https://docs.astral.sh/uv/):

```sh
make setup
make migrate
make test
make lint
uv run --locked uvicorn quartermaster.app:app --host 127.0.0.1 --port 8000 --no-access-log
```

`make test` uses deterministic CPU fixtures without network, cloud credentials or live models.
`make help` lists commands. Live GPU checks are opt-in and require reviewed supervision plus
explicit hardware authorization; see [M1](docs/milestone-1.md) and [M6](docs/milestone-6.md).
Real-model results and remaining owner-journey release gates are recorded separately from mocked tests.

[PLAN](PLAN.md) describes product boundaries and contracts; [TODO](TODO.md) tracks verified acceptance
criteria; [AGENTS](AGENTS.md) defines implementation rules. Help is also available in the running UI at `/help`.

QuarterMaster is an independent project and a development codename, with no exclusive branding claim.
Code uses [Apache-2.0](LICENSE). Models, source documents and third-party runtimes keep their own
licenses and distribution obligations; see [third-party notices](docs/third-party-licenses.md).
