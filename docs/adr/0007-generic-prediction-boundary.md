# ADR 0007: Version the generic prediction path independently of historical advice

Status: Accepted · 2026-10-25

## Decision

Keep `owner-decision/v1` and `teaching-dataset/v1` as the reviewed collection handoff. Convert their explicit targets into `prediction/v1` responses inside a new `training-job/v2`. Historical `training-job/v1` examples still retain their applied lessons and original response contract; never reinterpret old ratings or free text as typed targets.

Use `context/v4` and the existing bounded non-thinking 1,024-token generation profile for the new supervised rows, candidate comparison, local Ask and standalone runtime. Share prompt, schema and validation code. Capture the selected answer unit or choices, decision-time inputs, accessible knowledge excerpts and their lineage. An owner's reason is supervision, not a verified quotation or independent factual evidence. Do not invent citations for it.

Reuse the persisted training queue, finite container stages, adapter checks, safe merge/conversion and explicit promotion. Advertise the generic trainer as a separate `prediction-trainer` image target with a version 2 contract label. Start training from the pinned base; compare the resulting candidate against the model selected when the job was prepared, including a previous compatible adapter. Replay up to five taught cases on identical captured context/settings. Label this preference consistency, not unseen accuracy; leave the current selection unchanged until explicit promotion.

Generic candidates use `adviser-version/v2`; their standalone packages use `export/v4`. Freeze the knowledge used during training/comparison, its original bytes and one replay reference. Keep the number/category answer format in the package. Do not fabricate an evaluation-suite identity for a taught-case replay. The package uses only its local model and included sources; the builder database and external APIs are absent. Preserve historical context profiles and export versions 1–3.

## Limits and evidence

CPU fixtures exercise both target kinds, public trainer loading, current-model comparison, selection/retention, failure/cancellation, holdout exclusion, citation integrity and a freshly extracted package with fixture inference. An isolated import check verifies the standalone dependency closure without builder modules. Fake model bytes and mocked GPU stages establish software boundaries only. A new real GPU run, model-quality assessment and fresh-container generic export smoke test remain opt-in and unverified.

Typed prediction review and automatic review-to-teaching routing remain separate unfinished work. Saving a collection target already needs no general lesson or second approval. Knowledge changes still affect context immediately; preparing reviewed data never changes weights.
