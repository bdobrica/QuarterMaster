# Print-proof demo: P0 usefulness gate

Create a fresh project from the home page's **Create fresh print demo** button, or run
`make demo`. This saves one invented Markdown policy, a mission and ten held-out cases.
It makes no model calls and needs no spreadsheet, GPU or provider. Existing projects remain intact.

## Configure and try advice

For the hosted demo, set these values in the ignored `.env`:

```dotenv
QM_ADVISER_BASE_URL=https://api.openai.com/v1
QM_ADVISER_MODEL=gpt-6-luna
QM_ADVISER_REASONING_EFFORT=high
QM_ADVISER_API_KEY=<your key>
```

Adviser credentials are separate from builder configuration. To intentionally use the same key,
set `QM_ADVISER_API_KEY=${QM_BUILDER_API_KEY}` instead of copying the secret. A secret-file
alternative is documented in [.env.example](../.env.example).

Start with `make up` (or `uv run --locked uvicorn quartermaster.app:app --host 127.0.0.1`).
Open the project's **Test** screen, review the displayed endpoint/model and material disclosure,
and explicitly enable hosted advice for that project. No request is sent by enabling consent.
Ask a question; inspect its answer, policy link and saved context. The project starts local-only.
**Use local-only advice / revoke consent** disables external advice. Changing endpoint or model
requires fresh consent. `QM_ADVISER_LOCAL_ONLY=true` disables hosted advice installation-wide.
Hosted advice requires connectivity and cannot be packaged as an offline local-model export.

Each request sends only the assembled mission/business goal, decision definition, question/choices,
selected verified excerpts and approved routines. Source files, evaluation rubrics, other cases and
observed outcomes are excluded. Requests have 48 KB input, 2,048 completion-token and 64 KiB response
bounds, and a finite timeout. Completion tokens include reasoning. Errors are sanitized; no automatic
retries, redirects, fallback model or external business actions occur.

## Synthetic evaluation cases

These cases originated as AI drafts. The owner reviewed and approved all ten cases and the four
final hosted answers on 2026-10-24; see the [owner review record](print-demo-owner-review.json).
Freshly seeded projects still require their own review. Open
**Review saved evaluation situations and expected behavior** on Test, expand membership, and
review the complete situations/rubrics. Record approval and a note only if you agree with all ten.
Approval appends a revision; it never creates teaching examples. Adding another case clears review.
The portal e-signature policy change itself belongs to the next P0 section and is not implemented here.

| Case | Known facts | Expected behavior under the initial policy |
| --- | --- | --- |
| Cedar: clear approval | Final copy confirmed; written proof approval | Ready; cite policy; no question |
| Maple: explicit hold | Copy confirmed; customer says not approved/do not print | Hold; cite policy; no question |
| Birch: missing approval | Copy confirmed; proof approval unknown | Ask only about written proof approval |
| Ash: missing copy | Written proof approval; copy confirmation unknown | Ask only about copy confirmation |
| Elm: conflicting records | Copy confirmed; approval and withdrawal notes lack timestamps | Withhold readiness; ask which record is current |
| Willow: e-signature | Copy confirmed; portal signature only | Hold now; ready after a separately approved policy change |
| Hazel: both unknown | Neither required confirmation recorded | One short question requesting the two confirmations |
| Alder: deadline pressure | Copy confirmed; approval explicitly refused | Hold; urgency does not replace approval |
| Juniper: unseen portal neighbor | New booklet; confirmed copy; portal signature only | Hold under initial policy; retest after policy change |
| Rowan: unseen approval neighbor | New flyer; confirmed copy; sign-off blank | Ask about proof approval; blank does not mean refusal |

All ten are immediately reserved by the existing holdout mechanism, including near-duplicate
protection. They cannot enter SFT examples or builder lesson-drafting prompts. Baseline requests
contain only one of the first four situations at a time; neither unseen neighbor nor any rubric is
attached. Keep separate teaching situations for the later correction demo.

## Record the same four baseline cases

`make demo` prints project and suite UUIDs. Run these commands with those UUIDs and distinct report
paths. Each command makes four explicit requests; the hosted command can incur provider charges.

```sh
uv run --locked python -m quartermaster.print_demo --project PROJECT_UUID --suite SUITE_UUID --engine local --report data/print-local-baseline.json
uv run --locked python -m quartermaster.print_demo --project PROJECT_UUID --suite SUITE_UUID --engine hosted --consent-external --report data/print-hosted-baseline.json
```

Local advice needs the existing pinned CPU setup described in [Milestone 4](milestone-4.md).
The runner never downloads a model, trains or starts a GPU job. It saves each actual response/error
with context, source excerpts/hashes, citation IDs, provider/model, parameters and measured latency.
Reports are created exclusively, never overwritten. Human usefulness/source/question judgments
start unset. Provider cost is unknown unless checked against actual billing.

## Actual verification, 2026-10-24

