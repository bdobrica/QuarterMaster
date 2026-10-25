# QuarterMaster — the personal decision adviser

> **Collect → Teach → Ask → Review (optional) → Teach again.**
>
> QuarterMaster lets a person teach an AI how *they* make decisions, with their own knowledge, examples and corrections. The goal is to reproduce the owner's judgment and explain recommendations in the owner's terms—not to optimize an external benchmark.

**Product target:** a small, self-hosted, nontechnical MVP that demonstrates one genuine LoRA-powered improvement loop. [TODO.md](TODO.md) is the execution checklist; [README.md](README.md) is the honest entry point.

## 1. Four things the owner does

1. **Collect.** Save web pages, files or notes. QuarterMaster uses an optional capable builder LLM to extract useful information and organize examples. The owner can inspect or fix extracted details without knowing a schema.
2. **Teach.** Review examples and explain choices: “I'd offer €165,000, because…”, “I'd take this job”, “This customer should get a higher quote.” Record their preferred number or category, relevant considerations and reusable policies. These are the owner's judgments, not labels inferred from asking prices or historical outcomes.
3. **Ask.** Present a new situation. The selected base model plus the owner's LoRA adapter uses current knowledge and approved experience to predict a number or category and explain it in familiar language. Before training, an explicitly labeled base-model preview may still be used.
4. **Review (optional).** Accept, correct or elaborate on any answer. An accepted answer is positive teaching evidence; a corrected answer is new supervision. Skipping review means **no new label**, never implicit approval. The app captures a review once and feeds it into Teach automatically.

The owner never has to manually jump back to Teach after reviewing an answer. Collect and Teach start the adviser; **Ask → Review → Improve → Ask** is the ongoing loop. *Improve* is the background machinery, not a fifth user task.

## 2. The improvement engine is the product

A review preserves: original question/input, prediction, relevant sources and knowledge version, model/adapter version, owner's accepted or corrected target, optional explanation, and time. Records and earlier answers remain inspectable.

An acceptance or correction must identify the exact judgment being taught. A note alone does not approve a prediction, and a failed answer has no prediction to accept; the owner can still supply a correction. Repeated saves must not duplicate teaching evidence. A later review revision supersedes the earlier target for future teaching selections without rewriting already frozen datasets or answers.

After a review, a small background workflow:

1. Retrieves related earlier decisions (including **before** and **after** corrections) to understand when a preference applies.
2. Proposes the smallest useful destination: **source/extraction correction**, **knowledge/policy update**, **behavior example for LoRA**, **retrieval/context adjustment**, or a combination. It can group recurring corrections into a general lesson.
3. Automatically stores the reviewed decision as reusable teaching evidence; produces readable drafts for any broader KB/routine change. The owner must be able to edit/reject inferred generalizations, especially conflicts with earlier preferences. Avoid repeatedly asking approval for the exact correction they just provided.
4. Applies allowed, reversible KB changes and refreshes retrieval. Approved behavior examples join a versioned training set; **weights change only after a bounded LoRA training run**. No hidden or billable GPU execution.
5. Compares proposed behavior with a few earlier owner-reviewed cases, displays meaningful changed answers, and allows a new model candidate to be selected or rejected. Failed changes do not erase prior versions.

The app can prepare the next training job automatically and suggest **“Your adviser has enough new examples to learn from—improve it now?”**. Training and promotion remain explicit for the MVP; a future owner-configured automatic mode can be considered after that loop is dependable.

**Two speeds:** knowledge/context can improve on the next question; the trained decision behavior improves after LoRA training. Never say “the model learned” when only retrieval or a runtime instruction changed.

## 3. Knowledge and behavior are both first class

