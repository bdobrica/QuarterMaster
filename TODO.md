# QuarterMaster — MVP TODO

Build **Collect → Teach → Ask → Review → automatic improvement**. [PLAN](PLAN.md) defines behavior; [ADRs](docs/adr/README.md) preserve earlier results. Keep each change runnable; check items only after verification.

Existing foundations include source provenance, local/hosted inference, reviewed knowledge edits, answer reviews, immutable model runs, bounded LoRA and local export. Historical contracts remain valid for old records; they do not complete the new loop.

## Muster integration — 2026-10-25

- [x] Bring Muster's source, templates/assets, portable bundle tools and regression fixtures into this repo. Run Collect in the same FastAPI server with correct mounted navigation and lifecycle cleanup; no external checkout/service dependency.
- [x] Add publication discovery and verified, project-scoped, idempotent imports with complete immutable evidence/provenance copies. Preserve unfinished status; never infer teaching labels from checked source fields.
- [x] Add explicit number/unit and category owner decisions, selected decision-time inputs, append-only revisions and stale-save protection. Store a personal answer without an applied lesson or duplicate approval.
- [x] Activate published knowledge through the existing retrieval/citation path; preserve old revisions and require manual selection for conflicting imported versions.
- [x] Freeze portable reviewed teaching data with exact active knowledge and source lineage. Exclude reserved checks at target save and freeze. Keep this dataset separate from historical runnable LoRA jobs.
- [x] Add a non-destructive existing-data migration, retain the owner's prepared link fixture and editable starting policy article, document host browser requirements and the three pinned dependencies.
- [x] Connect `owner-decision/v1` and `teaching-dataset/v1` to the shared generic Prediction, bounded trainer, candidate comparison, Ask and standalone export. Do not pretend legacy `training-job/v1` accepts the new data.

Verification: `make test` passed (827 passed, 7 skipped, 2 deselected); `make lint` passed (184 formatted Python files). The opt-in integrated Chromium fixture walkthrough passed, and a built wheel includes both applications/templates/assets without local data. Local Markdown links and the imported 20-link fixture checked. Existing host data copied/verified into `data/muster`: 2 collections, 50 links, 31 captures, 13 reviews, 3 knowledge articles/revisions and 2 publications; original unchanged, cookies/credentials excluded. No real-site collection, provider/model call, GPU job, Docker build or fresh-container export check ran.

Generic connection verification: `make test` passed (859 passed, 7 skipped, 2 deselected); `make lint` passed (191 formatted Python files). The 32 prediction CPU cases cover both target kinds, public trainer loading, exact dataset download, selected-model replay, promotion/retention, three taught cases, independent knowledge changes, holdout exclusion, input/schema/citation failures, cancellation/cleanup and schema-v10 migration. A freshly extracted `export/v4` ran with fixture inference; a separate copied-runtime import check proved builder modules absent. The new `training-job/v2` uses the separately labelled `prediction-trainer`, shared `context/v4` and `prediction/v1`; historical jobs/exports retain their contracts. Local documentation links checked. No live provider/model call, GPU job, new browser walkthrough, Docker build or fresh-container export smoke test ran. Real-model quality and automatic typed review-to-teaching routing remain unchecked. See [ADR 0007](docs/adr/0007-generic-prediction-boundary.md).

## P0. Establish the generic owner-decision loop

- [ ] Define versioned **Example**, **OwnerDecision**, **Prediction** and **Review** contracts (or minimal compatible extensions): numerical value + unit **or** categorical choice + estimated probabilities; source references, owner's reasoning, optional corrections and version lineage. Preserve historical advice records.
- [ ] Add migration/compatibility tests from the current populated schema (v10, including the v9 upgrade): preserve source/citation identities and old advice, review, dataset, candidate and export hashes. Do not reinterpret historical Pass/Fail ratings or free-text corrections as approved typed targets. Keep KB and reviewed decisions usable when retaining the base or changing a compatible model/adapter selection; reject incompatible adapters without deleting teaching assets.
- [ ] Make **Collect / Teach / Ask / Review** the only primary navigation. An optional Review is a distinct inbox/history. Put raw IDs, model controls, metrics, dataset mappings, training recipes and export under **Advanced**.
- [ ] Audit everyday screens for technical vocabulary. Replace labels with familiar language, introduce one obvious next action and useful blank states; keep keyboard/mobile accessibility.
- [ ] Make the owner goal explicit per adviser: **“Help me decide…”** and **“What kind of answer should it give—number or choice?”**. No domain-specific core schema.

**Gate:** Someone unfamiliar with AI can say what each of the four sections does without reading a glossary.

## P0. Collect — saved material becomes reviewable examples

