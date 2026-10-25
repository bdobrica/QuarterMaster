# QuarterMaster — MVP TODO

Build **Collect → Teach → Ask → Review → automatic improvement**. [PLAN](PLAN.md) defines behavior; [ADRs](docs/adr/README.md) preserve earlier results. Keep each change runnable; check items only after verification.

Existing foundations include source provenance, local/hosted inference, reviewed knowledge edits, answer reviews, immutable model runs, bounded LoRA and local export. Historical contracts remain valid for old records; they do not complete the new loop.

## MVP stabilization — 2026-10-25

Normal TODO implementation is paused for this pass. Existing main-branch baseline: **859 passed, 7 skipped, 2 deselected; lint passed**. The first sandbox run failed on uv's read-only cache, an environment failure; the authorized host run passed.

- [x] Make Collect / Teach / Ask / Review the primary navigation, retain technical/recovery controls under Advanced, and configure one answer type/unit/choice set per adviser. Reuse selected decision-time fields across examples.
- [x] Add saved HTML to Muster's existing capture/extraction/review pipeline without execution or a second manager. Preserve exact bytes, declared provenance and format-1 publications. Start teaching automatically publishes/imports checked adviser-bound collections and activates unambiguous knowledge; unfinished work and conflicting titles require review.
- [x] Add append-only typed Accept / Correct / Add a note / Skip reviews. Reuse accepted/corrected targets automatically in Teach, related Ask context and bounded training. Preserve exact original answers/configuration/evidence, revisions, idempotent retries, stale-save protection and restart recovery. Notes/skips create no labels; reserved cases stay excluded. Preserve historical advice/dataset/export profiles through schema-v12 migration.
- [x] Offer scoped, owner-reviewed reusable policies through the existing knowledge editor; approved knowledge affects retrieval immediately. Show differing judgments in near-duplicate situations and block ambiguous duplicate training inputs. No automatic external router calls, GPU execution or promotion.
- [x] Exercise the browser flow with **three synthetic saved apartment pages**, real configured-provider field suggestion/extraction with application consent, a corrected detail, three scripted judgments, local Ask, a corrected answer, automatic Teach evidence and a bounded improvement request. This is a scripted Chromium rehearsal, not a nontechnical usability trial or the owner's actual prepared business material.
- [x] Execute a real bounded generic GPU run on the browser-created teaching snapshot: four eligible judgments including the correction, 12 completed steps, verified nonzero adapter weights, portable conversion and four identical-context base/candidate replays. Keep the candidate unselected. Structural completion is not a quality improvement.
- [x] Compare non-thinking with 512-token bounded thinking on the same local model. Both showed invalid/unsupported/wrong answers in development probes; bounded thinking took longer without a dependable benefit. Preserve non-thinking training/inference compatibility and historical profiles; record the new response-state prompt separately in ADR 0008.
- [x] Correct the model-facing response contract and context packaging: show every response field and the configured unit/choices, separate compact case facts from runtime metadata, generate the brief explanation before its typed target, and share that order with new supervision. Preserve historical context-v4/v5 hashes, selected adapter profiles and extracted export behavior. Add a bounded local capability smoke with expected results outside prompts/training. See ADR 0009; this improves observed controls without clearing the quality gate below.
- [x] Resolve the observed **number/category generation and missing-information failures** with a verified compatible model. The pinned 4B base/context-v6 passes all twelve synthetic controls, real-browser numbers/categories, relevant clarification and automatic correction-to-teaching reuse. Preserve the original unusable 0.8B run and its unselected candidate. This closes the controlled generation blocker, not useful unseen owner advice or LoRA personalization quality. See ADR 0010.
- [ ] Rehearse with the owner's actual prepared material and an uncoached nontechnical tester. Verify useful genuinely new cases, meaningful missing-data behavior and the owner's explicit candidate acceptance/retention decision.
- [x] Run a fresh-container standalone export smoke for the new generic prompt/model. The real 4B candidate version-5 package passed isolated offline CPU Compose with no builder database/provider/GPU. Its valid abstention establishes runtime compatibility, not personalized usefulness.

