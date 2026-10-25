import asyncio
import json
from copy import deepcopy
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from quartermaster import reliability
from quartermaster.app import create_app
from quartermaster.contracts.advice import Case, CompactAdvice
from quartermaster.contracts.reliability import (
    DecisionOnly,
    FieldRules,
    ReliabilityInput,
    ReliabilityRun,
)
from quartermaster.contracts.teaching import Lesson, LessonText
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
        self.schema_contexts = []

    async def measured_advice(self, *, system, context, parameters, compact, schema_context=None):
        self.calls.append((system, json.loads(context), parameters, compact))
        self.schema_contexts.append(schema_context)
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
        connection.execute("DROP TABLE answer_reviews")
        connection.execute("DROP TABLE knowledge_proposals")
        connection.execute("DROP TABLE reliability_runs")
        connection.execute("DROP TABLE reliability_reviews")
        connection.execute("DROP TABLE owner_decisions")
        connection.execute("DROP TABLE muster_imports")
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


def ablation_action(lab, *, count=3, status="applied"):
    action = deepcopy(lab[4])
    lessons = [
        Lesson(
            id=uuid4(),
            project_id=UUID(lab[1]),
            feedback_id=uuid4(),
            case_id=uuid4(),
            revision=4,
            created_at=datetime.now(UTC),
            status=status,
            origin="OWNER_DRAFT",
            text=LessonText(
                applicability=f"Inspection context {index}.",
                instruction=f"Reviewed instruction {index}.",
            ),
        )
        for index in range(count)
    ]
    # Seed approved records as fixture data; the experiment may only read them.
    with connect(lab[3].database_path) as connection:
        for lesson in lessons:
            connection.execute(
                "INSERT INTO lesson_revisions VALUES (?,?,?,?)",
                (str(lesson.id), lab[1], 4, lesson.model_dump_json()),
            )
    action["lesson_ablation"] = dict(
        relevant_id=str(lessons[0].id),
        relevant_rationale="Applies to the requested field.",
        irrelevant_id=str(lessons[1].id),
        irrelevant_rationale="Applies to a different question.",
    )
    return action, lessons


def test_lesson_ablation_changes_only_lesson_context(lab):
    client, project, fake, settings, _ = lab
    action, lessons = ablation_action(lab)
    with connect(settings.database_path) as connection:
        before = [tuple(r) for r in connection.execute("SELECT * FROM lesson_revisions")]
    run = execute(lab, action)
    assert run["schema_version"] == "quartermaster.reliability-run/v2"
    assert run["revision"] == 6 and len(fake.calls) == 4
    bodies = [call[1] for call in fake.calls]
    controls = [{k: v for k, v in body.items() if k != "approved_lessons"} for body in bodies]
    assert all(body == controls[0] for body in controls)
    assert [len(body["approved_lessons"]) for body in bodies] == [0, 3, 1, 1]
    assert bodies[2]["approved_lessons"] == [{"text": lessons[0].text.model_dump(mode="json")}]
    assert bodies[3]["approved_lessons"] == [{"text": lessons[1].text.model_dump(mode="json")}]
    assert {item["id"] for item in run["lessons"]} == {str(item.id) for item in lessons}
    assert all(call[0] == reliability.COMPACT_SYSTEM and call[3] for call in fake.calls)
    assert all(call[2] == PARAMETERS for call in fake.calls)
    assert all(
        r["response_schema"] == run["requests"][0]["response_schema"] for r in run["requests"]
    )
    assert all(
        r["input_sha256"] == reliability.digest({k: v for k, v in r.items() if k != "input_sha256"})
        for r in run["requests"]
    )
    with connect(settings.database_path) as connection:
        assert [tuple(r) for r in connection.execute("SELECT * FROM lesson_revisions")] == before
        assert connection.execute("SELECT COUNT(*) FROM training_examples").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM evaluation_holdouts").fetchone()[0] == 0
    page = client.get(f"/projects/{project}/reliability?run_id={run['id']}").text
    assert "Lesson ablation" in page and "All 1 supplied citations accessible" in page
    assert client.get(f"{url(lab)}/{run['id']}/reviews").json() == []
    rating = dict(
        expected_revision=0,
        factual_quality="not_assessed",
        clarification_relevance="fail",
        unsupported_assertions="not_assessed",
        citation_relevance="not_assessed",
        decision_usefulness="not_assessed",
        notes="An evaluation-only observation.",
    )
    assert client.post(f"{url(lab)}/{run['id']}/reviews/no_lessons", json=rating).status_code == 200
    assert client.get(f"{url(lab)}/{run['id']}").json() == run