- [x] Reuse bundled Muster for links/spreadsheets → retained rendered HTML/images → accepted schema → consented extraction → review → publication. Keep original bytes, source URLs/time, unknown values, source-linked evidence and human corrections. No scripts from source content execute in the app.
- [x] Keep organized published examples typed, attributable and explicitly checked/unfinished. Keep asking prices, observed outcomes and personal teaching targets separate. Preserve manual review/recovery and knowledge editing without a provider.
- [ ] Rehearse real capture/extraction in the integrated host installation with owner-authorized provider/browser access. Imported CPU regressions and local fixture browser checks do not verify access to real sites or model quality.

**Gate:** Collect a permitted page in Muster, check one extracted detail, publish it, and reuse it in Teach without editing JSON. The local fixture path is implemented; the new installation's real-page/provider rehearsal remains open.

## P0. Teach — capture the owner's mental model and train LoRA

- [x] Present checked published examples one at a time; capture an explicit preferred number/unit or choice and optional reasoning. Add/edit general policies through Muster's knowledge manager or the adviser's Knowledge screen.
- [ ] Distinguish source knowledge, owner-authored policies and reviewed decisions in storage and explanation, without requiring an objective verdict on the owner's preferences.
- [ ] Convert reviewed decisions into generic supervised examples: situation + relevant source/KB context → owner's target and explanation. Remove the **applied-lesson prerequisite** for explicit owner targets and eligible reviews; no general rule or second target approval is required. Keep AI suggestions pending until reviewed; keep reserved check examples out of training.
- [ ] Reuse the existing bounded GPU trainer and adapter/export boundary for this generic target. Show **Improve my adviser** with understandable resource/time warnings and an explicit start action. Do not ask for epochs, LoRA ranks, dataset JSONL or a manually frozen evaluation suite.
- [x] Align the new supervised response, prompt/context, validation and bounded generation profile across training, candidate evaluation and ordinary Ask. Exercise the public candidate/runtime and export-manifest boundary with CPU fixtures for both target kinds; preserve historical `context/v2` jobs and `context/v3` base exports. Full fresh-container generic export verification remains after the demo.
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

- [ ] Use the owner's already prepared **apartment** material for the demo: reviewed personal prices/reasons, owner policies, a new apartment and optional correction. Reuse Muster for collection; keep feature design outside the integration. Do not silently label examples from listing prices or assume a numeric discard/negotiation threshold.
- [ ] Run one real LoRA training/candidate/selection path and demonstrate that **Review becomes Teach automatically**. If the candidate isn't an improvement according to the owner, keep the prior one and show the honest result.
- [ ] Verify the other target kind with a small generic contract fixture, using the same code and no property-specific logic; no additional product demo is required.
- [ ] Ask one genuinely nontechnical tester to complete the four actions without coaching. Fix their first blockers; a real browser walkthrough is required in addition to CPU tests.
- [ ] Run focused tests, `make lint`, `make test`, and the relevant real-model/training checks **only with explicit hardware/provider authorization**. Record exactly what was and wasn't verified.

**MVP done:** someone saves material, teaches personal judgments, asks for a new prediction, optionally reviews it, and sees that review correctly enter the KB and/or reviewed LoRA learning cycle—without knowing the word LoRA.

## After the demo, not before

- [ ] Reduce README and Help friction in light of the real tester's feedback; keep technical/operator instructions linked under Advanced.
- [ ] Revalidate fresh-container standalone export for the new generic prediction contract; distinguish hosted preview from offline-local packages.
- [ ] Consider automatic low-risk improvement publication and scheduled LoRA training only after staged changes, costs and rollback are understandable.

**Parked:** autonomous external actions, managed cloud training, multi-user accounts, custom LightGBM/SHAP pipelines, geospatial/POI orchestration, model marketplaces, generic web scraping, excessive metrics and further retired-domain prompt experiments.

Direct saved-HTML upload into Collect can follow the working managed-browser/manual-review path if needed; do not build a second extraction/knowledge manager beside Muster.

## Documentation cleanup — 2026-10-25

- [x] Remove obsolete roadmaps, milestone/research diaries and previous app demos; preserve durable lessons in ADRs, current operations in one guide, and regression fixtures under tests. Check links, retirement behavior and CPU gates; commit the coherent cleanup.

The earlier repository audit is reflected in the unchecked tasks above: migration compatibility, ordinary-history/check separation, direct owner supervision, train/serve/export alignment, current-model comparison, durable routing and scoped consent. Its original evidence table remains in Git at `32590b0:TODO.md`.

Verification: 39 focused retirement/review tests and all 711 CPU tests passed; `make lint` passed. Local documentation links and unchanged legacy fixture/review bytes checked. No provider calls, real model/GPU jobs, browser walkthrough or fresh-container export check ran.
