# ADR 0009: Show the response contract and separate facts from runtime metadata

Status: Accepted · 2026-10-25

Supersedes ADR 0008's prompt choice for newly prepared teaching jobs and configured advisers
using the base. Selected adapters retain the prompt captured in their original training job.

## Decision

Use `context/v6` for the new owner prediction path. Describe every response field, its order,
the requested unit/choices and answer/clarify/abstain semantics in the visible instruction.
llama.cpp's response schema constrains decoding but is not included in the model's prompt;
see the [pinned upstream documentation](https://github.com/ggml-org/llama.cpp/blob/1a24df163920a4744a95373d178d790b72a9bb2f/grammars/README.md#json-schemas--gbnf).

Give the model compact case facts, the owner's policy, source excerpts and separately labelled
previous owner decisions. Retain the complete case, source identities/hashes and original
provenance in the immutable input snapshot. Keep later outcomes out of the prompt. Empty source
excerpts do not invalidate supplied case facts; personal preferences need no market validation.
Clarify only for obtainable details that could change this decision. Unknown conditions are
neither false nor zero. An impossible request calls for abstention, not a request for unknowable
future information.

Generate the brief owner-facing explanation before the typed target. For an explicit numerical
calculation, the explanation states the result and the target must agree. This is an explanation
of applied facts/policy, never a claim to expose internal reasoning. Use the same field order
for new supervised completions and the response grammar. Keep the bounded, non-thinking
1,024-token generation parameters and existing model selection/training authorization boundaries.
Historical context-v4/v5 systems, schemas, completion bytes, jobs and exports keep their meaning.

## Evidence and limits

The opt-in [local capability check](../../tests/smoke_prediction_reliability.py) uses synthetic
development policies with explicit arithmetic/choice rules. Expected answers never enter the
model prompt or training. It checks correct values/choices, relevant clarification, irrelevant
unknowns, conditional adjustments and unsupported outcomes; it records final responses and
runtime, without hidden reasoning. These controls are not unseen accuracy, an external benchmark
for owner preferences or evidence of LoRA improvement.

On the original ten controls, the pinned 0.8B base improved from **1/10 with context-v5 to 8/10
with context-v6**, but still mishandled an unknown repair condition and an irrelevant unknown.
The separate pinned 2B capability check passed **10/12** including time-allowance controls, but
still failed unknown repair needs and an unknown item count. Neither result clears the full
demonstration gate. Native-model checks also showed semantic errors, so valid JSON or a model
size increase alone is insufficient. No diagnostic model or candidate was promoted.
