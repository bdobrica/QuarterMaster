# ADR 0004: Useful decisions are separate from valid output

Status: Accepted · 2026-10-25

## Context

Earlier reliability work tried larger output budgets, compact prompts, lesson selection, focused contexts, explicit field definitions, minimal decision schemas, label encodings and decision-only LoRA. Several improved formatting or changed behavior without producing useful advice.

## Decision

Keep strict output/evidence validation and finite generation bounds. Preserve invalid results; do not silently repair JSON, deduplicate citations or promote rejected drafts. Treat format validity, factual support, necessary clarification and owner usefulness as separate checks.

Do not restore the experimental decision-selector pipeline or continue broad prompt sweeps as an MVP prerequisite. Keep its historical contracts/tests for compatibility. Further model work must serve the current reviewed owner-decision loop and isolate what changed.

## Recorded results

| Historical check | Result and lesson |
| --- | --- |
| Output-budget follow-up | A 1,024-token profile improved completion on development cases. A 12-step full-advice candidate still failed structural smoke checks; no deployable candidate was registered. Token fit and low loss did not establish comprehension. |
| Lesson ablation | 16/16 outputs were schema-valid; all chose clarification and none cited sources. Owner review accepted none as fully useful. Supplied lessons alone were insufficient. |
| Focused context and minimal contracts | Narrow packaging helped one decision type; owner review still rejected the advice. Minimal labels and alternative encodings exposed representation sensitivity without establishing a reliable selector. |
| Reviewed decision-only LoRA | On 30 frozen checks, base matched 9 and candidate 10. Both had 30 valid outputs; candidate unseen-domain matches declined from 4/12 to 2/12. Quality/regression gates failed; no promotion. |
| Bounded thinking in ordinary advice | Both base and existing experimental LoRA gave 4/4 validated responses, all clarification, with zero citations on the inspected cases. A working UI/export did not establish usefulness. |

These small, sometimes reused development sets are historical observations, not general accuracy estimates. No single cause of the semantic failures was isolated. The negative selector result does not establish that personal price teaching will fail; it prevents claiming that path already works.

## Consequences and evidence

Reuse the validation and controlled-comparison tools. Require honest before/after owner review and retain the previous adviser when a candidate fails. Do not turn protected failed cases into new supervision or call model percentages calibrated confidence.

Historical sources at `32590b0`: `docs/response-budget.md`, `docs/inference-reliability.md`, `docs/decision-policy-experiment.md`, `docs/working-adviser.md`. Related implementation commits: `8cbcf7b`, `2a711b5`, `7a0df59`, `fea25db`, `2356040`. Raw local experiment artifacts were ignored; the removed reports remain recoverable with `git show`.
