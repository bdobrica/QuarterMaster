"""Finite, replayable generation profiles shared by advice, evaluation and export."""

from copy import deepcopy

from quartermaster.errors import DomainError

LEGACY_PARAMETERS = {
    "temperature": 0,
    "seed": 17,
    "max_tokens": 512,
    "chat_template_kwargs": {"enable_thinking": False},
}
PARAMETERS = {**LEGACY_PARAMETERS, "max_tokens": 1024}


def checked_parameters(value=None):
    """Never substitute today's defaults for a captured historical request."""
    value = PARAMETERS if value is None else value
    if value not in (LEGACY_PARAMETERS, PARAMETERS):
        raise DomainError(
            "LOCAL_PARAMETERS: Use the supported 512- or 1024-token generation profile.", 409
        )
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
