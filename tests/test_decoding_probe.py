"""Probe controls and strict label parsing; no real model requests."""

import json
from copy import deepcopy

import pytest

from quartermaster.contracts.advice import DecisionOnly
from quartermaster.contracts.reliability import ReliabilityRequest
from quartermaster.decoding_probe import (
    VARIANTS,
    VISIBLE_DECISION_CONTRACT,
    classification,
    explicit_contract,
    variants,
)
from quartermaster.errors import DomainError
from quartermaster.generation import PARAMETERS
from quartermaster.reliability import CONTRACT_SYSTEM, digest


def request():
    data = dict(
        arm="decision_only",
        system=CONTRACT_SYSTEM,
        context=json.dumps(
            {"case": {"situation": "Development question."}, "approved_lessons": []}
        ),
        parameters=PARAMETERS,
        response_schema=DecisionOnly.model_json_schema(),
    )
    return ReliabilityRequest(**data, input_sha256=digest(data))


def response(content, **changes):
    return {"choices": [{"finish_reason": "stop", "message": {"content": content}, **changes}]}


def test_variants_preserve_snapshot_and_enum_control():
    saved = request()
    before = saved.model_dump_json()
    options = variants(saved, "pinned-base")
    assert [v["variant"] for v in options] == list(VARIANTS)
    a, b, c, rotated, plain = [v["payload"] for v in options]
    assert saved.model_dump_json() == before
    expected = deepcopy(a)
    expected["response_format"]["json_schema"]["schema"]["properties"]["decision"]["enum"].reverse()
    assert b == expected
    assert c["response_format"] == rotated["response_format"]
    assert {k: v for k, v in c.items() if k != "messages"} == {
        k: v for k, v in rotated.items() if k != "messages"
    }
    assert c["messages"][1] == rotated["messages"][1]
    assert "A=answer; B=clarify; C=abstain" in c["messages"][0]["content"]
    assert "A=clarify; B=abstain; C=answer" in rotated["messages"][0]["content"]
    assert "response_format" not in plain and "grammar" not in plain
    for v in options:
        p = v["payload"]
        assert p["messages"][1]["content"] == saved.context
        assert {k: p[k] for k in PARAMETERS} == PARAMETERS
        assert p["logprobs"] and p["return_tokens"] and p["verbose"]
        assert p["post_sampling_probs"] is False
        assert p["top_logprobs"] == 5 and p["stream"] is False
        assert p["model"] == "pinned-base"


def test_explicit_contract_changes_only_visible_instructions():
    saved = request()
    before = saved.model_dump_json()
    original = variants(saved, "base")[0]
    visible = explicit_contract(saved, "base")
    expected = deepcopy(original)
    expected["variant"] = "explicit_contract"
    expected["payload"]["messages"][0]["content"] += VISIBLE_DECISION_CONTRACT
    assert visible == expected
    assert saved.model_dump_json() == before
    assert visible["payload"]["response_format"] == original["payload"]["response_format"]
    for action in ("answer", "clarify", "abstain"):
        assert VISIBLE_DECISION_CONTRACT.count('{"decision":"' + action + '"}') == 1
        assert classification(visible, response('{"decision":"' + action + '"}')) == {
            "literal": action,
            "decision": action,
        }


@pytest.mark.parametrize("content", ['{"choice":"A"}', '{"decision":"answer","extra":1}'])
def test_visible_contract_keeps_strict_decision_parsing(content):
    with pytest.raises(ValueError):
        classification(explicit_contract(request(), "base"), response(content))


@pytest.mark.parametrize(
    "index,content,expected",
    [
        (0, '{"decision":"answer"}', "answer"),
        (1, '{"decision":"clarify"}', "clarify"),
        (2, '{"choice":"A"}', "answer"),
        (2, '{"choice":"C"}', "abstain"),
        (3, '{"choice":"A"}', "clarify"),
        (3, '{"choice":"C"}', "answer"),
        (4, " abstain\n", "abstain"),
    ],
)
def test_labels_decode_through_the_explicit_mapping(index, content, expected):
    assert (
        classification(variants(request(), "base")[index], response(content))["decision"]
        == expected
    )


@pytest.mark.parametrize(
    "index,content",
    [
        (0, '{"decision":"answer","reason":"extra"}'),
        (0, '{"decision":"answer","decision":"abstain"}'),
        (0, '{"decision":true}'),
        (0, '{"decision":["answer"]}'),
        (0, "[]"),
        (0, "null"),
        (2, '{"choice":"answer"}'),
        (3, '{"decision":"A"}'),
        (4, '"answer"'),
        (4, "answer."),
        (4, "I would answer."),
        (4, "answer clarify"),
    ],
)
def test_invalid_outputs_never_receive_label_credit(index, content):
    with pytest.raises((ValueError, TypeError)):
        classification(variants(request(), "base")[index], response(content))


def test_unfinished_generation_and_unreviewed_request_are_refused():
    with pytest.raises(DomainError, match="LOCAL_TOKEN_LIMIT"):
        classification(
            variants(request(), "base")[0],
            response('{"decision":"answer"}', finish_reason="length"),
        )
    saved = request()
    for changes in (
        {"arm": "compact_contract"},
        {"context": '{"approved_lessons":["Do not include this."]}'},
        {"response_schema": {}},
        {"system": "Different, unrecognized prompt."},
    ):
        with pytest.raises(DomainError, match="DECODING_INPUT"):
            variants(saved.model_copy(update=changes), "base")
