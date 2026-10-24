# QuarterMaster — Implementation TODO

**Status:** Milestones 0–7 locally verified; Milestone 8 usability/safety implementation and local checks completed. Full owner-journey release acceptance and the MVP tag remain pending. Real-model limitations are recorded without a quality-gain claim.

**Scope:** first self-hosted teachable-adviser MVP (`0.1.0`).  
**Design authority:** [PLAN.md](PLAN.md); implementation rules: [AGENTS.md](AGENTS.md).

Each checkbox should be small enough for one focused change and a meaningful verification step. Each milestone must leave the application in a runnable state. Keep completed items checked; do not mark a task complete until its acceptance check actually passes. GPU and real-provider checks are explicitly opt-in.

## Milestone 0 — Repository and local application skeleton

- [x] Create the standalone QuarterMaster repository (do not copy KitchenSoup application code).
- [x] Add an explicit open-source `LICENSE` and third-party model-license notes.
- [x] Add `pyproject.toml` with pinned Python support and runtime dependencies.
- [x] Add a `.gitignore` that excludes data volumes, uploads, checkpoints, keys and generated models.
- [x] Add `.env.example` with builder-provider settings and data directory configuration.
- [x] Add `.editorconfig` and configure Ruff.
- [x] Add pytest with a CPU-only default test selection.
- [x] Add a minimal FastAPI app with `GET /healthz`.
- [x] Add a Jinja2 base layout and initial project landing page.
- [x] Add HTMX UI dependency without a Node build step.
- [x] Add a minimal settings loader with safe defaults.
- [x] Add local filesystem artifact-root initialization.
- [x] Add SQLite connection and startup schema/version check.
- [x] Add `compose.yaml` with the web service and persistent data volume.
- [x] Bind the default published port to localhost.
- [x] Add `make help`, `make setup`, `make fmt`, `make lint` and `make test`.
- [x] Add `make up`, `make down`, `make logs` and `make migrate`.
- [x] Add CI for lint and CPU-only tests.
- [x] Add a fixture-driven smoke check for project creation.

**Acceptance criteria**

- [x] `docker compose up -d` starts a healthy UI with persistent SQLite and file storage.
- [x] `make test` passes without GPU, cloud credentials or live model API calls.
- [x] No KitchenSoup, ThinkPixelSR or SecondContext service is required.

Verification: [Milestone 0 record](docs/milestone-0.md).

---

## Milestone 1 — Early model-to-export feasibility spike (critical path)

- [x] Select one small open-weight Qwen text model; record exact upstream revision and license.
- [x] Verify text-only inference on the selected model and record minimum hardware tested.
- [x] Create a tiny reviewed `Case` → `Advice` SFT fixture with clarification behavior.
- [x] Pin a trainer image containing Transformers, TRL, PEFT and required GPU dependencies.
- [x] Run one bounded LoRA training job against the fixture on supported hardware.
- [x] Verify generated adapter metadata, expected files and output hashes.
- [x] Compare unmodified model and adapter behavior on a separate tiny fixture.
- [x] Spike LoRA merge or direct-adapter runtime compatibility.
- [x] Convert/export to the chosen GGUF/runtime representation.
- [x] Run the exported model in a fresh isolated llama.cpp-based container.
- [x] Validate constrained `Advice` JSON for one normal and one missing-information case.
- [x] Measure approximate CPU inference latency and artifact size.
- [x] Document the exact successful versions and unsupported configurations.
- [x] Add an opt-in `make test-gpu` target for the reproducible spike.
- [x] Record a fallback decision if the initially selected model cannot be exported safely.

**Acceptance criteria**

- [x] A real, fine-tuned adapter can be served independently of the trainer and builder.
- [x] The runtime can produce a valid advice response and ask a clarification question.
- [x] A failed conversion/export is detected, not silently reported as successful.

Implementation and verification: [Milestone 1 record](docs/milestone-1.md).

---

## Milestone 2 — Project, uploads and knowledge foundation

