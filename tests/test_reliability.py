import asyncio
import json
from copy import deepcopy
from uuid import UUID, uuid4

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from quartermaster import reliability
from quartermaster.app import create_app
from quartermaster.contracts.advice import Case, CompactAdvice
from quartermaster.contracts.reliability import FieldRules, ReliabilityInput
from quartermaster.db import SCHEMA_VERSION, connect, migrate
from quartermaster.errors import DomainError
from quartermaster.field_interpretation import interpret
from quartermaster.generation import PARAMETERS
from quartermaster.inference import (
    CompletionError,
    LocalInference,
    compact_response_schema,
    model_alias,
)
from tests.test_foundation import ORIGIN, select_knowledge, upload
from tests.test_teaching import draft

DICTIONARY = (
    b"# Field definitions\n"
    b"wait is elapsed days; 999 means no earlier inspection.\n"
    b"visits is a count of earlier inspections.\n"
    b"damage is yes or no; unknown establishes neither.\n"
)


def compact(refs=None, **changes):
    return CompactAdvice(
        **{
            "decision": "answer",
            "recommendation": "Two earlier inspections are recorded.",
            "reason": "visits=2 counts inspections, not days.",
            "evidence_refs": refs or [],
            "question": None,
            **changes,
        }
    )


class Measured:
    def __init__(self):
        self.calls = []
        self.error = None
        self.hook = None

    async def measured_advice(self, *, system, context, parameters, compact):
        self.calls.append((system, json.loads(context), parameters, compact))
        if self.hook:
            self.hook()
        if self.error:
            raise DomainError(self.error)
        data = json.loads(context)
        refs = [data["retrieved_evidence"][0]["citation_id"]]
        if compact:
            return globals()["compact"](refs), 80
        return draft(refs=refs, quotes=[data["case"]["situation"]]), 180


@pytest.fixture
def lab(settings, project_fixture):
    settings.local_base_url = "http://127.0.0.1:8080/v1"
    settings.local_model_sha256 = "a" * 64
    fake = Measured()
    with TestClient(create_app(settings, inference=fake)) as client:
        project = client.post("/api/projects", json=project_fixture).json()["id"]
        source = upload(client, project, DICTIONARY, "dictionary.md", "knowledge").json()
        select_knowledge(client, project, [source["id"]])
        evidence = client.get(f"/api/projects/{project}/knowledge/search?q=definitions").json()
        ref = evidence[0]["chunk"]["citation_id"]
        rules = [
            dict(
                field="wait",
                kind="integer",
                definition="Elapsed days since earlier inspection.",
                unit="days",
                sentinels={"999": "No earlier inspection."},
                unknown_values=["unknown"],
                citation_id=ref,
                source_quote="wait is elapsed days; 999 means no earlier inspection.",
            ),
            dict(
                field="visits",
                kind="integer",
                definition="Number of earlier inspections.",
                unit="inspections",
                citation_id=ref,
                source_quote="visits is a count of earlier inspections.",
            ),
            dict(
                field="damage",
                kind="category",
                definition="Reported damage status.",
                unit=None,
                unknown_values=["unknown"],
                categories={"yes": "Damage reported.", "no": "No damage reported."},
                citation_id=ref,
                source_quote="damage is yes or no; unknown establishes neither.",
            ),
        ]
        action = dict(
            situation="How many earlier inspections are recorded?",
            decision_inputs={"wait": "999", "visits": "2", "damage": "unknown"},
            field_rules={"reviewed": True, "rules": rules},
            inputs_available_at_decision=True,
        )
        yield client, project, fake, settings, action


def url(lab):
    return f"/api/projects/{lab[1]}/reliability-runs"


def execute(lab, action=None):
    response = lab[0].post(url(lab), json=action or lab[4])
    assert response.status_code == 200, response.text
    return response.json()