@pytest.mark.parametrize("change", ["same", "foreign", "missing", "extra", "not_uuid"])
def test_ablation_selection_is_explicit_and_strict(lab, change):
    action, _ = ablation_action(lab)
    selection = action["lesson_ablation"]
    if change == "same":
        selection["irrelevant_id"] = selection["relevant_id"]
    if change == "foreign":
        selection["relevant_id"] = str(uuid4())
    if change == "missing":
        selection.pop("relevant_rationale")
    if change == "extra":
        selection["instruction"] = "unreviewed replacement"
    if change == "not_uuid":
        selection["relevant_id"] = "not-a-uuid"
    response = lab[0].post(url(lab), json=action)
    assert response.status_code == 422
    assert not lab[2].calls and lab[0].get(url(lab)).json() == []


@pytest.mark.parametrize("status", ["pending", "reviewed", "rejected"])
def test_ablation_never_uses_unapplied_lessons(lab, status):
    action, _ = ablation_action(lab, status=status)
    response = lab[0].post(url(lab), json=action)
    assert response.status_code == 422 and "RELIABILITY_LESSONS" in response.text
    assert not lab[2].calls


def test_all_lessons_arm_refuses_silent_omissions(lab):
    action, _ = ablation_action(lab, count=9)
    response = lab[0].post(url(lab), json=action)
    assert response.status_code == 422 and "without omissions" in response.text
    assert not lab[2].calls


def test_old_snapshot_loads_and_run_arms_cannot_be_mislabeled(lab):
    original = execute(lab)
    original["action"].pop("lesson_ablation")
    loaded = ReliabilityRun.model_validate_json(json.dumps(original))
    assert loaded.action.lesson_ablation is None
    for change in (
        {"schema_version": "quartermaster.reliability-run/v2"},
        {"requests": original["requests"][:2]},
        {"outputs": original["outputs"][::-1]},
    ):
        with pytest.raises(ValidationError):
            ReliabilityRun.model_validate_json(json.dumps({**original, **change}))


def test_citation_presence_and_sentence_endings_are_separate_diagnostics(lab):
    async def uncited(**kwargs):
        return compact(
            decision="clarify", question="Which interval?", reason="Because the field"
        ), 40

    lab[2].measured_advice = uncited
    run = execute(lab)
    path = f"{url(lab)}/{run['id']}"
    checks = lab[0].get(path + "/diagnostics").json()[1]
    assert checks == dict(
        arm="compact_v2",
        citation_count=0,
        citation_status="none_provided",
        sentence_endings_valid=False,
    )
    assert run["outputs"][1]["citations_valid"] is True
    page = lab[0].get(f"/projects/{lab[1]}/reliability?run_id={run['id']}").text
    assert "No citations provided" in page and "review for truncation" in page
    assert "Citations accessible: True" not in page
    assert lab[0].get(path).json() == run


def test_ablation_restart_preserves_requests_and_does_not_retry(lab):
    action, _ = ablation_action(lab)
    captured = reliability.capture(lab[3], UUID(lab[1]), ReliabilityInput.model_validate(action))
    reliability.save(lab[3], captured)
    reliability.recover(lab[3])
    restored = reliability.get_run(lab[3], UUID(lab[1]), captured.id)
    assert restored.status == "interrupted" and restored.requests == captured.requests
    assert restored.schema_version == "quartermaster.reliability-run/v2"
    assert not lab[2].calls


@pytest.mark.parametrize(
    "field,changes,expected",
    [
        ("wait", {"state": "value", "value": 999, "unit": "days"}, ["state", "value", "unit"]),
        ("damage", {"state": "value", "value": "no", "unit": None}, ["state", "value"]),
        ("damage", {"state": "value", "value": "yes", "unit": None}, ["state", "value"]),
        ("visits", {"state": "value", "value": 2, "unit": "days"}, ["unit"]),
        ("visits", {"state": "value", "value": "2", "unit": "inspections"}, ["value"]),
        ("visits", {"state": "value", "value": 2, "unit": "inspections"}, []),
        ("wait", {"state": "sentinel", "value": None, "unit": None}, []),
        ("damage", {"state": "unknown", "value": None, "unit": None}, []),
        ("unconfigured", {"state": "value", "value": 0, "unit": "days"}, ["unconfigured_field"]),
    ],
)
def test_structured_claim_checks_do_not_certify_prose(lab, field, changes, expected):
    run = execute(lab)
    path = f"{url(lab)}/{run['id']}"
    claim = dict(
        field=field, citation_id=lab[4]["field_rules"]["rules"][0]["citation_id"], **changes
    )
    response = lab[0].post(path + "/check-claims", json={"claims": [claim]})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["results"][0]["mismatches"] == expected
    assert result["all_claims_match"] == (not expected)
    assert result["advice_prose_checked"] is False
    assert result["rules_sha256"] == run["rules_sha256"]
    assert lab[0].get(path).json() == run
    assert lab[0].get(path + "/reviews").json() == []