- [x] Define and validate `quartermaster.adviser/v1` project/adviser schema.
- [x] Implement project creation, listing, opening and renaming.
- [x] Add a mission textbox and optional business-goal field.
- [x] Persist the mission and all revisions with timestamps.
- [x] Add CSRF-safe upload actions and server-side file-size limits.
- [x] Store original uploads immutably under content hashes.
- [x] Reject unsupported file extensions and invalid content.
- [x] Parse CSV using explicit delimiter/encoding handling.
- [x] Parse XLSX worksheets without executing formulas/macros.
- [x] Parse Markdown and preserve headings and source positions.
- [x] Show spreadsheet sheet names, field names, row counts and sample rows.
- [x] Show missing-value and likely type/date summaries without rewriting input.
- [x] Let the owner label a source as observations, examples or knowledge.
- [x] Add a user-confirmed case-grain selector (one row/post/invoice/etc.).
- [x] Require explicit join keys before combining spreadsheet sources.
- [x] Identify candidate target/outcome columns and decision-time input columns.
- [x] Warn when a selected input looks unavailable at the proposed decision time.
- [x] Implement canonical case serialization from a reviewed field mapping.
- [x] Preserve source ID, sheet/row and field mapping in every derived case.
- [x] Chunk Markdown using heading-aware boundaries and bounded length.
- [x] Build a per-project SQLite FTS5 knowledge index.
- [x] Retrieve ranked chunks with stable citation/source identifiers.
- [x] Add source-replacement/reindex behavior via a new immutable knowledge revision.
- [x] Add parser and provenance tests with malformed files and hostile filenames.

**Acceptance criteria**

- [x] A project accepts multiple CSV/XLSX/MD uploads and previews them correctly.
- [x] Owner-confirmed mappings produce deterministic, provenance-linked cases.
- [x] A citation points to the actual uploaded source; removing a source from a revision removes its retrieval results.

Implementation and verification: [Milestone 2 record](docs/milestone-2.md).

---

## Milestone 3 — Guided business-problem interview

- [x] Define a small `BuilderLLM` protocol for structured responses.
- [x] Implement one OpenAI-compatible provider with configured model/base URL.
- [x] Store API credentials only as environment/secret-file references.
- [x] Add provider test/health action with bounded timeout and error copy.
- [x] Display external-data disclosure and capture explicit owner consent before sending source excerpts.
- [x] Implement interview state for mission, goal, available choices and target behavior.
- [x] Include source/schema summaries, not entire spreadsheets, in ordinary interview context.
- [x] Ask the owner what constitutes a historical case and what is known before advice.
- [x] Ask how business success or harm would be observed, where relevant.
- [x] Allow the owner to answer, edit or reject a builder interpretation.
- [x] Produce a proposed `AdviserSpec` for review before saving.
- [x] Add a visible `needs_examples` state for data without supervised advice.
- [x] Implement provider retry/invalid-JSON handling without losing interview state.
- [x] Create deterministic fake-provider fixtures for interviews and error cases.

**Acceptance criteria**

- [x] The owner can define an adviser through a short conversation and inspect/edit the resulting spec.
- [x] Unlabeled historical rows are never silently converted into ground-truth ideal advice.
- [x] The guided flow works in mocked offline tests.

Implementation and verification: [Milestone 3 record](docs/milestone-3.md).

---

## Milestone 4 — Test screen, context adviser and immediate lessons

- [x] Define versioned `Case`, `Advice`, `Lesson` and `Feedback` schemas.
- [x] Implement local inference adapter for the pinned base model.
- [x] Implement a bounded prompt/context assembler for mission, case, retrieved knowledge and approved lessons.
- [x] Ensure source excerpts are marked as untrusted content, not instructions.
- [x] Require structured `Advice` output with recommendation, explanation, citations and optional question.
- [x] Validate JSON output and reject unsupported fields/types.
- [x] Validate that cited IDs actually exist in the retrieved evidence.
- [x] Preserve case, knowledge revision, model and output with each test response.
- [x] Add the Test UI with a plain-language situation field.
- [x] Render recommendations, citations, uncertainties and clarification questions separately.
- [x] Add user feedback options: good, wrong call, missing knowledge, should ask, weak explanation.
- [x] Save the raw owner correction unchanged.
- [x] Use the builder provider to draft an explicit reusable lesson from the correction.
- [x] Show the proposed lesson and require owner approval/edit/rejection.
- [x] Keep lessons append-only and link them to their original cases.
- [x] Apply an approved lesson to the next inference through context retrieval.
- [x] Show in the UI that this improvement is **context**, not a weight update.
- [x] Add a “similar but unseen situation” fixture for generalization testing.
- [x] Add regression tests for nonexistent citations and unsupported decisive statements.

**Acceptance criteria**

- [x] The complete baseline → correction → reviewed lesson → retest loop works without a training job.
- [x] An unreviewed lesson never modifies active advice.
- [x] The adviser can ask for missing evidence instead of making an unsupported judgment.

