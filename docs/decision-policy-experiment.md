# Decision-only learning experiment

The owner approved the experimental direction after the explicit-contract baseline,
and subsequently approved all seventy-two teaching cases and independently confirmed
all thirty evaluation references. The experiment is frozen. The owner subsequently
authorized one bounded GPU attempt after conversion/comparison integration and CPU
checks pass; those checks and the one-step GPU preflight passed. The single
candidate completed all 120 steps, passed conversion and completed the frozen
comparison. It failed the provisional acceptance gates and remains unpromoted.
Structural inspection or approval of the direction is not individual target approval.
Promotion, lesson edits and normal adviser rollout remain outside this experiment.
Earlier sections record preparation checkpoints; the integration record below
supersedes their pending-execution status.

The question is whether reviewed supervision can teach the pinned 0.8B model to
distinguish `answer`, `clarify` and `abstain` on unseen inputs. Success would
establish a decision-selector result, not useful advice, factual prose, citation
support, calibration or business lift.

## Fixed visible contract

`explicit_contract` in `quartermaster/decoding_probe.py` appends one fixed contract
to Experiment C's shared task instructions. All three action meanings and all
three allowed `{"decision":"..."}` objects are visible. The three objects are
format alternatives with equal treatment, not case-specific labeled examples.
An answer can explain an unknown or negative value. Clarification requires an
obtainable fact relevant to the actual question. Abstention applies when the
requested conclusion is unsupported under the stated evidence and constraints.

The original strict `DecisionOnly` schema, literal labels and enum order remain
unchanged. Generation uses the pinned base model, temperature 0, seed 17,
1,024-token cap, thinking disabled and no lessons. Diagnostic token/log-probability
flags match the preceding schema/label probe. Training must capture **this exact
system text and context serialization**, rather than reconstructing a similar
prompt. Freeze its bytes and SHA-256 before any GPU job.

## Completed baseline

One configuration ran on twelve new synthetic development situations, balanced
across four proposed examples per decision and spread across library, warehouse,
printshop and theater records. The focused input includes the question, supplied
record values and explicitly synthetic definitions. Missing fields remain absent.
Definitions and recorded values stay separate. No bank records, existing frozen
cases, outcomes, teaching targets or approved lessons were read to construct them.
The model receives no proposed decisions, rationales or reviewer metadata.

| Measure | Observed result |
| --- | --- |
| Strict decision-contract validity | 12/12 |
| Returned action | `answer` in every case |
| Matches to proposed development labels | 4/12 |
| Answer / clarify / abstain recall against those labels | 4/4, 0/4, 0/4 |
| False answers on proposed unsupported cases | 4/4 |
| Completion tokens | 72 total; six per case |

The twelve references are **AI-drafted development hypotheses pending owner
review**, not independently approved ground truth. Those provisional scores cannot
be claimed as measured generalization accuracy. The all-answer output pattern is
directly observed. It does not establish a decoding defect or identify a cause.
This baseline uses fresh cross-domain raw focused contexts, unlike the earlier C
records; it is not a paired estimate of contract visibility alone. No further prompt
variants ran. The result justifies preparing the proposed supervised experiment,
subject to reviewed labels and an independent evaluation.

The exact requests, responses, rendered prompts, input/output token IDs,
pre-sampling log probabilities, expanded grammars, runtime settings and integrity
checks are under ignored `data/decision-policy/explicit-contract-01/`.
`data/decision-policy/baseline-review.md` contains every input/output for review.
No new UI service, database migration or ordinary adviser change was introduced.
Times from this sequential cached CPU run are not a latency benchmark.

## Teaching review pack

The original editable local file is `data/decision-policy/teaching-review.md`; original
drafts and the exact system text are in `teaching-drafts-01/drafts.json` and
`system.txt`. There are **60 AI_DRAFT synthetic examples: 20 per decision**, across
parcel shipping, rental records, hotels, repair records and greenhouses. All
sixty reviews start pending. Each includes a question, explicit case values,
synthetic definitions, proposed one-field target, rationale and space for edits.
Use the newer batch index described below for the current review workspace.

