# Inference reliability development comparison

The bank LoRA attempt proved the local training/conversion/checking path, while its
advice remained unreliable. The owner requested compact output, explicit field
interpretation and separate quality assessments before further training. Base
weights remain active. The failed job and protected frozen suites are preserved.

This is an **opt-in development experiment**, available from Test → “Try the
inference reliability development comparison,” at `/projects/{project_id}/reliability`.
Ordinary Test, lesson/SFT review, frozen evaluation and standalone packages continue
using their existing v1 advice contracts. Nothing here promotes a model, changes
adviser settings, generates supervision or schedules GPU work.

## Compact response

`quartermaster.advice/v2` has five content fields plus its explicit schema version:

```json
{
  "schema_version": "quartermaster.advice/v2",
  "decision": "clarify",
  "recommendation": "Withhold the interval calculation until its value is supplied.",
  "reason": "A contact count does not establish elapsed days.",
  "evidence_refs": [],
  "question": "What is the recorded elapsed interval?"
}
```

This illustration is not a training target or a claim that a particular source
supports the text. Limits: recommendation 240 characters, reason 400, question 160,
at most three distinct accessible citation UUIDs. Only `clarify` has a question;
`answer` and `abstain` require null. Multiple question marks are rejected, but syntax
cannot prove that a question is necessary, singular in meaning, or relevant. An
answer without a cited reference is rejected as unsupported in this experiment.