Verification: focused slice checks passed (54 tests); the final `make test` gate passed (**881 passed, 7 skipped, 2 deselected**), and `make lint` passed (198 Python files). Real Chromium, configured-provider extraction and the bounded local GPU worker ran successfully as software checks. Useful numeric advice, an uncoached nontechnical trial and a fresh-container generic export did not pass/run. Local evidence is retained under ignored `data/stabilization-demo-20261025/`: database/source bytes, adapter and portable model, `browser-report.json`, `profile-comparison.json`, real screenshots and GPU log. Training run `14bd9619-6d69-4a1a-aaa8-98e604104bb8` produced unselected candidate `639d7848-2d20-4f4f-aad4-b8e5e8a0e181`. No model/source bytes or credentials belong in Git. No push is authorized.

Generation follow-up verification: `make test` passed (**905 passed, 7 skipped, 2 deselected**); `make lint` passed (201 Python files). The original 0.8B base passed 8/10 original capability controls with context-v6 versus 1/10 with context-v5. A separate pinned 2B diagnostic passed 10/12, still failing two unknown-condition/count cases. These are synthetic development controls, not owner validation or LoRA quality. No diagnostic model was selected; the full reliability gate remains unchecked. Reports and separately retained diagnostic model bytes are under ignored `data/reliability-20261025/`. Historical profile hashes, selected context-v5 adapters, source integrity and extracted export-v4 behavior are covered by CPU tests. No new GPU training or fresh-container export has been claimed by this follow-up. See [ADR 0009](docs/adr/0009-visible-prediction-contract.md).

4B follow-up — 2026-10-26: the supported pinned model passed **12/12** controls (24–44 seconds each). Chromium verified an uploaded/cited policy → 55,000 EUR, a 54,000 EUR correction → automatic Teach evidence, a new unknown repair condition → clarification without a target, Visit, and a new proposal using related personal judgments. This used synthetic development material, not an uncoached owner trial. On three identical saved browser inputs bounded thinking gave the same response states but confused a previous correction with the new case's possible prices; retain non-thinking. Timing observations include CPU contention and are not a speed benchmark.

A real 4B NF4 quick run completed twelve steps, nonzero adapter checks, safe merge/conversion and four taught-case comparisons. Candidate `bec557db-d716-4f85-b6a7-68a1fc4d69cd` abstained on all four and remains **unselected**; no weight-quality improvement is claimed. Job `9d0ab146-03be-4b95-9318-6610712130c6` and the successful fresh offline version-5 export are retained in the isolated clone under ignored `data/reliability-20261025/adviser-4b/`; existing model/source bytes and historical jobs are unchanged. See [ADR 0010](docs/adr/0010-verified-local-model.md) for pins, recipe compatibility and exact limits.

Final follow-up gates: `make test` passed (**919 passed, 7 skipped, 2 deselected**); `make lint` passed (204 Python files). The rebuilt trainer accepted the exact frozen job and local GPU in a separate finite offline preflight without another training run. The read-only candidate gateway served the real artifact after its cold-start bound was corrected. The verified 4B base is installed separately and configured on the existing local endpoint; existing advisers require the explicit Advanced switch. No candidate promotion or push occurred.

Recommended next work, before resuming the ordinary backlog:

1. Rehearse the four activities with the owner's prepared material and genuinely new cases; let the owner judge the answers and missing-data questions.
2. Inspect the small LoRA candidate's failed preference replay before any further authorized training. Improve training only against reviewed targets; compare exact before/after errors and retain the base unless useful improvement is demonstrated.
3. Run an uncoached nontechnical trial and fix its first concrete blockers. Then resume remaining migration/compatibility and review-routing tasks in their P0 order.

Owner-material follow-up — 2026-10-26:

