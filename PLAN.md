# QuarterMaster — MVP reset

> **Pitch:** Teach a useful AI adviser in plain English. Give it knowledge, ask for advice, correct a mistake, approve the proposed improvement, and see the difference.

**Goal:** A convincing, nontechnical, five-minute live demo within a few focused development days. This is a prototype, not a release or an ML benchmark. See [TODO.md](TODO.md) for the execution order.

## The bet

**The product is the improvement harness, not the model.** A model is replaceable. A well-maintained knowledge base, reviewed routines, clear evidence, and a fast correction loop are the enduring asset.

QuarterMaster is an **adviser, not an actor**: it answers, recommends, asks one relevant question when needed, or says it lacks evidence. It never performs external business actions.

One nontechnical owner should be able to:

1. Describe what the adviser helps with and add a few plain-language knowledge articles. **No spreadsheet required.**
2. Ask a real question and see a short answer with clickable supporting sources and meaningful limitations.
3. Say “this is wrong; here is why.” QuarterMaster proposes a small, understandable fix.
4. Review a before/after diff, test the same and a fresh case, then approve or reject it.
5. Optionally train behavior from reviewed examples and compare a LoRA candidate. **Training is never automatic.**

## Two improvement lanes, one interface

| The correction means… | Change | When effective |
| --- | --- | --- |
| “That policy/fact/definition changed.” | Edit a **knowledge article**; review diff, version and reindex | Immediately after approval; no weight change |
| “Handle this kind of situation differently.” | Review a **behavior routine** (plain-language instruction and example); optionally collect examples for LoRA | Approved routine affects prompts immediately; **LoRA changes weights only after a separate reviewed training run** |

This distinction is important: a runtime routine can change observed behavior *without* training. The UI must always say whether an improvement came from knowledge, a routine, or new weights. An external LLM may **draft** an article, classify a correction, or propose examples, but it never silently publishes knowledge or labels.

Do not force a choice when ambiguous. Show the proposed lane and let the owner switch it. For hard safety/business rules, use explicit owner-reviewed requirements and deterministic checks where possible; let the model reason about everything else. Keep rules readable, not a new DSL.

## The experience (three places, not twelve tabs)

- **Adviser:** a simple question box; concise answer, supporting knowledge, what is missing, and a prominent **Improve this answer** action.
- **Knowledge:** readable articles/routines, add or change in natural language, review AI-drafted diffs, active versions and sources. This is the main product, not an upload appendix.
- **Improvements:** pending proposals, before/after replay, a tiny saved test set, and an explicit **Train behavior (LoRA)** action under Advanced. Export and diagnostics also stay under Advanced.

Keep initial setup to mission + knowledge + **Try it**. Hide source-role selectors, case mapping, token/decoding controls and ML vocabulary unless the owner chooses Advanced. Spreadsheets remain an optional source of historical examples, never an onboarding requirement.

## Smallest useful architecture

```text
Owner's question
    -> Adviser harness: mission + current knowledge/routines + case/history
    -> Read-only retrieval (sources with stable IDs)
    -> Swappable inference model (reason + answer, clarify, or abstain)
    -> Validated advice + citations + version/decision summary
    -> Owner correction
    -> External-capable builder LLM drafts KB patch or behavior routine
    -> Human reviews diff -> small replay gate -> approve -> versioned change
                                     \-> optional reviewed LoRA job -> compare -> promote/reject
```

Reuse **Python/FastAPI + Jinja/HTMX + SQLite + local artifacts** already in the repository. Reuse the working FTS5 knowledge index, lesson review, immutable records, evals, LoRA worker and standalone exporter. Refactor their *front door*; do not rebuild them.

**Knowledge first:** human-readable Markdown/articles are the source of truth. Every active article has an ID, title, provenance, version and optional owner. Changes produce a visible diff and fresh index. Include article title/headings with extracted passages. For the tiny demo corpus, favor complete relevant articles or existing FTS5 search over a vector database. Add embeddings/rerankers **only if retrieval demonstrably misses expected evidence**.

**One inference seam:** configure a capable OpenAI-compatible hosted model for the fastest useful demo, with explicit per-project consent before sending business content. Keep the existing local Qwen/llama.cpp path for privacy/offline use and later LoRA/export. Do not make the failing 0.8B model the only way to judge the product. A model swap must run the same small test set; no model chooser in the main UI. Hosted inference does **not** inherit the existing offline-export promise; show that distinction honestly.

