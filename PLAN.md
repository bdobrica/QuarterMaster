# QuarterMaster — personal adviser plan

**Collect → Teach → Ask → optional Review → automatic improvement → Teach.**

Build a small, self-hosted workshop where an ordinary person teaches an adviser their judgment. The owner provides knowledge, reviews examples, asks about new situations and optionally corrects answers. [TODO](TODO.md) is the execution checklist; [ADRs](docs/adr/README.md) preserve decisions and historical lessons.

## Owner activities

1. **Collect:** preserve material and provenance; organize reviewable examples. Assisted saved-page extraction is planned. Allow manual work without a builder provider.
2. **Teach:** record the owner's preferred number with units or category, optional reasoning and reusable policies. Source observations and AI suggestions are not approved targets. The owner's personal judgment needs no external objective benchmark.
3. **Ask:** use the selected compatible base/adapter, approved knowledge and eligible previous decisions to predict a number/category and give a short, sourced explanation. Clarification or abstention is valid when support is missing. Label base previews and uncertainty honestly.
4. **Review:** a standalone inbox/history with Accept, Correct, Add a note and Skip. Capture an explicit accepted/corrected target once and return it to teaching automatically. Notes/skips add no label; failed answers cannot be accepted but may be corrected.

Use familiar language, one primary action per screen and useful empty/error states. Model IDs, LoRA settings, datasets, diagnostics and exports belong under Advanced. Never require owners to understand model training vocabulary.

## Improvement loop

Store the exact input, prediction, sources, knowledge/model versions, owner's judgment, reasoning and time. Preserve original answers and append review revisions. Repeated saves must not duplicate evidence; revised targets supersede future selections without rewriting frozen datasets.

After review, retrieve related earlier decisions and propose the smallest useful source/extraction correction, knowledge/policy edit, behavior example or retrieval adjustment. Consult older history, surface conflicting preferences and keep broader inferred rules reviewable and reversible. Explicit feedback needs no second approval merely to be stored or reused as an eligible target.

Approved knowledge changes affect the next retrieved context. Reviewed behavior examples enter a versioned dataset; weights change only after explicit, bounded LoRA training. Preparing a job is not running it. No hidden GPU work, paid retry or automatic promotion.

Compare the proposed candidate against the currently selected adviser using identical captured context/settings. Show changed answers and allow rejection or retaining/reselecting the earlier version. Separate knowledge-only replay from weight comparisons. Replay of taught cases checks consistency with preferences, not unseen accuracy.

## Generic public contracts

- **Example:** decision-time situation, any supplied structured details and accessible source references.
- **Owner decision:** explicit reviewed target, optional explanation and lineage; distinct from asking prices, observed actions or later outcomes.
- **Prediction:** a number with units or an owner-defined category, plus explanation, sources, missing information and limitations. Any probability is model-estimated until validated for the use case.
- **Review:** acceptance/correction/note/skip linked to the exact answer, its captured context and revisions.

Keep original source bytes, content hashes, stable identities and versioned manifests. Citations must resolve to actual uploaded excerpts; identifiers and exact quotes alone do not prove an explanation's factual support. Explanations describe relevant evidence, not hidden internal reasoning.

## Architecture and compatibility

Reuse FastAPI, Jinja2/HTMX, SQLite, local artifacts, the current knowledge/review services, local inference adapter, bounded GPU trainer and portable CPU export. Do not import trainer internals into the app. Public contracts come before UI/trainer/export coupling.

| Boundary | Required transition |
| --- | --- |
| Historical storage | Sequential migrations; keep advice, ratings, sources, dataset/model/export hashes readable. Old Pass/Fail and free text are not automatically typed targets or training permission. |
| Question history | Separate ordinary saved/replayed questions from explicitly reserved checks. Preserve existing reservations; exclude their cases and corrections from training, synthetic prompts and related teaching context. |
| Supervision | An eligible owner decision/review is sufficient; remove the existing applied-lesson prerequisite and duplicate target approval. AI-drafted targets and broader inferred policies still need review. |
| Response path | Align the new target, prompt, validation and bounded generation settings across training, Ask, candidate checks and standalone runtime. Keep historical context/export profiles unchanged. |
| Model selection | Compare against the current selection, including a previous adapter. Knowledge and reviewed decisions survive model swaps; reject incompatible adapters without losing teaching assets. |
| Routing | Persist progress and recover interrupted work without duplicate proposals. Capture locally without a builder. Consent must cover the actual minimized payload, including related history; hosted-advice consent is separate. |

Treat uploads and model output as untrusted data. Never execute uploaded HTML/scripts or generated commands. Keep later outcomes out of decision inputs and protect frozen evaluation cases. No silent joins, labels, generalizations or externally changing actions.

## Demonstration and scope

Use the owner's prepared apartment material as the current demonstration: teach personal valuations and policies, ask for a new price with reasons, then review and reuse the feedback. Listing price is a separate comparison value, not automatically a valuation label. The owner confirmed discarding large price gaps in either direction; numeric thresholds remain owner policy. Do not build extraction tooling or feature design as part of documentation cleanup.

Verify both numerical and categorical contracts without restoring the retired product examples or adding domain-specific core fields. The owner chooses whether a prediction fits their judgment; that is not proof of market value, factual truth or business lift.

**MVP success:** a newcomer can collect material, teach judgments, get an understandable prediction, optionally review it and see that review reused automatically. The app distinguishes updated knowledge from trained/selected model changes. A real training run may fail to improve; retaining the previous adviser is a valid outcome.

Existing subsystem and export checks are reusable evidence, not completion of this product. No separate vector database, multi-agent runtime, model marketplace, custom tabular/SHAP pipeline, geospatial service, general crawler, multi-tenancy or cloud orchestration is needed. Keep autonomous external actions out of scope.