def test_absent_field_cannot_establish_zero_and_citation_must_match_definition(lab):
    action = deepcopy(lab[4])
    action["decision_inputs"].pop("wait")
    run = execute(lab, action)
    path = f"{url(lab)}/{run['id']}/check-claims"
    claim = dict(
        field="wait",
        state="value",
        value=0,
        unit="days",
        citation_id=action["field_rules"]["rules"][0]["citation_id"],
    )
    result = lab[0].post(path, json={"claims": [claim]}).json()
    assert result["results"][0]["mismatches"] == ["state", "value", "unit"]
    claim.update(state="absent", value=None, unit=None, citation_id=str(uuid4()))
    result = lab[0].post(path, json={"claims": [claim]}).json()
    assert result["results"][0]["mismatches"] == ["citation_id"]


@pytest.mark.parametrize(
    "change",
    [
        {"value": False},
        {"state": "unknown", "value": 0},
        {"state": "value", "value": None},
        {"state": "inferred"},
        {"extra": "sensitive assertion"},
        {"citation_id": "not-a-uuid"},
    ],
)
def test_malformed_claims_rejected(lab, change):
    run = execute(lab)
    claim = dict(
        field="visits",
        state="value",
        value=2,
        unit="inspections",
        citation_id=lab[4]["field_rules"]["rules"][0]["citation_id"],
    )
    claim.update(change)
    response = lab[0].post(f"{url(lab)}/{run['id']}/check-claims", json={"claims": [claim]})
    assert response.status_code == 422
    assert "sensitive assertion" not in response.text


def test_claim_forms_access_and_scope(lab, project_fixture):
    run = execute(lab)
    claim = dict(
        field="visits",
        state="value",
        value=2,
        unit="inspections",
        citation_id=lab[4]["field_rules"]["rules"][0]["citation_id"],
    )
    payload = {"claims": [claim]}
    path = f"{url(lab)}/{run['id']}/check-claims"
    assert (
        lab[0].post(path, json=payload, headers={"Origin": "https://hostile.invalid"}).status_code
        == 403
    )
    assert lab[0].post(path, json={"claims": []}).status_code == 422
    assert lab[0].post(path, json={"claims": [claim, claim]}).status_code == 422
    other = lab[0].post("/api/projects", json=project_fixture).json()["id"]
    assert (
        lab[0]
        .post(f"/api/projects/{other}/reliability-runs/{run['id']}/check-claims", json=payload)
        .status_code
        == 404
    )
    form = f"/projects/{lab[1]}/reliability/{run['id']}/check-claims"
    assert lab[0].post(form, data={"claims": json.dumps(payload)}).status_code == 403
    response = lab[0].post(form, headers=ORIGIN, data={"claims": json.dumps(payload)})
    assert response.status_code == 200 and "Adviser prose checked: false" in response.text
    response = lab[0].post(form, headers=ORIGIN, data={"claims": "sensitive bad json"})
    assert response.status_code == 422 and "sensitive bad json" not in response.text