- **Knowledge base:** original sources, extracted facts, human-authored policies, contextual notes and approved revisions. Source bytes and article history remain traceable. A person's preferences are valid policy input without external verification of whether their judgment is objectively fair or optimal.
- **Training examples:** situation/context → owner's preferred numerical or categorical target → owner's explanation. AI-drafted targets are only proposals until the owner reviews them; a source listing's *asking price* does not automatically become the owner's preferred valuation.
- **LoRA:** learns recurring decision patterns from reviewed examples. This is a deliberate product choice even when a specialized tabular model might outperform it on conventional numerical accuracy.
- **Inference:** uses a swappable language model with the specific compatible adapter and current retrieved knowledge. A base-model swap generally requires a new adapter; the portable assets are the owner's KB, decisions and correction history.

The system distinguishes **what a source said** from **what the owner believes or prefers** in its explanation. That distinction is for intelligibility and accurate attribution, not a gate preventing subjective policies from influencing predictions.

## 4. A generic decision contract

Do not bake real estate, customer support, marketing or a particular feature table into the core.

- **Input:** a situation assembled from source material and/or a user's new question, with any available structured details and cited sources.
- **Prediction:** either a **number with units** (price, duration, score, etc.) or a **category from the owner's choices**, optionally with a probability distribution.
- **Explanation:** a short owner-facing summary of relevant considerations, knowledge articles and similar reviewed choices. Identify missing information and uncertainty without dumping prompts, traces or model internals.
- **Review:** accept, change the number/category, explain why, or skip. Every reviewed result links back to the exact version that produced it.

A model-generated confidence percentage must be labeled as an estimate, **not a calibrated real-world probability** until validated for that use. Supporting examples and KB passages explain the recommendation; they do not claim to reveal hidden neural reasoning.

## 5. UI rule: ordinary language, almost zero setup

These four actions are the primary navigation: **Collect · Teach · Ask · Review**. Review has its own queue/history, not merely a feedback box under Ask. Use one primary action per screen, strong empty states, and familiar examples.

| Say to the owner | Keep in Advanced / internal code |
| --- | --- |
| **Add examples** / **Save a page** | Ingestion job, parse, chunk, schema |
| **Tell it what you'd choose** | Supervised label, SFT example |
| **Explain what matters to you** | Knowledge revision, policy/routine |
| **Improve my adviser** | LoRA recipe, adapter, GPU worker |
| **See what changed** | Evaluation suite, frozen run, diff |
| **Earlier version** / **Current version** | UUID, SHA-256, snapshot manifest |

Never require users to understand **LoRA, JSONL, epochs, SHAP, embeddings, evaluation freezing, prompt budgets, model IDs or feature engineering**. Explain necessary tradeoffs through outcomes: “Takes time and may need a compatible GPU”; “This answer used your earlier choices”; “This knowledge change is already active.” Technical details remain available for operators.

Use short, contextual questions; sensible defaults; clear saved/draft/active states; friendly recovery from failed extraction or training; and no hidden cloud use or surprise charges. A nontechnical person should succeed without watching a tutorial.

## 6. Architecture: reuse what already works

Keep FastAPI, Jinja2/HTMX, SQLite, immutable local artifacts and the existing source/knowledge/review, model, LoRA and export seams. A small builder-LLM interface may normalize saved HTML pages and draft knowledge/review proposals with disclosure and consent. Treat every uploaded page and model-generated extraction as untrusted; never run scripts inside pages.

A minimal flow is:

1. **Sources:** preserved HTML/Markdown/CSV/XLSX files and provenance.
2. **Organizer:** extract examples, suggest fields, summarize missing data; owner can correct.
3. **KB and experience store:** versioned source knowledge, policies, raw decisions, accepted/corrected supervision and related-case retrieval.
4. **Trainer:** serialize only reviewed teaching examples; exclude reserved check cases; run bounded LoRA; store a candidate adapter and its provenance.
5. **Adviser:** base model + compatible adapter + KB/context → typed answer and readable explanation.
6. **Review router:** turn feedback into KB/extraction proposals and training examples, with revision-aware replay and rollback.

No separate vector database, multi-agent runtime, general web crawler, AutoML factory or learned numeric feature pipeline is necessary for the first demo. Add complexity only when it makes **Collect → Teach → Ask → Review** easier or more dependable.

### Compatibility while replacing the old workflow