- [x] Investigate the failed 4B preference replay before further training. A read-only real-GPU probe verified all four complete target/loss masks and the exact frozen public job. Price-token loss decreased only 1.1–2.8%; completion loss decreased 0.8–1.3%. This does not establish useful free predictions, unseen quality or a sole failure cause. No new training, model selection or historical artifact rewrite occurred. See the [investigation record](docs/operator-guide.md#investigating-the-failed-preference-replay).
- [x] Allow the generic improvement request to choose the existing bounded standard recipe, instead of always forcing twelve steps. Present the choice as training time, preserve the quick default for existing clients and keep execution/promotion separate. Focused tests passed (80); `make test` passed (**922 passed, 7 skipped, 2 deselected**); `make lint` passed. Tests verify number/category snapshots, unchanged historical job bytes, the browser form and rejection of unlimited/arbitrary settings. This change alone makes no training-quality claim.
- [x] Preserve an actionable timeout when the outer prediction deadline wins before the local adapter wraps it. Heavy owner-material requests exceeded the bound under concurrent GPU work; they were incorrectly labelled invalid answers. Number/category regression tests retain the exact input in Review and show an actionable timeout. `make test` passed (**924 passed, 7 skipped, 2 deselected**); `make lint` passed. This fixes error classification, not model quality or runtime speed.
- [ ] Rehearse with actual imported apartment material and three owner-supplied EUR judgments/reasons. The owner authorized choosing the listings and restated their directional policies; those policies do not supply numerical price targets. Preserve source claims separately from subjective assumptions and keep a different listing for the new-case question.
- [ ] Run the owner-requested **agent-simulated workflow check** with these targets, review/correction reuse and a bounded improvement request. The owner deferred their UI inspection. Keep the separate uncoached human-trial criterion open; an agent simulation cannot verify it.
- [ ] After the judgments are available, verify a bounded improvement against the captured current selection, exact owner-target errors, meaningful missing facts and genuinely new cases. Retain the base unless the owner explicitly selects a useful candidate; policy/retrieval effects are not LoRA quality gains.

Follow-up baseline: `make test` passed (**919 passed, 7 skipped, 2 deselected**); `make lint` passed (204 Python files). The first sandbox invocation hit uv's read-only cache; the authorized host run passed. A verified private rehearsal copy is under ignored `data/rehearsal-20261026/owner/`; original collection bytes/publications remain unchanged. Diagnostic evidence is under `data/rehearsal-20261026/lora-investigation/`. No new training run or human trial is claimed.

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

- [x] Define versioned **Example**, **OwnerDecision**, **Prediction** and **Review** contracts (or minimal compatible extensions): numerical value + unit **or** categorical choice + estimated probabilities; source references, owner's reasoning, optional corrections and version lineage. Preserve historical advice records.
- [ ] Add migration/compatibility tests from the current populated schema (v10, including the v9 upgrade): preserve source/citation identities and old advice, review, dataset, candidate and export hashes. Do not reinterpret historical Pass/Fail ratings or free-text corrections as approved typed targets. Keep KB and reviewed decisions usable when retaining the base or changing a compatible model/adapter selection; reject incompatible adapters without deleting teaching assets.
- [x] Make **Collect / Teach / Ask / Review** the only primary navigation. An optional Review is a distinct inbox/history. Put raw IDs, model controls, metrics, dataset mappings, training recipes and export under **Advanced**.
- [ ] Audit everyday screens for technical vocabulary. Replace labels with familiar language, introduce one obvious next action and useful blank states; keep keyboard/mobile accessibility.
- [x] Make the owner goal explicit per adviser: **“Help me decide…”** and **“What kind of answer should it give—number or choice?”**. No domain-specific core schema.

**Gate:** Someone unfamiliar with AI can say what each of the four sections does without reading a glossary.

## P0. Collect — saved material becomes reviewable examples

- [x] Reuse bundled Muster for links/spreadsheets → retained rendered HTML/images → accepted schema → consented extraction → review → publication. Keep original bytes, source URLs/time, unknown values, source-linked evidence and human corrections. No scripts from source content execute in the app.
- [x] Keep organized published examples typed, attributable and explicitly checked/unfinished. Keep asking prices, observed outcomes and personal teaching targets separate. Preserve manual review/recovery and knowledge editing without a provider.
- [ ] Rehearse real capture/extraction in the integrated host installation with owner-authorized provider/browser access. Imported CPU regressions and local fixture browser checks do not verify access to real sites or model quality.

**Gate:** Collect a permitted page in Muster, check one extracted detail, publish it, and reuse it in Teach without editing JSON. The local fixture path is implemented; the new installation's real-page/provider rehearsal remains open.

## P0. Teach — capture the owner's mental model and train LoRA

- [x] Present checked published examples one at a time; capture an explicit preferred number/unit or choice and optional reasoning. Add/edit general policies through Muster's knowledge manager or the adviser's Knowledge screen.
- [ ] Distinguish source knowledge, owner-authored policies and reviewed decisions in storage and explanation, without requiring an objective verdict on the owner's preferences.
- [x] Convert reviewed decisions into generic supervised examples: situation + relevant source/KB context → owner's target and explanation. Remove the **applied-lesson prerequisite** for explicit owner targets and eligible reviews; no general rule or second target approval is required. Keep AI suggestions pending until reviewed; keep reserved check examples out of training.
- [x] Reuse the existing bounded GPU trainer and adapter/export boundary for this generic target. Show **Improve my adviser** with understandable resource/time warnings and an explicit start action. Do not ask for epochs, LoRA ranks, dataset JSONL or a manually frozen evaluation suite.
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

- [x] Build an independent **Review** list with **Accept / Correct / Add a note / Skip** for successful and failed Ask results. Capture the exact original answer and context. Skipping never implies approval.
- [x] Feed accepted and corrected decisions into Teach **without a second manual copy/import/approval step**. A correction is a supervised target; accepted predictions can become positive examples when the owner explicitly accepts them.
- [ ] Separate ordinary saved/replayed questions from **explicitly reserved evaluation checks**. Preserve existing check exclusions; store their reviews without teaching from them. Filter reserved cases and their corrections from training, synthetic prompts and related-example routing. Test ordinary review → teaching, reserved review → evaluation-only, copied cases and prevention of reserving an already taught case as unseen.
- [x] Persist review → teaching/routing transitions with duplicate prevention and restart recovery. Test repeated submissions, stale/concurrent saves, revised targets, note-only/skip actions and corrections of failed answers. Supersede earlier targets for future selection while preserving frozen datasets and historical decisions; a note alone must not silently approve a prediction.
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
- [ ] Run focused tests, `make lint`, `make test`, relevant local real-model/GPU/training checks and bounded provider API checks with non-sensitive development data without separate task authorization. Provisioning cloud GPU/compute jobs requires task authorization and a reviewed command. Preserve application consent and data-minimization safeguards for users' business content. Record exactly what was and wasn't verified.

**MVP done:** someone saves material, teaches personal judgments, asks for a new prediction, optionally reviews it, and sees that review correctly enter the KB and/or reviewed LoRA learning cycle—without knowing the word LoRA.

## After the demo, not before

- [ ] Reduce README and Help friction in light of the real tester's feedback; keep technical/operator instructions linked under Advanced.
- [x] Revalidate fresh-container standalone export for the new generic prediction contract; distinguish hosted preview from offline-local packages. The 4B version-5 runtime passed; second-machine operation remains unverified.
- [ ] Consider automatic low-risk improvement publication and scheduled LoRA training only after staged changes, costs and rollback are understandable.

**Parked:** autonomous external actions, managed cloud training, multi-user accounts, custom LightGBM/SHAP pipelines, geospatial/POI orchestration, model marketplaces, generic web scraping, excessive metrics and further retired-domain prompt experiments.

Saved-HTML upload now reuses the existing extraction/knowledge manager. It is a text-only capture; original files remain downloadable as data.

## Documentation cleanup — 2026-10-25

- [x] Remove obsolete roadmaps, milestone/research diaries and previous app demos; preserve durable lessons in ADRs, current operations in one guide, and regression fixtures under tests. Check links, retirement behavior and CPU gates; commit the coherent cleanup.

The earlier repository audit is reflected in the unchecked tasks above: migration compatibility, ordinary-history/check separation, direct owner supervision, train/serve/export alignment, current-model comparison, durable routing and scoped consent. Its original evidence table remains in Git at `32590b0:TODO.md`.

Verification: 39 focused retirement/review tests and all 711 CPU tests passed; `make lint` passed. Local documentation links and unchanged legacy fixture/review bytes checked. No provider calls, real model/GPU jobs, browser walkthrough or fresh-container export check ran.
