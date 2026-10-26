# Architecture decisions

These decisions retain the useful results of earlier work without keeping duplicate roadmaps or experiment diaries. Recorded on 2026-10-25; historical observations below are not new verification. Implementation gaps belong in [TODO](../../TODO.md).

| ADR | Decision |
| --- | --- |
| [0001](0001-personal-adviser.md) | Build a generic personal adviser with four owner activities. |
| [0002](0002-local-model-and-portable-runtime.md) | Reuse the verified local LoRA and portable CPU runtime path. |
| [0003](0003-immutable-evidence-and-evaluation.md) | Preserve evidence, historical profiles and evaluation separation. |
| [0004](0004-reliability-lessons.md) | Require useful decisions; stop treating prompt experiments or low loss as success. |
| [0005](0005-reviewed-knowledge-and-feedback.md) | Separate immediate knowledge changes from reviewed behavior training. |
| [0006](0006-integrated-muster.md) | Bundle Muster in QuarterMaster; keep checked source data separate from owner targets. |
| [0007](0007-generic-prediction-boundary.md) | Share generic prediction across reviewed training, local Ask and portable export; preserve historical advice. |
| [0008](0008-stabilized-owner-loop.md) | Connect typed feedback, saved-page handoff and versioned owner-response prompts without changing historical artifacts. |
| [0009](0009-visible-prediction-contract.md) | Show the full response contract, compact decision facts and align explanation/target generation without rewriting old profiles. |
| [0010](0010-verified-local-model.md) | Use the verified pinned 4B base, bounded quantized LoRA recipe and compatible portable runtime while preserving historical models. |
| [0011](0011-bounded-owner-preference-recipe.md) | Preserve the bounded stronger recipe experiment while retaining the existing default after overfitting and missing-information regressions. |

Accepted ADRs describe intended design; they do not mark unfinished features complete. Supersede an accepted decision with a new ADR rather than rewriting its meaning.

Removed documents remain in Git. For example, `git show 32590b0:docs/milestone-6.md` retrieves the complete original training record. Each ADR identifies its historical sources. Some raw model outputs and artifacts were only stored under ignored local `data/`; Git contains their recorded summaries, not those raw bytes. Existing regression fixtures remain test data, not current product examples.