Implementation and verification: [Milestone 4 record](docs/milestone-4.md). The real CPU model
asked for missing damage status but over-asked on a complete case; the recorded rubric miss is
a quality limitation, not a claimed improvement. The full reviewed-lesson loop is verified with
deterministic providers; real-model generalization remains unproven.

---

## Milestone 5 — Frozen evaluations and comparison

- [x] Define immutable `EvaluationSuite` and `EvaluationRun` contracts.
- [x] Add a UI to save a Test situation as an evaluation case.
- [x] Let the owner specify expected behavior or a small rubric per case.
- [x] Mark evaluation examples as held out from training selection.
- [x] Freeze suite membership, revision and source hashes before training.
- [x] Run the same suite against base-only and base-plus-context variants.
- [x] Persist model/prompt/knowledge/lesson revision per output.
- [x] Show side-by-side advice with citations and questions.
- [x] Add human ratings `A better`, `B better`, `same`, `both bad`.
- [x] Add structured feedback category and free-text rationale per comparison.
- [x] Add deterministic checks for schema validity and citation integrity.
- [x] Add rubric check for expected clarification versus unsupported recommendation.
- [x] Display improved, regressed and unreviewed counts separately.
- [x] Keep recorded business outcomes separate from human preference ratings.
- [x] Prevent held-out cases from being promoted into training examples accidentally.
- [x] Add fixtures proving that a changed knowledge set is not credited as training improvement.

**Acceptance criteria**

- [x] A frozen suite produces reproducible inputs and comparable saved outputs.
- [x] The owner can identify regressions and retain an earlier version.
- [x] Evaluation does not claim causal business lift from user preference alone.

Implementation and verification: [Milestone 5 record](docs/milestone-5.md). Frozen A/B inputs,
holdout protection, separate preference ratings and regression counts are verified. Real CPU
outputs remained structurally valid but over-asked or asked about irrelevant facts; the full
synthetic rubric was not satisfied. No weight or business-lift improvement is claimed.

---

## Milestone 6 — Reviewed examples and real LoRA training

- [x] Define versioned `TrainingExample`, `TrainingRun` and artifact-manifest schemas.
- [x] Add UI to promote an approved correction into a supervised example.
- [x] Offer builder-drafted examples with clearly marked `AI_DRAFT` provenance.
- [x] Require human approval before an AI-drafted example enters SFT data.
- [x] Show full training prompt and target response for each selected example.
- [x] Deduplicate exact and near-duplicate training cases.
- [x] Enforce locked evaluation suite exclusion before dataset freeze.
- [x] Snapshot selected source, lesson, base model and recipe revisions.
- [x] Implement train-data JSONL serialization with stable order and IDs.
- [x] Add data sufficiency warning instead of implying that five examples ensure quality.
- [x] Define one bounded `quick` LoRA preset and one `standard` preset.
- [x] Add GPU capability preflight, disk estimate and user-visible resource warning.
- [x] Implement persisted single-job queue without a distributed queue service.
- [x] Start the pinned trainer container with scoped mounts and explicit GPU opt-in.
- [x] Record status transitions, bounded logs, failure code and cancellation intent.
- [x] Detect interrupted runs after application restart without automatic billable retry.
- [x] Verify adapter files, hashes, base revision and training manifest on completion.
- [x] Register a new immutable **candidate** adviser version.
- [x] Run a smoke inference and selected frozen evaluation suite on that candidate.
- [x] Require explicit owner promotion; never auto-replace the active version.
- [x] Mock trainer transitions and failure recovery in CPU-only tests.
- [x] Run live `make test-gpu` on a reviewed synthetic fixture.

**Acceptance criteria**

- [x] An owner can train from reviewed lessons without writing JSONL or Python.
- [x] Base and fine-tuned models remain distinct; artifact lineage is inspectable.
- [x] A canceled/failed training job cannot be mistaken for a deployable model.

Implementation and verification: [Milestone 6 record](docs/milestone-6.md). After explicit owner approval, one bounded 12-step WSL GPU run completed through the application workflow, verified/converted the adapter and compared the real candidate on identical frozen inputs. The candidate remains unpromoted. Both models missed the complete-case rubric and over-asked on the incomplete case; this verifies the workflow and shows no quality gain.

---

## Milestone 7 — Standalone adviser export