def test_three_arm_control_and_immutable_provenance(lab):
    client, project, fake, settings, action = lab
    before = client.get(f"/api/projects/{project}").json()
    run = execute(lab)
    assert run["status"] == "completed" and run["revision"] == 5
    assert len(fake.calls) == 3 and all(o["schema_valid"] for o in run["outputs"])
    a, b, c = [call[1] for call in fake.calls]
    assert a == b
    assert {k: v for k, v in c.items() if k != "field_interpretations"} == a
    assert [call[2] for call in fake.calls] == [PARAMETERS] * 3
    assert [call[3] for call in fake.calls] == [False, True, True]
    assert fake.calls[0][0] == reliability.SYSTEM
    assert fake.calls[1][0] == fake.calls[2][0] == reliability.COMPACT_SYSTEM
    assert [fact["state"] for fact in c["field_interpretations"]] == [
        "sentinel",
        "value",
        "unknown",
    ]
    assert c["field_interpretations"][1]["value"] == 2
    assert c["field_interpretations"][1]["unit"] == "inspections"
    assert c["field_interpretations"][0]["value"] is None
    assert c["field_interpretations"][2]["value"] is None
    assert all(
        request["input_sha256"]
        == reliability.digest({k: v for k, v in request.items() if k != "input_sha256"})
        for request in run["requests"]
    )
    assert run["evidence"][0]["excerpt_sha256"] and run["rules_sha256"]
    assert [o["completion_tokens"] for o in run["outputs"]] == [180, 80, 80]
    assert client.get(f"/projects/{project}/reliability?run_id={run['id']}").status_code == 200
    assert client.get(f"/api/projects/{project}").json() == before
    with connect(settings.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM reliability_runs").fetchone()[0] == 5
        for table in (
            "feedback",
            "lesson_revisions",
            "training_examples",
            "training_runs",
            "adviser_versions",
            "evaluation_holdouts",
        ):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


@pytest.mark.parametrize(
    "value,state,typed",
    [
        (None, "missing", None),
        ("", "missing", None),
        ("unknown", "unknown", None),
        ("999", "sentinel", None),
        ("0", "value", 0),
        ("12", "value", 12),
        ("-1", "invalid", None),
        ("2.5", "invalid", None),
        ("2 days", "invalid", None),
        (" 2", "invalid", None),
    ],
)
def test_exact_interpretation(lab, value, state, typed):
    run = reliability.capture(lab[3], UUID(lab[1]), ReliabilityInput.model_validate(lab[4]))
    rule = FieldRules.model_validate(
        {"reviewed": True, "rules": [lab[4]["field_rules"]["rules"][0]]}
    )
    fact = interpret({"wait": value}, rule, run.evidence)[0]
    assert (fact.state, fact.value, fact.raw_value) == (state, typed, value)
    assert interpret({}, rule, run.evidence)[0].state == "absent"


@pytest.mark.parametrize(
    "change",
    [
        {"decision_inputs": {"wait": True}},
        {"decision_inputs": {"wait": 2}},
        {"inputs_available_at_decision": 1},
        {"inputs_available_at_decision": False},
        {"observed_outcome": "yes"},
        {"unexpected": "sensitive"},
        {"field_rules": {"reviewed": False, "rules": []}},
        {"field_rules": {"reviewed": 1, "rules": []}},
    ],
)
def test_invalid_inputs_do_not_call_model_or_mutate(lab, change):
    response = lab[0].post(url(lab), json={**lab[4], **change})
    assert response.status_code == 422
    assert not lab[2].calls and lab[0].get(url(lab)).json() == []
    assert "sensitive" not in response.text


@pytest.mark.parametrize(
    "change",
    [
        {"citation_id": str(uuid4())},
        {"source_quote": "invented quote"},
        {"sentinels": {"unknown": "negative fact"}},
    ],
)
def test_invalid_or_ambiguous_rule_rejected_before_transmission(lab, change):
    action = deepcopy(lab[4])
    action["field_rules"]["rules"][0].update(change)
    response = lab[0].post(url(lab), json=action)
    assert response.status_code in (404, 422)
    assert not lab[2].calls and lab[0].get(url(lab)).json() == []


def test_cross_project_and_removed_source_rejected(lab, project_fixture):
    client, project, fake, _, action = lab
    other = client.post("/api/projects", json=project_fixture).json()["id"]
    assert client.post(f"/api/projects/{other}/reliability-runs", json=action).status_code == 422
    revision = client.get(f"/api/projects/{project}/knowledge").json()["id"]
    assert select_knowledge(client, project, [], revision).status_code == 201
    assert client.post(url(lab), json=action).status_code == 404
    assert not fake.calls


def test_schema_citation_and_quality_scores_stay_separate(lab):
    client, project, fake, _, _ = lab

    async def bad(**kwargs):
        return compact([str(uuid4())]), 22

    fake.measured_advice = bad
    run = execute(lab)
    assert run["outputs"][1]["schema_valid"] is True
    assert run["outputs"][1]["citations_valid"] is False
    assert run["outputs"][1]["advice"] is None
    path = f"{url(lab)}/{run['id']}/reviews"
    assert client.get(path).json() == []
    rating = dict(
        expected_revision=0,
        factual_quality="fail",
        clarification_relevance="fail",
        unsupported_assertions="fail",
        citation_relevance="fail",
        decision_usefulness="not_useful",
        notes="Counts and dates were confused.",
    )
    assert client.post(path + "/compact_v2", json=rating).status_code == 200
    assert client.post(path + "/compact_v2", json=rating).status_code == 409
    assert client.get(path).json()[0]["factual_quality"] == "fail"
    assert client.get(f"{url(lab)}/{run['id']}").json() == run
    assert client.get(f"/projects/{project}/reliability?run_id={run['id']}").status_code == 200
    assert client.post(path + "/invalid", json=rating).status_code == 422


def test_failure_is_durable_and_does_not_retry(lab):
    lab[2].error = "LOCAL_TOKEN_LIMIT: Synthetic truncation."
    run = execute(lab)
    assert len(lab[2].calls) == 3
    assert all(not o["schema_valid"] and o["advice"] is None for o in run["outputs"])
    assert len(lab[0].get(url(lab)).json()) == 1


def test_recovery_and_busy_run(lab):
    client, project, fake, settings, action = lab
    captured = reliability.capture(settings, UUID(project), ReliabilityInput.model_validate(action))
    reliability.save(settings, captured)
    assert client.post(url(lab), json=action).status_code == 409
    assert not fake.calls
    reliability.recover(settings)
    interrupted = reliability.get_run(settings, UUID(project), captured.id)
    assert interrupted.status == "interrupted" and interrupted.revision == 2
    assert reliability.get_run(settings, UUID(project), captured.id).requests == captured.requests
    assert execute(lab)["status"] == "completed"


def test_protected_record_cannot_be_development_even_with_new_question(lab):
    client, project, _, settings, action = lab
    # Existing holdout record deliberately uses a different question and JSON prefix.
    case = Case(
        case_id=uuid4(),
        situation="Reserved question.\nRecorded inputs: " + json.dumps(action["decision_inputs"]),
    )
    from quartermaster import teaching
    from quartermaster.contracts.teaching import TestInput
    from tests.test_teaching import FakeInference

    test = asyncio.run(
        teaching.advise(
            settings, FakeInference(), UUID(project), TestInput(situation=case.situation)
        )
    )
    from quartermaster.holdouts import case_fingerprint

    with connect(settings.database_path) as connection:
        connection.execute(
            "INSERT INTO evaluation_holdouts VALUES (?,?,?,?)",
            (project, str(test.case.case_id), case_fingerprint(test.case), str(test.id)),
        )
    response = client.post(url(lab), json=action)
    assert response.status_code == 409 and "RELIABILITY_HELD_OUT" in response.text
    assert not lab[2].calls


@pytest.mark.parametrize(
    "changes",
    [
        {"decision": "clarify", "question": None},
        {"decision": "answer", "question": "Why?"},
        {"question": "One? Two?", "decision": "clarify"},
        {"recommendation": "x" * 241},
        {"reason": "x" * 401},
        {"question": "x" * 161, "decision": "clarify"},
        {"schema_version": "quartermaster.advice/v1"},
        {"extra": "secret"},
        {"evidence_refs": ["not-a-citation"]},
        {"evidence_refs": ["a" * 36]},
    ],
)
def test_compact_contract_invalid_combinations(changes):
    with pytest.raises(ValidationError):
        compact(**changes)


def test_compact_wire_uses_actual_citation_enum_and_returns_usage(settings):
    ref = str(uuid4())
    context = json.dumps(
        {"retrieved_evidence": [{"citation_id": ref, "text": "Actual reference."}]}
    )
    schema = compact_response_schema(context)
    assert len(schema["oneOf"]) == 3
    assert schema["oneOf"][0]["properties"]["evidence_refs"]["items"]["enum"] == [ref]
    alias = model_alias("a" * 64)
    calls = []

    def respond(request):
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": alias}]})
        calls.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": compact([ref]).model_dump_json()},
                    }
                ],
                "usage": {"completion_tokens": 87},
            },
        )

    inference = LocalInference(
        settings,
        transport=httpx.MockTransport(respond),
        alias=alias,
        base_url="http://localhost/v1",
    )
    result, tokens = asyncio.run(
        inference.measured_advice(system="Short advice", context=context, compact=True)
    )
    assert result.schema_version == "quartermaster.advice/v2" and tokens == 87
    assert calls[0]["response_format"]["json_schema"]["schema"] == schema
    assert calls[0]["max_tokens"] == 1024