def test_decision_selection_changes_only_system_and_omits_lessons(lab):
    action, _ = ablation_action(lab)
    action.pop("lesson_ablation")
    action["decision_selection"] = True
    client, project, fake, settings, _ = lab
    before = client.get(f"/api/projects/{project}").json()
    with connect(settings.database_path) as connection:
        lessons_before = list(map(tuple, connection.execute("SELECT * FROM lesson_revisions")))
    run = execute(lab, action)
    assert run["schema_version"] == "quartermaster.reliability-run/v3"
    assert run["revision"] == 5 and len(run["lessons"]) == 3
    assert list(reliability.DECISION_SYSTEMS) == [r["arm"] for r in run["requests"]]
    assert len(fake.calls) == 3
    assert fake.calls[0][0] == reliability.COMPACT_SYSTEM
    assert [c[0] for c in fake.calls] == list(reliability.DECISION_SYSTEMS.values())
    assert len(set(c[0] for c in fake.calls)) == 3
    for call in fake.calls:
        assert call[1] == fake.calls[0][1]
        assert call[1]["approved_lessons"] == []
        assert call[1]["structured_inputs"] == action["decision_inputs"]
        assert len(call[1]["field_interpretations"]) == 3
        assert call[2] == PARAMETERS and call[3] is True
    assert all(
        r["response_schema"] == run["requests"][0]["response_schema"] for r in run["requests"]
    )
    assert all(
        r["input_sha256"] == reliability.digest({k: v for k, v in r.items() if k != "input_sha256"})
        for r in run["requests"]
    )
    with connect(settings.database_path) as connection:
        assert (
            list(map(tuple, connection.execute("SELECT * FROM lesson_revisions"))) == lessons_before
        )
        for table in ("training_examples", "evaluation_holdouts", "reliability_reviews"):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    assert client.get(f"/api/projects/{project}").json() == before
    assert (
        "Decision-selection experiment"
        in client.get(f"/projects/{project}/reliability?run_id={run['id']}").text
    )
    assert client.get(f"{url(lab)}/{run['id']}").json() == run


@pytest.mark.parametrize("value", [False, 1, "true", {}, []])
def test_decision_selection_requires_explicit_true(lab, value):
    action = {**lab[4], "decision_selection": value}
    assert lab[0].post(url(lab), json=action).status_code == 422
    assert not lab[2].calls


def test_decision_selection_cannot_mix_experiments(lab):
    action, _ = ablation_action(lab)
    action["decision_selection"] = True
    assert lab[0].post(url(lab), json=action).status_code == 422
    assert not lab[2].calls


def test_decision_selection_recovery_preserves_no_lesson_requests(lab):
    action = ReliabilityInput.model_validate({**lab[4], "decision_selection": True})
    captured = reliability.capture(lab[3], UUID(lab[1]), action)
    reliability.save(lab[3], captured)
    reliability.recover(lab[3])
    saved = reliability.get_run(lab[3], UUID(lab[1]), captured.id)
    assert saved.status == "interrupted" and saved.requests == captured.requests
    assert saved.schema_version == "quartermaster.reliability-run/v3"
    assert not lab[2].calls
    document = saved.model_dump(mode="json")
    for changes in (
        {"schema_version": "quartermaster.reliability-run/v1"},
        {"requests": document["requests"][::-1]},
        {"action": {**document["action"], "decision_selection": None}},
    ):
        with pytest.raises(ValidationError):
            ReliabilityRun.model_validate({**document, **changes})


def test_decision_selection_failure_has_no_retry_or_quality_credit(lab):
    lab[2].error = "LOCAL_TOKEN_LIMIT: No complete response."
    run = execute(lab, {**lab[4], "decision_selection": True})
    assert len(lab[2].calls) == 3
    assert all(o["advice"] is None and not o["schema_valid"] for o in run["outputs"])
    assert lab[0].get(f"{url(lab)}/{run['id']}/reviews").json() == []


def context_action(lab, fields=None):
    return {
        **deepcopy(lab[4]),
        "context_selection": {
            "fields": fields or ["visits"],
            "rationale": "The question asks only for the recorded inspection count.",
            "reviewed": True,
        },
    }


