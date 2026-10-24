# Reviewed knowledge changes

Open a project’s **Knowledge** tab to read its active Markdown articles, original source IDs,
content hashes and active knowledge revision. Search shows only excerpts in that revision,
with links to their original lines. Historical revisions remain searchable explicitly.

## Change a policy

1. Choose **Change this article**, or add a new article. Describe the change and choose
   **Preview AI request**, or write the complete article under **Write or edit manually**.
2. AI drafting uses the existing optional builder configuration (`QM_BUILDER_BASE_URL`,
   `QM_BUILDER_MODEL`, and its separate key configuration). The preview shows the exact
   article, instruction, endpoint, model, system message and response schema before consent.
   No saved questions, evaluation cases/rubrics, outcomes or other articles are included.
   This uses the existing single bounded request: at most 2,048 output tokens, configured
   input-byte/timeout limits, no tools, redirects or automatic retries. Large replacements
   may need manual editing if the provider cannot finish within that output limit.
3. Review the before/after diff and source attribution. AI and manual drafts both require
   **Approve and activate knowledge**. A draft can be edited manually into a new proposal.
   Rejection leaves active knowledge unchanged. A proposal based on an older active version
   cannot overwrite newer policy: recreate it from the current article.
4. Approval stores new immutable source bytes, replaces only the affected active source,
   creates a knowledge revision and rebuilds its excerpts immediately in the same database
   transaction as the approval. Adding an article preserves the other active articles.
   Superseded text is excluded from current retrieval; historical citations still resolve
   when their original revision is specified. This changes context, never model weights.

## Verify the change

An active approved proposal offers **Retest original and fresh question**. Choose an existing
question from the preceding knowledge revision and supply a different, previously untested
situation. The button explicitly runs four advice requests: before/after for each question.
Hosted advice uses the project’s existing scoped consent; provider charges may apply.

Both arms use the same current mission, routines, model, prompt and generation settings.
The prior knowledge selection is the only intended change. Each case retains the same ID and
facts across its two arms; observed outcomes are excluded. Citation allow-lists change to match
the actual retrieved sources. A historical answer is preserved and rerun rather than silently
claiming its old settings match today’s. Output, failures, latency, excerpts and cited source links
are saved as ordinary immutable test runs; saved pair links remain on the Knowledge screen.
A fresh question that has already had an actual test run is rejected. A demo’s not-run sentinels
do not count as model exposure. No replay inputs are sent to the builder or automatically trained.

Compare **Retrieved excerpts actually sent**, valid citation links, and the answers. A successful
JSON response or citation ID alone does not establish usefulness; the owner still reviews that.

## Verification record

Focused tests cover manual/AI drafts, exact consent, invalid request contracts, failure and restart
states, rejection, concurrent/stale approval, transactional rollback, new-article membership,
current-versus-historical citations, cross-project isolation, form origin, escaping, schema errors,
and controlled replay. Replay tests use a deterministic fake adviser; they are not model evidence.
The schema-8 migration adds append-only knowledge proposals and preserves existing records.

Executed: `make test` (**703 passed**), `make lint` (Ruff checks and formatting passed),
and `git diff --check`. The running Knowledge page returned HTTP 200. No new GPU/training,
model installation, browser automation or fresh-container export check was run for this change.

The owner approved the print policy in the app and confirmed approval in chat. Active knowledge
is `60d79a0f-4ca2-4c10-8ee9-6eab9ecc501d`; the preceding revision and source bytes remain intact.
The approved article accepts customer portal e-signatures as written proof approval, preserves
final-copy confirmation, and excludes unsigned portal records.

Four actual hosted requests used `gpt-6-luna`, high reasoning and identical settings across both
arms. The original Willow question changed from a validated **hold** to a validated **ready**.
The fresh Linden question produced an old-policy draft recommending hold, but its supporting
quote changed the capitalized “The” to “the”: exact-quote validation rejected it. No validated
before answer exists for that pair. Its new-policy answer validated as **ready**. Both ready
answers cite `f6ec3a47-c9a6-5adc-a19d-2a2840e6ce12`, the actually retrieved replacement article.
All validated citation links resolve against their recorded revisions. Current search excludes
the superseded article. There were no retries, prompt changes, builder calls or weight changes.

| Question | Previous knowledge | Approved knowledge |
| --- | --- | --- |
| Original Willow | Hold, valid citation · 5,383 ms | Ready, updated citation · 4,253 ms |
| Fresh Linden | Quote-validation failure · 4,336 ms | Ready, updated citation · 3,881 ms |

Full immutable outputs, evidence snapshots, approval revision and checks are recorded in
[live replay evidence](knowledge-live-replay.json); the original report is also retained under
`data/print-knowledge-replay.json`. Provider cost was not measured. The owner subsequently reviewed the comparison and
confirmed “Looks good.” This is recorded separately in [owner review](knowledge-owner-review.json),
linked to the unchanged evidence by its hash and run IDs. The historical report retains its
original pending-review status; the quote-validation failure remains a failure.
The previous hosted/local baseline evidence and approved case review remain unchanged.