The existing adapter already sends `response_format: json_schema`. The pinned
[llama.cpp server](https://github.com/ggml-org/llama.cpp/blob/1a24df163920a4744a95373d178d790b72a9bb2f/tools/server/README.md)
and [grammar guide](https://github.com/ggml-org/llama.cpp/blob/1a24df163920a4744a95373d178d790b72a9bb2f/grammars/README.md)
document schema-to-grammar constrained decoding. All three arms retain that mechanism;
the new compact schema bounds strings/arrays and constrains citations and the
decision/question combinations. Validation still runs after generation. A valid
shape, complete JSON and accessible citation IDs do not prove factual entailment.
Empty references pass accessibility vacuously and provide no citation support.
The UI reports these as **No citations provided**, separately from **All supplied
citations accessible**. A read-only `/api/projects/{project_id}/reliability-runs/{run_id}/diagnostics`
endpoint returns citation count/status and a sentence-ending punctuation check for
each output, including historical runs without rewriting their saved bytes. A
punctuated string can still be incomplete or wrong. This diagnostic neither
certifies prose nor repairs it, and leaves schema-validity scores unchanged.

## Explicit field definitions

Rules are generic data, never executable expressions, scripts, templates or inferred
business policies. An owner supplies and confirms `quartermaster.field-rules/v1`:

```json
{
  "reviewed": true,
  "rules": [{
    "field": "elapsed",
    "kind": "integer",
    "definition": "Days since the previous inspection.",
    "unit": "days",
    "sentinels": {"999": "No previous inspection recorded."},
    "unknown_values": ["unknown"],
    "categories": {},
    "citation_id": "REPLACE_WITH_AN_ACCESSIBLE_CITATION_UUID",
    "source_quote": "REPLACE_WITH_THE_ACTUAL_VERBATIM_DEFINITION"
  }]
}
```

The placeholders deliberately cannot validate. Use an actual excerpt from the
selected project knowledge revision. The engine verifies original bytes, revision
membership and the verbatim quote before sending any case. This proves attribution,
not that the owner's interpretation is correct. An edited/AI-proposed rule needs
review before setting `reviewed` to true; this is independent of SFT approval.

Supported kinds are a nonnegative integer of up to 12 digits, with explicit units,
and a category with exact named values/meanings. Tokens are case-sensitive; no
trimming, fuzzy matching, numerical guessing or unknown-to-negative coercion occurs.
At most 20 rules can use four definition excerpts. Rules are saved in each immutable
comparison, not silently installed as active project behavior.

Interpretation states are `absent` (no key), `missing` (null/empty), `unknown`
(configured exact token), `sentinel`, `value`, and `invalid`. Sentinels have a
meaning and preserve the original raw value; they have no numeric measurement or
unit. Integer values preserve both number and unit. Unknowns establish neither a
positive nor a negative fact. Multiple fields are interpreted independently; the
engine never repairs conflicting values or guesses their recording scope.

## Running and reviewing a comparison

`POST /api/projects/{project_id}/reliability-runs` accepts:

```json
{
  "situation": "What facts does this development record establish?",
  "decision_inputs": {"elapsed": "999"},
  "field_rules": {"reviewed": true, "rules": []},
  "inputs_available_at_decision": true
}
```

An empty rule list is valid and performs no interpretation. Add reviewed rules to
test that arm. Values must be exact strings or null. Later outcomes and ideal
answers have no contract fields. The owner must still ensure free text and inputs
contain only decision-time information; this is not semantic leakage detection.

### Controlled lesson ablation

To isolate lesson-context effects, include an optional `lesson_ablation` object:

```json
{
  "relevant_id": "REPLACE_WITH_AN_APPLIED_LESSON_UUID",
  "relevant_rationale": "Why this existing lesson appears to apply to this request.",
  "irrelevant_id": "REPLACE_WITH_A_DIFFERENT_APPLIED_LESSON_UUID",
  "irrelevant_rationale": "Why this lesson may be irrelevant to this request."
}
```

These placeholders deliberately do not validate. Find exact IDs through
`GET /api/projects/{project_id}/lessons`. Both selected records must be applied in
this project, distinct and included in the captured inventory. Rationales record
operator hypotheses, not verified relevance, owner quality ratings, new lesson
approval or new instructions. Missing, pending, rejected and foreign selections
fail before generation. The comparison refuses to call an arm “all lessons” if
any applied lesson would be omitted by existing context limits.

| Arm | Approved lessons in context |
| --- | --- |
| `no_lessons` | None |
| `all_lessons` | All captured applied lessons |
| `relevant_lesson` | Only the selected relevant lesson |
| `irrelevant_lesson` | Only the selected potentially irrelevant lesson |

All four arms use exactly the previous interpreted-v2 system, compact schema,
field interpretations, source excerpts, mission, input values, model alias and
generation parameters. Only the `approved_lessons` array differs. Role rationales
and arm names are not added to the model context. This is a manual controlled
ablation, not an automatic retrieval/filtering policy or a prompt rewrite.

New ablation snapshots use `quartermaster.reliability-run/v2`; historical three-arm
snapshots remain readable as v1, with their original request hashes. No database
migration is needed (schema remains 7). Older application versions cannot read
the new four-arm documents; use the compatible application for the experiment
copy. The same 600-second comparison bound, durable per-output revisions, single
running comparison guard, cancellation/restart handling and no-retry policy apply.
Each completed four-arm run has six revisions including initial/final states.

Citation relevance and question relevance still require separate review. The
field interpreter establishes typed facts; it cannot detect contradictions in
arbitrary adviser prose. Generating structured claims and changing sentence
formatting must be captured separately from the lesson-only ablation.

### Decision-selection instructions

The owner reviewed all 16 ablation outputs: none was fully useful. The relevant
lesson produced a partially correct missing-interval question with an incorrect
explanation. Irrelevant lessons redirected some requests, but errors without
lessons show that selection alone is insufficient. Preserve the three approved
lessons; diagnose answer-versus-clarify behavior before another training run.

Set `"decision_selection": true` on the same request instead of `lesson_ablation`
to select a three-arm, no-lessons comparison:

| Arm | System instructions |
| --- | --- |
| `existing_instructions` | Unchanged `COMPACT_SYSTEM` from interpreted v2 |
| `answer_first` | Same system plus an explicit answer-when-sufficient instruction |
| `decision_gated` | Same system plus a question/fact/sufficiency decision checklist |

The additions follow the owner's proposed behavioral instructions. The existing
system already says to answer when facts suffice; the comparison tests whether
explicit reinforcement or ordering changes behavior. The checklist asks for no
extra output or hidden reasoning. It is **not an implemented deterministic gate**.
Only the system string differs within a case. Full inputs, case UUID, mission,
sources, definitions, interpreted facts, response schema, model and generation
parameters are identical. No approved lessons enter any request; the captured
inventory remains audit metadata only. No relevance labels or expected decisions
are sent to the model. Fresh cases are preflighted before inference.

`false`, non-boolean selections, extra fields, or combining this flag with lesson
ablation are rejected. New snapshots use `quartermaster.reliability-run/v3` with
three ordered requests/outputs and five revisions on completion. Historical v1/v2
records remain readable without rewriting their stored bytes; the SQLite schema
remains 7. Earlier application versions cannot read v3 documents, so use isolated
experiment storage. Bounds, per-output persistence, interruption recovery and no
automatic retries match the existing lab.

Inspect each **draft's** decision as well as accepted advice: a direct answer with
no citation remains rejected as `ADVICE_SUPPORT`. A shift toward answers does not
establish appropriate decisions, factual accuracy or usefulness. Citation presence
and accessibility remain separate from relevance/coverage; punctuation remains a
diagnostic, not a completeness validator. The explicit-claim checker still does
not validate generated prose. No validators, schema constraints, lesson text,
ordinary adviser defaults, training or exports change in this experiment.

Context reduction and two-stage decision/content generation are separate follow-up
experiments. Mixing them here would prevent attribution of any behavioral change.

### Question-focused context selection (Experiment B)

The owner reviewed all twelve Experiment A attempts and supported the negative
finding: the tested instruction additions did not resolve clarification bias.
Keep that evidence intact. Set `context_selection` instead of either earlier
experiment flag:

```json
{
  "fields": ["elapsed"],
  "rationale": "This question asks only for the recorded elapsed interval.",
  "reviewed": true
}
```

Use actual configured field names. The selection must contain 1–20 distinct names,
each with an attributed rule, including any requested absent field. Explicit
`reviewed: true` confirms the selection; it does not approve a teaching example
or establish rule correctness. Unreviewed, duplicate, unconfigured, extra-field or
mixed experiment configurations fail before generation. No model selects fields.
The rationale is audit metadata and is not sent as an instruction.

| Arm | Model context |
| --- | --- |
| `full_context` | Existing full structured record, mission/decision definition, original evidence and all typed interpretations |
| `relevant_raw` | Original question, explicitly selected supplied inputs, their rules and verbatim source-definition spans |
| `relevant_interpreted` | Exactly the raw view plus the selected typed interpretations |

All arms use unchanged `COMPACT_SYSTEM`, compact advice/v2, base weights,
temperature 0, seed 17, 1,024 output tokens and **no lessons**. The raw/interpreted
pair differs only in `field_interpretations`. Focused views also remove the full
record repeated inside `case.situation`, the general mission and the broader
decision definition. This comparison measures that context-packaging bundle;
it cannot attribute an effect to individual fields versus mission framing.
The original question is preserved verbatim; free text that itself contains
irrelevant facts is not automatically redacted. Keep the question focused.

New `quartermaster.reliability-run/v4` snapshots retain `full_context` exactly equal
to the control request, complete source excerpts/provenance and `definition_spans`
for every selected field. Spans preserve the rule's verbatim `source_quote`, its
original citation UUID and character offsets in the full excerpt (end exclusive).
Repeated citation IDs can identify distinct verbatim spans of the same original
excerpt; no new source IDs or fabricated excerpts are created. Selected views
are derived projections, never replacements for original source bytes. Missing
keys stay absent; sentinels, unknowns, nulls and exact types retain their meanings.
The SQLite schema remains 7; v1/v2/v3 snapshots remain readable without rewriting
stored bytes. Older images cannot read v4 runs; use an isolated database copy.

The **full control's exact response schema**, including its citation UUID enum,
is used in all three outbound requests. The adapter's explicit `schema_context`
argument is used only to build this shared compact schema; the full context does
not enter focused message content. Consequently a UUID for an excluded excerpt
can remain in the shared grammar, but validation rejects it unless that arm's
actual `retrieved_evidence` contains it. Accessible citations still do not prove
relevance or claim coverage. Unsupported uncited answers stay rejected drafts.
Adapters without shared-schema support fail preflight with an actionable error.
Historical inference calls retain their existing schemas and defaults.

The normal per-output persistence, 600-second comparison limit, interruption
recovery and no-retry policy apply. A complete run adds five revisions. No new
validator infers facts from prose, certifies sentence completeness or converts
expected decisions into overall quality scores. Record decision appropriateness,
recommendation/reason consistency, repeated questions about supplied facts,
completeness and citation support separately in the human review. A minimal
decision-only schema is deferred to a separate diagnostic, as requested.

### Narrow checks on explicit claims

Each saved comparison offers “Check explicit field assertions,” also available as
`POST /api/projects/{project_id}/reliability-runs/{run_id}/check-claims`. The
`quartermaster.field-claims/v1` input contains 1–20 distinct `claims`, each with
`field`, `state`, `value`, `unit`, and the definition's `citation_id`. Numbers must
be integers rather than numeric strings. Non-value states require null value and
unit. Extra fields, duplicate fields and ambiguous value/state combinations fail
validation. This check is read-only: no ratings, teaching or adviser changes.

The checker compares only explicit assertions with the captured owner-configured
interpretations. It rejects a measurement of zero for an absent number, a numeric
sentinel used as elapsed days, yes/no asserted from an unknown category, a wrong
unit, an unconfigured field, or a citation different from the field's attributed
definition. Results use `quartermaster.field-claim-check/v1`, pin the run/rules hash,
and report separate state/value/unit/citation mismatches. No banking semantics or
substring searches occur in the engine.

This is a foundation for contradiction rejection, **not automatic validation of
the generated advice**. Compact v2 has no structured claim field. Assertions are
submitted explicitly by the operator/API caller; a caller can omit a false prose
assertion or submit correct claims beside false prose. Responses therefore always
say `advice_prose_checked: false`. A match proves consistency with configured
scalar facts only, not correctness of the rules, citation relevance, completeness,
necessary clarification, business usefulness or factual entailment of free text.

### Default three-arm design comparison

Each request captures the same base alias, adviser snapshot, selected full source
excerpts and approved lessons in three arms before any generation:

| Arm | Output / system | Extra interpretation |
| --- | --- | --- |
| `current_v1` | Existing v1 response and system | None |
| `compact_v2` | Compact response and question-focused system | None |
| `interpreted_v2` | Same compact response and system | Attributed typed facts |

All arms see the same raw structured inputs and reviewed rule definitions. The
v1 comparison includes this common experimental context; it is not an exact rerun
of an older frozen request. Comparing v1 with v2 measures the combined contract
and instruction change. Comparing the two v2 arms isolates interpretation. All
use temperature 0, seed 17, 1,024 output tokens and the pinned base/llama.cpp
revisions. Arms run sequentially in fixed order; elapsed times include input
processing/cache effects and are observations, not controlled performance benchmarks.
There is no unconstrained-decoding arm or automatic retry.

Request hashes, exact prompts/schemas/parameters, original provenance, rules hash,
interpretations and each output are saved append-only. Database migration 6 → 7
adds only experiment/review tables. At most one comparison is running; each has
a 600-second total bound and each local request retains the configured timeout.
Restart/interruption preserves completed outputs and records an interrupted state.
Model identity is checked before every case transmission.

Schema validity, citation accessibility, normalized validated draft length, local
completion-token usage when available, and elapsed time are recorded separately.
Incomplete output is rejected, with token usage retained when reported. No partial
advice is accepted. A grammar can end a string mid-sentence at its character limit;
readability and completeness of meaning still need review.

For each arm, the UI and
`POST /api/projects/{project_id}/reliability-runs/{run_id}/reviews/{arm}` separately
record factual quality, clarification relevance, absence of unsupported assertions,
citation relevance (`pass` / `fail` / `not_assessed`), usefulness
(`useful` / `not_useful` / `not_assessed`), notes and expected review revision.
Reviews append revisions and never rewrite outputs. No quality credit is inferred
from valid JSON, no combined score is computed, and owner preference is not observed
business lift. These reviews are not lesson or SFT records.

The experiment rejects existing holdout fingerprints/lexical near-duplicates and
exact JSON structured-record copies with rewritten questions. These guards do not
detect every paraphrase, altered subset or non-JSON copy. Use distinct development
records and keep protected cases/rubrics out of prompts and supervision.

## Verification and remaining gates

### Initial three-arm comparison

`make test`: **506 passed**. `make lint`: passed (108 Python files formatted).
The 44 new reliability checks cover strict contracts, scalar states/units, source
membership/quotes, separate quality reviews, stale revisions, interruption/recovery,
holdout-record rejection, CSRF, rendering, usage on rejected completions and the
non-destructive v6 migration. Existing historical generation, evaluation, training
and export fixture tests pass. No new standalone model/package check was performed;
v2 export is not implemented or claimed.

Four distinct development records from the existing pre-cutoff development pool
were used: source rows 25276 (known interval), 27660 (interval omitted), 202
(no prior contact) and 5006 (unknown credit-default status). The protected frozen
suite, its rubrics and row outcomes were not used. The original bank SQLite data
and source blobs were copied; the original downloaded dictionary was uploaded
byte-for-byte as an additional Markdown source **only in the copy**. The configured
count, day/sentinel and unknown distinctions follow the owner's requested rules,
with exact original dictionary attribution; no new ideal answers were authored.
The same three existing approved lessons entered every arm.

Twelve finite local CPU requests completed against the unchanged pinned base GGUF
(`c85ac7c9cb8ecb014270ee852dd9580cff838ad294120c6dabfb41f5be29b004`),
using the existing CPU inference service on the i5-9300H laptop:

| Arm | Schema valid | Reported completion tokens, in case order | Observed seconds range |
| --- | --- | --- | --- |
| Current v1 | 2/4 | 1024, 590, 1024, 356 | 36.770–66.524 |
| Compact v2 | 3/4 | 188, 178, 174, 158 | 25.097–29.693 |
| Interpreted v2 | 4/4 | 143, 211, 191, 184 | 24.878–32.169 |

These are format results and individual latency observations, not quality scores
or performance benchmarks. Two v1 outputs reached the token limit. One compact-v2
output failed contract validation; its exact validation cause was not retained.
No request was retried. All twelve scalar interpretations matched explicit
state/value/unit checks; this verifies preprocessing, not the model's use of facts.

Semantic failures remain substantial:

- Known interval: the compact arm questions a supplied definition; the interpreted
  arm invents a need for a separate current interval despite `pdays=4`.
- Missing interval: the interpreted recommendation states that an absent interval
  is zero, while its reason says it cannot be calculated. Both compact arms ask
  about supplied definitions or introduce unrelated prioritization.
- No prior contact: the interpreted arm asks whether `previous=0` is a count or
  an outcome despite the explicit count definition.
- Unknown credit default: all arms drift toward elapsed-time clarification instead
  of answering the credit-default question. Several compact reasons end mid-sentence
  at the character bound.

All compact outputs that passed validation chose `clarify` with empty citations.
Accessible IDs and 4/4 complete JSON in the interpreted arm therefore do not
establish grounded or useful advice. No human quality ratings, factual-quality
pass rate, preference improvement or business gain are claimed.

Ignored local evidence is under `data/bank-marketing/inference-reliability-01/`:
`setup.json`, four complete run snapshots, `results.json`, `verification.json`,
`verification-manifest.json`, trusted operator scripts and a pinned Compose file.
The editable `data/bank-marketing/inference-reliability-review.md` contains all
twelve outputs and separate blank quality-review fields. No file notes are
automatically imported into lessons, SFT or API ratings. The earlier GPU review
file remains byte-identical.

The live probe image was
`sha256:b8726d3e38b21755dd221614a6d24627640c7de696fc82c2099aace90f6a8685`.
The final UI image, adding a preflight error for unsupported custom inference
adapters without changing generation prompts/schemas, is
`sha256:9e508088396cdf079161418854347f31110cc075c334b5877fedecc0c02601ef`.
Both use the existing pinned Python 3.13 Trixie base and locked dependencies.
The copied experiment is available on localhost port **18011**. Container health,
rendering of a saved comparison and separate review fields were checked over HTTP.
This was not an independent human UI journey.

The original bank app on port 18010 remains on schema 6, adviser revision 6 and
base weights. Its original metadata tables, sources, tests, reviews, supervision,
failed job and frozen suites were verified unchanged. The ordinary builder on
port 8000 remains healthy with zero projects. No GPU job or model promotion ran.

The next development question is why the model ignores the request and supplied
facts even with explicit interpretation. Repeated elapsed-time themes on unrelated
questions suggest checking instruction and lesson-selection effects in a separately
captured ablation; this experiment does not establish the cause. Keep the original
approved lessons intact until any proposed edit is reviewed. Useful development
behavior, a fresh controlled evaluation, v2 integration/export and MVP acceptance
remain pending. More LoRA supervision is not justified by these format results alone.

### Lesson ablation — 24 October 2026

The owner's follow-up requested a lesson-only comparison before changing approved
lesson text, promoting v2 or spending another GPU cycle. Four new development
records were selected from the original pre-cutoff region: source rows 24266
(known four-day interval), 24110 (interval omitted), 10002 (no earlier contact),
and 10005 (unknown default). The selected ten decision-input columns exclude
outcomes and post-call fields. Source values were checked against the original
download. Prior recorded development/teaching vectors and source rows were
excluded; these are distinct records, not proven independent clients.

All 16 local CPU generations used the previous interpreted-v2 system/schema,
source excerpts, reviewed field rules, mission, base GGUF and generation settings.
Within each case only the lesson array differed; exact bodies/hashes and lesson
revisions were checked. The three approved lesson records were never edited.
Known/history/default requests selected the existing interpretation lesson as
relevant and the missing-interval lesson as potentially irrelevant. The missing
interval request selected the interval lesson as relevant and the prioritization
lesson as potentially irrelevant. These selections are operator hypotheses.

| Arm | Schema valid | Outputs providing citations | Reported completion tokens, total |
| --- | --- | --- | --- |
| No lessons | 4/4 | 0/4 | 745 |
| All three | 4/4 | 0/4 | 646 |
| One relevant | 4/4 | 0/4 | 752 |
| One potentially irrelevant | 4/4 | 0/4 | 723 |

Every response chose `clarify`. All twelve scalar state/value/unit checks passed,
but no arm met the requested foundation behavior across the cases. No quality
gain, factual-quality score or owner preference is claimed. Fixed arm order and
shared CPU runtime/cache also prevent timing comparisons as benchmarks.

Technical inspection found:

- Known four days: the no-lessons arm acknowledges four days but asks about
  contact/outcome information. All/irrelevant arms ask for the supplied interval;
  the relevant arm invents ambiguity between equivalent elapsed-day descriptions.
- Absent interval: the relevant interval lesson produces the needed interval/dates
  question, but its reason calls absence a sentinel and invents a contradiction.
  Other arms ask for subscription status, supplied definitions or prioritization.
- No earlier contact: all/irrelevant arms drift toward elapsed-time questions.
  The no-lessons arm repeats the original question; the relevant arm invents a
  default-field conflict and returns `"clarify"` as the question text.
- Unknown default: no-lessons/relevant arms initially acknowledge unknown means
  neither yes nor no, then truncate or ask for default again. All/irrelevant arms
  turn to elapsed-time questions.

Lesson context changes the outputs and can amplify irrelevant clarification in
these cases. Failures without lessons show it is not the sole problem. Selecting
one apparently relevant lesson does not establish reliable application. Sentence
ending punctuation is present in all fields for only two of the sixteen outputs;
this is a diagnostic, not proof that those two explanations are complete. The
formatting problem is **not fixed** by this comparison. No automatic selector,
default v2 rollout, new training targets or LoRA run is justified by these results.

The first probe was deliberately stopped after one saved generation because a
planned later case overlapped earlier teaching. Its partial snapshot remains
interrupted under `data/bank-marketing/lesson-ablation-01/` and is excluded from
the results. A subsequent input-only preflight found no unused four-day record
in the small 4,000-row sample and made zero model calls. The completed comparison
therefore selected fresh input-only records from the original development region.
Both failures are retained; no automatic model retry was introduced.

Ignored evidence lives under `data/bank-marketing/lesson-ablation-02/`, including
setup/actions, original-input provenance, four complete run snapshots, diagnostics,
results, verification, HTTP checks, trusted operator scripts and hash manifests.
The new editable `data/bank-marketing/lesson-ablation-review.md` contains the sixteen
outputs, technical observations and blank owner review fields. Existing review
files remain byte-identical and no notes were imported into ratings or SFT.

The pinned probe image is
`sha256:0ff4c73d3bc839ccd4e78851712fb84182208749449304972a5cd94fb192948c`.
The final review UI image, adding separate structured assertion checks without
changing generation, is
`sha256:022e80605768b2b9371d889def38b6e57829790011c8e904af0ed05adf564d31`.
It is available on localhost **18012**, with a separate schema-7 database copy.
The original bank app and the previous comparison database, sources, lessons,
supervision, failed job, frozen suites and owner ratings were verified unchanged.

`make test`: **536 passed**. `make lint`: passed (110 Python files formatted).
Thirty additional focused cases cover lesson-only controls, invalid/unapplied
selections, omissions, historical snapshots, restart handling, citation presence,
strict structured assertions, exact value/unit/source matching, cross-project
access and forms. All four real saved pages/diagnostics and nine read-only claim
checks passed over localhost HTTP, including absent-as-zero, absent-as-sentinel,
sentinel-as-measurement and unknown-as-no rejection. Their result page states
explicitly that adviser prose is unchecked. No new model/package export test or
GPU test ran; v2 standalone export remains unimplemented.

The next controlled experiment should address the persistent tendency to clarify
despite an answer being supplied, alongside the constrained-string cutoff. It
should isolate question/mission framing or a structured-claim response design,
without editing approved lessons or asserting that a passing scalar claim check
certifies free text. The owner subsequently reviewed all sixteen outputs, as
recorded in the decision-selection section above. Reliable development behavior,
a fresh frozen comparison and normal v2 integration remain pending.

### Decision-selection probe — 24 October 2026

Twelve finite CPU requests compared the three instruction variants on fresh
pre-cutoff source rows: **27770** (seven elapsed days), **24912** (interval
deliberately omitted), **15001** (no earlier contact), and **15005** (unknown
credit default). Original input values were verified against the pinned download.
Prior development/teaching rows and captured input vectors, including projections
onto the new available fields, were excluded. These are distinct records, not
proven independent clients. No frozen cases, rubrics, outcomes or review targets
entered generation.

Each case retained the full ten pre-call input fields (nine for missing interval),
unchanged mission/decision definition, four accessible source excerpts, reviewed
field rules and three attributed scalar interpretations. All request contexts,
response schemas and generation parameters were identical within a case. Only
the system instruction strings changed. No lesson entered any request. Base GGUF,
seed 17, temperature 0, 1,024-token budget and constrained decoding were unchanged.
Arms ran in fixed order on the shared CPU service; timings are observations,
not controlled performance benchmarks.

| Instructions | Schema valid / attempted | Answers / readable | Clarify / readable | Cited / readable | Reported tokens, all attempts |
| --- | --- | --- | --- | --- | --- |
| Existing | 3/4 | 0/3 | 3/3 | 0/3 | 798 |
| Answer-first | 4/4 | 0/4 | 4/4 | 0/4 | 834 |
| Decision-gated | 4/4 | 0/4 | 4/4 | 0/4 | 735 |

The existing-instructions unknown-category attempt failed `LOCAL_JSON` after
238 reported tokens. No partial draft or decision was retained; its exact
validation cause is unavailable. It is not counted as a clarification or a
citation-free readable response. No request was retried. The prior run's 16/16
validity therefore does not establish that formatting is solved for fresh inputs.
All twelve scalar state/value/unit reference checks passed; they do not certify
the generated prose. Eleven readable responses all chose `clarify` without refs.

Technical observations, **not owner ratings**:

- Known seven days: existing and answer-first invent ambiguity between equivalent
  descriptions of elapsed days. Decision-gated explicitly says the answer is
  seven days, yet asks for elapsed days again and cuts off its recommendation.
- Missing interval: existing asks about current subscription and equates absence
  with no contact history. Answer-first questions the supplied count definition.
  Decision-gated asks for the earlier contact date, a relevant direction, but
  its explanation is truncated and does not become an accepted useful response.
- No earlier contact: existing repeats the original question and incorrectly
  describes the prior outcome as a current campaign outcome. Answer-first asks
  for the supplied sentinel again. Decision-gated invents a definition/value
  conflict and returns a truncated statement as its question.
- Unknown default: answer-first initially recognizes that neither yes nor no is
  established, then asks for the supplied value again. Decision-gated recognizes
  unknown but dismisses the user's interpretation question and repeats it.

These additions did not resolve decision selection under this full-context
configuration. This does not establish that all prompt designs fail, that lesson
selection has no value, or which of mission framing, context, model capability
and constrained response design is responsible. No variant is selected for normal
advice. A separate question-focused context comparison is the next diagnostic;
two-stage generation and semantic-validator changes remain separate follow-ups.
Punctuation flags still do not repair truncated explanations. Citation relevance,
coverage, fact consistency of prose, decision appropriateness and usefulness
require review, rather than being inferred from validity or decision labels.

Ignored evidence is under `data/bank-marketing/decision-selection-01/`: preparation
provenance, selected inputs/actions, setup, exact requests/hashes and four saved
runs, diagnostics, results, verification, image pins, trusted scripts, Compose,
HTTP checks and a hash manifest. A preparation-only hashing error on SQLite binary
columns was corrected before any model call. A report-only null diagnostic count
was corrected after generation; neither failure caused a model retry or changed
saved outputs. `data/bank-marketing/decision-selection-review.md` contains all
twelve results, explicit review references and separate blank owner assessment
fields. It is evaluation/development only and is not imported into lessons/SFT.
Earlier review files remain byte-identical. API quality ratings remain empty.

The CPU probe/review image, built from the pinned Python 3.13 Trixie base and
locked dependencies, is
`sha256:2e0662b58371a8db5c4d88fda66e28f76342a27be10e029b0a341712356ae91d`.
The isolated compatible UI is on **localhost:18013**, using a copy of the preceding
lab's schema-7 database and source bytes. Twenty append-only run revisions were
added; every other copied metadata table and source was unchanged. Original bank
and previous lab databases, approved lessons, teaching data, frozen suites, failed
job and active base adviser were verified unchanged.

`make test`: **545 passed**. `make lint`: passed (110 Python files formatted).
The 83 focused reliability tests include nine additional cases for prompt-only
controls, no-lessons requests, explicit selection/mutual exclusion, immutable
hashes, historical compatibility, recovery and adapter failures without retries
or quality credit. Read-only localhost checks passed for health, all twelve
historical/new saved pages (v1/v2/v3), diagnostics and empty review lists; saved
tables remained unchanged. No frontier model, GPU/training job, standalone export smoke
or model promotion ran. Ordinary Test/export still use their existing contracts.

### Question-focused context probe — Experiment B

The owner requested explicit field selection with unchanged instructions, weights,
compact schema, decoding and no lessons. Four new pre-cutoff records were selected
before generation: source rows **27842** (eight elapsed days), **25456** (interval
omitted), **20001** (no earlier contact) and **20007** (unknown default). Original
source values and both full/available input-vector exclusions were checked against
prior development and teaching records. Later frozen records, rubrics and outcomes
were excluded. The selected fields follow the owner's question types: `pdays`,
`pdays` including its absence, `pdays` plus `previous`, and `default`. Complete
original inputs and evidence remain in each immutable run.

The first attempt, preserved under `data/bank-marketing/context-selection-01/`,
was disrupted when the shared CPU inference container was OOM-killed at its 4 GiB
limit (Docker exit 137, `OOMKilled=true`). It recorded eight outbound POSTs, seven
readable outputs and five connection failures across twelve logical attempts.
The eighth POST was interrupted; four subsequent model-identity GETs could not
connect. Its final operator assertion correctly failed because twelve POSTs had
not occurred. These are infrastructure failures, not five model-quality failures.
The exact cause of memory growth was not established; the memory limit explains
the kill but does not identify a leak or a particular schema as its root cause.
No automatic retry occurred, and every saved request/output remains intact.

The shared service was restored without changing its image or configuration. One
explicit separate repeat used a fresh CPU instance with the same pinned image,
model, server defaults and launch parameters, capped at **8 GiB RAM**, with total
memory-plus-swap also 8 GiB, four CPUs and no GPU. The same four preselected records
and field selections were repeated; no new records were chosen after inspecting
results. Per-run case UUIDs differ in the user messages; the saved comparison
verifies context equality after normalizing only those UUIDs. The partial and
complete attempts are not pooled, and their different outputs do not establish
bitwise reproducibility or a causal memory effect.

The following table describes only the complete isolated repeat:

| Arm | Schema valid / attempts | Answer / clarify | Expected-decision matches / attempts | Cited responses / readable |
| --- | --- | --- | --- | --- |
| Full context | 4/4 | 0 / 4 | 1/4 | 1/4 |
| Relevant raw | 4/4 | 1 / 3 | 2/4 | 0/4 |
| Relevant interpreted | 4/4 | 1 / 3 | 2/4 | 0/4 |

Expected decisions (`answer`, `clarify`, `answer`, `answer`) were owner-provided
review metadata and never entered prompts. Matching them does not establish correct
explanations, appropriate questions or useful advice. Both direct answers were
rejected as `ADVICE_SUPPORT` because they supplied no citation. The full known-case
response supplied three accessible references but still asked an unnecessary
question; accessibility does not establish relevance or coverage. The local
verification's `accepted_drafts` field counts outputs retained by existing
experimental validators, not owner approval, factual quality or deployability.

Technical observations, **not owner quality ratings**:

- Known eight days: full context invents a need for a reference date. Both focused
  arms answer eight days, but wrongly attribute the supplied value to retrieved
  definitions and provide no citation. Context changed the selected decision in
  this example; neither answer establishes acceptable grounded advice.
- Missing interval: all arms select the expected `clarify`. The full arm asks for
  already-supplied prior-contact/outcome values. Relevant raw requests the interval
  but truncates its recommendation. Relevant interpreted incorrectly calls absence
  a sentinel and says the case schema lacks a required decision field.
- No earlier contact: full/raw request the supplied prior count again. Interpreted
  recognizes the sentinel and zero count and even includes the answer “No” inside
  its question, while still selecting `clarify` and cutting off other fields.
- Unknown default: all arms acknowledge uncertainty but ask for the supplied value
  again. Full context also incorrectly describes unknown as absence of credit;
  focused outputs still fail to answer the interpretation question directly.

Question-focused context is a plausible contributor to decision behavior in this
small comparison, but it does not resolve the foundation failures. The raw and
interpreted focused arms have the same decision pattern here; no incremental
quality benefit of typed facts is established. No configuration was accepted for
ordinary advice, no lessons were edited and no new supervision was created.
The decision-only schema diagnostic remains deferred; it was not run.

All twelve exact outbound JSON payloads, byte hashes, model alias, system messages,
contexts, full response schemas, `response_format` name/strictness, streaming flag,
and generation parameters were saved and checked against the immutable requests.
The server's `/props` defaults and actual launch arguments were recorded too:
8,192-token context, four threads, zero GPU layers, one slot, Jinja template,
`enable_thinking=false`, no context shift. Its startup `-n 512` default was preserved;
every experiment POST explicitly set `max_tokens=1024`, temperature 0 and seed 17.
The response format was `json_schema`, name `grounded_advice`, `strict=true`,
`stream=false`. No decision-only or unconstrained-decoding request was made.

The full control's citation enum was byte-for-byte the same across each case's
three outbound schemas; focused messages contained only their selected views.
Definition spans, original source and excerpt hashes, all twelve scalar reference
checks, twenty appended run revisions and unchanged other metadata were verified.
Source context sizes were 7,196–7,603 bytes full, 857–1,536 raw, and 1,183–2,238
interpreted. Reported completion tokens summed to 910, 640 and 564 respectively.
Fixed arm order, different context lengths and shared cache within the isolated
runtime prevent treating the saved elapsed times as controlled benchmarks.

The complete evidence is under `data/bank-marketing/context-selection-02/`, with
setup/actions, preparation and repeat provenance, four final runs/diagnostics,
twelve wire records, server defaults/image pins, verification, trusted scripts,
HTTP checks and hash manifests. `data/bank-marketing/context-selection-review.md`
contains all twelve results and blank separate fields for decision appropriateness,
factual quality, internal consistency, supplied-information questions, clarification
relevance, completeness, source attribution, citation coverage and usefulness.
Its notes are evaluation/development only and never automatically enter SFT or
lessons. Previous review files and original/earlier experiment databases remain
unchanged; API human-quality ratings remain empty.

The pinned probe and UI image is
`sha256:c03c2994c8fe441d2c5ed6d297939e69f24ec582adb052b4b46ef3b49bffb007`,
built from the verified Python 3.13 Trixie base and locked dependencies. The review
UI is on **localhost:18014**. Inference remains on an internal Docker network; only
the web service also joins a bridge for the loopback UI binding. The initial
internal-only web network passed container health but did not publish its port;
that UI-only correction was made after all model calls finished. No generation
settings changed for it.

`make test`: **561 passed**. `make lint`: passed (111 Python files formatted).
The 99 focused reliability tests include sixteen additional cases covering reviewed
selection constraints, exact projections/spans, absent fields, immutable full
context, real HTTP-adapter schema equality and exclusion of unrelated message
content, rejection of citations outside a selected view, holdout protection,
compatible adapters, historical formats and recovery without retries. No frontier
model, GPU/training job, agentic trainer or standalone export smoke was used.
Ordinary Test, training, frozen evaluation and exports retain their existing
contracts. At this verification point owner review, reliable behavior and MVP
acceptance remained pending; the subsequent owner review is recorded below.

Read-only localhost checks passed for health, all sixteen saved comparison pages
and diagnostics (v1–v4), and empty human-review lists, with no metadata changes.
The final CPU services and UI were healthy; the isolated repeat was not OOM-killed.
Both experiment attempts have local evidence hash manifests. No raw dataset,
SQLite database, model checkpoint or local review file is a repository change.

### Experiment B owner review

The owner reviewed the twelve complete-repeat outputs and accepted the technical
conclusion: focused packaging changed decision selection, while neither focused
configuration is accepted for deployment. Raw and interpreted focused contexts
matched on decision labels; no additional model decision-selection benefit from
typed interpretations was demonstrated. The independently verified interpreter
remains useful regardless of model behavior. The intervention changed a packaging
bundle, not just unrelated customer fields. Both resource-attempt records remain
separate and their elapsed times are not performance evidence.

The owner identified an attribution error in the known-interval focused output:
the case supplies eight; the dictionary defines `pdays`. A dictionary citation
does not independently verify a customer's stored value. The immutable evidence
model preserves structured inputs separately from reference excerpts and derived
interpretations. No citations are automatically attached to arbitrary prose.
Citation construction and sentence completeness remain unresolved. This review
does not edit approved lessons, establish business lift or create supervision.

### Minimal decision contract — Experiment C

Use `decision_contract` instead of `context_selection`, with the same explicit
`fields`, `rationale` and strict `reviewed: true` selection object. It is mutually
exclusive with every other experiment. Every selected field, including an absent
one, requires an attributed rule. The two ordered arms are `compact_contract` and
`decision_only`. Each makes one bounded CPU generation, with the same base alias,
generation parameters, system message and exact selected interpreted user context.
Only the response schema differs. Full original context, source snapshots, all
field interpretations and verbatim definition spans remain available for audit.

`quartermaster.reliability-run/v5` identifies this comparison. Its minimal wire
contract is exactly `{"decision": "answer"}` (or `clarify` / `abstain`), with no
extra fields allowed. The response schema is captured in every request. No schema
version field is added to the minimal output; the run envelope versions it. The
existing compact arm still uses `quartermaster.advice/v2`, including its version
field, character limits, decision/question branches and citation constraints.
Historical run versions 1–4 remain readable without rewriting their source bytes.
There is no database migration or change to normal Test, frozen replay or exports.

Both arms use a **shared contract-neutral task prompt**, captured verbatim. The
earlier compact system explicitly demands advice/v2 and all its text fields, which
would contradict a decision-only contract. The new shared prompt preserves action
selection instructions and distinguishes case values from reference definitions;
advice/citation instructions are conditional on fields requested by the schema.
It is identical across C's two arms, but differs from A/B. C therefore supports
within-case comparisons, not claims about a prompt-independent improvement over
earlier experiments. It also changes schema grammar topology (compact `oneOf`
branches versus a one-field enum). A difference cannot by itself prove whether
response composition or constrained decoding is responsible. No unconstrained
or multiple-stage model generation is introduced.

A valid minimal label is saved as a draft with **no `advice`**. Citation count and
sentence diagnostics are null, and citation status is **not applicable**. The UI
and API refuse to award this arm factual/citation/advice-quality ratings; record
decision appropriateness in the separate experiment review instead. A correct
action does not prove an explanation, useful recommendation or grounded claim.
Compact outputs retain existing validation, including rejection of uncited direct
answers. No citations are manufactured, and punctuation remains diagnostic only.

The run captures both requests before generation, saves each output durably, and
has the existing 600-second comparison limit. Identity, completion checks and
per-request timeout still apply. Restart/interruption leaves a durable status and
never triggers automatic retries. An incompatible injected adapter is refused
before capture/save. Neither field selection nor expected decisions use another
model. Approved lesson records are audit inventory only, never model context.

#### Recorded CPU comparison

Eight pre-cutoff development records were selected before generation, with explicit
field lists and no model relevance selection. They exclude previously used source
rows, full decision-input vectors and available-field projections (at least nine
shared fields), plus later frozen records and outcomes. Full source hashes and
original values were checked; only the same ten pre-call fields are captured.
Distinct dataset records are not proven independent customers. Expected decisions
below are **operator-drafted development hypotheses for owner review**, not approved
ideal advice, statistical labels or training supervision:

| Question | Source row | Selected fields | Proposed action |
| --- | --- | --- | --- |
| Known interval, eleven days | 29512 | pdays | answer |
| Requested interval omitted | 24615 | pdays, preserving absence | clarify |
| Recorded earlier contact | 22002 | pdays, previous | answer |
| Unknown default category | 22001 | default | answer |
| Prior contact count and its unit | 25998 | previous | answer |
| Reconcile no-contact sentinel and nonzero count into one recording scope | 27780 | pdays, previous | clarify |
| Calibrated subscription probability without a predictive model | 22004 | pdays, previous | abstain |
| Exact future subscription date without forecasting evidence | 22005 | pdays, previous | abstain |

The scope question deliberately asks for reconciliation that the definitions do
not establish; it does not label the source values erroneous or silently repair
them. The two unsupported requests explicitly prohibit further information
collection. They test selection under that stated constraint, not spontaneous
recognition of every unsupported business request. No new generic-domain teaching
examples or lesson changes were introduced.

All sixteen generations completed on one fresh isolated CPU instance capped at
8 GiB memory (memory-plus-swap also 8 GiB), four CPUs and no GPU. The pinned model,
runtime image, launch arguments and server defaults match B's complete repeat.
There were no connection failures, OOM kills, timeouts, retries or extra model
calls. The operator bound was sixteen requests, 180 seconds per request,
600 seconds per comparison and 3,600 seconds total. Compact always ran first, so
elapsed times and cache reuse are not controlled performance measurements.

| Metric | Compact contract | Decision only |
| --- | --- | --- |
| Parseable JSON | 8/8 | 8/8 |
| Strict contract valid (`schema_valid` diagnostic) | 5/8 | 8/8 |
| Raw selected actions | 8 abstain | 8 abstain |
| Hypothesis matches with a contract-valid output | 1/8 | 2/8 |
| Answerable hypotheses matched | 0/4 | 0/4 |
| Clarification hypotheses matched | 0/2 | 0/2 |
| Unsupported hypotheses matched with a valid output | 1/2 | 2/2 |
| Cited contract-valid responses | 3/5 | not applicable |

**The paired raw decision labels are identical on all eight cases.** The apparent
one-label advantage among valid minimal outputs comes entirely from a compact
format rejection on the future-date case. It does not demonstrate better action
selection. Counting all raw labels for diagnostic purposes gives 2/8 hypothesis
matches in both arms, but rejected compact objects remain unusable outputs.
All minimal labels abstain, so the two matching unsupported cases provide no
evidence of discrimination between answerable and unsupported requests.

The three compact rejections (unknown category, scope, future date) were duplicate
citation UUIDs. Their JSON was parseable and generation ended with `stop`; the
post-generation Pydantic contract rejected duplicates. This is not evidence that
JSON syntax failed or a token limit was reached. The historical `schema_valid`
field includes these stricter contract checks, beyond JSON-schema shape alone.
Raw HTTP responses are retained separately so this distinction remains auditable.
No duplicate was removed to turn a rejected output into an accepted one.

Technical observations, not owner quality ratings:

- Known interval: compact repeats that `pdays=11` is supplied, then invents a need
  for current/contact dates and abstains. Minimal also abstains.
- Missing interval: compact reports `absent` but abstains rather than requesting
  the missing interval. Minimal also abstains.
- No history: compact quotes the documented sentinel but claims the evidence
  cannot establish earlier contact. Minimal abstains.
- Unknown category: the rejected raw compact reason is `yes`, despite the explicit
  unknown value; it also repeats its reference UUID. Minimal abstains.
- Contact count: compact identifies value two and unit contacts, then abstains on
  the question asking exactly that count/unit. Minimal abstains.
- Recording scope: abstention does not match the proposed clarification behavior;
  compact is also rejected for duplicate citations.
- Unsupported requests: both raw labels abstain; the probability explanation is
  cut off and contains malformed prose, and the future-date object repeats a
  citation. Correct labels do not establish complete, useful advice.

Every compact recommendation reaches its 240-character cap in the raw response;
two reasons reach 400 characters. None of the five contract-valid compact outputs
passes the all-text sentence-ending diagnostic. Punctuation remains only a signal;
the saved text, including visible mid-thought endings, requires human review.
The minimal arm generates fourteen completion tokens per case (112 total), versus
1,680 total for compact, including rejected responses. This is an output-size
observation, not an advice-quality or controlled latency improvement.

This comparison does **not** show that removing response composition solves
decision selection. Unlike earlier runs' `clarify` pattern, both C arms choose
`abstain`; the shared task prompt differs from A/B, and no causal attribution to
prompt, model or decoder alone is justified. No two-stage runtime, constrained
enum-order study, automatic citation assembler, new lessons, LoRA job or agentic
trainer was added. These results do not justify normal rollout or an MVP tag.

Ignored evidence is under `data/bank-marketing/decision-contract-01/`: input-only
preparation and hypotheses, exact actions/setup, before-database, eight final run
snapshots/diagnostics, sixteen exact outbound request bodies with hashes, sixteen
raw HTTP completions, server defaults and resource/image pins, verification,
trusted scripts, Compose, HTTP checks and hash manifest. A report-only equality
check initially compared a trailing space with Pydantic's documented trimmed
string. Verification was corrected to account only for that trimming; original
response bytes and saved outputs remain unchanged, with no repeated model call.

`data/bank-marketing/decision-contract-review.md` contains all sixteen results,
raw rejected completions, proposed decisions and editable observations. Review
decision appropriateness separately; compact also has factual, consistency,
source-attribution, completeness, citation and usefulness fields. Minimal advice
quality is explicitly not applicable. No owner ratings are inferred from this
technical assessment or automatically imported into API ratings, lessons or SFT.

Verification checked all sixteen exact wire requests and responses, identical
messages/parameters within each pair, all twenty-four scalar states/values/units,
original source/excerpt hashes and selected definition spans. Thirty-two run
revisions were appended; all other copied tables and all seven original/prior
experiment databases and earlier review files remained unchanged. Active base
weights, three approved lessons, training records and protected suites are intact.
The compatible isolated review UI is on **localhost:18015**.

`make test`: **585 passed**. `make lint`: passed (111 Python files formatted).
The 123 focused reliability tests cover strict minimal decoding, exact shared
controls, no advice credit, mutually exclusive selection, holdout protection,
malformed/extra outputs, token-limit and connection failures, adapter preflight,
durable recovery and historical formats. No real GPU/training job, external
builder, agentic trainer, standalone export smoke or normal-adviser rollout ran.

Read-only checks passed for health, all twenty-four saved comparison pages and
diagnostics (v1–v5), and empty API review lists, with every saved table unchanged.
The probe image is
`sha256:7f8b99ff22a367dca7258a44d3c46ceb0f495641039d9a725bdee85a5f3ec74a`.
After generation, one UI sentence was corrected to describe the default
three-request mode accurately. The final review image is
`sha256:3432dd0322c744d4808fc1bc23f43699b7e984249f8380652e6b2d1e6490fdc7`;
both use the verified Python 3.13 Trixie base and locked dependencies. The probe
image, original Compose and completed requests are preserved; inference was not
restarted for this wording change. Final health/resource checks passed without
OOM or GPU use. Source data, databases, raw completions, review files and model
bytes remain ignored local artifacts. Owner review and MVP acceptance are pending.

### Experiment C owner review and schema/label sanity check

The owner reviewed C as a negative decision-selection result: removing composition
did not create discrimination, and recognizing a supplied integer or count did
not establish that the model would answer it. The owner requested a small
representation diagnostic before more prompt experiments, model changes or
architecture. The change from A's `clarify` to C's `abstain` cannot be attributed
to response length alone because the shared task prompt changed too. That review
does not create API quality ratings or supervision from evaluation records.

The operator-only helper `quartermaster/decoding_probe.py` builds five variants
from a captured C minimal request and parses exactly one declared label. It is
not imported by normal advice, training, exports or the application UI. No new
runtime mode, database revision, dependency or service is added for this check.
Three **saved C development contexts** are reused: known eleven days, omitted
interval and unsupported calibrated probability. These are targeted diagnostic
cases, not fresh generalization evidence. Proposed expected actions are
`answer`, `clarify`, `abstain`, kept outside all requests.

| Variant | Representation change | Other controls |
| --- | --- | --- |
| Original | Existing `decision` enum: answer, clarify, abstain | Exact C messages and schema |
| Reversed enum | abstain, clarify, answer | Exact original messages; only enum order changes |
| Codes | `choice` enum A/B/C; mapping A=answer, B=clarify, C=abstain | Adds explicit field/mapping/output examples to the shared task prompt |
| Rotated codes | A=clarify, B=abstain, C=answer | Same code schema/enum; only mapping text changes |
| Plain | One action word; no `response_format` or grammar | Replaces one output-format instruction; same task semantics and user context |

All variants use the pinned base weights, identical focused user context within
each case, no lessons, temperature 0, seed 17 and the same 1,024-token cap. No
output budget was raised. Diagnostic flags are identical throughout:
`logprobs=true`, `top_logprobs=5`, `post_sampling_probs=false`,
`return_tokens=true`, `verbose=true`, `stream=false`. Earlier C did not request
these flags, so the instrumented baseline is reported explicitly. Its three
actions reproduce C's abstentions; no bitwise reproducibility claim is made.

The plain comparison changes its format instruction as well as removing
constraints. Codes change the field name, label tokens and explicit output
instruction/example package. These comparisons cannot isolate a grammar-mask
effect or a label-token preference from every other representation influence.
The rotated-code pair does hold its schema, enum and output examples fixed while
changing the stated mapping. Original versus reversed is a pure enum-order check.

#### Recorded results

Exactly fifteen bounded CPU generations completed on the existing isolated C
service, with its same pinned image, 8 GiB memory/memory-plus-swap, four CPUs,
one slot and zero GPU use. No runtime restart, extra model, training, retry or
normal-adviser change occurred. The probe had a 900-second total bound and
180 seconds per request. Fixed order, reused contexts, prompt-cache effects and
concurrent CPU tests prevent treating elapsed times as performance benchmarks.

| Variant | Known interval | Missing interval | Unsupported probability | Proposed-label matches |
| --- | --- | --- | --- | --- |
| Original | abstain | abstain | abstain | 1/3 |
| Reversed enum | abstain | abstain | abstain | 1/3 |
| Codes | A → answer | B → clarify | A → answer | 2/3 |
| Rotated codes | C → answer | C → answer | C → answer | 1/3 |
| Plain | answer | clarify | answer | 2/3 |

All fifteen outputs ended with `stop`, parsed as exactly one declared label and
had no context truncation. These are classification outputs, not advice, citation
or factual-quality passes. The enum-order reversal changed each recorded grammar
but not its rendered prompt or selected action. No order effect was observed in
this single reversal. Codes and plain text recovered the known/missing actions,
but both failed the unsupported request. Rotating the code mapping changed the
missing-case action incorrectly. This is not a single fixed literal across both
mappings: original codes use A/B/A, rotated codes C/C/C. Neither a fixed-token bias
nor a reliably preserved semantic action explains every pair.

The test establishes **representation sensitivity in this setup**, not a confirmed
decoder defect, a reliable replacement configuration or an inherent inability to
select every appropriate action. In particular, the baseline's all-abstain pattern
is not invariant to the interface. One representation's extra proposed-label match
on these reused cases does not establish general quality improvement or usefulness.

#### Prompt, grammar and token evidence

The exact expanded GBNF was returned in the server's verbose generation settings
and saved for every request; plain outputs have an empty grammar. The original
and reversed grammars allow all three semantic labels in the respective orders;
code grammars allow A/B/C. The actual rendered baseline/reversed prompts are
identical and do **not** render the JSON response schema. It is applied through
the grammar in this pinned setup. Neutral-code prompts explicitly show their
output field, values, mappings and examples. The model-visible contract therefore
differs as well as the tokens/field used to represent its action. This is a reason
to investigate contract communication before inferring that the model cannot use
the supplied facts; it does not establish a server serialization defect.

The server's `/apply-template` outputs were saved before generation, tokenized
with `add_special=true`, `parse_special=true`, `with_pieces=true`, and checked
against each verbose processed prompt. All fifteen prompt-token counts match
server usage. Every generated token ID matches its recorded log-probability
entry and completion count. Actual expanded grammars, full server props/template,
rendered prompts, input pieces/IDs and output IDs/top-five log probabilities are
retained. Pre-sampling token probabilities include alternatives later excluded by
the grammar; they are neither post-mask action probabilities nor calibrated
confidence that a decision is correct. No hidden internal reasoning is inferred.

The inspected protocol is the pinned [server documentation](https://github.com/ggml-org/llama.cpp/blob/1a24df163920a4744a95373d178d790b72a9bb2f/tools/server/README.md)
and request/response source in that revision. The already-cached source archive
matched the Dockerfile's SHA-256
`495fa6f41f7c0d0a68a44e2053c663fb6291fd44a552577039822c02733b9a5c`.
No dataset or case content was sent to an external service for that inspection.

#### Architectural disposition

Keep normal operation unchanged and do not promote codes or plain classification.
This diagnostic found representation sensitivity, so installing a larger decision
pipeline would get ahead of the evidence. Treat **model-visible output-contract
communication** and **semantic sufficiency policy** as separate responsibilities.
The next contract check should control explicit output-field/meaning instructions
before concluding that a decoder or the model weights are the principal cause.
This is a bounded interface investigation, not another unconstrained prompt search.

A subsequent deterministic prototype should cover only explicit, reviewed question
identifiers and attributed field conditions. It should preserve case values,
reference definitions and derived claims separately, expose exactly which rule
matched, and report uncovered/conflicting rules without hidden banking keywords
or model-generated business policy. A deterministic label would not certify later
generated explanations or recommendations. No such router or extra model stage
is installed by this diagnostic. Duplicate-citation prevention also remains a
separate versioned change; strict rejection and historical schemas stay intact.
Lessons, GPU training and the agentic trainer remain deferred.

Evidence is under ignored `data/bank-marketing/decoding-sanity-01/`: the pre-run
`quartermaster.decoding-probe/v1` plan, three original C snapshots, exact HTTP
request/response bytes and hashes, rendered templates, tokenization, per-output
results, expanded GBNF, server props, verification, runtime pins and hash manifest.
There were fifteen generation calls and forty-seven non-generation HTTP calls
for properties, identity, formatting and tokenization. Those metadata calls did
not generate answers. All prior database tables, C snapshots and earlier review
files were verified unchanged. No API ratings, SFT targets or lessons were created.

`data/bank-marketing/decoding-sanity-review.md` contains all fifteen raw outputs,
literal-to-action mappings, explicit technical limitations and editable owner
observations. Its proposed labels and notes remain evaluation/development only.
`make test`: **606 passed**. `make lint`: passed (113 Python files formatted).
The twenty-one focused tests check exact controls, immutable inputs, code remapping,
strict one-label parsing, duplicate/extra JSON fields, invalid literals, unfinished
generations and refusal of unsuitable saved requests. No real GPU/training run,
standalone export smoke, production integration or new architecture rollout ran.

The helper image is
`sha256:a51edeccaae70aaadbf93e8acbd0499f606f7bc24fd9343c79fea2fb47d299fe`,
built with the pinned Python 3.13 Trixie base and locked dependencies. It used the
existing `qm-decision-contract-inference-1` service; no new review UI was started.
Final checks verified its unchanged image/model/launch arguments, healthy state,
resource bounds and all fifteen actual sampling profiles. All nine earlier
database snapshots and previous review files remained unchanged. The evidence
manifest includes the editable review file's initial hash; later owner edits do
not automatically become labels or alter prior diagnostic results.

### One final visible-contract baseline and focused learning preparation

The next owner review changes the earlier training deferral: stop extended prompt
search, run one explicit-contract baseline, then prepare reviewed supervision for
action selection if discrimination is still unreliable. This does not approve
AI-authored labels or change the existing lessons and active weights.

The fixed visible contract and original strict minimal schema produced twelve
valid outputs on twelve new synthetic development requests across four domains.
Every output chose `answer`: four of twelve proposed-label matches, zero proposed
clarify/abstain recall, and four false answers on unsupported requests. The label
references are pending owner review. This is a new baseline with different focused
contexts, not a paired causal estimate against C. There were no further variants,
retries, GPU jobs, training examples imported or runtime promotions.

The [decision-policy experiment preparation](decision-policy-experiment.md) records
the exact contract, limitations, pending owner review pack of sixty separate
AI-drafted synthetic teaching cases, proposed frozen acceptance gates and bounded
candidate plan. The full-advice trainer cannot consume minimal labels; the
separate experimental training boundary remains to implement after review.
No decision-selector stage has been installed in normal adviser operation.