The cases cover zero versus missing, explicit negative and unknown values,
sentinels, counts versus intervals, sufficient information despite unrelated
missing fields, simple arithmetic and supplied thresholds. Missing units,
denominators, dates, preferences and conflicting scopes exercise clarification.
Unsupported calibrated predictions, exact future events, causal proofs and
universal guarantees exercise abstention. Many unsupported requests explicitly
limit the available evidence; the owner should check whether these are useful
boundary examples rather than superficial wording shortcuts. Diversity and
transfer are hypotheses to evaluate, not established by the count.

These are separate synthetic teaching situations, not recycled development inputs
or modified protected cases. No evaluation files are read by their preparation
script. Their definitions are invented premises, not external source citations or
real-world verified guidance. Review must establish coherent premises and the
appropriate label. `AI_DRAFT` provenance remains after approval.

Edit each review to APPROVE, REVISE or REJECT, and correct the final decision and
observations as needed. A revised case needs approval of its final content. Review
edits do not automatically import targets, start training or change lessons. Keep
the original draft bytes; freeze a new reviewed snapshot binding each final case,
target, owner review and exact prompt to hashes. Pending/rejected cases cannot
enter SFT. If removals destroy balance or coverage, prepare replacement drafts for
review rather than silently relabeling cases.

At initial draft preparation there was **no approved training JSONL or GPU authorization**. The existing
`training-example/v1`, job consumer and candidate smoke path require full
`GroundedAdvice`; they cannot accept a decision label. Do not weaken those
contracts or disguise labels as advice. The separate experimental contract and
bounded stage runner below prepare this boundary without changing those contracts.
No new runtime service, dependency or normal two-stage adviser was added.

## Batch review and contrast extension

Start with local `data/decision-policy/review-index.md`. Six ten-case batch files
cover DP-001–060; `contrastive-review.md` adds DP-061–072. Initially all **72 cases
were pending**, with 24 proposed examples per class across the same five domains.
All now have hash-bound owner approval in the completed-review snapshot below.
The original sixty drafts, original review file and baseline records are unchanged.

Each of four new groups repeats exactly the same supplied facts and definitions
for three questions: reading a supplied fact, resolving a necessary missing fact,
and requesting an unsupported conclusion. Background phrases about absent models,
calibration and obtainable information appear across all three labels. Only the
question changes within a group. This targets superficial wording shortcuts;
it does not prove that the model will learn the intended policy.

The new review copies also replace sequential DP identifiers in model-visible
synthetic definitions with opaque IDs. The original sixty questions, values,
definition texts and proposed labels are unchanged. This removes an avoidable
identifier/order cue while preserving original bytes for audit. The complete
new system/context/target snapshot is `supervision-review-02/input/pack.json`.
No DP labels, domains, rationales or review notes enter model messages.

Record per-case APPROVE / REVISE / REJECT, final decision and observations. Review
the entire final case, not just the proposed label. Markdown files are workspaces;
there is no automatic approval importer. Reconciliation must reject conflicting
decisions between old and new review files, preserve AI provenance, and bind an
owner approval to the hash of the final case/target before freezing. An edit
invalidates an earlier approval. Pending/revised cases block freeze; explicit
rejections are recorded and excluded, with balance/coverage checked again.

## Separate evaluation review

`data/decision-policy/evaluation-review.md` contains thirty **AI-drafted,
evaluation-only references**, ten per class across five domains. Each domain has
six cases, two per class. Museum and roastery are absent from teaching (twelve
cases). Initially these were **not frozen, approved or run**. They were authored after the
teaching draft snapshot was sealed and checked for exact question/value overlap.
That ordering was not independent human review. The owner subsequently explicitly
approved all thirty final references, as recorded below, before any model output
was generated. The original workspace still preserves technical recommendations
and PENDING markers; the separate owner confirmation supplies approval authority.

