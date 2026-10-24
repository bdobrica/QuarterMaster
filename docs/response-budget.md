# Response completion and compact prompts

Follow-up: the owner's review led to a separate [inference reliability development
comparison](inference-reliability.md), with compact advice/v2, attributed field rules
and separate quality reviews. This record and its failed GPU result remain historical.

The [bank acceptance baseline](bank-marketing-acceptance.md) exposed truncated JSON
and factual errors in complete answers. These are separate failure modes. New advice
uses a finite 1,024-token output profile, temperature 0, seed 17 and thinking disabled.
A response that reaches the token limit returns `LOCAL_TOKEN_LIMIT` with an explicit
next step. Partial output never becomes advice, feedback or supervision. There are
no automatic retries; the existing request, response-size and time limits remain.

## Historical replay

The local adapter and candidate comparison accept only the exact supported 512- and
1,024-token profiles. Evaluation sends each captured request's parameters, including
historical 512-token requests. It does not substitute current defaults. Existing
suite hashes, outputs and training decisions are unchanged.

New requests use `context/v2`: compact JSON with each retrieved excerpt's actual
`citation_id` and complete `text`, plus each approved lesson's complete text.
Full source/ excerpt hashes, source IDs, locations and lesson IDs/revisions remain
in the saved evidence and lesson snapshots. The model prompt omits duplicated
provenance metadata; it does not summarize or truncate the underlying evidence.
Historical `context/v1` serialization remains available for exact export replay.
Neither prompt includes observed outcomes or evaluation rubrics.

New exports use `quartermaster.export/v2`, with explicit `inference_parameters` and
the evaluated `prompt_version`. The standard runtime reproduces those settings.
Version 1 packages retain the historical 512-token / `context/v1` defaults. An old
runtime image cannot execute a version 2 package; `make test-export` checks this
before starting the container. Build the updated standalone-runtime target and set
its exact image ID using the [operator guide](operator-guide.md).

The updated trainer image is also required when training with `context/v2` examples;
older trainer images accept only the original prompt-version contract. Model, llama.cpp,
training recipe, supervision review and promotion rules have not changed.

## Local verification

`make test`: 462 CPU tests passed. `make lint`: passed. Regression tests cover exact
legacy/current generation payloads, truncation without retry, unsupported parameters,
complete evidence and lesson text, preserved snapshot provenance, historical suite
replay, versioned package validation and standalone budget selection.

The initial live follow-up used `context/v1` with 1,024 tokens: all three reviewed
development situations completed valid JSON. They still asked unnecessary questions,
misread supplied definitions or requested post-call duration. This is a format result,
not a factual-quality gain. Original failures remain intact.

An offline tokenizer-only check found the three reviewed targets needed 2,275,
2,325 and 2,276 tokens with original pre-lesson prompts, exceeding the unchanged
2,048-token trainer limit. A sizing projection using `context/v2` and all three
reviewed lessons needed 1,666, 1,716 and 1,667 tokens. This projection verifies fit;
actual immutable training snapshots are checked separately before a run.

Owner review: the local, ignored `data/bank-marketing/corrections-review.md` contains
edited approval for cases 1, 2 and 4. Case 3 remains **revise**, excluded from lessons
and SFT pending field-scope clarification. The exact reviewed file is snapshotted
with SHA-256 `68b2e4fc43ee0cd95620090fdd04998518280b49eb0743839aa097e27508943d`.
No subscription outcomes supplied the target answers. Written review and local GPU
permission do not automatically promote a candidate or establish adviser quality.

Session evidence and further live results are recorded under ignored
`data/bank-marketing/acceptance-02/response-budget/`. The original application data
was backed up before the isolated web image update. The ordinary builder on port
8000 is not part of this acceptance experiment.

### Reviewed teaching loop

The isolated app applied the owner's exact edited corrections through public API
feedback → manual owner-edited draft → reviewed → applied transitions. Three SFT
records were separately reviewed and approved. The records retain the edited owner
wording; the local audit preserves their earlier AI-draft provenance and review hash.
No frontier provider was used. Adviser revision 6 retains base weights.

Two other development situations were run before and after those lessons with the
same `context/v2` implementation and 1,024-token profile. All four responses were
schema-valid and used accessible citation IDs. The missing-interval response became
more focused on relevant dates, but repeated the questions. The complete-history
response still requested definitions already supplied, treating zero as ambiguous.
Retrieval of all three approved lessons is verified; useful generalization is not.
These are operator observations, not recorded owner ratings or evidence of lift.

A separate five-case suite was frozen before the lessons or training, using the
original reserved situations and rubrics, with compact requests and the larger
budget. Suite `4d2daf52-110f-4013-aa45-eb653b7ec227`, revision 7; SHA-256
`cb3a076796c1c7747cbb0c92e26e5bd2c49728769bf30dccadd304706d179d4d`.
The original frozen suite is unchanged. The candidate comparison uses the new
suite's identical B context for base and candidate, excluding later lessons so
context edits cannot be credited as weight improvement.