def test_context_selection_preserves_full_snapshot_and_exact_views(lab):
    action, _ = ablation_action(lab)
    action.pop("lesson_ablation")
    action["context_selection"] = context_action(lab)["context_selection"]
    action["decision_inputs"]["unrelated"] = "private-unselected-marker"
    before = lab[0].get(f"/api/projects/{lab[1]}").json()
    run = execute(lab, action)
    assert run["schema_version"] == "quartermaster.reliability-run/v4" and run["revision"] == 5
    full, raw, interpreted = [json.loads(r["context"]) for r in run["requests"]]
    assert run["full_context"] == run["requests"][0]["context"]
    assert "private-unselected-marker" in run["full_context"]
    assert "private-unselected-marker" not in json.dumps([raw, interpreted])
    assert raw["case"]["situation"] == action["situation"]
    assert raw["case"]["case_id"] == full["case"]["case_id"]
    assert "mission" in full and "decision_definition" in full
    assert not {"mission", "decision_definition", "field_interpretations"} & set(raw)
    assert {k: v for k, v in interpreted.items() if k != "field_interpretations"} == raw
    assert raw["structured_inputs"] == {"visits": "2"}
    assert [r["field"] for r in raw["field_rules"]["rules"]] == ["visits"]
    assert [f["field"] for f in interpreted["field_interpretations"]] == ["visits"]
    span = run["definition_spans"][0]
    assert span["text"] == "visits is a count of earlier inspections."
    source = next(e for e in run["evidence"] if e["citation_id"] == span["citation_id"])
    assert source["text"][span["start"] : span["end"]] == span["text"]
    assert raw["retrieved_evidence"] == [{"citation_id": span["citation_id"], "text": span["text"]}]
    assert all(not body["approved_lessons"] for body in (full, raw, interpreted))
    assert len(run["lessons"]) == 3
    assert all(
        call[0] == reliability.COMPACT_SYSTEM and call[2] == PARAMETERS for call in lab[2].calls
    )
    assert lab[2].schema_contexts == [run["full_context"]] * 3
    assert all(
        r["response_schema"] == compact_response_schema(run["full_context"])
        for r in run["requests"]
    )
    assert all(
        r["input_sha256"] == reliability.digest({k: v for k, v in r.items() if k != "input_sha256"})
        for r in run["requests"]
    )
    assert lab[0].get(f"/api/projects/{lab[1]}").json() == before
    page = lab[0].get(f"/projects/{lab[1]}/reliability?run_id={run['id']}").text
    assert "Question-focused context experiment" in page and "Complete original context" in page
    with connect(lab[3].database_path) as c:
        assert c.execute("SELECT COUNT(*) FROM training_examples").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM reliability_reviews").fetchone()[0] == 0


def test_context_selection_preserves_absence_without_inventing_value(lab):
    action = context_action(lab, ["wait"])
    action["decision_inputs"].pop("wait")
    run = execute(lab, action)
    raw, interpreted = [json.loads(r["context"]) for r in run["requests"][1:]]
    assert raw["structured_inputs"] == interpreted["structured_inputs"] == {}
    assert "field_interpretations" not in raw
    assert interpreted["field_interpretations"][0]["state"] == "absent"
    assert interpreted["field_interpretations"][0]["value"] is None
    assert len(raw["field_rules"]["rules"]) == 1


@pytest.mark.parametrize(
    "change",
    [
        "empty",
        "duplicate",
        "unconfigured",
        "missing_review",
        "false",
        "integer",
        "extra",
        "mixed_decision",
        "mixed_lessons",
    ],
)
def test_context_selection_is_explicit_and_strict(lab, change):
    action = context_action(lab)
    selection = action["context_selection"]
    if change == "empty":
        selection["fields"] = []
    if change == "duplicate":
        selection["fields"] *= 2
    if change == "unconfigured":
        selection["fields"] = ["unconfigured"]
    if change == "missing_review":
        selection.pop("reviewed")
    if change == "false":
        selection["reviewed"] = False
    if change == "integer":
        selection["reviewed"] = 1
    if change == "extra":
        selection["expected_decision"] = "answer"
    if change == "mixed_decision":
        action["decision_selection"] = True
    if change == "mixed_lessons":
        action["lesson_ablation"] = ablation_action(lab)[0]["lesson_ablation"]
    assert lab[0].post(url(lab), json=action).status_code == 422
    assert not lab[2].calls


def test_context_spans_and_version_cannot_be_mislabeled(lab):
    run = execute(lab, context_action(lab))
    for change in ("full", "span", "citation", "offset", "version"):
        document = deepcopy(run)
        if change == "full":
            document["full_context"] = "{}"
        if change == "span":
            document["definition_spans"][0]["text"] = "Invented definition."
        if change == "citation":
            document["definition_spans"][0]["citation_id"] = str(uuid4())
        if change == "offset":
            document["definition_spans"][0]["end"] += 10000
        if change == "version":
            document["schema_version"] = "quartermaster.reliability-run/v3"
        with pytest.raises(ValidationError):
            ReliabilityRun.model_validate_json(json.dumps(document))
    original_requests = run["requests"]
    saved = reliability.capture(
        lab[3], UUID(lab[1]), ReliabilityInput.model_validate(context_action(lab))
    )
    reliability.save(lab[3], saved)
    calls = len(lab[2].calls)
    reliability.recover(lab[3])
    restored = reliability.get_run(lab[3], UUID(lab[1]), saved.id)
    assert restored.status == "interrupted" and restored.requests == saved.requests
    assert len(lab[2].calls) == calls
    assert lab[0].get(f"{url(lab)}/{run['id']}").json()["requests"] == original_requests


