# Milestone 5 — Frozen evaluations and context comparison

Owners can reserve unseen Test situations, write expectations, freeze the exact model inputs,
and inspect A/B results with separate human ratings and deterministic checks. The active adviser
is never changed by evaluation. There is no training, automatic promotion or external builder
request in this workflow.

## Owner flow

1. Open a project and choose **Evaluate frozen situations side by side**. Create a named suite.
2. In **Test**, enter a new situation using only facts known before deciding. On its response,
   expand **Save as evaluation case** and select the draft suite. A failed response can also
   supply a useful evaluation situation.
3. Write what good advice should do. Choose recommend, ask first, abstain, or manual-only behavior.
   This rubric is owner-authored and is never attached to the inference request.
4. Saving immediately reserves the situation as a project holdout. Teaching feedback and builder
   lesson drafting are blocked for it. A situation already used for feedback cannot be described
   as an unseen holdout: use another case. Reservation persists even if a draft is abandoned.
5. Save up to 10 distinct cases. The UI encourages 5–10 representative cases, including difficult
   and missing-information cases. A small suite does not establish general quality.
6. **Freeze suite and inputs** captures membership, rubrics, original Test links, source hashes,
   mission, selected knowledge and approved lessons. Frozen suites cannot be edited. Create another
   suite if you need different membership, expectations or context; the same held-out Test can be
   included in another suite.
7. Run the frozen suite. **A** uses only the decision-time case, with no custom mission, definition,
   knowledge or lessons. **B** uses the captured mission/definition and retrieved knowledge/lessons.
   Both use the same pinned unmodified model, safety instructions and inference parameters.
   The base-only arm may be less meaningful for tasks that require business-specific instructions;
   inspect both exact requests before interpreting a preference.
8. Compare recommendations, explanations, citations, questions and limitations side by side.
   Choose **A better**, **B better**, **same** or **both bad**, a category and your rationale.
   Revisions preserve earlier ratings and the rationale's original whitespace. Ratings do not
   become feedback, lessons, training targets or observed outcomes.
9. Counts show improved (B preferred), regressed (A preferred), same, both bad and unreviewed cases
   separately. Failed outputs and expected-behavior failures are separate counts. Earlier runs
   remain accessible, and the active adviser stays as it was. No version promotion occurs here.

Model setup is unchanged from [Milestone 4](milestone-4.md). Creating suites, reserving cases and
reviewing saved results need no model/API key. Freezing and running require the configured local
model identity. An incompatible configured model or prompt implementation is rejected rather than
silently changing a frozen run's inputs.

## Contracts and reproducibility

[Public contracts](../quartermaster/contracts/evaluation.py) are strict, reject extra fields and
use the following versions:

| Contract | Stored content |
| --- | --- |
| `quartermaster.evaluation-suite/v1` | UUID/revision, creation/freeze time, project, cases, owner rubrics, normalized case hashes, source hashes, exact paired requests and frozen-suite SHA-256 |
| `quartermaster.evaluation-run/v1` | UUID/revision, timestamp, exact suite revision/hash, status, each output and its request hash, unchanged-weights context-comparison marker |
| `quartermaster.comparison-rating/v1` | Run/case identifiers, revision/time, human preference, category and unchanged rationale |

Each frozen request records the full adviser snapshot, model alias containing base revision and
GGUF hash, pinned engine revision, prompt version, exact system/context, response schema, inference
parameters, selected excerpt bytes/source hashes/positions and exact lesson IDs/revisions/text.
A's adviser snapshot records the capture for lineage, but its actual request omits custom context.
Every source in the selected knowledge revision is hash-verified at freeze, including sources not
retrieved for these cases. Citation checks on execution reverify accessible original excerpts
against the frozen knowledge revision. A missing/corrupt source causes an explicit output failure;
current retrieval never substitutes for frozen excerpts.

Freezing serializes the adviser/lesson/knowledge capture with approvals. Later project edits and
reindexing cannot change a saved suite's request bytes. Reruns reuse those exact inputs and create
new immutable outputs. A run references an immutable suite revision, so its model, prompt, source
and lesson lineage remains inspectable. SHA-256 detects accidental snapshot changes; it is not a
signature against a malicious local database operator. Reproducible inputs do not promise bitwise
identical generated outputs across hardware or inference implementations.

Each case is run sequentially as A then B, with the existing finite local-adapter timeout. A run
has a 1,200-second total bound and at most 20 requests. A durable `running` revision is written
before inference, then a checkpoint after every output, and a terminal `completed` or `interrupted`
revision. `completed` means execution finished, not that the model passed the rubric. Each output
can hold a sanitized error instead of advice. Cancellation, timeout and restart preserve completed
outputs, never retry automatically, and never replace earlier runs. One evaluation runs at a time
across the local application. The bounded request runs in-process; leave the page open while it
finishes. Training job orchestration remains Milestone 6.

## Holdout and outcome protection

