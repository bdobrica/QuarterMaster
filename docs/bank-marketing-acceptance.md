# Bank-marketing MVP acceptance session

This session checks a pre-call adviser and the teach → test → correct → evaluate loop.
This document preserves the original CPU acceptance results. The subsequent
[owner-reviewed follow-up](response-budget.md) records response-budget and prompt
changes, three approved edited corrections, and separate training/export verification.
It does not treat subscription prediction accuracy as the MVP gate. Source: Moro, Rita
and Cortez (2014), [Bank Marketing, UCI](https://doi.org/10.24432/C5K306), CC BY 4.0;
related paper: [DOI 10.1016/j.dss.2014.03.001](https://doi.org/10.1016/j.dss.2014.03.001).
The owner supplied the local download. No dataset rows are committed to this repository.

## Owner-approved setup

The owner reviewed this setup and answered **“Looks good. Proceed.”** in this conversation.
That approval covers the mapping, reference summary, adviser specification and local CPU
baseline. It does not approve lessons, SFT targets, a GPU run or model promotion.

**Mission:** Help a marketing analyst review the information available before a bank
term-deposit campaign call. Explain relevant prior-contact facts, identify missing
evidence, and ask a focused question before offering unsupported prioritization advice.

**Goal:** Test useful, evidence-grounded pre-call advice and improvement after reviewed
corrections; do not claim conversion probabilities, permission to contact, or increased
subscriptions.

**Case:** One historical campaign contact, considered just before that contact. This
is an offline reconstruction, not a proven point-in-time feature snapshot.

**Inputs:** `age`, `job`, `marital`, `education`, `default`, `housing`, `loan`, `pdays`,
`previous`, `poutcome`. For this exercise only, assume these recorded profile and prior
campaign fields were available before the current call. The download cannot independently
prove this assumption. `source_row` is provenance, never a predictive input.

**Outcome:** `y`, stored separately, never used as target advice. Exclude `duration`
(known after calling), `campaign` (includes the current contact), recorded last-contact
channel/calendar fields (not confirmed plans), and economic indicators (publication-time
availability not established). Do not automatically join the old and additional variants.

**Choices:** Summarize the available evidence, ask a relevant missing-information question,
or abstain from unsupported prioritization. No business action is available to the adviser.

**Desired behavior:** Explain prior-contact fields correctly, cite the uploaded dictionary
summary, distinguish unknown from no, and avoid inventing consent, current customer interest,
bank policy, calibrated predictions or causal effects. A previous success is not proof of
current subscription. `pdays=999` means no previous contact, not 999 elapsed days.

**Success/harm:** Owner review of factual support, relevant questions, unnecessary questions
and unsupported claims. Subscription is a separate historical outcome, not a human rating
or proof that the adviser helped. No ideal-advice examples have been supplied yet.

The Markdown remains attributed as an **AI-drafted summary of the downloaded dictionary
and experiment limits**, reviewed for use as reference context, not an invented bank policy
or approved training supervision.

## Reproducible local preparation

```sh
uv run --locked python -m tests.prepare_bank_marketing \
  --dataset-dir ~/bank-marketing \
  --output data/bank-marketing/acceptance-02
```

Use a new output directory for another run. The helper never edits the download or an
existing experiment. It creates a bounded observations CSV, a reference Markdown, separate
reserved inputs/outcomes and a content-hashed preparation manifest under ignored `data/`.
It sends nothing to an external provider and creates no advice targets or training job.

The canonical source is `bank-additional/bank-additional-full.csv`: 41,188 rows, 21 columns,
5,834,924 bytes; SHA-256
`74adfc578bf77a7ff4bb1ba4a9f8709d9e3c6907342959c2c8416847e0afb4d8`.
It exceeds the app's 10,000-row / 100,000-cell limits despite fitting the 8 MiB byte limit.
`bank-additional.csv` has 4,119 rows / 86,499 cells and fits, but overlaps its full file and
is a random subset, not an independent later evaluation set. `bank-full.csv` has 45,211 rows
and 17 columns **including** `y`; `bank.csv` has 4,521 rows and 17 columns. There are 12 exact
duplicate complete rows in the additional full file. Missing-category values use `unknown`;
the application preserves those strings rather than silently treating them as blanks or no.

Preparation uses the first 80% as the development pool (cut after data row 32,950), selecting
4,000 distinct input vectors spaced systematically across that pool without examining their
outcome. It reserves up to 24 similarly spaced later distinct inputs and excludes profile
proxies seen anywhere in the earlier pool. Taking only the earliest 4,000 rows was rejected:
all had `previous=0`, `pdays=999`, `poutcome=nonexistent`, omitting useful history variations.
The profile proxy comprises the first seven input fields listed above. Original 1-based
CSV record positions, including the header, are retained as `source_row`.

This prevents exact input/profile overlap for this selection. It **does not establish client
independence**: there is no client ID, exact date or reliable entity grouping. Similar
profiles remain, demographic proxies are not identities, and the bounded filtered subset
is not representative. Reserved rows become protected app holdouts only after explicitly
saving and freezing an evaluation suite. Do not upload their outcomes as knowledge or use
them in lesson/example drafting prompts.

The revised development selection contains 3,413 `nonexistent`, 528 `failure` and 59
`success` prior-campaign outcomes. The 24 reserved cases contain 14, 2 and 8 respectively.
These are coverage counts for `poutcome`, not current subscription predictions or scores.
The app does not automatically learn patterns or ideal advice from uploaded observations.

## Acceptance evidence and remaining gates

The owner selected “Pre-call adviser and teaching loop” in this conversation. Preparation
is complete: 4,000 development observations and 24 reserved later cases, with disjoint exact
input vectors and profile proxies. Seven focused deterministic preparation tests passed.

The isolated acceptance UI is running at
<http://127.0.0.1:18010/projects/f02c8241-c267-4eb4-9c9b-70ae3b90aa0c>.
Its fresh bind-mounted application data is in ignored
`data/bank-marketing/acceptance-02/appdata`; setup/events are in `session.json` and the
fixed Compose definition is `compose.json` alongside it. It uses the existing web image
`sha256:d8d4abec6604d0f1db3bb59181df5c65d7f761bb88eb9e7fdec6614ba911dfa1`
and existing CPU inference service. This is a fresh application data check using installed
images, not a second-machine or dependency-installation check. It publishes only localhost,
has a non-root user, read-only root filesystem, no GPU/Docker socket/provider credentials,
and bounded CPU/memory. The ordinary app at port 8000 still has zero projects.

Both prepared files uploaded successfully and their original-download bytes matched.
The observations preview correctly showed 4,000 records. Teach, Test, Train, Evaluate,
Export and interview pages returned HTTP 200. The actual Evaluate URL is `/evaluations`;
an initial verification-script typo `/evaluate` returned 404 and was corrected.
After owner approval, the mapping, knowledge selection and manual guided interview were
applied through the public API. All 4,000 derived cases were checked: only the ten approved
inputs enter their situations, `y` stays in `observed_outcome`, and every target candidate
is empty. Mapping ID: `c330cb68-400c-55a4-8912-ea9126f85278`. The adviser advanced to revision 3,
retained base weights and stayed `needs_examples`. Full records: ignored `applied-setup.json` and
the append-only event entries/approval scope in `session.json`. This is an operator-assisted
session; it does not prove a nontechnical owner independently completed the UI journey.

### First live baseline: four failed responses

The unchanged app used the pinned unmodified base model, temperature 0, seed 17,
512 output tokens and the selected Markdown context. Each request had a finite 180-second
local inference timeout. No external provider, lesson or trained candidate was involved.
`baseline.json` preserves the exact contexts, parameters, cases and failed records.

| Probe | Source CSV record | Test ID | Result |
| --- | --- | --- | --- |
| No prior contact; interpret `pdays=999` | 2 | `355ffa56-be65-428e-bb3f-7992ab993d97` | `LOCAL_JSON` |
| Previous campaign success; prioritization evidence | 24852 | `015065b5-3823-4918-8324-2f044d63c661` | `LOCAL_JSON` |
| Apparently conflicting prior history | 24078 | `7614cbad-a42a-464d-8096-92a512310b68` | `LOCAL_JSON` |
| Missing previous-contact interval | 28435 | `2b617374-38e7-4227-b969-2efb0f014344` | `LOCAL_JSON` |

The last probe deliberately omits `pdays` from a real development row and is recorded as
a missing-data variant, not an unmodified historical record. The four calls took roughly
39–41 seconds each on the existing CPU service. These are individual observations, not a
latency benchmark. All four failed records remain unchanged; none received a silent retry.

### Explicit diagnostic: output limit and semantic failure

Two additional, clearly separate CPU diagnostic requests repeated the first saved baseline request
at budgets of 512 and 1,024 tokens. They were not substituted for baseline results and
changed no app setting, source, model or saved Test record. The ignored diagnostic record is
`appdata/verification/response-budget-diagnostic.json` and includes the exact raw responses.

- At 512 tokens: `finish_reason=length`, 512 completion tokens; incomplete JSON rejected.
- At 1,024 tokens: `finish_reason=stop`, 754 completion tokens; schema/advice validation passed.

The longer response was still wrong about its evidence: it requested a definition for
`pdays=999` although that definition was present in the retrieved reference. It also asked
for bank policy/calibration information to interpret a documented dataset code. It listed
real retrieved citation IDs, which proves accessible references, not semantic support or
usefulness. Increasing an output limit alone does not establish adviser viability.

An independent source audit found 4,110 full-file records where `pdays=999` occurs alongside
`previous>0`. Under the supplied dictionary this is an apparent tension that warrants
clarification. It is not silently repaired or asserted to be a proven source error.
The exact audit is in ignored `history-audit.json`.

### Evaluation and learning status

Five cases from four reserved later historical rows were saved and frozen before any
lesson or training: known interval, apparently conflicting history, missing interval,
no previous history, and an unknown category. The last two ask different questions about
the same row; these are not five independent customers. The missing-interval case explicitly
removes `pdays` from its source inputs. Rubrics are AI-drafted operationalizations of the
approved setup, not human ratings or ideal SFT advice. Only safe inputs go to inference;
reserved outcomes and rubrics do not. The application settings stayed unchanged.

Suite: `ef097a07-7f21-4f1c-923e-e8c526de3c28`, frozen revision 7, SHA-256
`ac39857ab02a4ff97904ed47b0471e85425e7d25901d9dda0e00dfdef795005a`.
Run: `2726fd69-7c13-432e-978c-62dec2be396a`, completed revision 12, ten persisted outputs.
[Open the saved comparison](http://127.0.0.1:18010/projects/f02c8241-c267-4eb4-9c9b-70ae3b90aa0c/evaluations?run_id=2726fd69-7c13-432e-978c-62dec2be396a).

| Case | Original CSV record | A: base only | B: base + approved context |
| --- | --- | --- | --- |
| Known interval | 36470 | Valid JSON; asks for dates despite supplied interval | `LOCAL_JSON` |
| Conflicting history | 32962 | Valid JSON; asks for a client name/account ID rather than resolving history | `LOCAL_JSON` |
| Missing interval | 39010 | Valid JSON; asks for a date and irrelevant contact duration | `LOCAL_JSON` |
| No history | 33347 | Valid JSON; treats the supplied zero count as missing | Valid cited JSON; asks for dates of a previous contact despite zero count |
| Unknown category | 33347 | Valid JSON; recognizes `unknown` but asks about unrelated history fields | `LOCAL_JSON` |

All five A outputs were schema-valid; one of five B outputs was schema-valid. Six outputs
passed the structural citation/support checks, but A had no retrieved evidence or citations,
and B's valid response listed accessible IDs without answering the question adequately.
Two of ten outputs passed the narrow expected-behavior check, both A clarification outputs.
That check does not assess question relevance: the client-ID question and the unnecessary
duration request demonstrate the limit. These counts are not a quality score.

There are zero human comparison ratings; analyst observations above are not recorded as
owner preferences, approved supervision or business results. No weight improvement was
assessed. The source files and frozen suite stayed unchanged. Exact outputs and scope are
in ignored `evaluation-baseline.json` and `evaluation-summary.json`.

There are no approved lessons, training examples, GPU jobs, promoted versions or bank-adviser
exports. Feedback currently requires a successful Test response, so the four failed baseline
records cannot yet be used for the correction → reviewed lesson step.

The live negative-path checks confirmed `422 FEEDBACK_TEST` for feedback on a failed
baseline record and `409 EVALUATION_HELD_OUT` for feedback on the successful held-out test.
Neither request created a lesson or changed any weights. The frozen suite remained byte-for-byte
equal through its public JSON representation; all ten request snapshots omitted outcomes,
rubrics and lessons. Evidence: ignored `negative-path-checks.json`.

### What needs to change before proceeding to training

1. Make ordinary structured answers finish within a documented finite generation budget.
   Distinguish token-limit failures from malformed JSON in actionable UI diagnostics.
   A production budget change must preserve/replay historical frozen parameters: evaluation,
   trainer and exporter currently check them against the shared fixed profile. Do not simply
   change a global constant and invalidate earlier runs or silently substitute new parameters.
2. Recheck direct dictionary comprehension and relevant questions on untouched held-out cases.
   The 1,024-token diagnostic demonstrates format feasibility, not a useful factual answer.
3. Obtain a valid, separate development response for owner correction. Review the exact lesson,
   retest an unseen case, and inspect both gains and regressions before approving SFT targets.
   Held-out cases remain excluded even when they expose tempting mistakes to teach from.

These are next steps, not fixes claimed as implemented. This acceptance run deliberately
keeps the shipped application and weights unchanged so its failures remain assessable.

The first immutable preparation attempt remains under `acceptance-01` with its own trial
database, preserved after rejecting its narrow early-period selection. The running session
uses only `acceptance-02`. Do not combine their sources or treat either as approved SFT.

Preparation-step verification: `make test` passed 442 CPU tests; `make lint` passed. The
preparation helper's focused seven-test gate passed after revising the selection to span
both periods. This continuation changed no application code or inference settings; it ran
real CPU requests through the deployed public API and the two explicit diagnostics.
There were 21 model-generation requests: four development probes, five initial held-out
probes, ten frozen comparison outputs and two diagnostics. No GPU, training, external
builder or standalone export check was run in this bank session. The ordinary project
store stayed empty. Dataset files, prepared rows, application data and session outputs
remain ignored. The guarded, single-use operator scripts are preserved under ignored
`operator-scripts/`; they are verification records, not an automatic training pipeline.

At the end of this original session, the owner still needed to inspect baseline behavior,
any correction/lesson, unseen retest and
frozen comparisons. Keep unreviewed supervision unapproved. A new domain
training run needs reviewed targets and a bounded command approved for this session. Earlier
synthetic GPU/export checks establish component feasibility, not bank-domain usefulness.
The later review and standing local GPU authorization are recorded in the follow-up;
they do not change the original baseline or approve the held-back third correction.

The [release checklist](../TODO.md#mvp-release-gate--explicit-owner-journey) stays pending
until its actual session evidence exists. Opening the UI and assessing usefulness are human
acceptance steps; HTTP checks alone do not establish that a new owner can follow the README.
No MVP tag, bank-domain quality gain, conversion accuracy or business lift is claimed.