No existing protected suite, case or rubric was used to author these drafts.
Do not use the new evaluation inputs or reference labels to generate additional
teaching. Owner revisions must retain the separation; if future teaching changes
are informed by these cases, establish a fresh independent evaluation instead.
Exact overlap guards do not detect all semantic paraphrases or establish population
independence. Original protected suites remain unchanged.

## Freeze acceptance before training

The following are **proposed experiment gates for owner review**, not achieved
results or automatic promotion rules:

| Gate | Proposed requirement |
| --- | --- |
| Structural validity | Every frozen output passes the strict one-field contract; invalid outputs count as misses |
| Discrimination | Macro accuracy at least 90%, with recall at least 80% for each of the three labels |
| Cross-domain transfer | At least 80% accuracy in every evaluated domain, including domains absent from teaching |
| Paired improvement | At least 15 percentage points better than unchanged base on the same frozen inputs |
| Unsupported-answer regression | Zero `answer` outputs on frozen cases labeled `abstain`; report every other false answer separately |
| Clarification regression | No increase over base in unnecessary `clarify` on frozen `answer` cases |

Prepare and independently review **30 new frozen decision-only cases**, ten per
label, across at least five domains, including at least two unseen teaching
domains and ten cases from those unseen domains. Final labels and rationales must
be approved before outputs are inspected. This is a proposed suite size, not a
statistical reliability guarantee. Do not recycle this baseline, earlier lab
development records, their rubrics, or the existing protected suites. Keep original
frozen suites unchanged. Do not reveal new frozen inputs/labels to a teaching
generator or mount them in the trainer. The person drafting teaching examples
should not use protected suite contents to add examples.

Compare base and candidate on identical immutable question/evidence messages,
visible contract, schema and sampling profile. Record all outputs including
invalid ones, the confusion matrix, per-class/per-domain counts, paired case
changes and false-answer errors. Keep owner judgments separate from outcomes.
If base already passes the reviewed frozen criteria, reconsider whether training
is necessary. Do not tune the prompt, labels or recipe after seeing frozen results.
Failure is a preserved experiment result, not an invitation to retry implicitly.

The scorer reports total/correct/invalid counts, a confusion matrix including an
invalid column, each class/domain denominator, all paired label changes and false
answers on both clarification and unsupported cases. It never drops failed outputs.
The macro measure is mean per-class recall (balanced accuracy), equal to accuracy
on the balanced thirty-case suite. The numerical gates remain **provisional
experimental criteria**, not a general reliability claim or promotion rule.

Wilson 95% binomial intervals accompany overall, class and domain results and the
unsupported false-answer rate. They are descriptive under independent-trial
assumptions; authored cases may be correlated and are not a random population
sample. Even zero errors on ten unsupported cases has an upper interval around
28%. Report that uncertainty with raw counts rather than interpreting a zero-error
gate as a safety guarantee. The scorer does not assess advice quality or promote.

## Proposed single candidate and bounds

Use the already pinned `Qwen/Qwen3.5-0.8B` revision
`2fc06364715b967f1860aea9cf38778875588b17`, without the failed bank adapter.
Retain the proven float32, rank-4/alpha-8 `q_proj`/`v_proj`, learning rate 1e-5,
seed 17, batch one and completion-only loss settings. Supervise only
`{"decision":"answer|clarify|abstain"}` plus the tokenizer's end token; no advice,
reason, question or citation fields. Tokenize the exact frozen chat template with
thinking disabled. Reject over-2,048-token examples before training, without
truncating or dropping them silently.

The decision-only recipe is 120 optimizer steps (about 1.67 passes if all 72 rows
are approved at batch one), one candidate, one-hour training deadline, four CPU and
10 GiB host RAM. This is a separate versioned recipe; existing full-advice
quick/standard presets are unchanged. The pinned SFT configuration is checked on
CPU, but the new GPU training path has not run. The hour is an upper bound, not a
duration estimate. More steps do not themselves imply more peak memory, and this
CPU check does not establish memory fitness for the GTX 1660 Ti.
Run a finite hardware/sequence-length preflight first. A timeout or OOM is a
durable failure; no implicit retry, extra epochs or GPU memory guarantee.
Conversion and CPU comparison each get a separate 20-minute deadline. Verify the
adapter, merged GGUF, exact runtime image and source hashes before comparison.
Keep the same pinned Python 3.13 Trixie and tested model/runtime lineage.