[Holdout selection guard](../quartermaster/holdouts.py) checks both the source Case UUID and a
SHA-256 of normalized situation/choices. IDs, separate outcomes, Unicode compatibility forms,
casing, whitespace and choice ordering cannot turn a copied situation into an eligible example.
Saving membership and reservation is atomic. Reserving a case and creating teaching feedback are
serialized, so concurrent requests cannot approve both. Builder lesson preparation and sending
also recheck exclusion before any external call.

The shared `require_eligible(connection, project_id, cases)` guard is the boundary for Milestone 6:
call it inside the write transaction during example selection, before synthetic-example prompts,
and again at dataset freeze. No application SFT example promotion/selection path exists yet.
The independent Milestone 1 command still uses its separate static reviewed toy corpus; it never
reads application projects or evaluation records. This milestone creates no training examples.

This is exact/normalized duplicate protection, not semantic near-duplicate detection. Paraphrases,
case details copied into arbitrary owner text, or a manually uploaded document containing an
evaluation answer cannot be reliably identified. Owners must keep evaluation cases out of their
teaching material. The application does not feed evaluation rows, rubrics or comparison ratings
to the builder. The guided interview still uses schema summaries and explicitly selected knowledge,
not evaluation records.

`Case.observed_outcome`, if present on an imported/stored case, stays separate and is excluded by
`decision_input()` from both model requests. It appears only in a separately labeled review detail.
Ratings have no outcome field and reject one as an extra input. No delayed-outcome collection UI
or causal estimator is added. Owners must also omit later outcomes from free-text situation fields.

## Interpreting checks and comparisons

- Schema validity is structural validation of `GroundedAdvice`/`Advice`. Citation integrity means
  references belong to the actual verified frozen excerpt set. Supporting-quote checks reuse
  [the existing advice validation](../quartermaster/teaching.py). Missing declared facts replace
  decisive draft text with a withholding response. These establish provenance, not entailment.
- The automatic behavior check compares the **displayed** recommend/clarify/abstain behavior with
  the owner's expected behavior. A recommendation when clarification/abstention was expected is
  flagged. Failed responses fail a specified behavior check; manual-only rubrics have no automatic
  pass/fail. A question about an irrelevant fact can pass the clarify check. The written rubric
  and factual correctness still require human review.
- A/B preferences describe the effect of custom context with unchanged weights. The page compares
  frozen input fingerprints with the preceding saved run and warns if suite/rubric/context inputs
  differ. Different source hashes cannot be credited as training improvement. There is no combined
  score, LLM judge or claim of causal business lift. Candidate-model comparisons holding context
  fixed, and explicit model promotion, remain Milestone 6.

## API and storage

All routes below start with `/api/projects/{project_id}`. Mutations enforce same-origin; browser
forms require Origin and reject duplicate/extra fields. Lookups, membership and ratings are project
scoped. Existing browser form routes mirror the actions under `/projects/{project_id}`.

| Route | Method / action |
| --- | --- |
| `/evaluation-suites` | GET latest 50; POST `{name}` |
| `/evaluation-suites/{id}` | GET latest or `?revision=N` |
| `/evaluation-suites/{id}/cases` | POST `{expected_revision, test_id, rubric: {expected_behavior, expectation}}` |
| `/evaluation-suites/{id}/freeze` | POST `{expected_revision}` |
| `/evaluation-suites/{id}/run` | POST `{expected_revision}`; explicit local A/B execution |
| `/evaluation-runs` | GET latest 50 |
| `/evaluation-runs/{id}` | GET latest or `?revision=N` |
| `/evaluation-runs/{id}/ratings` | GET latest rating per case |
| `/evaluation-runs/{id}/ratings/{case_id}` | POST `{expected_revision, preference, category, rationale}`; revision 0 for first rating |

Preference values are `a_better`, `b_better`, `same`, `both_bad`. Categories reuse `good`, `wrong_call`,
`missing_knowledge`, `should_ask`, `weak_explanation`. Behavior values are `any`, `recommend`,
`clarify`, `abstain`. UUIDs and SHA-256 values use canonical strings. Model/provider credentials are
never stored in these records. Existing JSON snapshots can contain business information: protect
and back up the data volume.

SQLite v5 adds suite/run/rating revisions and project holdout reservations transactionally;
v1–v4 migrations retain old documents and source bytes. Back up before upgrading. Older application
versions reject schema v5; restoring a backup is required for rollback, not editing `user_version`.

## Verification record

Verified locally on 2026-10-24:

- `uv run --locked pytest tests/test_evaluations.py -q`: **28 passed**. Coverage includes frozen
  requests after knowledge/lesson changes, original suite/run revision access, strict/invalid/extra
  fields, project scoping/CSRF/HTML escaping, separate outcomes, all preference counts, stale rating
  revisions, normalized duplicate holdouts, selection and prepared-builder exclusion, taught-case
  rejection, 10-case limits, schema/citation/quote failures, clarification/abstention, model mismatch,
  source loss, timeout/cancellation, persisted checkpoints, restart recovery and no implicit retry.
- `make test`: **339 passed**, Python 3.13.5; no model network connections, GPU or provider account.
  Existing v1–v3 upgrade fixtures were updated to represent actual old schemas. A populated v4
  upgrade fixture compares all 13 prior metadata/index tables and original upload bytes.
