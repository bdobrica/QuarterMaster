# Working adviser: Teach → Test → Correct → Export

New ordinary tests enable bounded local thinking and include the project's selected
knowledge, business goal, decision definition and approved lessons. Training and
historical experiments retain their original inputs and settings. No weights or
training labels were changed, and no GPU job was run for this change.

The software journey works independently of training. **Advice quality remains an
open gate:** in the real bank check, both unchanged models asked unnecessary questions
and supplied no citations. A successful response or package is not an accepted recommendation.

## Use the application

1. **Teach:** describe the mission and business goal. Upload Markdown definitions and
   business rules as knowledge, then save the selected sources. Uploading alone does
   not select a source. Use the guided interview if a decision definition is needed.
2. **Test:** ask the actual decision-time question and supply the known facts. Inspect
   the recommendation, necessary question, limitations and linked source excerpts.
   The optional existing-LoRA comparison saves both responses against one captured
   context. It changes no active model, weights, examples or source files.
3. **Correct:** write what should change under the response. Draft a reusable lesson
   manually, review its applicability and approve it for context. Pending/rejected
   lessons have no effect. Optional external drafting still requires exact preview
   and consent. Try a similar situation after approval; do not assume the model will
   apply the instruction correctly just because it was supplied.
4. **Export:** select a successful base test and acknowledge its included business
   content. The archive contains those tested weights, mission, knowledge sources,
   approved lessons and one decision-time reference situation. It excludes training
   rows, raw corrections, evaluation rubrics, outcomes, credentials and the database.
   Inspect the result before relying on it. Candidate exports remain under Advanced.

CPU advice may take up to three minutes per model. A comparison runs sequentially and
can take twice as long. Failed calls are saved, without automatic retries. Private
thinking is not displayed or stored in ordinary test responses.

## Local setup

Follow the [README](../README.md) for basic startup. After `make model-setup`, set
the printed model hash and `QM_LOCAL_BASE_URL=http://inference:8080/v1` in `.env`.
Apply the small advice override so the web application can read the base bundle
for export; ordinary Teach startup still needs no model directory:

```sh
docker compose -f compose.yaml -f compose.advice.yaml --profile advice up -d --build --wait
docker build -f trainer/Dockerfile --target standalone-runtime -t quartermaster-standalone-runtime:thinking .
docker image inspect quartermaster-standalone-runtime:thinking --format '{{.Id}}'
```

Put that exact image ID into `QM_EXPORT_RUNTIME_IMAGE` in `.env`, then rerun the
Compose command to apply it. Host Python deployments set `QM_LOCAL_MODEL_DIR` to
their unchanged `data/local-model` directory; the advice Compose override uses `/model`.

After downloading an archive:

```sh
make test-export EXPORT=/absolute/path/adviser.tar
```

This checks a fresh extracted package using offline CPU containers. Preserve its
report. Follow the archive's instructions to serve its separate browser UI/API.

Optional comparison uses an operator-started CPU service, configured through
`QM_COMPARISON_BASE_URL` and `QM_COMPARISON_MODEL_SHA256`. Its verified GGUF must be
served as `qm-comparison-<SHA256>`. The web application checks that exact model alias
before sending the captured context. Keep model mounts read-only, use the pinned
llama.cpp image, disable GPU layers and retain finite CPU/RAM/time bounds. This does
not import an experimental selector as a normal trained adviser or promote it.

## What changed

New ordinary tests use `context/v3` and an explicit final-response contract. They
ask for a supported answer or next step and permit clarification only when a specific
obtainable fact blocks the actual question. They distinguish unknown, missing and
negative facts, and case values from dictionary definitions.