The GPU command binds the reviewed dataset hash, frozen evaluation hash, recipe,
image IDs and local artifact locations before execution. Reviews and the execution
authorization are separate records; the current bounded attempt is described below.
Keep weights isolated from normal adviser selection/export. Even passing these
gates requires a separate decision about architecture and full advice quality;
it does not authorize automatic promotion.

## Implemented preparation boundary

`quartermaster/contracts/decision_training.py` defines separate review-pack,
hash-bound example approval, 120-step recipe, job and artifact-manifest contracts.
The captured baseline system SHA-256 is fixed. Contexts permit only the narrow
synthetic question/values/definitions/no-lessons shape. Duplicate context keys,
non-finite values, extra fields and stale approvals are refused. Approved instances
are revalidated, including after nested changes.

`quartermaster/decision_training.py` freezes only resolved, balanced, approved
supervision plus a separately approved thirty-case evaluation. It checks unseen
domain coverage and exact overlap before creating an immutable new directory.
Only `job.json` and `train.jsonl` go in the trainer input directory. The evaluation
file is a sibling, committed by hash; unexpected files in the trainer input are
refused. The frozen bundle described below was created only after all owner reviews
were resolved; the original pending draft packs are preserved.

`quartermaster/decision_worker.py` runs one explicit stage and records immutable
started/completed/failed/cleanup-required files. CPU draft checking accepts pending
teaching only and has no GPU device flag. Reviewed CPU checking requires a frozen
job. GPU preflight and training require both explicit opt-in and an owner approval
record binding the exact job and command hashes, plus verified preceding preflight
records. The later conditional execution authorization is recorded separately below.

The optional `decision-trainer` Docker target uses the pinned Python 3.13 Trixie and
existing locked ML dependencies. Its `trainer/decision_worker.py` independently
loads the reviewed job before GPU work. Future GPU preflight runs one optimizer
step at the longest reviewed sequence, with a 300-second bound and no saved
candidate. The training stage starts fresh and is capped at 120 steps/3,600 seconds.
Containers have no network, a read-only root, four CPU, 10 GiB RAM and finite PID/
temporary-storage bounds. Host timeouts add 30 seconds for process handling, and
cleanup targets only the named experiment container. Failed attempts cannot be
silently rerun into the same stage directory. At that preparation checkpoint the
GPU paths had not yet executed; the later authorized run is recorded below.

The initial runner stopped at an isolated adapter manifest. The subsequent integration
adds decision-specific GGUF verification and a paired frozen CPU generation harness;
the scorer alone was not sufficient.
No candidate is registered in ordinary adviser selection or exports.

## Baseline verification record

`make test`: **609 passed**. `make lint`: passed. The focused probe suite's
24 tests include the visible-contract control: only system instructions change;
schema, input bytes, sampling and strict label validation stay fixed. Twelve
real CPU generations completed with no truncation, retry or resource failure.
Rendered templates match the server's processed prompts, including its normal
outer-whitespace trimming. Input/output token counts, expanded grammar and actual
sampling parameters were verified for every response. Nine previous experiment
databases, saved C snapshots and all previous bank review files remain unchanged.
The inference service remains healthy on the same pinned model/image and launch
arguments, with an 8 GiB memory limit, four CPU and no GPU device access.

The two local review files are editable; initial hashes are preserved in the
evidence manifest. No real GPU run, training, new standalone export smoke or
normal adviser rollout ran. At baseline completion, the independent frozen selector
suite, experimental trainer boundary and concrete GPU command were still pending.

## Supervision-preparation verification