def test_context_selection_requires_shared_schema_adapter_before_generation(lab):
    async def old_adapter(*, system, context, parameters, compact):
        raise AssertionError("Must fail before inference")

    lab[2].measured_advice = old_adapter
    response = lab[0].post(url(lab), json=context_action(lab))
    assert response.status_code == 422 and "RELIABILITY_ADAPTER" in response.text
    assert lab[0].get(url(lab)).json() == []


def test_shared_schema_is_sent_without_full_context_message(lab):
    action = context_action(lab)
    action["decision_inputs"]["unrelated"] = "secret-unselected-value"
    captured = reliability.capture(lab[3], UUID(lab[1]), ReliabilityInput.model_validate(action))
    calls = []
    alias = model_alias("a" * 64)
    ref = str(captured.definition_spans[0].citation_id)

    def respond(request):
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": alias}]})
        payload = json.loads(request.content)
        calls.append(payload)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": compact([ref]).model_dump_json()},
                    }
                ],
                "usage": {"completion_tokens": 40},
            },
        )

    inference = LocalInference(lab[3], transport=httpx.MockTransport(respond), alias=alias)
    run = asyncio.run(
        reliability.run_comparison(
            lab[3], inference, UUID(lab[1]), ReliabilityInput.model_validate(action)
        )
    )
    assert len(calls) == 3 and all(o.advice for o in run.outputs)
    assert all(
        p["response_format"]["json_schema"] == calls[0]["response_format"]["json_schema"]
        for p in calls
    )
    for call, request in zip(calls, run.requests, strict=True):
        assert call["response_format"] == {
            "type": "json_schema",
            "json_schema": {
                "name": "grounded_advice",
                "strict": True,
                "schema": request.response_schema,
            },
        }
        assert call["messages"][1]["content"] == request.context
        assert call["messages"][0]["content"] == reliability.COMPACT_SYSTEM
    assert "secret-unselected-value" in json.dumps(calls[0])
    assert "secret-unselected-value" not in json.dumps(calls[1:])


def test_focused_citations_must_be_present_in_selected_view(lab):
    client, project, fake, settings, _ = lab
    sources = client.get(f"/api/projects/{project}/sources").json()
    additional = upload(
        client,
        project,
        b"# Inspection history\nmaterials counts stored items.\n",
        "other.md",
        "knowledge",
    ).json()
    current = client.get(f"/api/projects/{project}").json()["knowledge_revision"]
    selection = select_knowledge(
        client, project, [s["id"] for s in sources] + [additional["id"]], expected=current
    )
    assert selection.status_code == 201
    # Capture an unrelated attributed field, guaranteed present only in the full view.
    action = context_action(lab)
    chunks = client.get(f"/api/projects/{project}/knowledge/search?q=materials").json()
    ref = next(e["chunk"]["citation_id"] for e in chunks if e["source"]["id"] == additional["id"])
    action["field_rules"]["rules"].append(
        dict(
            field="materials",
            kind="integer",
            definition="Count of stored items.",
            unit="items",
            citation_id=ref,
            source_quote="materials counts stored items.",
        )
    )
    action["decision_inputs"]["materials"] = "9"
    captured = reliability.capture(settings, UUID(project), ReliabilityInput.model_validate(action))
    irrelevant = next(e for e in captured.evidence if str(e.source_id) == additional["id"])

    async def wrong_source(**kwargs):
        return compact([str(irrelevant.citation_id)]), 45

    fake.measured_advice = wrong_source
    run = execute(lab, action)
    assert run["outputs"][0]["advice"] is not None
    for output in run["outputs"][1:]:
        assert output["schema_valid"] and output["draft"] is not None
        assert output["advice"] is None and output["citations_valid"] is False
        assert "ADVICE_CITATION" in output["error"]


@pytest.mark.parametrize("mode", ["context_selection", "decision_contract"])
def test_selected_views_cannot_bypass_full_record_holdout(lab, mode):
    from quartermaster import teaching
    from quartermaster.contracts.teaching import TestInput
    from quartermaster.holdouts import case_fingerprint
    from tests.test_teaching import FakeInference

    test = asyncio.run(
        teaching.advise(
            lab[3],
            FakeInference(),
            UUID(lab[1]),
            TestInput(
                situation="Reserved different question.\n" + json.dumps(lab[4]["decision_inputs"])
            ),
        )
    )
    with connect(lab[3].database_path) as c:
        c.execute(
            "INSERT INTO evaluation_holdouts VALUES (?,?,?,?)",
            (lab[1], str(test.case.case_id), case_fingerprint(test.case), str(test.id)),
        )
    action = context_action(lab)
    if mode == "decision_contract":
        action[mode] = action.pop("context_selection")
        contract_adapter(lab)
    response = lab[0].post(url(lab), json=action)
    assert response.status_code == 409 and "RELIABILITY_HELD_OUT" in response.text
    assert not lab[2].calls


