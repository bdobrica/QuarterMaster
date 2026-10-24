"""Finite, replayable generation profiles shared by advice, evaluation and export."""

import json
from copy import deepcopy

from quartermaster.errors import DomainError

LEGACY_PARAMETERS = {
    "temperature": 0,
    "seed": 17,
    "max_tokens": 512,
    "chat_template_kwargs": {"enable_thinking": False},
}
PARAMETERS = {**LEGACY_PARAMETERS, "max_tokens": 1024}
# Product advice only. Historical experiments and supervised rows retain PARAMETERS.
ADVICE_PARAMETERS = {
    **PARAMETERS,
    "max_tokens": 2048,
    "chat_template_kwargs": {"enable_thinking": True},
    "reasoning_budget_tokens": 512,
    "reasoning_format": "deepseek",
}


def checked_parameters(value=None):
    """Never substitute today's defaults for a captured historical request."""
    value = PARAMETERS if value is None else value
    if value not in (LEGACY_PARAMETERS, PARAMETERS, ADVICE_PARAMETERS):
        raise DomainError("LOCAL_PARAMETERS: Use a supported, bounded generation profile.", 409)
    return deepcopy(value)


def completed_choice(response):
    choices = response["choices"]
    if len(choices) != 1:
        raise ValueError
    if choices[0]["finish_reason"] == "length":
        raise DomainError(
            "LOCAL_TOKEN_LIMIT: The answer reached its output limit and was not saved as advice. "
            "Shorten the situation or request a more concise answer, then retry explicitly."
        )
    if choices[0]["finish_reason"] != "stop":
        raise ValueError
    message = choices[0]["message"]
    if message.get("tool_calls") or message.get("refusal"):
        raise ValueError
    return message["content"]


def unambiguous_json(content):
    """Reject repeated keys instead of silently accepting the final conflicting value."""

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Repeated JSON key")
            result[key] = value
        return result

    return json.loads(content, object_pairs_hook=unique)