The subsequent review-preparation change passes **633 CPU tests** and `make lint`.
Twenty-four focused tests cover pending/revised/rejected review transitions, stale
approval hashes after case changes, balanced selection, evaluation reuse, unseen
domains, frozen file integrity, unexpected trainer mount contents, strict context
and label validation, invalid generations in scores, descriptive uncertainty,
resource/authorization guards, durable timeout/cleanup failure and no automatic
retry. Tokenizer tests preserve the captured prompt and reject overlength rows;
recipe checks refuse a drift back to twelve steps.

The first fresh CPU container checked all seventy-two pending drafts. After input
validation and the explicit CPU recipe check were completed, a separate final-image
smoke check used an unchanged copy in `data/decision-policy/cpu-preflight-final/`.
Earlier reports remain intact. Both checks are tokenization/configuration checks,
not model generations or training attempts. The GPU recipe's memory fitness and
one-hour training completion remain unverified until a separately authorized GPU
preflight/run. No protected suite or active adviser was modified.

The final tested image is
`sha256:92435d6344b0339c22da632aaa055cd60b728cef513617804f97b38c3a790e84`.
Its completed CPU report confirms the exact 120-step, batch-one, completion-only,
float32 configuration and all seventy-two sequence lengths (508–554 tokens).
It has not passed a GPU memory/training test. The commands executed were:

```sh
docker build -f trainer/Dockerfile --target decision-trainer -t quartermaster-decision-trainer:review .
uv run --locked python -m quartermaster.decision_worker cpu-drafts \
  --bundle data/decision-policy/cpu-preflight-final \
  --base data/spike/base-2fc06364715b967f1860aea9cf38778875588b17 \
  --image sha256:92435d6344b0339c22da632aaa055cd60b728cef513617804f97b38c3a790e84
```

The existing completed stage directory deliberately prevents repeating that
command into the same record. Any later CPU check of changed reviewed inputs
needs a new recorded bundle; it does not reuse draft CPU success as GPU clearance.

## First owner review checkpoint

The owner completed all six ten-case batch files, approving **DP-001–060** with
per-case observations. The final questions, supplied values, synthetic definition
texts and labels are unchanged. This records twenty approved examples per class
across the five teaching domains, with `AI_DRAFT` provenance retained. Notes remain
audit metadata and do not become additional model instructions or lessons.

The new local `data/decision-policy/supervision-owner-review-01/` snapshot preserves
the exact six owner-edited files, each source hash, final content-bound approval
and observations. `pack.json` carries sixty approved and twelve pending records;
the original draft pack and editable review files remain intact. Reconciliation
verified that all model-message and target bytes are unchanged by adding reviews.
The processing timestamp records import time, not an invented human review time.

At that checkpoint the contrastive file had twelve PENDING entries, and the separate
evaluation file had thirty PENDING references. The older aggregate teaching-review.md
also remained pending; its untouched draft markers did not revoke the six explicit
batch approvals or approve any other case. No conflicting completed review was
found. The derived review index now points to the recorded approvals and remaining
files. Do not discard pending contrasts to bypass review. No frozen job, training
JSONL, GPU preflight, training, promotion or active-adviser change was made.

## Completed review and frozen experiment

The owner subsequently approved DP-061–072 individually. Evaluation file notes
recommended approval while explicitly leaving independent owner confirmation
pending. The owner then explicitly confirmed **“Approve DE-001–DE-030 as reviewed”**
in response to a question scoped only to evaluation references, not GPU execution.
That confirmation resolves the independent review; the technical recommendations
are preserved without attributing their authorship to the owner.

`data/decision-policy/owner-review-complete-01/` records the source files, exact
confirmation, content-bound approvals and prior-review lineage. All 72 teaching
cases and 30 evaluation references are approved, with unchanged case facts,
definitions, labels, model messages and `AI_DRAFT` provenance. Previous snapshots
and owner-edited workspaces remain intact. The current index and
`current-experiment.json` point to the authoritative completed review and frozen
bundle; old PENDING draft markers do not reverse recorded owner confirmation.

The immutable job is `6ef32a9c-c449-4dd9-bff0-72d8a5e87069`, under local
`data/decision-policy/decision-experiment-01/`:

| Artifact | SHA-256 |
| --- | --- |
| Job | `62d007d47bb9121223812a274b4d3ac077841b49f7acc0243e70627135eea2b5` |
| Training JSONL | `ae37c69976322a98c24073eeacbe2a14ceafba9565640b5b93d0b6e0b9a2b953` |
| Frozen evaluation | `ec2d07424c9dabfc89287585a1b20460d40b1f7e351e7e29c84e49cc59083b0d` |

The dataset has 24 approved targets per class. The evaluation has ten per class,
five domains and twelve cases in the two unseen teaching domains. Only `job.json`
and `train.jsonl` are mounted as trainer input; evaluation records remain a sibling
file, referenced only by hash. `comparison-plan.json` captures the strict minimal
schema, fixed generation profile/system, base/runtime lineage, provisional gates
and scorer source hash before any evaluated model output is generated.

The frozen job's actual CPU preflight passed using the previously tested image:
all 72 rows fit at 508–554 tokens; the 120-step CPU SFT configuration check passed.
Its prompt/target token diagnostics match the earlier draft check exactly. This
does not check GPU memory or start optimization. The 24 focused decision-training
tests passed again; no application code changed during review reconciliation.

At review completion, **GPU execution remained unapproved** and no GPU preflight,
training, evaluation generation or promotion had run. The subsequent integration
and explicit conditional execution authorization are separate from those approvals.
Existing development baseline reference labels remain separate from this newly
approved frozen suite and outside SFT.

## Conversion and comparison integration

`decision_artifacts.py` verifies the separate decision manifest, frozen job/dataset
hashes, exact PEFT recipe, adapter file hashes and safetensors framing. Full-advice
jobs retain their original contract; only their existing LoRA structure checker is
shared. The decision consumer additionally checks finite, nonzero LoRA updates,
uses the established text-only `safe_merge=True` and Q8_0 converter, then binds the
GGUF/license hashes to the unchanged decision contract and original training
manifest. Conversion has no GPU device access and a 1,200-second deadline.

`decision_comparison.py` validates the original frozen plan and creates a separate
generation-only file containing exact questions, context, system, schema and
parameters. Neither reference labels nor teaching data enter the comparison
containers. Each CPU arm mounts only its model, those identical inputs and its
own output directory. It checks model bytes and runtime identity, retains exact
requests/raw responses, rendered prompts, grammar and token diagnostics, and
rejects incomplete responses, altered decoding settings, duplicate keys or extra
fields. Every frozen case remains in the denominator, including missing records,
timeouts and container failures. Cleanup failures also prevent an experiment pass.
The shared comparison deadline is 1,200 seconds with at most sixty generations;
there are no generation retries, candidate registration or promotion.

The trainer mounts only the verified base, `job.json`/`train.jsonl`, and its empty
output directory. Evaluation is a sibling outside all mounts; an ancestor mount
that would expose it is rejected. The trainer image includes no review/evaluation
data. Tests exercise that boundary and byte-for-byte prompt/target preservation.

Verification: **657 CPU tests passed** (`make test`); `make lint` passed. The ninety
focused decision/conversion/training tests include a deterministic paired harness
with valid results, duplicate/extra fields, wrong identities, context/output
truncation, decoding drift, request timeouts, missing outputs and cleanup failure.
An additional real CPU smoke safely merged deterministic fixture LoRA weights,
converted an 811,843,232-byte GGUF and loaded/generated from it in a fresh isolated
container. It is explicitly a compatibility fixture, not training or a candidate.
The comparison runtime's llama-server binary matches the earlier runtime byte for
byte (`838ba6ec3c451098b939c7baecb2b698fcaa913b516c6540fd06f3ed0a77a86c`).

## Authorized bounded attempt

Local `data/decision-policy/decision-experiment-02/` preserves exact copies of the
original frozen job, training JSONL, evaluation, freeze and comparison-plan bytes.
It is a new execution record with the same job and data hashes, not a new split or
revised target set. The original `decision-experiment-01/` remains unchanged.

