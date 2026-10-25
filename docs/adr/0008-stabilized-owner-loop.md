# ADR 0008: Connect typed feedback without rewriting historical teaching

Status: Accepted · 2026-10-25

Supersedes ADR 0007's prompt choice for newly configured advisers. Historical `context/v4`, training jobs and exports retain their captured prompt, schema and parameters.

## Decision

Keep Collect, Teach, Ask and Review as the four primary activities. Save the answer kind and unit/choices once in an append-only adviser revision. An absent format is omitted from serialization so old artifact hashes remain verifiable. Previously selected collection input fields are reusable defaults, still editable by the owner.

Saved HTML becomes a text-only capture in Muster's existing extraction/review/publication pipeline. Keep exact uploaded bytes and the optional declared original address; never execute HTML, fetch its resources or manufacture screenshots. Format-1 publications continue to enumerate actual files; text-only capture metadata explicitly has no screenshot. The adviser-bound Start teaching action publishes checked material, imports its verified bundle and activates unambiguous knowledge. Unfinished work and conflicting article titles require review. Original publications and decisions are preserved.

Store typed reviews separately from historical Pass/Fail advice reviews. Accept and Correct append an explicit number/category judgment, linked to the immutable original input, result, source snapshots and model/knowledge configuration. Note and Skip append history without a target and do not revoke a prior explicit judgment. An identical retried submission returns the same review; stale changes conflict. Saving feedback and selecting eligible teaching data require no provider or GPU. Reserved cases remain reviewable but cannot become teaching evidence.

`teaching-dataset/v2` extends the public snapshot with reviewed prediction lineage alongside existing collection decisions. `training-job/v2` accepts either teaching snapshot version; historical dataset-v1 bytes and supervision retain their meaning. Latest explicit reviews replace earlier targets only in future selections; frozen snapshots never change. Recheck holdout eligibility on capture, snapshot and training dispatch. Prevent reserving already taught situations as unseen checks.

Ask retrieves knowledge excerpts and up to three lexically relevant reviewed decisions from the complete latest teaching history. Label those decisions as owner preferences, separately from source excerpts. Never invent source citations for a judgment. Broader policies remain drafts through the existing knowledge approval/rollback path. No new automatic provider transmission or training execution is introduced.

Newly configured advisers use `context/v5`: a shorter visible owner-response instruction and a schema that enforces answer/clarify/abstain field consistency. Keep the non-thinking 1,024-token profile, pinned model, supervised completion template, candidate comparison and portable runtime aligned. Selected adapters retain their training prompt version. Version-4 exports can explicitly carry either generic prompt version. Historical context-v4 validation remains available.

## Evidence and limits

The controlled local comparison found invalid state combinations with the older generic schema. A coherent schema and shorter instructions improved structural validity, but both non-thinking and 512-token bounded thinking still produced wrong numbers and unsupported answers to missing-data cases. Bounded thinking took about 18–21 seconds versus 5–7 seconds and showed no dependable quality advantage. The final comparison on the three browser-reviewed numerical cases again failed both profiles; the category control abstained without thinking and answered correctly with thinking. Non-thinking took 4.6–5.5 seconds versus 18.7–20.8 seconds with bounded thinking. Retaining non-thinking is a bounded runtime/compatibility decision, not a quality claim.

The real browser rehearsal used three synthetic saved apartment pages, a configured external provider with the collection consent screens, three scripted personal judgments, the pinned local model, a correction and a queued improvement. Its base preview returned an absurd price. Mechanical completion does not establish useful advice or personalized quality. A nontechnical tester and useful unseen predictions remain separate acceptance gates. CPU fixtures and replay of taught cases cannot establish LoRA improvement.

See [TODO](../../TODO.md) for exact verification results and remaining demonstration blockers. No external objective benchmark is required to accept the owner's preferences.