- `make lint`: Ruff check and format check passed, **67 files** reported by Ruff.
- Production image built from the existing digest-pinned **Python 3.13 slim Trixie** recipe
  (Python 3.13.17 in the built image). No dependencies, model/container pins or model weights changed.
- [Evaluation HTTP smoke](../tests/smoke_evaluations.py) passed in a fresh production container,
  network `none`, read-only/nonroot, 2 CPUs / 512 MiB / 128 processes with temporary data. It used
  the actual local HTTP adapter against a loopback fake model, exercised browser forms end to end,
  saved four outputs and comparison ratings, blocked holdout teaching and left the adviser unchanged.
  These are deterministic workflow tests, not model-quality evidence.
- Existing [teaching](../tests/smoke_teaching.py), [foundation](../tests/smoke_foundation.py) and
  [interview](../tests/smoke_interview.py) HTTP smokes also passed against the final image with
  disposable data and synthetic loopback providers. This checks compatibility with corrections,
  consent/review, uploads, mapped cases, citations and invalid-builder-JSON recovery.
- A separate disposable web container used the **existing local CPU inference service** for six
  synthetic requests: two original Tests, followed by four frozen A/B outputs. No builder call,
  GPU training or persistent project write occurred. The suite had no uploaded knowledge or lessons;
  B added the mission. Qwen/Qwen3.5-0.8B revision
  `2fc06364715b967f1860aea9cf38778875588b17`, GGUF Q8_0 SHA-256
  `c85ac7c9cb8ecb014270ee852dd9580cff838ad294120c6dabfb41f5be29b004`, llama.cpp
  `1a24df163920a4744a95373d178d790b72a9bb2f`, temperature 0, seed 17, 512 output tokens,
  thinking disabled. Runtime limits remained 4 CPUs / 4 GiB, on the existing Intel i5-9300H WSL2 host.
  All four outputs passed structural validation with empty, valid citation arrays.

  | Synthetic case | Expected behavior | A observed | B observed | Automatic behavior check |
  | --- | --- | --- | --- | --- |
  | Current inspection, no reported damage | Recommend subject to checks | Clarify | Clarify | Both failed |
  | Current inspection, damage unknown | Clarify damage status | Clarify | Clarify | Both passed the behavior-only check |

  The first case over-asked about inspection/type/location. On the second, A asked about sander
  type/inspection method; B asked about sander type/location rather than damage. Thus **neither B
  output satisfied the full written fixture rubric**, even though the second passed the narrow
  ask-first check. This is a recorded limitation, not an improvement claim. The smoke's fixed A/B
  ratings exercise the UI only and must not be interpreted as human quality judgments.
- Before upgrading the live volume, SQLite online backup wrote
  `/data/backups/pre-milestone-5-26ac9ecd-f61e-45b0-aa3e-4bf60e4201c3.sqlite3` and a companion JSON
  fingerprint manifest. Actual v4 → v5 migration preserved all **13** prior tables. This live
  volume had zero projects/artifacts; populated preservation is covered by the CPU fixtures.
- `docker compose --profile advice up -d --build --wait`: both services healthy. Web remains
  published only at `127.0.0.1:8000`; inference has no published port. The evaluation API is present
  in the running app's OpenAPI schema. Existing ignored `.env` settings were preserved.
- `git diff --check` passed; all 22 changed/new files were reviewed as text, documentation links
  resolve, and no uploads, model artifacts, environment files or detected credential patterns are
  in the diff. Temporary smoke containers were removed; only web and inference remain running.

No external builder call, live GPU/training/cloud job, export run or manual browser visual
inspection was performed. No causal business lift, training improvement or real-model lesson
generalization is established. Synthetic fixtures remain explicitly software-test data, not SFT
supervision. The local application's training/export UI remains Milestones 6–7.

## Repeating the isolated HTTP check

These commands run synthetic software fixtures, not reviewed SFT supervision:

```sh
docker build -t quartermaster-web:m5 .
docker run -d --name quartermaster-m5-http-check --network none --read-only \
  --cap-drop ALL --security-opt no-new-privileges --memory 512m --cpus 2 \
  --pids-limit 128 --tmpfs /tmp:rw,nosuid,nodev,size=128m \
  -e QM_DATA_DIR=/tmp/qm-m5 -e QM_LOCAL_BASE_URL=http://127.0.0.1:8092/v1 \
  -e QM_LOCAL_MODEL_SHA256=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
  quartermaster-web:m5
docker exec -i quartermaster-m5-http-check python - < tests/smoke_evaluations.py
docker rm -f quartermaster-m5-http-check
```

Wait for web startup before the `exec` command. The script starts a loopback fake local model and
exercises the actual HTTP adapter and browser form routes. For a live local CPU check, configure a
fresh disposable web container to reach the pinned runtime, then run the script with `--live`.
It sends six synthetic requests (two original Tests plus four A/B outputs), never calls a builder,
and records behavior checks without asserting model quality. Ratings in this script are deliberate
workflow fixtures, not human assessments of live output quality.