The owner explicitly instructed: “Once those checks pass, proceed with the GPU
attempt.” After those checks passed, `execution-checks.json`,
`reviewed-command.json` and `gpu-authorization.json` bound that conditional
authorization to the actual artifacts and exact command hashes. This does not
claim that the earlier label approval authorized GPU work or that the owner
manually authored the generated command record.

| Component | Pin or bound |
| --- | --- |
| Decision trainer image | `sha256:35ae9b8d5c944fc2d8b19f51069ef15235555f90570cd773229aabbd74bb102f` |
| Decision CPU runtime image | `sha256:1c13d385f1772ab2cafd3cc0ae38239eecce385ed38cf9e26ef6847063a71014` |
| Base snapshot manifest SHA-256 | `49d2dc89728943d410ab258048d49815d5844245287342c250798ba9b040de1d` |
| GPU preflight command SHA-256 | `9b4c30315584dc8244d8b39a6f3b1f2d1476f51ccc47e41bc3a74bbd5f046a12` |
| Training command SHA-256 | `a8c8a82b86924b9409a23c7969493ceeca9799703f62f6ad6242e71a8efadec1` |
| GPU preflight | One optimizer step at the longest reviewed sequence; 300 seconds |
| Candidate training | Fresh base, 120 steps maximum, 3,600 seconds |
| Trainer/converter resources | Four CPU, 10 GiB RAM/total memory+swap, 128 PIDs, 2 GiB temporary storage, no network |
| CPU comparison resources | Four CPU, 8 GiB RAM/total memory+swap, 128 PIDs, no network or GPU |

Host stage timeouts add thirty seconds for process handling, followed by targeted
container cleanup. Existing attempt directories refuse reuse. Progress events are
append-only and contain only step/timing/memory diagnostics. A timeout/OOM is a
durable failure and does not authorize another run or expanded limits.

The one-step GPU preflight completed successfully on the longest 554-token row,
with 4,728,545,280 peak allocated VRAM bytes against 6,442,123,264 reported total
bytes. This is allocator telemetry, not a measurement of total/reserved device
memory or a guarantee that every training step fits. It created no candidate.

The exact operator invocations dispatched were:

```sh
uv run --locked python -m quartermaster.decision_worker gpu-preflight \
  --bundle data/decision-policy/decision-experiment-02 \
  --base data/spike/base-2fc06364715b967f1860aea9cf38778875588b17 \
  --image sha256:35ae9b8d5c944fc2d8b19f51069ef15235555f90570cd773229aabbd74bb102f \
  --gpu-mode wsl --run-gpu \
  --authorization data/decision-policy/decision-experiment-02/gpu-authorization.json

uv run --locked python -m quartermaster.decision_worker train \
  --bundle data/decision-policy/decision-experiment-02 \
  --base data/spike/base-2fc06364715b967f1860aea9cf38778875588b17 \
  --image sha256:35ae9b8d5c944fc2d8b19f51069ef15235555f90570cd773229aabbd74bb102f \
  --gpu-mode wsl --run-gpu \
  --authorization data/decision-policy/decision-experiment-02/gpu-authorization.json
```

These are recorded invocations, not instructions to repeat completed stages.
The authorization record binds their generated Docker argument arrays by hash;
the immutable stage directory also prevents repetition. A live isolation check
confirmed the actual trainer's four mounts, disabled network, read-only root,
four-CPU/10-GiB bounds, and absence of evaluation files inside `/input`.

The single fresh-base training stage completed all 120 optimizer steps. Its
completion-only training loss was `0.1555226505578806`, with
`4,738,343,936` peak allocated VRAM bytes. The last progress event was at about
330 seconds on the training worker's clock (this excludes preceding orchestration
and is not an inference latency benchmark). These are execution diagnostics,
not evidence of generalization or advice quality.

The decision training manifest SHA-256 is
`60f4c9dafc97c3e3482193f69ee6e1f4faf9949722f5bff0ed8238f942dc5034`;
the adapter safetensors SHA-256 is
`ea1f34226f1b316d4fe6fc60a3dd3e82a7e8c2d7458c9e4ea54352f3a4115863`.
The adapter retains the original job, dataset, pinned base and decision-only
recipe. No full-advice manifest was substituted or registered as an adviser.