def contract_action(lab):
    action = context_action(lab)
    action["decision_contract"] = action.pop("context_selection")
    return action


def contract_adapter(lab, decision="answer"):
    original = lab[2].measured_advice

    async def measured(*, system, context, parameters, compact, decision_only=False):
        if decision_only:
            return DecisionOnly(decision=decision), 8
        return await original(
            system=system, context=context, parameters=parameters, compact=compact
        )

    lab[2].measured_advice = measured


def test_decision_contract_changes_only_schema_and_never_credits_label_as_advice(lab):
    contract_adapter(lab)
    action = contract_action(lab)
    action["decision_inputs"]["unrelated"] = "unselected-private-value"
    before = lab[0].get(f"/api/projects/{lab[1]}").json()
    run = execute(lab, action)
    assert run["schema_version"] == "quartermaster.reliability-run/v5"
    assert run["revision"] == 4 and run["status"] == "completed"
    a, b = run["requests"]
    assert [a["arm"], b["arm"]] == ["compact_contract", "decision_only"]
    for key in ("system", "context", "parameters"):
        assert a[key] == b[key]
    assert a["system"] == reliability.CONTRACT_SYSTEM
    assert b["response_schema"] == DecisionOnly.model_json_schema()
    assert a["response_schema"] == compact_response_schema(a["context"])
    assert run["full_context"] != a["context"]
    assert "unselected-private-value" in run["full_context"]
    assert "unselected-private-value" not in a["context"]
    selected = json.loads(a["context"])
    assert selected["structured_inputs"] == {"visits": "2"}
    assert selected["field_interpretations"][0]["value"] == 2
    assert selected["approved_lessons"] == []
    assert run["outputs"][0]["advice"] is not None
    minimal = run["outputs"][1]
    assert minimal["draft"] == {"decision": "answer"} and minimal["schema_valid"]
    assert minimal["advice"] is None and minimal["citations_valid"] is None
    diagnostics = lab[0].get(f"{url(lab)}/{run['id']}/diagnostics").json()[1]
    assert diagnostics == dict(
        arm="decision_only",
        citation_count=None,
        citation_status="not_applicable",
        sentence_endings_valid=None,
    )
    page = lab[0].get(f"/projects/{lab[1]}/reliability?run_id={run['id']}").text
    assert "Decision-contract experiment" in page
    assert "Citations and prose quality not applicable" in page
    assert "/reviews/decision_only" not in page
    assert lab[0].get(f"/api/projects/{lab[1]}").json() == before
    assert lab[0].get(f"{url(lab)}/{run['id']}/reviews").json() == []
    for request in run["requests"]:
        assert request["input_sha256"] == reliability.digest(
            {k: v for k, v in request.items() if k != "input_sha256"}
        )


@pytest.mark.parametrize("decision", ["answer", "clarify", "abstain"])
def test_decision_only_http_schema_and_strict_completion_validation(lab, decision):
    calls = []
    alias = model_alias("a" * 64)
    ref = lab[4]["field_rules"]["rules"][0]["citation_id"]

    def respond(request):
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": alias}]})
        payload = json.loads(request.content)
        calls.append(payload)
        content = (
            json.dumps({"decision": decision})
            if len(calls) == 2
            else compact([ref]).model_dump_json()
        )
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": content}}],
                "usage": {"completion_tokens": 8},
            },
        )

    inference = LocalInference(lab[3], transport=httpx.MockTransport(respond), alias=alias)
    run = asyncio.run(
        reliability.run_comparison(
            lab[3],
            inference,
            UUID(lab[1]),
            ReliabilityInput.model_validate(contract_action(lab)),
        )
    )
    assert len(calls) == 2 and run.outputs[1].draft == DecisionOnly(decision=decision)
    for payload, request in zip(calls, run.requests, strict=True):
        assert payload["response_format"]["json_schema"]["schema"] == request.response_schema
        assert payload["response_format"]["json_schema"]["strict"] is True
    assert {k: v for k, v in calls[0].items() if k != "response_format"} == {
        k: v for k, v in calls[1].items() if k != "response_format"
    }


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"decision": "recommend"},
        {"decision": True},
        {"decision": "answer", "reason": "Unsupported extra text."},
        {"decision": "clarify", "question": "What?"},
    ],
)
def test_minimal_decision_refuses_missing_invalid_and_extra_fields(payload):
    with pytest.raises(ValidationError):
        DecisionOnly.model_validate(payload)