The exact approved SFT snapshots contain 1,526, 1,647 and 1,665 tokens including
the complete assistant target. The three serialized targets match the reviewed
structured records exactly. Frozen case situations, observed outcomes and rubrics
are absent from model training messages. The queued quick job is
`f72ec927-3ece-4307-a205-86b70710c879`: 12 steps, rank 4, float32, completion-only
loss, 2,048-token sequence cap, 20-minute training limit, separate bounded conversion
and comparison stages, offline containers, 4 CPU and 10 GiB RAM. WSL GPU preflight
passed. One observation showed the GTX 1660 Ti using 5,957 / 6,144 MiB at 100%;
this is not a measured peak or benchmark. There is no automatic retry or promotion.

### Fresh standalone checks

The final runtime image is
`sha256:a1869e5890ee75e296ff57813310090f004694ba5070edfc64086a42cdb36585`.
Both checks passed in new extracted packages with no external network, builder,
database, GPU or frontier credentials:

- `make test-export` on the explicitly synthetic lineage fixture at
  `data/export-smoke-fixtures/bank-budget-v2/synthetic-lineage-runtime-fixture.tar`:
  `context/v2`, 1,024 tokens, one accessible excerpt. Report
  `export-check-7b466d49-583c-4056-a6fb-55d1bc61d871.json`. This is a runtime fixture,
  not bank training or a new real M6 lineage claim.
- A new immutable export of the prior real synthetic M6 candidate,
  `4c90a918-f409-4a0e-8ef5-8a55624b2fea`, checked through the same
  `export_smoke.smoke` implementation: original `context/v1`, 512 tokens, exact
  historical context hash
  `fd6fff9faf79273fa24152db49a0bc6c8a8e6d66cec000e9c57b3ef8373ec975`.
  Report `export-check-f5986d2c-552e-4a36-9165-c804a15de0af.json`. Its frozen context
  contains no retrieved excerpts, so this does not prove a positive citation.

An earlier final-runtime packaging attempt returned `EXPORT_BUILD` before creating
its manifest/archive. Independent diagnostics found the copied file hashes and
reconstructed manifest valid and the manifest directory writable. The cause remains
unresolved; a separate explicit attempt completed and passed the fresh check. The
incomplete directory `4b5d99f3-9698-4a21-99e0-3b4ba83ba172` lacks `archive.json` and
is not offered as a completed export. No original package was edited to bypass checks.

### Bank GPU result: rejected candidate

All 12 training steps completed with finite training loss `1.6935123602549236`.
The adapter passed framing, recipe, base-revision and content-hash verification;
merge and GGUF conversion completed. The adapter is 642,112 bytes, SHA-256
`838ac9137be4738cb1002df16644cd1e1a57ca06859f96ac737691cee282143c`.
Training loss on three reviewed examples is not an evaluation-quality score.

The worker persisted all ten outputs from identical frozen B inputs:

| Arm | Schema-valid outputs | Output-limit failures |
| --- | --- | --- |
| Base weights | 3 / 5 | 2 |
| Attempted LoRA weights | 4 / 5 | 1 |

The known-interval case exhausted the output budget in both arms. The no-history
case completed JSON only in the attempted LoRA arm, but still requested dates of
previous contacts and misread the documented sentinel. Other valid answers treated
supplied values as missing, mixed contact counts with intervals, or asked irrelevant
questions. One additional complete JSON response does not establish useful advice.
There are zero owner comparison ratings and no claimed factual or business gain.

The durable job state is **failed**, code `CANDIDATE_SMOKE`: the deployable-candidate
check requires every candidate response to pass structural/evidence checks. Training
and conversion succeeded, but **no candidate version was registered, promoted or
exported for this bank adviser**. The active weights remain the original base. No
GPU retry was run. The bounded workflow cleaned up its temporary containers.

The local `data/bank-marketing/gpu-attempt-review.md` copies the protected evaluation
situations and both saved arms for human inspection, with blank observation fields.
It is explicitly evaluation-only: do not turn those cases or notes into supervision.
Exact records are in `gpu-result.json`, `comparison-summary.json` and the job's
`comparison.jsonl` under the ignored session storage.

The next technical experiment should constrain response verbosity explicitly before
spending more GPU time. The 1,024-token setting mitigates truncation on the reviewed
development examples but does not reliably complete all frozen situations. A future
shorter generation schema must be versioned and preserve these captured failures and
older schemas. Factual comprehension remains a separate unresolved gate; another
budget increase alone is not evidence that the adviser can follow the reviewed lessons.
The owner-journey release checklist and MVP tag therefore remain pending.
