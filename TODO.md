# QuarterMaster — four-step MVP TODO

**The build order is Collect → Teach → Ask → Review → automatic improvement → repeat.** See [PLAN.md](PLAN.md). Check a box only after implementation and verification. Keep the current app usable after every small change.

**Existing, reusable foundations (not completion of this new MVP):** source upload and provenance, hosted/local inference, reviewed KB edits, saved-answer review, immutable model runs, bounded LoRA training, and local export. The print-shop and bank experiments remain historical evidence.

The replacement [AGENTS.md](AGENTS.md) already describes the four activities and automatic feedback capture; the former instruction to reconcile its Teach/Test/Correct wording is obsolete. The [repository audit below](#repository-audit--2026-10-25) records additional implementation dependencies. Historical versioned contracts remain valid for old records; implement the new behavior through compatible extensions or new versions.

## P0. Establish the generic owner-decision loop

- [ ] Define versioned **Example**, **OwnerDecision**, **Prediction** and **Review** contracts (or minimal compatible extensions): numerical value + unit **or** categorical choice + estimated probabilities; source references, owner's reasoning, optional corrections and version lineage. Preserve historical advice records.
- [ ] Add migration/compatibility tests from the current populated schema (v9): preserve source/citation identities and old advice, review, dataset, candidate and export hashes. Do not reinterpret historical Pass/Fail ratings or free-text corrections as approved typed targets. Keep KB and reviewed decisions usable when retaining the base or changing a compatible model/adapter selection; reject incompatible adapters without deleting teaching assets.
- [ ] Make **Collect / Teach / Ask / Review** the only primary navigation. An optional Review is a distinct inbox/history. Put raw IDs, model controls, metrics, dataset mappings, training recipes and export under **Advanced**.
- [ ] Audit everyday screens for technical vocabulary. Replace labels with familiar language, introduce one obvious next action and useful blank states; keep keyboard/mobile accessibility.
- [ ] Make the owner goal explicit per adviser: **“Help me decide…”** and **“What kind of answer should it give—number or choice?”**. No domain-specific core schema.

**Gate:** Someone unfamiliar with AI can say what each of the four sections does without reading a glossary.

## P0. Collect — saved material becomes reviewable examples

- [ ] Accept **saved HTML pages** as well as existing Markdown/CSV/XLSX. Preserve original bytes, source URL/name and date when supplied. Sanitize HTML; never execute scripts or instructions from source content.
- [ ] Use an optional consented builder LLM to extract a concise reusable example and relevant details. Show source-linked text and a simple **Keep / Fix / Ignore** review; allow manual extraction when no provider is configured.
- [ ] Store organized examples with stable provenance, deduplication and an explicit **unconfirmed** state for uncertain extractions. Don't silently turn an ad's asking price or a historical outcome into an owner's preferred target.
- [ ] Test malformed/hostile pages, empty extraction, repeated listings and provider errors. No general scraper, mandatory geospatial service or external data purchase for MVP.

**Gate:** Save a property advertisement page, inspect an organized example, fix one extracted detail, and reuse it in Teach without editing JSON.

## P0. Teach — capture the owner's mental model and train LoRA

- [ ] Present examples one at a time. Ask **“What would you choose/offer?”** and optionally **“Why?”**; allow editing a number/category and adding general personal policies.
- [ ] Distinguish source knowledge, owner-authored policies and reviewed decisions in storage and explanation, without requiring an objective verdict on the owner's preferences.
- [ ] Convert reviewed decisions into generic supervised examples: situation + relevant source/KB context → owner's target and explanation. Remove the **applied-lesson prerequisite** for explicit owner targets and eligible reviews; no general rule or second target approval is required. Keep AI suggestions pending until reviewed; keep reserved check examples out of training.
- [ ] Reuse the existing bounded GPU trainer and adapter/export boundary for this generic target. Show **Improve my adviser** with understandable resource/time warnings and an explicit start action. Do not ask for epochs, LoRA ranks, dataset JSONL or a manually frozen evaluation suite.
- [ ] Align the new supervised response, prompt/context, validation and bounded generation profile across training, candidate evaluation and ordinary Ask. Exercise the public candidate/runtime and export-manifest boundary with CPU fixtures for both target kinds; preserve historical `context/v2` jobs and `context/v3` base exports. Full fresh-container generic export verification remains after the demo.
- [ ] Compare a new candidate with the **currently selected model**, including a previously promoted adapter, on identical captured context/settings. Keep a base comparison optional; test rejected candidates and retaining/reselecting the earlier version without changing active knowledge. Label replay of taught examples as preference consistency, not unseen accuracy.
- [ ] Verify a real end-to-end LoRA candidate on reviewed generic examples (with owner-authorized hardware); show exact before/after predictions and errors without inventing a quality improvement.

**Gate:** An owner can teach several numerical or categorical examples and request a LoRA improvement without any machine-learning configuration.

## P0. Ask — the personalized adviser answers understandably

- [ ] Accept a new situation or an organized saved example, and return a **number with unit** or a **category** in a stable typed contract. Preserve ability to clarify or abstain when information is insufficient.
- [ ] Serve the selected base model with its **compatible LoRA adapter**, relevant KB/policies and selected past examples. Clearly distinguish **not trained yet**, **new model ready** and **current model**.
- [ ] Show a brief **“Why this fits what you've taught me”** explanation with relevant policies, source passages and earlier reviewed examples. Never present hidden chain-of-thought or unsupported feature attribution as fact.
- [ ] Display uncertainty in plain language; label any numerical confidence as model-estimated until properly calibrated. Keep full traces, citations/validation, usage and revision fingerprints available in Advanced.
- [ ] Verify the same API and UI contracts on at least one numerical case and one category case; test bad output, stale adapter, missing source and conflicting knowledge.

**Gate:** A useful personal prediction and readable explanation can be obtained without selecting a pipeline or understanding model internals.

## P0. Review → Improve → Teach, automatically

- [ ] Build an independent **Review** list with **Accept / Correct / Add a note / Skip** for successful and failed Ask results. Capture the exact original answer and context. Skipping never implies approval.
- [ ] Feed accepted and corrected decisions into Teach **without a second manual copy/import/approval step**. A correction is a supervised target; accepted predictions can become positive examples when the owner explicitly accepts them.
- [ ] Separate ordinary saved/replayed questions from **explicitly reserved evaluation checks**. Preserve existing check exclusions; store their reviews without teaching from them. Filter reserved cases and their corrections from training, synthetic prompts and related-example routing. Test ordinary review → teaching, reserved review → evaluation-only, copied cases and prevention of reserving an already taught case as unseen.
- [ ] Persist review → teaching/routing transitions with duplicate prevention and restart recovery. Test repeated submissions, stale/concurrent saves, revised targets, note-only/skip actions and corrections of failed answers. Supersede earlier targets for future selection while preserving frozen datasets and historical decisions; a note alone must not silently approve a prediction.
- [ ] Implement a small improvement router using the current builder/knowledge/lesson facilities. Consult related previous examples, including older decisions beyond the current 50-record lists, and propose: extraction fix, KB/policy edit, LoRA behavior example, retrieval/context improvement, or combined changes. Prefer a reusable lesson over memorizing one instance.
- [ ] Keep local feedback capture and manual teaching usable without a builder provider. Before any router request, disclose and obtain consent for its minimized correction/related-example payload; hosted-advice consent does not authorize builder transmission. Test absent/refused/stale consent, provider errors and interrupted sends without automatic retries or lost feedback.
- [ ] Apply explicitly approved/reversible knowledge edits immediately and reindex. Automatically collect reviewed LoRA examples; prepare a candidate job when useful, but keep GPU execution and model promotion explicit for MVP.
- [ ] Detect conflicts with earlier reviews and show them in everyday terms: **“You made a different choice in a similar situation—should this rule apply only here?”** Never silently replace older judgments.
- [ ] Replay a **small set of previously reviewed questions**, preserving old/new versions and source context. Show which answers changed and let the owner accept, reject or roll back; avoid an opaque leaderboard.
- [ ] Verify regression safety: accepted/corrected/skip transitions, no evaluation-to-training leakage, source provenance, failure recovery, knowledge rollback and non-promoted LoRA candidates.

**Gate:** Review one new prediction; see the feedback appear automatically as teaching evidence, a proposed KB fix and/or a prepared LoRA improvement. After an authorized training run, compare the next prediction with the previous model. The review loop must not require navigating back to Teach.

## P0. Live, domain-generic demonstration

- [ ] Assemble a small **real-estate** demonstration from legitimately saved pages (no bespoke crawler): extracted examples, several owner-labeled fair prices and reasons, a few owner-authored policies, an unseen property and an optional correction.
- [ ] Run one real LoRA training/candidate/selection path and demonstrate that **Review becomes Teach automatically**. If the candidate isn't an improvement according to the owner, keep the prior one and show the honest result.
- [ ] Exercise a second unrelated **category or number** adviser using the same code/contracts, with no property-specific logic.
- [ ] Ask one genuinely nontechnical tester to complete the four actions without coaching. Fix their first blockers; a real browser walkthrough is required in addition to CPU tests.
- [ ] Run focused tests, `make lint`, `make test`, and the relevant real-model/training checks **only with explicit hardware/provider authorization**. Record exactly what was and wasn't verified.

**MVP done:** someone saves material, teaches personal judgments, asks for a new prediction, optionally reviews it, and sees that review correctly enter the KB and/or reviewed LoRA learning cycle—without knowing the word LoRA.

## After the demo, not before

- [ ] Reduce README and Help friction in light of the real tester's feedback; keep technical/operator instructions linked under Advanced.
- [ ] Archive the old print-shop/bank research and root [PLAN_OLD.md](PLAN_OLD.md)/[TODO_OLD.md](TODO_OLD.md) under a clear historical index, without erasing negative outcomes, current API evidence or protected datasets. Repair old milestone/owner-workflow links to replaced TODO headings; distinguish historical verification from current acceptance.
- [ ] Reconcile remaining old demo/help wording with the accepted four-step direction without erasing security or historical evidence.
- [ ] Revalidate fresh-container standalone export for the new generic prediction contract; distinguish hosted preview from offline-local packages.
- [ ] Consider automatic low-risk improvement publication and scheduled LoRA training only after staged changes, costs and rollback are understandable.

**Parked:** autonomous external actions, managed cloud training, multi-user accounts, custom LightGBM/SHAP pipelines, geospatial/POI orchestration, model marketplaces, generic web scraping, excessive metrics and further bank/print prompt experiments.

## Repository audit — 2026-10-25

Starting state: branch `main` at `03be122`, with only the owner's four replacement direction documents modified. No accepted ADR files were found. The existing UI, HTML ingestion, typed-target and automatic-improvement gaps were already in this checklist; the additions above cover dependencies found in code and tests:

| Current implementation evidence | Consequence for the new loop |
| --- | --- |
| [Review contracts](quartermaster/contracts/reviews.py), [review storage](quartermaster/answer_reviews.py) and [schema migrations](quartermaster/db/__init__.py) preserve Pass/Fail/Pending and free text, separately from teaching. | Preserve historical semantics; add explicit targets and durable review-to-teaching transitions rather than relabeling old ratings. |
| [Saved questions](quartermaster/saved_questions.py), [evaluation reservation](quartermaster/evaluations.py) and [exclusion checks](quartermaster/holdouts.py) make every saved check a holdout. [Existing tests](tests/test_owner_ui.py) require reserved reviews to create no teaching. | Ordinary history/replay needs its own path; retain the protected-check exception when routing reviews. |
| [Training examples](quartermaster/contracts/training.py) require a lesson; [example creation](quartermaster/training.py) starts from an applied lesson and separately reviewed response. | Explicit owner judgments need a direct supervision path. |
| [Evaluation snapshots](quartermaster/evaluations.py), [generation profiles](quartermaster/generation.py), [Ask](quartermaster/teaching.py) and [export contracts](quartermaster/contracts/export.py) use different historical product profiles. | A new schema alone cannot establish train/serve/export compatibility; exercise each boundary without rewriting old artifacts. |
| [Worker comparisons](quartermaster/training_worker.py) always compare the unmodified base with the candidate. | A second training cycle needs the selected previous model as its comparison, with knowledge and settings held fixed. |
| [Lesson drafting](quartermaster/teaching.py) currently uses one correction; [builder consent](quartermaster/builder.py) is separate from hosted advice. | Related-history routing needs bounded selection, durable recovery and consent for the expanded content. |

Verification: `make test` **711 passed**; `make lint` passed (140 Python files formatted). These deterministic checks establish the current implementation baseline, including old behavior that must migrate; they do not complete any new MVP checkbox. No application code changed during this audit. No live provider calls, model inference, GPU jobs, browser walkthrough or fresh-container export checks were run.

> If work doesn't help a busy owner **collect, teach, ask, review or benefit from their feedback**, it is not MVP work.
