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
certifies free text. Owner quality review, reliable development behavior, a fresh
frozen comparison and normal v2 integration remain pending.
