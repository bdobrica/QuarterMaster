# ADR 0011: Preserve bounded recipe experiments without promoting failed defaults

Status: Accepted · 2026-10-26

Extends ADR 0010 with a retained experimental recipe version. Its recipe-v2 default, base pin,
NF4 precision and inference/export profile remain unchanged.

## Decision

Retain `lora-recipe/v2` for ordinary new 4B improvement requests. Preserve the completed
experimental `lora-recipe/v3` job and its fixed learning rate `0.0002`, without offering it as a
new default or owner parameter. Both retain rank 4, alpha 8, q/v targets, seed 17, completion-only
loss, 2,048-token maximum and 12/48-step, 20/60-minute training bounds. Owners choose a time allowance, never optimizer
parameters. Execution and promotion remain separate explicit actions.

Recipes v1/v2 retain `0.00001` exactly, including newly prepared v2 jobs. Validate each frozen
job against its captured recipe version; never regenerate old job bytes with a new default. The trainer consumes that
captured rate. Its v3 capability label is required for v3 jobs and also permits unchanged v2
jobs; an old v2 image cannot execute v3. Original full-precision v1 behavior is unchanged.

This is one bounded optimization change, not a new trainer or an inference-profile change.
Training still starts from the exact pinned base; merge reloads that original base before Q8_0
conversion. Context-v6, non-thinking generation, model compatibility and export-v5 remain intact.

## Motivation and verification

The original twelve-step run had correct completion masks, complete price supervision and no
truncation. A read-only GPU probe found only small teacher-forced likelihood changes. A later
48-step v2 run on three actual owner prices completed structurally but returned zero for all
three candidate prices. More steps at the old rate did not establish useful personalization.

The official [TRL PEFT integration guidance](https://huggingface.co/docs/trl/peft_integration)
uses `2e-4` for LoRA SFT; its [SFT guidance](https://huggingface.co/docs/trl/sft_trainer) also
explains that adapter training generally uses a higher rate. That motivates a controlled
experiment; it does not establish quality for this adviser.

The controlled v3 job preserved byte-identical training rows, owner targets, decision context,
teaching snapshot and captured base selection from the v2 job. All three sequences fit
(1,740–1,835 tokens). It completed 48 real GPU steps on the same RTX 2070 SUPER and verified
finite nonzero adapter tensors, safe merge and Q8_0 conversion. Training loss alone is not an
acceptance criterion. The matched free predictions were:

| Taught case | Owner EUR | Base EUR | v2 candidate EUR | v3 candidate EUR |
| --- | ---: | ---: | ---: | ---: |
| Șandulești | 110,000 | 0 | 0 | 100,000 |
| Needs renovation | 70,000 | 9,000 | 0 | 70,000 |
| Topolovăț | 100,000 | Abstained | 0 | 100,000 |

No price target or previous reviewed decision was inserted into its own replay prompt. The v3
candidate reproduced two prices exactly and missed the third by 10,000 EUR, but its explanations
failed: it called floor 2/10 the top floor, reversed a risk rationale, called floor 2/4 the bottom
and repeated sentences. These results support improved taught-price fitting, **not useful
personalization**. The candidate remains unselected. The original weak runs are retained.

On a different saved listing (52 m², floor 6/10), both arms received the same captured current
owner goal, knowledge and three previous reviewed decisions at sixteen serving threads. The
base proposed 85,000 EUR but incorrectly applied a ground-floor penalty. With area removed it
asked for area and gave no target, although its explanation retained the floor error. The v3
candidate gave 110,000 EUR in **both** cases, copying the ground-floor Șandulești explanation
verbatim onto the different apartment. It failed the necessary missing-information behavior.
Neither new proposal has an invented owner label. This is observed overfitting and a reason to
reject v3 as a default, not to promote it because two training prices match.

The bounded-thinking diagnostic also did not establish dependable owner judgment. Preserve the
shared non-thinking generation profile. Clearer goal instructions are context changes and did
not eliminate these factual errors. Do not disguise them with output-value clamps or fabricated
training labels.

The finite GPU run and CPU boundary tests verify execution, historical readability and fixed
bounds. The v3 candidate’s version-5 package also passed fresh isolated offline CPU Compose with
no builder database, provider or GPU. This is a runtime compatibility check, not a quality gate.
Focused CPU checks passed (87), the full CPU gate passed (953; 7 skipped, 2 deselected), and
lint passed. Actual artifacts and final answers remain private under `data/rehearsal-20261026/`;
`recipe3-replay-assessment.json` and `final-owner-comparison.json` record exact errors. No existing model
or original source bytes were rewritten, and no candidate was selected.

## Limits

Three personal judgments cannot establish general valuation quality or independently identify
every policy's numerical effect. Taught-case replay measures preference consistency only.
A different saved listing has no invented owner target. Missing-information checks must clarify
without a target when a necessary obtainable detail is absent. Source claims, owner assumptions
and previous reviewed prices remain distinct; no objective market validation is required.

Knowledge/goal corrections affect context immediately and are not weight-learning gains.
Keep candidates unselected until the owner reviews the concrete comparison and explicitly
chooses a version. A successful GPU run, schema-valid reply or offline startup alone is not
proof that the model learned useful personal judgments.