@pytest.mark.parametrize("other", ["context_selection", "decision_selection", "lesson_ablation"])
def test_decision_contract_cannot_mix_experiments(lab, other):
    action = contract_action(lab)
    action[other] = (
        context_action(lab)["context_selection"]
        if other == "context_selection"
        else True
        if other == "decision_selection"
        else ablation_action(lab)[0]["lesson_ablation"]
    )
    assert lab[0].post(url(lab), json=action).status_code == 422
    assert not lab[2].calls


def test_decision_contract_preflights_adapter_and_recovers_without_retry(lab):
    response = lab[0].post(url(lab), json=contract_action(lab))
    assert response.status_code == 422 and "RELIABILITY_ADAPTER" in response.text
    assert lab[0].get(url(lab)).json() == []
    captured = reliability.capture(
        lab[3], UUID(lab[1]), ReliabilityInput.model_validate(contract_action(lab))
    )
    reliability.save(lab[3], captured)
    reliability.recover(lab[3])
    restored = reliability.get_run(lab[3], UUID(lab[1]), captured.id)
    assert restored.status == "interrupted" and restored.requests == captured.requests
    assert not lab[2].calls


@pytest.mark.parametrize("change", ["context", "system", "parameters", "version", "advice"])
def test_decision_contract_snapshots_reject_mixed_controls_or_advice_credit(lab, change):
    contract_adapter(lab)
    document = execute(lab, contract_action(lab))
    if change in ("context", "system", "parameters"):
        document["requests"][1][change] = {} if change == "parameters" else "changed"
    if change == "version":
        document["schema_version"] = "quartermaster.reliability-run/v4"
    if change == "advice":
        document["outputs"][1]["advice"] = document["outputs"][0]["advice"]
    with pytest.raises(ValidationError):
        ReliabilityRun.model_validate_json(json.dumps(document))


def test_decision_contract_failure_and_review_do_not_create_quality_credit(lab):
    contract_adapter(lab)
    run = execute(lab, contract_action(lab))
    response = lab[0].post(
        f"{url(lab)}/{run['id']}/reviews/decision_only",
        json={
            "expected_revision": 0,
            "factual_quality": "pass",
            "clarification_relevance": "pass",
            "unsupported_assertions": "pass",
            "citation_relevance": "pass",
            "decision_usefulness": "useful",
            "notes": "A label is not advice.",
        },
    )
    assert response.status_code == 409 and "RELIABILITY_REVIEW" in response.text
    with connect(lab[3].database_path) as c:
        for table in ("reliability_reviews", "training_examples", "feedback", "adviser_versions"):
            assert c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


@pytest.mark.parametrize("failure", ["extra_field", "bad_decision", "length", "connection"])
def test_minimal_failures_are_durable_without_retry_or_advice_credit(lab, failure):
    calls = []
    alias = model_alias("a" * 64)
    ref = lab[4]["field_rules"]["rules"][0]["citation_id"]

    def respond(request):
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": alias}]})
        calls.append(json.loads(request.content))
        content, finish = compact([ref]).model_dump_json(), "stop"
        if len(calls) == 2:
            if failure == "connection":
                raise httpx.ConnectError("Local diagnostic connection failed.")
            if failure == "extra_field":
                content = '{"decision":"answer","reason":"Not allowed."}'
            if failure == "bad_decision":
                content = '{"decision":"recommend"}'
            if failure == "length":
                content, finish = '{"decision":"answer"}', "length"
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": finish, "message": {"content": content}}],
                "usage": {"completion_tokens": 8},
            },
        )

    run = asyncio.run(
        reliability.run_comparison(
            lab[3],
            LocalInference(lab[3], transport=httpx.MockTransport(respond)),
            UUID(lab[1]),
            ReliabilityInput.model_validate(contract_action(lab)),
        )
    )
    assert len(calls) == 2 and run.status == "completed"
    output = run.outputs[1]
    assert output.error and not output.schema_valid
    assert output.advice is None and output.draft is None and output.citations_valid is None
    assert output.citation_status == "not_applicable"
    if failure != "connection":
        assert output.completion_tokens == 8
    saved = reliability.get_run(lab[3], UUID(lab[1]), run.id)
    assert saved == run
