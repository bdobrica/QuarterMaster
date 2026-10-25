# ADR 0005: Two learning speeds, one captured owner review

Status: Accepted · 2026-10-25

## Context

Reviewed knowledge editing already produced useful changes without training. The old feedback flow nevertheless required separate lessons and separately approved training targets, making the owner repeat work. Independent review/history controls improved usability but did not close the learning loop.

## Decision

Approved knowledge revisions affect retrieval immediately. Weights change only through a separate bounded training run and explicit candidate selection. Show which changed; never call a context edit trained learning.

Capture an explicit accepted or corrected target once and reuse it as teaching evidence, except for protected checks. Notes and skips are not approval. Revisions supersede targets for future selection without altering frozen data. New routing must be durable and idempotent.

Broader inferred policies remain drafts with understandable diffs, conflict checks, approval/rejection and rollback. An explicit personal judgment needs no external correctness benchmark or mandatory general lesson. Local capture works without a builder; external drafting requires consent for the actual minimized payload, including related history. Hosted-advice consent does not cover builder transmission.

## Evidence

- Commit `f00d182` implemented immutable knowledge proposals and controlled before/after replay. A real hosted replay changed the original answer after owner-approved policy replacement; a fresh old-policy answer failed exact-quote validation and remained failed. Both new-policy answers validated and cited the replacement article. The owner accepted the result. This demonstrates context change, not trained generalization.
- Commit `03be122` added append-only answer reviews, readable versions and saved-question reruns. Reviews of reserved questions remained evaluation-only. The owner accepted the revised controls; this was not an uncoached usability study.
- No automatic review-to-training loop or generic numerical teaching was established by those changes.

## Consequences

Retain the working [knowledge edit](../../quartermaster/knowledge_editing.py) and [review](../../quartermaster/answer_reviews.py) foundations. Remove duplicate approval for explicit targets in the new loop, while preserving old ratings as ratings and old hashes as recorded. Migration, direct supervision and recovery remain open in [TODO](../../TODO.md).

Historical sources at `32590b0`: `docs/knowledge-workflow.md`, `docs/knowledge-live-replay.json`, `docs/knowledge-owner-review.json`, `docs/owner-workflow.md`. Full historical reports belong in Git rather than the current owner guide.
