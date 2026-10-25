# ADR 0003: Immutable evidence and separate evaluation

Status: Accepted · 2026-10-25

## Context

Prompt, budget, knowledge and model settings changed during earlier experiments. Attributing a changed answer to training becomes impossible if those inputs drift together. Earlier frozen records and exports must remain reproducible.

## Decision

Keep original source bytes and append revisions for knowledge, reviews, datasets, models and exports. Capture exact prompts, schemas, generation settings, evidence and model identity with each run. Preserve historical serialization and hashes when adding new contracts; never silently replay an old case with current defaults.

Keep decision-time facts, owner targets and later outcomes separate. Explicitly reserved evaluation cases and their corrections cannot enter teaching, synthetic prompts or related-case routing. Existing reservations remain protected. Ordinary question history and replay must have a separate path: saving a question must not silently reserve every future teaching example.

Compare the selected current adviser and candidate on identical captured knowledge, prompts and settings. A knowledge-only comparison measures context changes. Replay of taught examples checks preference consistency; it is not unseen evaluation.

Citations must resolve to accessible original excerpts. Validate identifiers and exact quotes, but do not describe those checks as proof of factual entailment or the model's internal reasoning.

## Evidence and consequences

The training workflow froze checks before later lessons and preserved that earlier context in its export. Attaching newer lessons would have falsified the comparison. Later base exports added a distinct tested-answer path rather than inventing training lineage.

The current app still uses historical `context/v2` training/comparisons and `context/v3` ordinary advice. Preserve both and explicitly align the new generic path. Existing saved questions are reserved checks; migrate deliberately rather than lifting exclusions.

Relevant boundaries: [holdouts](../../quartermaster/holdouts.py), [evaluation snapshots](../../quartermaster/evaluations.py), [generation profiles](../../quartermaster/generation.py), [export contracts](../../quartermaster/contracts/export.py). Historical sources at `32590b0`: `docs/milestone-5.md`, `docs/milestone-7.md`, `docs/response-budget.md`, `docs/working-adviser.md`, `docs/owner-workflow.md`.
