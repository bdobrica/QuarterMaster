# ADR 0001: Generic personal adviser, four owner activities

Status: Accepted · 2026-10-25

## Context

The earlier milestone roadmap accumulated technical experiments and several unrelated demonstrations. Working subsystems did not add up to a comprehensible product. The owner replaced the direction documents, then requested removal of the obsolete docs and app demos.

## Decision

Build one self-hosted, single-user adviser around **Collect → Teach → Ask → optional Review**, with reviewed feedback returning to teaching automatically. Keep model and deployment controls under Advanced. The adviser recommends; it never performs external actions.

Core contracts support numbers with units and categorical choices. Keep domain details in examples and owner knowledge. The owner's reviewed judgment is a legitimate personal training target; distinguish it from source observations, observed outcomes and factual correctness.

The current example is personal apartment valuation using material the owner has already prepared. Extraction and feature design are separate future work. Retire earlier examples from the product journey; retain their regression fixtures only where they protect existing behavior.

## Consequences

Reuse the existing application foundations. Do not restart on a domain-specific schema, a tabular prediction factory, a separate vector database or speculative cloud/multi-user infrastructure. A second target kind remains a contract test, not a reason to restore multiple owner demos.

The full four-activity loop remains unfinished. [PLAN](../../PLAN.md) defines it; [TODO](../../TODO.md) tracks delivery.

## Evidence

- Direction reset and repository audit: commit `32590b0`, root `AGENTS.md`, `PLAN.md`, `TODO.md`, `README.md`.
- Prior UI improvements: commit `03be122`. Readable versions, independent answer reviews and saved-question history worked; they did not implement automatic review-to-teaching.