- [x] Define versioned `ExportManifest` with model, source, knowledge and runtime fingerprints.
- [x] Create one standard runtime application independent of the builder database.
- [x] Implement runtime `GET /healthz`.
- [x] Implement runtime `POST /v1/advise` with validated `Advice` response.
- [x] Add a minimal standalone browser interface for entering a case and reading advice.
- [x] Load selected `AdviserSpec`, approved lessons and knowledge index at runtime.
- [x] Implement the verified LoRA merge/convert/quantization path from Milestone 1.
- [x] Check model format compatibility before packaging.
- [x] Include copied model and knowledge bytes with hashes in the export.
- [x] Generate `compose.yaml` with a pinned runtime image version.
- [x] Generate an operator README with CPU/RAM/disk requirements and localhost endpoint.
- [x] Package output as a downloadable archive with deterministic paths.
- [x] Exclude builder credentials, raw owner secrets and unselected sources.
- [x] Extract an export into a fresh temporary directory for validation.
- [x] Start its runtime in an isolated Compose environment.
- [x] Query a reference advice case and verify response schema and citations.
- [x] Verify the exported runtime makes no builder/frontier-provider calls for core advice.
- [x] Surface clear errors for missing image, incompatible model or corrupt artifact.
- [x] Add `make test-export` for the integration smoke.

**Acceptance criteria**

- [x] A chosen fine-tuned adviser runs without a QuarterMaster container or database.
- [x] The exported package can be started using documented Docker Compose commands.
- [x] The model, lesson and knowledge versions match the selected evaluated candidate.

Implementation and verification: [Milestone 7 record](docs/milestone-7.md).
After the separate M1-based fixture check, a real newly trained M6 candidate was
exported through the app API and served from a fresh offline Compose extraction.
Model and frozen context fingerprints matched; no builder, database, frontier API
or GPU was available to the exported runtime. The evaluated knowledge/lesson snapshot
was empty by design and was preserved. The candidate remains unpromoted; no quality
gain is claimed. Documented localhost startup was also tested with the M1 runtime fixture.

---

## Milestone 8 — Usability, safety and release polish

- [x] Add helpful blank/empty state on each of the five tabs.
- [x] Add a sample mission and small synthetic data/docs fixture with explicit labeling.
- [x] Add one second-domain synthetic demo proving no domain-specific code edits.
- [x] Show source size, token estimate and external-provider disclosure before large build calls.
- [x] Add per-provider timeout and maximum-input protections.
- [x] Ensure no uploaded text or API keys appear in ordinary logs.
- [x] Add prompt-injection regression fixtures for malicious Markdown cells.
- [x] Add path traversal and archive extraction regression tests.
- [x] Confirm locally scoped port exposure and document reverse-proxy security limitations.
- [x] Add project export/backup guidance for the persistent data volume.
- [x] Document local GPU prerequisites, unsupported hardware and approximate model footprint.
- [x] Document source upload, knowledge revision and example-review behavior.
- [x] Document LoRA model licensing and distribution constraints.
- [x] Document contextual improvement versus weight training clearly in the UI.
- [x] Add a small troubleshooting section for API, training and model-export failures.
- [x] Add an honest capability/limitation section to README.
- [x] Run full CPU test, lint and Compose boot checks from clean state.
- [x] Run opt-in real GPU and standalone export validation; record hardware/results (retain the unchanged owner-approved M6 GPU run; recheck export during M8).
- [x] Review README, PLAN, TODO and AGENTS for consistency with actual shipped behavior.
- [ ] Tag an MVP only after release gate passes.

**Acceptance criteria**

- [ ] A new user can follow README from a clean environment.
- [x] Both demonstration domains work using the same contracts.
- [x] The shipped UI never claims an unverified training, export or business improvement.

Implementation and verification: [Milestone 8 record](docs/milestone-8.md); operation, privacy, hardware and recovery: [operator guide](docs/operator-guide.md). Clean-volume startup, backup/restore and the same public workflow across three synthetic domains are verified. Real CPU advice still over-asks and one print-domain retest failed JSON validation. The earlier explicitly approved M6 GPU run is retained as hardware evidence; no new GPU run or supervision approval is implied. Fresh standalone export validation is recorded separately. The full human owner journey below has not passed as one clean-install session; no MVP tag is created.

---

## Inference reliability follow-up — before another bank LoRA attempt

The owner review prioritizes inference design over another GPU run. Keep the base
weights active and the failed job/artifacts intact. This development comparison is
separate from the protected frozen suite and creates no training supervision.

