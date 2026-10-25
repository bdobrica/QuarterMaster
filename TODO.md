# QuarterMaster — MVP rescue checklist

**Work in this order.** Ship one useful, reviewable improvement loop before doing more model research. Keep changes small and the app runnable after each step. [PLAN.md](PLAN.md) is the product contract.

## P0 — Make the demo answer useful (first)

- [x] Create a **fresh synthetic print-shop demo project** with one short policy article and a plain-language mission; no CSV mapping, GPU, or external provider needed just to create it.
- [x] Save **8–12 human-reviewed cases**: clear approval, explicit hold, missing approval, missing copy, conflicting evidence, e-signature update, and two unseen near-neighbors. Keep evaluation cases out of training and AI drafting prompts.
- [x] Run the existing local model on 4 representative cases; record actual answers, citations and latency as the honest baseline. Do not tune its prompts for days.
- [x] Add a **single OpenAI-compatible adviser inference adapter** behind the existing inference interface (the external builder adapter is not yet an adviser adapter). Make a capable provider the recommended demo engine, local inference an explicit alternative; record provider/model in every run.
- [x] Require clear per-project consent for external advice, showing what business material will leave the machine; support a local-only mode, bounded input/output, sanitized errors and no silent billable retries.
- [x] Confirm the chosen engine answers the four baseline cases **usefully**, with correct sources and no unnecessary questions. If it fails, fix retrieved context or response contract once; stop expanding the system until this works.

**Gate:** A single question yields grounded, intelligible advice or one relevant missing-fact question. A provider's JSON-valid response alone does not pass.

Implementation and actual four-case hosted results: [P0 print demo](docs/print-demo.md). Ten cases are saved and held out; the owner reviewed and approved all cases and final answers on 2026-10-24. The hosted rerun produced ready / hold / approval question / copy question with valid policy citations (3.3–5.3 seconds). The pinned CPU runtime is installed and the four-case local baseline is recorded: two unnecessary questions, one relevant question without a citation, and one quote-validation failure (21.8–28.8 seconds); see [local evidence](docs/print-demo-local-baseline.json). Owner usefulness confirmation is recorded in the app and [review evidence](docs/print-demo-owner-review.json).

## P0 — Put knowledge in the driver's seat

- [x] Make **Knowledge** a primary screen: show the active articles, revisions, source text and search/retrieval results before any spreadsheet machinery.
- [x] Add plain-language **“Change our knowledge”**: builder LLM proposes a small edit to an existing Markdown article or a new article. Manual editing must also work.
- [x] Show a human-readable **before/after diff**, source attribution and the affected article. Require owner approval; rejection leaves the current KB unchanged.
- [x] On approval create a new immutable knowledge revision, reindex immediately, and display the new active version. Verify removed/superseded text cannot be retrieved as current policy.
- [x] Retest the original question **and an unseen one** using the same model/settings. Display changed retrieved excerpts and citations, not only the answer text.

Implementation and verification: [reviewed knowledge workflow](docs/knowledge-workflow.md). The owner approved the policy in the app. Four actual hosted requests show original hold → ready and fresh quote-validation failure → ready; both new-policy answers cite the retrieved replacement article. See [live replay evidence](docs/knowledge-live-replay.json). The fresh old-policy failure is preserved. The owner reviewed and approved the new answers and comparison; see [owner review](docs/knowledge-owner-review.json).

**Gate:** “Portal e-signature counts as sign-off” becomes an approved policy edit; a fresh print job changes from hold/uncertain to ready **because the new policy was retrieved**, with a valid link to it.

## P0 — Repair the owner workflow (next, before more training features)