**Bounded reasoning:** provide mission, decision facts, applicable routines and retrieved evidence. Allow the model to decide whether to answer or ask for missing decisive information. Return one useful answer or one targeted question, not a compulsory interrogation. Do not demand or display hidden chain-of-thought. Explain instead through cited source text, relevant case facts, applicable routine, missing facts, model/KB versions and a short decision summary. Validate actual citation IDs; their existence alone is not proof of support.

**Small evaluation gate:** maintain **8–12 owner-reviewed situations**, including clear answer, missing input, conflicting sources, policy update and a near-neighbor. Keep them separate from training. After each proposal, replay changed and unaffected cases using the same model/settings, and display **helped / harmed / unchanged / failed** with human-readable examples. The three questions are: Was the advice useful and grounded? Did it ask only necessary questions? What did it cost in time/money? No blended score or additional academic probes. An LLM judge may assist, not certify success.

**Trace without theater:** each response records its model, prompt/routine/KB version, retrieved excerpts, outcome and latency/usage. Each training candidate records reviewed input examples, withheld test cases, base model, recipe, artifact, cost/time and comparison. The user can answer “what changed and why?” without pretending to see the model's internal thoughts.

## Demo to build first: the print-proof adviser

Use the repository's existing **synthetic print-shop** fixture; do not start with bank marketing.

1. Ask whether a job with confirmed final copy but no proof sign-off may be printed. Adviser says **hold**, citing the active policy.
2. Say: “An e-signature in our proofing portal counts as customer sign-off.” QuarterMaster proposes a **knowledge edit**; owner reviews and approves it.
3. Ask about a *different* job with confirmed copy and an e-signature. Adviser now says **ready**, citing the updated article. Show old/new KB revision and answers.
4. Correct a behavior mistake: “If proof approval is unknown, ask about approval; don't ask unrelated questions.” Review a **routine** and retest an unseen case.
5. Open Advanced to show that reviewed behavior examples can produce a **LoRA candidate**, with honest side-by-side results and manual promotion. A failed candidate stays rejected; that is a healthy outcome, not a demo failure.

This is the business pitch: **a domain expert makes a useful, reviewable improvement in minutes without touching code, prompts, or weights.** A second synthetic domain (tool rental) is a smoke check for domain independence, not another bespoke build.

## What the existing project already proved

- Knowledge ingestion/versioning, source citations, correction review, frozen cases, LoRA training and independent local export are largely implemented and tested. Preserve these seams.
- The real bank case is **not** a passed usefulness demo: the local model repeatedly asked irrelevant questions or returned invalid advice. The focused decision-only LoRA candidate matched **10/30** approved references versus **9/30** for base and still produced unsupported answers. **Do not train another bank candidate to save the demo.** Historical records stay available, but stop growing that experiment.
- The already-tested standalone local exporter is valuable. Keep it working, but don't make offline packaging or another GPU run a blocker for the first live product demonstration.

## Ruthless boundaries

**Not now:** customer-support platform, multi-agent orchestration, autonomous actions, arbitrary model marketplaces, GraphRAG, fine-tuning sweeps, enterprise governance, new metrics dashboards, causal business-lift claims, and more bank-marketing diagnostics. No new long research documents. Keep historical investigations in an archive/index rather than deleting useful negative evidence.

**Demo-ready means:** on a fresh local project, a newcomer can create an adviser, get at least one genuinely useful cited response, change knowledge in natural language, approve a visible diff, see a correct change on a fresh case without regressing the basics, and understand exactly whether the change was knowledge, routine or LoRA. Prefer a working 90-second live story over another 100 test cases.

## Research that drives these choices

- [Anthropic — Building effective agents](https://www.anthropic.com/research/building-effective-agents): begin with simple composable retrieval/tool workflows; extra agent layers have costs.
- [Anthropic — Contextual Retrieval](https://www.anthropic.com/research/contextual-retrieval): preserve source context, consider full small documents and combine lexical/semantic retrieval only as needed.
- [Ovadia et al. — Fine-Tuning or Retrieval?](https://arxiv.org/abs/2312.05934): retrieval is the more direct route to adding facts; fine-tuning is not a dependable fact database.
- [Hu et al. — LoRA](https://arxiv.org/abs/2106.09685): low-rank adapters are a practical, separate behavior-adaptation mechanism.
- [Anthropic — Demystifying evals for AI agents](https://www.anthropic.com/research/demystifying-evals-for-ai-agents): small representative tasks, human review, deterministic checks and visible regressions are useful before elaborate metrics.

The research guides architecture; **the demo cases determine what to build next**.