- [x] Implement and verify an opt-in compact `quartermaster.advice/v2` contract while preserving v1 replay/export.
- [x] Implement owner-configured integer/category field rules with exact source attribution and explicit review confirmation.
- [x] Capture controlled current-v1 / compact-v2 / interpreted-v2 base-model comparisons with durable outputs and usage measurements.
- [x] Keep factual quality, clarification relevance, unsupported assertions, citation relevance and usefulness separate from output validity.
- [x] Run independent development probes and record semantic failures as well as completions.
- [x] Add an opt-in lesson-only ablation with explicit relevant/irrelevant selections, exact revisions, and unchanged interpreted-v2 generation; refuse silently omitted or unapplied lessons.
- [x] Report missing citations separately from accessible supplied citations and expose sentence-ending diagnostics without claiming complete prose.
- [x] Add separate read-only structured assertion checks against captured field states, typed values, units and definition citations; explicitly leave adviser prose unchecked.
- [x] Run a new-development lesson ablation and record technical findings separately from owner ratings: 16/16 schema-valid, zero citations, all clarify; no configuration accepted for normal advice.
- [ ] Obtain owner quality review of the lesson ablation; automatic formatting checks and operator observations do not replace it.
- [ ] Integrate model-generated structured claims and complete short explanations in a separate controlled experiment before claiming automatic contradiction rejection; do not certify arbitrary prose through keyword checks.
- [ ] Establish reliable development behavior, then freeze a fresh controlled comparison without modifying historical suites.
- [ ] Consider 30–50 varied, separately reviewed teaching examples only after the inference experiment supports further training; this count is a hypothesis, not a sufficiency guarantee.

Proposed quality thresholds remain unachieved: all outputs schema-valid on the small
frozen suite, exact configured reference interpretation, no unnecessary questions on
fully specified requests, no unsupported assertions, and owner-rated useful improvement
over the comparator. A tiny perfect suite would not establish broad reliability.
Implementation and verification: [inference reliability](docs/inference-reliability.md).

---

## MVP release gate — explicit owner journey

The owner-approved [bank-marketing acceptance session](docs/bank-marketing-acceptance.md)
uses isolated storage, provenance and separate later evaluation inputs. Mission, uploads,
mapping and manual interview are applied through the public API after owner review.
The first four live baseline requests failed JSON validation; explicit diagnostics found
output truncation and a separate semantic failure. Operator assistance does not establish
independent UI usability, and setup acceptance does not establish a useful learning loop.
Five later cases are frozen and their ten-output baseline is saved: A produced valid JSON
in 5/5 cases, B in 1/5, with irrelevant questions in valid outputs. Rubrics remain explicitly
AI-drafted and there are no human ratings. The [reviewed follow-up](docs/response-budget.md)
preserves that baseline, adds bounded generation and compact prompts, applies three
owner-edited lessons/targets and submits a separate local GPU job. The unseen complete
case still over-asks; a useful learning improvement is not yet established.

- [ ] Start builder with `docker compose up -d` and open its local web UI.
- [x] Create a mission in ordinary language.
- [x] Upload a CSV/XLSX observations file and a Markdown knowledge file.
- [x] Inspect case schema and confirm what was known at decision time.
- [x] Complete the guided interview and review adviser specification.
- [ ] Ask the context-only adviser a situation question and receive cited advice.
- [x] Give an “ask for missing evidence” correction; approve the lesson.
- [ ] Retest a related unseen case and observe the lesson in effect.
- [x] Freeze a separate evaluation suite and capture baseline results.
- [x] Approve a set of SFT examples and submit a local GPU LoRA job.
- [ ] Obtain a verified candidate version and evaluate against the baseline.
- [ ] Inspect visible improvements and regressions, then select the active version.
- [ ] Export and start the adviser in a new directory without QuarterMaster.
- [ ] Call its advice API with no frontier API key and inspect cited output.
- [ ] Repeat Teach → Test → Evaluate with a second unrelated business domain.

**Do not call the release complete** if the learning loop works only through prompt edits, the exported adviser needs the builder, or the evaluation set leaked into training.

## Deferred backlog (not part of 0.1.0)

- [ ] Optional hosted/remote GPU training provider with cost budget.
- [ ] Pluggable knowledge retrieval using embedded vectors.
- [ ] More spreadsheet/document formats and larger ingestion jobs.
- [ ] Calibrated typed choices/scores and Jev/Kev-like decision heads.
- [ ] Image/PDF ingestion and multimodal advice.
- [ ] Automated lesson clustering and improvement proposals with explicit approval.
- [ ] Longitudinal outcome tracking and A/B experimentation.
- [ ] Drift detection, root-cause triage and automated rebuild proposals.
- [ ] Multi-user tenant separation, source-level permissions and authentication.
- [ ] External action tools or fully autonomous agents (requires separate design approval).