def test_v6_migration_preserves_bytes(lab):
    _, _, _, settings, _ = lab
    with connect(settings.database_path) as connection:
        before = [tuple(r) for r in connection.execute("SELECT * FROM adviser_revisions")]
        connection.execute("DROP TABLE reliability_runs")
        connection.execute("DROP TABLE reliability_reviews")
        connection.execute("PRAGMA user_version=6")
    migrate(settings.database_path)
    migrate(settings.database_path)
    with connect(settings.database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert [tuple(r) for r in connection.execute("SELECT * FROM adviser_revisions")] == before


def test_model_failure_preserves_token_usage_without_partial_advice(settings):
    alias = model_alias("a" * 64)

    def respond(request):
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": alias}]})
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "length", "message": {"content": "private partial"}}],
                "usage": {"completion_tokens": 1024},
            },
        )

    inference = LocalInference(
        settings,
        transport=httpx.MockTransport(respond),
        alias=alias,
        base_url="http://localhost/v1",
    )
    with pytest.raises(CompletionError) as failure:
        asyncio.run(
            inference.measured_advice(
                system="Adviser", context='{"retrieved_evidence":[]}', compact=True
            )
        )
    assert failure.value.completion_tokens == 1024
    assert "private partial" not in str(failure.value)


def test_csrf_forms_and_invalid_configuration(lab):
    client, project, fake, _, action = lab
    assert (
        client.post(
            url(lab), json=action, headers={"Origin": "https://hostile.invalid"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/projects/{project}/reliability", data={"configuration": json.dumps(action)}
        ).status_code
        == 403
    )
    response = client.post(
        f"/projects/{project}/reliability",
        headers=ORIGIN,
        data={"configuration": "private invalid JSON"},
    )
    assert response.status_code == 422 and "private invalid JSON" not in response.text
    assert not fake.calls


def test_unexpected_adapter_failure_is_durable(lab):
    async def broken(**kwargs):
        raise RuntimeError("sanitized by framework")

    lab[2].measured_advice = broken
    with pytest.raises(RuntimeError):
        asyncio.run(
            reliability.run_comparison(
                lab[3], lab[2], UUID(lab[1]), ReliabilityInput.model_validate(lab[4])
            )
        )
    saved = reliability.list_runs(lab[3], UUID(lab[1]))
    assert len(saved) == 1 and saved[0].status == "interrupted"
    assert "RELIABILITY_FAILED" in saved[0].error


def test_rule_text_is_never_executed_and_rendering_is_escaped(lab):
    action = deepcopy(lab[4])
    action["field_rules"]["rules"][0]["definition"] = "<script>execute secrets</script>"
    run = execute(lab, action)
    page = lab[0].get(f"/projects/{lab[1]}/reliability?run_id={run['id']}").text
    assert "<script>execute secrets</script>" not in page
    assert "\\u003cscript\\u003e" in page or "&lt;script&gt;" in page


def test_unreviewed_or_malformed_adapter_does_not_get_quality_credit(lab):
    async def unsupported(**kwargs):
        return compact(), 25

    lab[2].measured_advice = unsupported
    run = execute(lab)
    assert run["outputs"][1]["schema_valid"]
    assert run["outputs"][1]["citations_valid"]
    assert run["outputs"][1]["advice"] is None
    assert "ADVICE_SUPPORT" in run["outputs"][1]["error"]
    assert lab[0].get(f"{url(lab)}/{run['id']}/reviews").json() == []