The generation profile is temperature 0, seed 17, `enable_thinking=true`,
`reasoning_budget_tokens=512`, `max_tokens=2048` and `reasoning_format=deepseek`.
The total cap includes thinking; 2,048 tokens are not reserved for the final answer.
The local deadline is at most 180 seconds. Only final content enters advice validation.
The [Qwen model card](https://huggingface.co/Qwen/Qwen3.5-0.8B) describes thinking
support and warns about loops in this small model. The pinned
[llama.cpp server](https://github.com/ggml-org/llama.cpp/blob/1a24df163920a4744a95373d178d790b72a9bb2f/tools/server/README.md)
and its `server-common.cpp` support the per-request reasoning budget and separate
reasoning output. Actual live requests used the thinking template and generated
separate reasoning content. A cap guarantees termination, not a good conclusion.

The selected knowledge revision is ranked using the whole situation, mission and
decision definition. Nonmatching policies remain eligible, instead of disappearing
when the question lacks their keywords. Complete excerpts and lessons enter a
24,000-byte context budget; omissions are reported. Small selected revisions can
include all excerpts. Unselected uploads, other projects and spreadsheet outcomes
do not enter this reference selection. Builder and standalone use the same ordering
and budgeting, with exact source/excerpt checks.

The final-response schema keeps short fields and accessible citation IDs. Validation
rejects invalid/truncated JSON, repeated JSON keys, inaccessible or repeated citation
IDs, invented recommendation quotes and source quotes without their citation. Declared
missing information withholds a decisive draft. Abstention keeps the supplied
explanation while withholding a decision. A question must have question syntax;
these checks do not prove it is necessary or that prose is factually correct.

New base exports use `quartermaster.export/v3`, bind to the exact successful test
hash, and have no candidate, training or evaluation IDs. They preserve `context/v3`
and its inference parameters. Old version 1/2 exports and old context/generation
profiles retain their historical meanings and wire fields. SFT construction and
frozen diagnostic prompts remain unchanged. No new framework or dependency was added.

## Local verification — 2026-10-24

The live comparison uses the same four previously inspected Bank Marketing records
from context-selection-02, not new independent holdouts. Each request includes all
11 selected knowledge excerpts and the same three owner-approved lessons, with no
context omissions. Both arms use identical question, record, context, schema, system
instructions and generation settings.

| Model | Base GGUF / existing candidate |
| --- | --- |
| Base | `c85ac7c9cb8ecb014270ee852dd9580cff838ad294120c6dabfb41f5be29b004` |
| Existing LoRA | `6bed83199e1f551793c2dfbb49a2748ae22b7b162c9bc6071a7a349eec358fd2` |

The existing LoRA is the latest 120-step **decision-only** candidate. Complete advice
is outside its supervised target; this check does not establish improvement or a
new accepted adviser. Its prior failed decision-policy gates remain unchanged.

| Observed result | Base | Existing LoRA |
| --- | --- | --- |
| Readable final responses | 4/4 | 4/4 |
| Validated displayed responses | 4/4 | 4/4 |
| Clarification decisions | 4/4 | 4/4 |
| Responses with citations | 0/4 | 0/4 |

The known interval, no-history and unknown-category cases still ask for supplied or
unnecessary information. The missing-interval case asks for an interval/dates;
this alone does not certify its explanation or usefulness. No owner quality ratings
were manufactured. No model was promoted, and no new supervision was created.

An initial one-case preparation check used a smaller thinking budget and an earlier
instruction draft; its invented quote was rejected and it remains preserved outside
the paired comparison. No failed output was silently repaired or counted as a gain.

The working bank project is available at
<http://127.0.0.1:18016/projects/f02c8241-c267-4eb4-9c9b-70ae3b90aa0c/test>.
Use this working copy for subsequent teaching; its new corrections live in
`data/working-adviser-01/appdata`. The original project/review services remain unchanged.

Executed verification:

- `make test`: **675 passed**; `make lint`: passed.
- Real browser/API comparison saved base test `9d16837c-dd2a-4876-aa6b-b70459cb4b59`
  and existing-LoRA test `c84583e4-810d-4a32-a915-954fb9250508`. Their case, system,
  context, schema, parameters, evidence and lessons match. No active selection changed.
- Teach, Test and Export pages returned 200. All eleven provided source links were
  accessible. The browser distinguishes provided knowledge from model-selected citations.
- Final base archive `4e3af538-45f6-41a4-8317-3d821ddbdcc3` passed `make test-export`
  in a fresh offline CPU container. Its context and eleven excerpts match the saved
  test; builder/database/training modules are absent. This is a transport/context
  check, not evidence of useful or correctly cited advice.
- The final web image is
  `sha256:5f83fabd5a03757ab12a5c1988a98aac9ded7c03ae8056d3a7c9ec552ace2a9d`;
  standalone image is
  `sha256:14503852b4ca1e1af9abce0003761aab65378964108a71a3dc5ac71434134715`.
  An earlier archive/report remains preserved before the malformed-completion error
  handling fix. Neither export run retrained or changed model bytes.

Local raw records, exact commands, image/model pins, paired API records and audits
live under ignored `data/working-adviser-01/`. The current archive's report is
`appdata/artifacts/exports/f02c8241-c267-4eb4-9c9b-70ae3b90aa0c/4e3af538-45f6-41a4-8317-3d821ddbdcc3/export-check-f90c6ae1-1ad8-42ae-8993-7cae43601a57.json`
under that directory. Generated model files and downloaded data remain outside Git.
