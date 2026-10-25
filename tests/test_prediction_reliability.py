"""A structurally valid model response is not necessarily a useful decision."""

import json
from datetime import UTC, datetime
from uuid import UUID

import pytest

from quartermaster.contracts.advice import Case
from quartermaster.contracts.adviser import AdviserSpec
from quartermaster.contracts.answers import NumberAnswer
from quartermaster.contracts.prediction import Prediction
from quartermaster.prediction_context import RESPONSE_ORDER, assemble, completion_for
from tests.smoke_prediction_reliability import CATEGORY, NUMBER, check


def prediction(behavior="answer", *, value=55000, question=None):
    return Prediction(
        behavior=behavior,
        target=(
            {"kind": "number", "value": value, "unit": "EUR"}
            if isinstance(value, (int, float))
            else {"kind": "category", "value": value}
        )
        if behavior == "answer"
        else None,
        explanation="Synthetic development result.",
        evidence_refs=[],
        question=question,
        limitations=[],
    )


def test_valid_wrong_numbers_and_categories_fail_capability_check():
    assert check(prediction(), NUMBER, 55000)
    assert not check(prediction(value=1.2e15), NUMBER, 55000)
    assert check(prediction(value="Visit"), CATEGORY, "Visit")
    assert not check(prediction(value="Pass"), CATEGORY, "Visit")
    assert not check(prediction("abstain"), NUMBER, 55000)
    assert not check(None, NUMBER, 55000)


@pytest.mark.parametrize(
    ("expected", "question"),
    [
        ("area", "What is the floor area?"),
        ("repair", "Are repairs needed?"),
        ("price", "What is the asking price?"),
    ],
)
def test_missing_data_requires_relevant_question_and_withheld_target(expected, question):
    assert check(prediction("clarify", question=question), NUMBER, expected)
    assert not check(prediction("clarify", question="What is the wall colour?"), NUMBER, expected)
    assert not check(prediction(), NUMBER, expected)
    assert not check(prediction("abstain"), NUMBER, expected)
    assert check(prediction("abstain"), NUMBER, "abstain")


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("context/v4", "862d07a754c78c57919bf3c8c032db819fc3b2e5c881ca9582ce039bbba3d719"),
        ("context/v5", "7371c97d817915ab7d24e511eb3b3612c8d9e3b54dc34844b4f45ff22bfcf5f3"),
    ],
)
def test_historical_prediction_profiles_keep_their_original_hashes(version, expected):
    spec = AdviserSpec(
        id=UUID(int=1),
        revision=1,
        created_at=datetime(2026, 10, 25, tzinfo=UTC),
        name="Historical control",
        mission="My rule is 2 hours per item and one setup hour.",
    )
    item = assemble(
        spec,
        Case(case_id=UUID(int=2), situation="There are 3 items."),
        NumberAnswer(kind="number", unit="hours"),
        [],
        prompt_version=version,
    )
    assert item.input_sha256 == expected


def test_new_profile_keeps_full_snapshot_but_only_decision_facts_in_model_context():
    spec = AdviserSpec(
        id=UUID(int=1),
        revision=1,
        created_at=datetime(2026, 10, 25, tzinfo=UTC),
        name="Configured control",
        mission="Help me decide my personal price.",
        answer_format=NUMBER,
        business_goal="Use my preferences.",
    )
    case = Case(
        case_id=UUID(int=2),
        situation="Decision-time facts.",
        choices=["One", "Two"],
        observed_outcome="This later outcome must not enter a prompt.",
    )
    item = assemble(spec, case, NUMBER, [])
    data = json.loads(item.context)
    assert item.case == case
    assert data["case_facts"] == case.situation and data["case_choices"] == case.choices
    assert data["owner_policy"] == spec.mission and data["owner_goal"] == spec.business_goal
    assert str(case.case_id) not in item.context and "later outcome" not in item.context
    assert data["source_excerpts"] == data["previous_owner_decisions"] == []
    for branch in item.response_schema["oneOf"]:
        assert list(branch["properties"]) == list(RESPONSE_ORDER)
        assert branch["required"] == list(RESPONSE_ORDER)
    assert list(json.loads(completion_for(prediction(), "context/v6"))) == list(RESPONSE_ORDER)
    for version in ("context/v4", "context/v5"):
        assert completion_for(prediction(), version) == prediction().model_dump_json()