The existing foundations have constraints that must be resolved before connecting the new loop:

- **Preserve historical meaning.** Introduce compatible, versioned contracts and sequential migrations. Keep earlier advice, reviews, source bytes, datasets, model runs and exports readable and hash-verifiable. Old Pass/Fail ratings and free-text corrections are not automatically numerical/category labels or permission to train. Keep reviewed decisions and knowledge independent of the selected model; an incompatible adapter must be rejected without losing those assets.
- **Separate ordinary history from reserved checks.** Saving an ordinary question or replaying a taught example must not reserve it against teaching. Explicitly reserved evaluation cases remain protected, including existing saved check questions. Their reviews can be stored and inspected but cannot feed training, synthetic-data prompts or the improvement router's teaching context. A replay of taught cases demonstrates consistency with prior preferences; it is not unseen evaluation evidence.
- **Teach directly from owner decisions.** The current training-example path requires an applied lesson first. Replace that prerequisite for the new contracts: an explicit owner decision or eligible answer review is sufficient supervision, without approving a general rule or reentering a target. Broader inferred rules and AI-drafted targets still require review.
- **Align the product response path.** Current training/comparisons use historical `context/v2`, while ordinary Ask uses `context/v3`; candidate and base exports also have different manifest constraints. The new prediction contract must reach serialization, inference validation, candidate checks and the standalone runtime through public contracts. Verify the product prompt/schema and finite generation settings together; retain historical profiles for historical records. This work does not require further bank experiments.
- **Compare the model actually being replaced.** Candidate selection must show the currently selected adviser versus the proposed candidate with the same captured knowledge, examples, prompt and settings. Preserve a base comparison as an optional diagnostic. Keep knowledge-only replay separate so it cannot be described as a weight improvement.
- **Make automatic capture dependable and consented.** Store feedback locally even without a builder provider. Persist routing progress, recover interrupted work without duplicate examples/proposals, and keep external calls behind consent covering the actual minimized content, including related decisions. Consent to hosted advice is not consent to send review history to a builder. No automatic provider retry or GPU execution follows a saved review.

## 7. Demonstrate it with real estate; stay domain-generic

First demo: save a modest set of real estate listing pages; use an assisted extraction pass; let the owner assign several **personal fair prices and reasons**; train a small LoRA adapter; ask about an unseen property; review and correct an estimate; automatically add the new decision to Teach; retrain a candidate when enough reviewed examples exist; compare understandable old/new predictions.

Nearby transport, schools, shops, building age, maintenance concerns and other owner-selected considerations can appear in personal policies. Do not turn these into fixed real-estate fields or require a bespoke mapping/geospatial pipeline. The owner can explain why a consideration matters; the system reflects that explanation as an owner policy, not as a proven fact about people or property.

Then smoke-test a second unrelated decision type (e.g., a category choice or a custom-service quote) using the **same generic contracts**, without domain-specific code.

**MVP success:** a newcomer can collect material, teach a few judgments, obtain a typed prediction with an understandable explanation, optionally correct it, and see that review reappear automatically in the next teaching/training cycle. The app shows whether KB or weights actually changed. Owner acceptance is the measure of fit to their mental model; do not claim market accuracy, causal lift or calibrated probabilities.

## 8. Honest status and scope

Already demonstrated in the current codebase: consented hosted advice, reviewed KB edits, readable saved-question reviews, a small local LoRA training/export path and immutable comparison records. The print-shop demo established those *subsystems*, but **not** this new four-step generic personal-decision product. The old bank-model and print-shop experiments are historical implementation evidence, not the new MVP acceptance gate.

**Not now:** autonomous posting/actions, multi-user hosting, arbitrary model marketplaces, large-scale scraping, custom LightGBM/SHAP pipelines, full POI enrichment, elaborate metrics, new bank experiments or domain-specific schemas. Keep historical docs for reference without placing them in the ordinary user journey.

The guiding question for every change:

> **Does this make it easier for a busy person to teach QuarterMaster a judgment, receive an understandable decision, or turn a review into useful learning?**
