# ADR 0006: Muster is QuarterMaster's bundled collection and knowledge manager

Status: Accepted · 2026-10-25

## Context

The owner built and accepted Muster separately, then requested its integration as part of QuarterMaster **in this repository**, with the old checkout removable. Its collector already retains original evidence, distinguishes reviewed/unreviewed extraction, manages human-approved Markdown and publishes immutable format-1 bundles. Rebuilding those capabilities would duplicate working product code.

## Decision

Import Muster's application, templates, assets, portable checker/consumer scripts and relevant regression tests. Mount it under `/collect` in QuarterMaster's single server and explicitly enter/close its lifespan. Keep editable collection state in its own SQLite/artifact area under the ordinary data directory. Do not depend on the old checkout, spawn a separate service, or import its private storage models into the adviser/trainer.

The public handoff remains `muster.bundle/1`. Validate inventory, checksums, paths, references, supported field types and review statuses before registering an independent immutable copy. Identity is project + manifest digest + example ID; local collection/job numbers are not global identities. New publications do not mutate previous imports or silently carry approvals across them. Unknown schemas fail closed; source HTML is downloadable data, never executed.

Muster review confirms extracted observations; personal teaching explicitly supplies a number/unit or category and optional reasoning. These are separate append-only contracts. Select and confirm decision-time input fields; leave outcomes, notes and candidate labels out unless deliberately selected as known inputs. Store owner judgments once without an applied-lesson prerequisite. Exclude reserved checks both at save and dataset freeze. Keep article bytes/revision provenance and distinguish image inferences from observed facts and later human corrections.

Knowledge activation changes retrieved context immediately and explicitly. Conflicting imported article titles need manual selection. Frozen `quartermaster.teaching-dataset/v1` snapshots contain typed judgments, selected inputs, lineage and exact current knowledge; they are portable reviewed data, not historical `training-job/v1` jobs. Do not silently coerce them into the legacy answer format or claim weights changed. Align generic training/Ask/export in the existing open TODO group.

## Consequences and provenance

The default deployment gains three pinned runtime dependencies: Playwright for the managed browser, jsonschema for Muster's accepted extraction schemas and python-dotenv for its retained standalone launcher. Reuse QuarterMaster's HTTPX2 transport instead of adding another HTTP stack. No GPU dependency, Node build, background cloud work or provider call is introduced at startup. The default container does not provide a desktop/browser; headed collection runs on a configured host.

Source provenance: QuarterMasterMuster commit `ac9221e`. Imported its committed browser implementation; the source checkout's uncommitted automation-hiding changes were left untouched there and excluded, consistent with its no-stealth boundary. Formatting, HTTP transport imports and test paths were adapted here. The original checkout remains unchanged. The original root roadmaps/installers were not imported; the current [operator guide](../operator-guide.md) and [bundle contract](../muster/bundle.md) are authoritative for integrated operation.

A one-time data copier preserves the existing local database, retained sources, knowledge and publications independently of the old checkout. It excludes browser cookies, credentials and old configuration. The owner's [apartment policy article](../../examples/apartments/owner-policies.md) is ordinary editable knowledge; preferences and unverified beliefs must not become universal facts or domain-specific core fields.
