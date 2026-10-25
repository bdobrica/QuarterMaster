# Owner workflow usability repair

Implemented on 2026-10-25 following the owner's UI review. Implementation, browser verification and owner acceptance are recorded in [TODO.md](../TODO.md#p0--repair-the-owner-workflow-next-before-more-training-features).

## Everyday use

- **Adviser:** ask a question, inspect its sources, and choose Pending, Reviewed: Pass or Reviewed: Fail. A technical failure cannot be marked Pass. Recording a rating or correction does not create a lesson or change the adviser. Open **Draft a teaching improvement** for a separate draft/review/approval flow on eligible questions, including failed responses. Recorded corrections are available there without retyping.
- **Knowledge:** read articles and review edits. Versions appear as v1.0.0, v1.1.0, etc., with Current/Previous and change summaries in history. **Check this change** compares the earlier question with itself before/after and another example with itself before/after. It explains why both checks matter and discloses four requests before running.
- **Improvements:** a wide **Saved questions** table shows expectations, latest answers, review status, knowledge version, local time and earlier answers. Filter Pending/Pass/Fail, open/correct an answer, or select questions and preview a rerun. Earlier answers retain their reviews; new answers start Pending.

**Save as check question** is available without creating a check set first. The owner writes the expectation; the app groups questions into draft Saved questions sets, up to the existing ten-question limit. Saving permanently excludes the situation from training. Asking or rating once does not require saving. Existing demo questions appear here too; placeholder records say Not run yet.

A protected check answer can still be reviewed and corrected. That correction is evaluation-only: it does not enter lessons, training or builder prompts. A link offers a separate general-policy edit without copying protected material. Questions already used for teaching cannot be reserved as unseen checks. Review histories are append-only and visible on the answer, including a return to Pending.

## Advanced use

Training uses approved examples and a separate check set. A reviewed draft check set is captured automatically when the owner explicitly queues training; the short bounded recipe is the default. Steps and alternative recipes are collapsed under Advanced. Queueing does not start the GPU worker, promote a candidate or retry work. Missing prerequisites link to question review and check-set management. The existing API still accepts explicit recipes and frozen snapshots.

**Technical diagnostics** is labeled for operators, explains its purpose, links back to the adviser, and collapses experimental configuration and structured output. Existing historical experiments and detailed comparison ratings remain accessible.

## Identity and storage

UUIDs, source hashes, immutable source bytes and UTC timestamps remain unchanged internally. Knowledge labels derive from immutable project history in insertion order: the first revision is v1.0.0; each later content/selection revision increments the minor number. Model candidates use an independent Model v1.1.0, v1.2.0 sequence; the base is v1.0.0. These labels identify releases, not compatibility or quality guarantees. Technical identities remain available in details and APIs.

Dates use the browser's timezone with an explicit zone label. Hover exposes the exact UTC timestamp. Without JavaScript, the server renders a readable, explicitly labeled UTC fallback. No timezone preference or framework dependency was added.

Database migration 8 → 9 adds only append-only answer review records, with optimistic revision checks. Reviews identify the exact test response, evaluation output, candidate comparison side or diagnostic output. Historical runs, training exclusions and source records are preserved. The local database was backed up before updating the running app.

## Verification

- `make test`: **711 passed**, including migration preservation, strict review inputs, stale updates, project isolation, correction-on-failure, reserved-question exclusion, rerun preview/history and guided training with no GPU execution.
- `make lint`: passed. Additional focused checks covered the final review-history and template changes.
- Chromium walkthrough against an isolated synthetic project with a fake model: Fail → correction → save question → preview/rerun → approve knowledge → two Before/After pairs → Pass → Pending. Checked hidden advanced training/diagnostic controls, local date boundary conversion and no-JavaScript UTC fallback. Screenshots were inspected locally, not committed as product evidence.
- Chromium read-only checks of the actual local print project: Knowledge, Improvements, Adviser, Train, Check sets and Technical diagnostics returned HTTP 200, displayed readable versions and had no JavaScript errors.

No hosted model calls, builder drafting, GPU training or new export-container run were performed for this UI change. Browser automation demonstrates the controls work; it does not establish that an uncoached owner finds them intuitive. After reviewing the revised app, the owner confirmed “Yes, all good.” and requested the commit. This records owner acceptance; a separate uncoached-user study was not performed. Advanced training target editing and historical diagnostic experiments still contain technical language.