The verified CPU conversion completed as an 811,843,232-byte Q8_0 GGUF, SHA-256
`6bed83199e1f551793c2dfbb49a2748ae22b7b162c9bc6071a7a349eec358fd2`.
Its conversion record binds the original job, dataset, system/response contract,
training manifest and unchanged model license. The original base GGUF remains
`c85ac7c9cb8ecb014270ee852dd9580cff838ad294120c6dabfb41f5be29b004`.

The CPU conversion and comparison invocations are:

```sh
uv run --locked python -m quartermaster.decision_worker convert \
  --bundle data/decision-policy/decision-experiment-02 \
  --base data/spike/base-2fc06364715b967f1860aea9cf38778875588b17 \
  --image sha256:35ae9b8d5c944fc2d8b19f51069ef15235555f90570cd773229aabbd74bb102f

uv run --locked python -m quartermaster.decision_comparison \
  --bundle data/decision-policy/decision-experiment-02 \
  --base data/spike/base-2fc06364715b967f1860aea9cf38778875588b17 \
  --base-gguf data/local-model/model.gguf \
  --image sha256:1c13d385f1772ab2cafd3cc0ae38239eecce385ed38cf9e26ef6847063a71014 \
  --output data/decision-policy/decision-experiment-02/comparison
```

## Frozen comparison result — candidate not accepted

All sixty generations completed under the bounds: thirty base and thirty candidate
responses, with **no invalid outputs** or execution/cleanup failures. The final
audit confirms unchanged frozen source bytes and operational code, identical
rendered prompts, expanded grammars and actual generation settings between arms.
Evaluation labels remained outside training and generation inputs. No retries ran.

| Measure | Unchanged base | Attempted LoRA |
| --- | --- | --- |
| Strict valid outputs | 30/30 | 30/30 |
| Correct reviewed decisions | 9/30 (30%) | 10/30 (33.3%) |
| Correct `answer` references | 9/10 | 5/10 |
| Correct `clarify` references | 0/10 | 3/10 |
| Correct `abstain` references | 0/10 | 2/10 |
| False `answer` on unsupported requests | 10/10 | 7/10 |
| False `answer` on clarification requests | 10/10 | 6/10 |
| Unnecessary `clarify` on answerable requests | 1/10 | 5/10 |
| Correct unseen-domain decisions (museum/roastery) | 4/12 | 2/12 |

The candidate changes the output distribution (18 `answer`, 9 `clarify`, 3
`abstain`, versus base 29/1/0) but improves by only **one case, 3.3 percentage
points**. It passes the structural gate and fails every proposed quality,
improvement and regression gate. Cross-domain transfer is not established;
performance on the twelve unseen-domain cases declined. Low training loss does
not establish a learned transferable decision policy. No cause is isolated here,
and no new recipe, prompt, model or retry was selected from these results.

Overall descriptive Wilson 95% intervals are approximately 16.7–47.9% for base
and 19.2–51.2% for candidate. Full class/domain intervals, confusion matrices,
paired changes and raw records are in local
`data/decision-policy/decision-experiment-02/comparison/comparison.json`.
The authored cases may be correlated; these intervals and this small suite are
not a broad reliability estimate or evidence of business lift.

The active adviser stays on the base model. The attempted adapter/GGUF, exact
commands, progress/failure records and hashes are retained without registration
as an ordinary adviser candidate or export. The original approved lessons and
protected suites are unchanged. No additional GPU run or promotion is implied.

`data/decision-policy/gpu-attempt-review.md` presents all thirty questions,
approved expected labels and both raw minimal outputs, with per-case and overall
spaces for owner observations. These pending model-result reviews do not revoke
the earlier case/label approvals or turn evaluation records into supervision.
Local `decision-experiment-02/status.md`, `final-audit.json` and
`verification-manifest.json` summarize and hash the retained execution record.