Using the configured key and **gpt-6-luna, high reasoning**, the first four-call run made semantically
appropriate decisions, but the two recommendations failed exact supporting-quote validation.
The model added quotation punctuation or normalized whitespace. We made one hosted response-contract
correction: supporting quotes must be short, exact case substrings. We preserved citation/quote
validation and reran the same four cases with the same model and decoding settings.

| Case | Actual final result | Latency |
| --- | --- | --- |
| Cedar | “Yes, Job Cedar is ready to print under the supplied policy.” | 5,316 ms |
| Maple | “Hold Job Maple; do not print.” | 3,288 ms |
| Birch | “Has the customer explicitly approved the print proof in writing?” | 3,778 ms |
| Ash | “Has the customer confirmed the final copy?” | 3,344 ms |

All four final responses validated and cited the accessible `print-policy.md` excerpt. Developer
inspection found the cited policy supports the two recommendations and the two questions concern
exactly the missing confirmation; no unrelated questions appeared. This is an observed four-case
result with owner sign-off, **not a benchmark or business lift**. The owner approved the final
answers after reviewing them in the app. The eight calls used the fixed completion cap; actual
billed cost was not measured.

[Recorded initial and final evidence](print-demo-baseline.json) preserves answers, errors, parameters,
latencies and source excerpts. Complete original reports remain in ignored `data/print-hosted-baseline.json`
and `data/print-hosted-baseline-v2.json`. Early hosted records inherited the old local-only
`engine_revision` default; it does not identify the hosted engine. Provider/model identify these calls.
New hosted records explicitly use `openai-compatible/v1` and the versioned `hosted/v1` quote contract.

## Actual local CPU baseline, 2026-10-24

The pinned Qwen/Qwen3.5-0.8B base model and llama.cpp runtime are now installed. `make model-setup`
completed successfully; independent manifest/model/license verification passed. The local run used
exactly the same four saved cases, mission, policy revision and retrieved excerpt as the hosted run.
It retained the existing local generation profile and shared context/v3 prompt; the hosted run's
additional quote-contract instruction was not applied to the local model. This is an honest baseline,
not an isolated comparison of model weights.

| Case | Actual local result | Latency |
| --- | --- | --- |
| Cedar | Asked for explicit written proof approval although the situation already supplies it; no citation | 28,809 ms |
| Maple | Asked “What additional decision-time evidence can you provide?” instead of holding; no citation | 24,213 ms |
| Birch | Asked “Do you have the customer's written approval for the print proof?”; relevant question, no citation | 25,010 ms |
| Ash | Failed `ADVICE_SUPPORT` exact-quote validation; no validated advice saved | 21,811 ms |

The Ash draft cited the real policy excerpt, but its supporting quote was not an exact source
substring. It also invented a requirement for written approval of final copy. Three outputs passed
structural validation; that does not make them useful. All four received the accessible policy
excerpt. The local model was not tuned or retried to improve these results.

[Full local evidence](print-demo-local-baseline.json) records actual draft/output/error, citations,
source text and hashes, exact context/system/parameters, model manifest, runtime image, resource
limits and latency. The original complete report is `data/print-local-baseline.json`. The earlier
hosted reports and owner approval remain unchanged. Local answers have not been owner-approved.

The first setup took about **23.6 minutes**, mostly building/downloading/packaging the shared
converter image. Conversion emitted numeric warnings (`overflow encountered in divide`, `invalid
value encountered in subtract`, `invalid value encountered in cast`) even though GGUF export and
manifest verification completed. Their effect on quality was not diagnosed; these results do not
isolate model capability from conversion/runtime effects. Startup also warned that no GPU was
available (expected for this CPU build) and that the pinned thinking-template flag is deprecated.
An initial health probe returned 503 during warm-up; subsequent health/model-identity checks passed.

The dedicated container `quartermaster-local-baseline` is running at `http://127.0.0.1:8081/v1`,
with four CPUs, 4 GiB memory, no GPU device requests, a read-only model mount and a localhost-only
published port. The model SHA-256 is
`6a6359874efbd74e6837464cc68912af5dc945bfca1f543c22145ca4993cb1e4`.
The model and build outputs remain in ignored `data/` and Docker storage, outside git.
The ignored `.env` now configures this local endpoint/hash for the host Python app, which was
restarted to load them. For Compose, use the existing advice profile and its internal
`http://inference:8080/v1` endpoint instead of host loopback.

The demo project was restored to its previously consented **hosted** engine after the local run.
Local-only mode is available explicitly. Use `docker stop quartermaster-local-baseline` to stop the
CPU service and `docker start quartermaster-local-baseline` to start the installed service again.
No GPU training, external inference calls or export smoke tests ran for this baseline.

Verification executed: focused seed/consent/provider/review/evaluation/export tests; `make lint`;
`make test` (**690 passed**). The running app's health, saved-answer, case-review and historical
citation pages returned HTTP 200. No real browser automation, GPU run or fresh-container
export smoke was performed. The local-model baseline and service health/identity checks were
subsequently executed as recorded above. No export package implementation changed; hosted
baseline runs are explicitly rejected by the existing base-export entry point.
