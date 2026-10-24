"""Small operator diagnostic; never imported by normal advice, teaching or exports."""

import json
from copy import deepcopy

from quartermaster.contracts.advice import DecisionOnly
from quartermaster.errors import DomainError
from quartermaster.generation import checked_parameters, completed_choice

ACTIONS = ("answer", "clarify", "abstain")
VARIANTS = ("original", "reversed_enum", "codes", "rotated_codes", "plain")
JSON_INSTRUCTION = "Return only JSON matching the response schema."
PLAIN_INSTRUCTION = (
    "Return exactly one action word: answer, clarify, or abstain. "
    "Do not return JSON or explanations."
)
VISIBLE_DECISION_CONTRACT = """
Select exactly one decision:
answer: The requested question can be answered from supplied evidence. This includes
reporting that an explicitly unknown category establishes neither yes nor no.
clarify: A specific obtainable fact needed to answer is missing or its scope is ambiguous.
abstain: The requested conclusion is unsupported under the available evidence and
constraints; asking for an ordinary missing fact would not establish that conclusion.
The output has exactly one field named decision. Its value must be answer, clarify,
or abstain. Return only one of these JSON objects, with no explanation or extra fields:
{"decision":"answer"}
{"decision":"clarify"}
{"decision":"abstain"}
These are output alternatives, not labeled examples or a preference for any action.
"""


def explicit_contract(request, alias):
    """One fixed decision-only baseline; preserve the schema, context and sampling.

    The same visible contract must be captured in any subsequent reviewed SFT
    messages. This helper neither creates supervision nor starts training.
    """
    original = variants(request, alias)[0]
    original["variant"] = "explicit_contract"
    original["payload"]["messages"][0]["content"] += VISIBLE_DECISION_CONTRACT
    return original


def variants(request, alias):
    """Replay a captured minimal request, changing only the documented representations.

    Diagnostic flags are identical throughout and differ from the earlier replay.
    In particular, the plain arm also changes one output-format instruction, so it
    does not isolate a grammar effect from all other response-format influences.
    """
    if (
        request.arm != "decision_only"
        or request.response_schema != DecisionOnly.model_json_schema()
        or request.system.count(JSON_INSTRUCTION) != 1
        or json.loads(request.context).get("approved_lessons") != []
    ):
        raise DomainError("DECODING_INPUT: Use a saved no-lessons minimal development request.")
    original = {
        "model": alias,
        "messages": [
            {"role": "system", "content": request.system},
            {"role": "user", "content": request.context},
        ],
        **checked_parameters(request.parameters),
        "stream": False,
        "logprobs": True,
        "top_logprobs": 5,
        "post_sampling_probs": False,
        "return_tokens": True,
        "verbose": True,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "grounded_advice",
                "strict": True,
                "schema": deepcopy(request.response_schema),
            },
        },
    }
    result = []
    for name in VARIANTS:
        payload = deepcopy(original)
        mapping = dict(zip(ACTIONS, ACTIONS, strict=True))
        if name == "reversed_enum":
            payload["response_format"]["json_schema"]["schema"]["properties"]["decision"][
                "enum"
            ].reverse()
        if name in ("codes", "rotated_codes"):
            meanings = ACTIONS if name == "codes" else ("clarify", "abstain", "answer")
            mapping = dict(zip(("A", "B", "C"), meanings, strict=True))
            schema = payload["response_format"]["json_schema"]["schema"]
            schema["title"] = "NeutralDecision"
            schema["properties"] = {
                "choice": {"enum": ["A", "B", "C"], "title": "Choice", "type": "string"}
            }
            schema["required"] = ["choice"]
            payload["messages"][0]["content"] += (
                "\nEncode the selected action in choice using this mapping: "
                + "; ".join(f"{code}={meaning}" for code, meaning in mapping.items())
                + '. Return only {"choice":"A"}, {"choice":"B"}, or {"choice":"C"}.'
            )
        if name == "plain":
            payload.pop("response_format")
            payload["messages"][0]["content"] = request.system.replace(
                JSON_INSTRUCTION, PLAIN_INSTRUCTION
            )
        result.append({"variant": name, "mapping": mapping, "payload": payload})
    return result


def classification(variant, response):
    """Strict diagnostic parsing; do not extract a label from explanatory prose."""
    content = completed_choice(response).strip()
    if variant["variant"] == "plain":
        literal = content
    else:
        data = json.loads(content, object_pairs_hook=unique_keys)
        field = "choice" if variant["variant"] in ("codes", "rotated_codes") else "decision"
        if not isinstance(data, dict) or set(data) != {field}:
            raise ValueError("Expected exactly one classification field")
        literal = data[field]
    if not isinstance(literal, str) or literal not in variant["mapping"]:
        raise ValueError("Expected one declared literal label")
    return {"literal": literal, "decision": variant["mapping"][literal]}


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON keys")
        result[key] = value
    return result
