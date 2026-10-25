# QuarterMaster

**Teach an AI how you personally make decisions.** Collect examples, explain what you would choose, ask about a new situation, and optionally review the answer. QuarterMaster turns your feedback into useful knowledge and reviewed examples for improving a fine-tuned adviser.

The product experience has **four simple activities**:

| | What you do |
| --- | --- |
| **1. Collect** | Save pages, documents and notes. QuarterMaster helps organize them. |
| **2. Teach** | Say what you would choose, estimate or recommend—and why. |
| **3. Ask** | Get a number or a choice, with an explanation based on what you've taught it. |
| **4. Review (optional)** | Accept an answer, correct it or add a note. QuarterMaster feeds that experience back into teaching automatically. |

**Review is a full part of the product**, not an afterthought. Approved knowledge can change immediately; reviewed decision examples accumulate for LoRA training. The app should handle those mechanics without asking ordinary people to learn machine-learning vocabulary.

The first practical example will use saved real-estate advertisements and personal valuations; the same system must also work for other number or category decisions, such as choosing a job or pricing a service. **The owner's judgment is the teaching target**, not a supposedly universal “correct” decision.

## Project status

<em>This is an actively changing development prototype, not a released personal-decision product.</em>

The current repository **already has** working foundations for document upload/provenance, local and consented hosted advice, reviewed knowledge edits, saved questions and answer reviews, a bounded local LoRA trainer, comparisons, and standalone local export. A print-shop demonstration verified several of these components. Earlier bank and print experiments are preserved as research records.

The **new four-step experience and its complete Review → Improve → Teach → LoRA loop are not yet implemented together**. In particular, generic numerical/category predictions from owner decisions, saved-page extraction, automatic review routing and the streamlined Collect/Teach/Ask/Review UI remain in [TODO.md](TODO.md). Do not mistake the existing synthetic print-proof demo for proof of personalized model learning.

See [PLAN.md](PLAN.md) for the product contract and [TODO.md](TODO.md) for the prioritized work.

## Run the current development build

You need Docker Engine and Docker Compose v2. From the repository:

```sh
cp .env.example .env
docker compose up -d --build --wait
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). The current project/knowledge UI does not require a GPU or API key to start. Initial dependency/container builds require internet access. It is a trusted, localhost-only single-user prototype, not a remotely secured service.

To try the **existing** synthetic print-proof demonstration, install Python 3.13 and `uv`, run `make setup` and `make demo`, then follow [the current demo instructions](docs/print-demo.md). That is a technical starting point while the new generic example/teaching experience is built.

To request actual model advice:

- **Hosted inference:** configure a compatible provider using the variables in [.env.example](.env.example), then explicitly consent in the project UI before sending any business content. See [provider behavior and limits](docs/print-demo.md). No external fallback happens silently.
- **Local inference:** run `make model-setup`, configure the printed model fingerprint and local inference URL, then use the advice Compose profile documented in [local model setup](docs/milestone-4.md). The pinned small model can be slow on CPU and its previous advice quality was limited.
- **Training:** the existing LoRA workflow needs compatible GPU hardware and an explicit operator-run job. Historical GPU/export smoke tests establish a technical path, **not** that a personally trained adviser already makes better judgments. See [training](docs/milestone-6.md) and [export](docs/milestone-7.md).

## How improvement is meant to work

1. Each owner-reviewed answer is recorded with the original situation, prediction, correction or acceptance, notes, knowledge and model version.
2. QuarterMaster looks at related previous examples and prepares the smallest useful change: fix an extraction, update knowledge or policy, add a LoRA teaching example, or refine what context is retrieved.
3. Reviewed corrections become teaching evidence **without being copied by hand**. Broader AI-drafted rules stay understandable and reviewable; incompatible earlier preferences are surfaced rather than silently overwritten.
4. New knowledge can be used on the next question. A LoRA adapter changes model behavior only after an explicit bounded training run; the owner can compare and choose the new version or keep the old one.

The owner sees ordinary status messages like **“Saved your correction”**, **“Updated your knowledge”**, and **“New adviser version ready to try.”** Model parameters, IDs and technical diagnostics belong under Advanced. The intended primary navigation is **Collect · Teach · Ask · Review**; the current UI has not yet fully migrated.

## Development

With Python 3.13 and [uv](https://docs.astral.sh/uv/):

```sh
make setup
make migrate
make test
make lint
uv run --locked uvicorn quartermaster.app:app --host 127.0.0.1 --port 8000 --no-access-log
```

CPU tests use deterministic fixtures without credentials or a GPU. Real provider requests and GPU jobs are opt-in; do not imply they ran merely because mocked tests pass.

The existing implementation uses Python/FastAPI, Jinja2/HTMX, SQLite full-text search, immutable local artifacts, an optional OpenAI-compatible builder/adviser provider, local llama.cpp inference and a separately operated LoRA trainer. The current local export path can run independently of QuarterMaster once its model/runtime image is obtained; hosted-provider advisers are **not** offline exports.

## Important limits

- QuarterMaster gives **advice**, not autonomous business actions. It does not send messages, post, buy, schedule or modify outside accounts.
- Original source material, extracted content and model responses can be incorrect or malicious. Pages are treated as data, not executable instructions. The owner must check important details.
- Explanations can cite available sources, owner policies and earlier reviewed choices. They do **not** reveal the model's hidden internal reasoning or guarantee factual support merely by showing a citation.
- A confidence percentage from a model is not automatically a calibrated probability. Tiny training sets can overfit or fail to improve behavior.
- External model calls require an explicit choice and may transmit business content. Keep credentials out of logs and exports. Back up the persistent `quartermaster-data` volume before risky upgrades; `docker compose down -v` deletes it.
- Local ports have no built-in login/TLS. Exposing the app publicly requires operator-provided protection. The base model, third-party libraries and user documents have their own licenses.

See [operator guidance](docs/operator-guide.md), [third-party notices](docs/third-party-licenses.md), and [AGENTS.md](AGENTS.md) for engineering invariants. QuarterMaster is a development codename; project code is [Apache-2.0](LICENSE).