Owner feedback on 2026-10-25: the current UI is hard to use despite the completed knowledge capability. The checked implementation milestones above remain historical evidence; the usability repair and owner approval are recorded below. Follow [PLAN.md's usability requirements](PLAN.md#usability-repair-before-more-machinery). Implement in this order, in small runnable changes:

- [x] Replace visible UUID versions with stable project-scoped semantic release labels and short change summaries. Use Knowledge v1.0.0 initially, v1.1.0 for the next approved content change; preserve internal IDs and immutable history. Cover existing projects, active/history views, saved answers and comparisons; put hashes and raw IDs in Technical details. Do not renumber history on reload or imply a quality guarantee.
- [x] Display readable local dates/times with timezone and an exact-UTC detail/fallback. Use the browser's timezone or an explicit owner setting, not the server's assumed location. Verify date boundaries and no-JavaScript fallback.
- [x] Replace “Retest original and fresh question” with **Check this change**. Explain **Try the earlier question again** versus **Try another example**, each compared Before/After using previous/current knowledge. Include a concrete example, two clearly separated pairs, source changes and the four-request/cost preview; keep the same model/settings and do not label a merely new question a training holdout.
- [x] Add consistent **Pending / Reviewed: Pass / Reviewed: Fail** controls and **Correct this answer** on all answer surfaces: ordinary tests, saved check questions, replay/evaluation comparisons, and technical/invalid-response failures. Keep technical failure separate from owner judgment. Ratings save without mandatory prose or automatic lesson creation; resetting to Pending preserves review history. Show which exact run/version was reviewed; new reruns start Pending.
- [x] Make a failed answer's correction available directly from its row/card with the original question, response/error and owner's words preserved. Keep draft → review → apply separate from rating. For protected check questions, save evaluation-only feedback without transmitting it to teaching/builder prompts; offer a separate policy edit or independently authored teaching example without copying protected material. Test rejection and leakage protection.
- [x] Add an **Improvements → Saved questions** table using existing records: question/name, expected answer/behavior, latest answer, Pending/Pass/Fail, version and local last-run time. Filter by review status; open a row to inspect sources/history and correct it. Rerun selected questions with request/cost disclosure, retain failed rows and earlier runs/reviews. No upload/mapping prerequisite.
- [x] Replace ordinary “Save as evaluation case” with **Save as check question** and explain “Check this again after changes; kept out of training.” Asking/rating does not require saving. Use **Check set** and **Use this set for comparison**; automatically capture immutable inputs on the explicit comparison action. Preserve permanent training exclusion and human review of draft expectations. Keep advanced evaluation machinery accessible.
- [x] Guide optional training with approved examples, separately reserved check questions and direct prerequisite actions. Select the existing bounded default recipe; move steps, recipe internals and manual freeze controls to Advanced. Show limits, local worker availability, explicit GPU action and manual candidate promotion. No automatic training, GPU runs or retries.
- [x] Rename/link **Advanced → Technical diagnostics** with a one-sentence purpose and a route back to the adviser. Lead with an actionable failure summary; collapse raw JSON, experimental controls, hashes and codes. Preserve archived experiments; do not expose them as the normal review dashboard.
- [x] Verify focused tests for stable labels, timezone formatting, review transitions, failure corrections, immutable reruns, consent and protected-data exclusions; run `make test` and `make lint`. Walk through the app in a real browser with a nontechnical owner: find a saved question → mark Fail → correct → approve → compare earlier/another question → mark Pass or Pending. Also check that optional training has understandable prerequisites without choosing steps or manually freezing a suite. Record remaining blockers honestly.

Implementation and verification: [owner workflow](docs/owner-workflow.md). The implementation and synthetic browser walkthrough are complete. The owner reviewed the revised app and approved it: “Yes, all good.” This is owner acceptance, not a separately observed uncoached-user study.

**Gate:** The owner can complete that flow without interpreting a UUID, UTC timestamp, “evaluation case,” “held-out suite,” or training step count. These tasks are not complete until the screens are implemented and reviewed; this document update alone passes none of them.

## P0 — One-click correction to reviewed improvement

- [ ] Put **Improve this answer** next to every Test result, **including failures/invalid JSON**. Capture the user's raw words and the original run or error.
- [ ] Have the optional builder LLM suggest **Knowledge fix** or **Behavior fix**, with one-sentence rationale and a manual override; uncertain cases require the owner's choice.
- [ ] Route knowledge fixes to article review. Route behavior fixes to a **reviewed routine** (“When X, do Y; don't do Z”) using the existing lesson machinery. Label it **runtime instruction, not trained weights**.
- [ ] Never auto-activate drafts. Show applicable cases, routine revision and where it appeared in the answer's context.
- [ ] Add a compact **before/after replay** with **helped / harmed / same / failed** and a place for the owner to correct the judgment. Include relevance of clarification questions and real support for citations.
- [ ] Keep the existing advanced **Train behavior (LoRA)** route: explicitly select approved examples, show held-out exclusions and job constraints, compare candidate against baseline on unchanged context, and offer **Promote / Reject**. Do not initiate GPU work implicitly.

**Gate:** A newcomer can issue a correction, approve the right sort of change, and verify it on another case in minutes without seeing a schema, token count or LoRA parameter.

## P0 — Simplify the front door and prove it live

- [x] Make primary navigation **Adviser / Knowledge / Improvements**. Put tables, joins, advanced training, eval setup, model diagnostics and export behind an unintrusive Advanced section.
- [ ] Make onboarding **mission → add knowledge → try a question**. Allow Markdown/plain text first; CSV/XLSX are optional and should never block asking the adviser.
- [ ] Keep answer cards short: **Advice**, **Why (cited)**, **What I still need**. Put model/KB/routine version, prompt and trace in expandable details; never call this hidden model reasoning.
- [ ] Build a deterministic demo-reset/seed command and a **90-second script**: original print job → knowledge correction/diff → new job → behavior routine → side-by-side evidence.
- [ ] Ask **one nontechnical friend** to try it without coaching. Fix the first two blockers they encounter before adding features.
- [ ] Run focused tests, `make lint`, `make test` and a real browser walk-through with the selected inference engine. Verify consent, rejection, KB replacement, source citations, correction-on-failure and no held-out leakage.

**Gate:** Clean local startup, successful new-user flow, at least one human-reviewed knowledge improvement and a correct unseen retest. Record real response latency and any external API cost; do not invent business lift.

## P1 — Keep the working machinery, lose the clutter (after the demo works)

- [ ] Cut `README.md` to **what it does / three-step startup / two-minute demo / honest limits**. Link one technical appendix for Advanced users.
- [ ] Move historical `docs/milestone-*`, bank reliability probes, decision-policy experiments and long diagnostics behind a small `docs/archive/README.md` index. Preserve evidence, URLs and git history; do not delete original research or data blindly.
- [ ] Label bank marketing **archived research fixture, not the MVP dataset**. Preserve frozen sets and negative results; do not run new bank training or mix its cases into the print demo.
- [ ] Reconcile `AGENTS.md`, Help, nav labels and any links against the new [PLAN.md](PLAN.md); remove stale milestone-as-product instructions without weakening privacy, provenance and review rules.
- [ ] Recheck the existing **standalone local export** on a fresh extracted package. Show clearly that hosted-model projects require provider connectivity and are not offline exports.
- [ ] Run the same print-shop flow on **tool rental** without domain-specific code changes.

## Explicitly parked until someone asks for it

- [ ] More bank LoRA runs, decision-classification probes and prompt/schema ablations.
- [ ] Vector DB, graph KB, automatic routines, multi-agent swarm or self-deploying changes.
- [ ] General-purpose spreadsheet AutoML, business outcome attribution, broad metrics dashboards.
- [ ] More model families, model marketplace, hosted GPU orchestration, multiuser/RBAC and business actions.

**The rule:** If an item doesn't make the next nontechnical user correction faster, clearer or safer, it is probably not MVP work.
