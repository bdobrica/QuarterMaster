"""Retired workflow fixtures protect consent, provider failures and immutable evidence."""

import asyncio
import json

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from quartermaster import evaluations, teaching
from quartermaster.app import create_app
from quartermaster.config import Settings
from quartermaster.contracts.adviser import AdviceEngineEdit
from quartermaster.contracts.teaching import TestInput as AdviceInput
from quartermaster.db import connect
from quartermaster.errors import DomainError
from quartermaster.generation import ADVICE_PARAMETERS
from quartermaster.holdouts import require_eligible
from quartermaster.inference import HOSTED_PARAMETERS, HostedInference, hosted_schema
from quartermaster.projects import edit_advice_engine, get_adviser
from tests.legacy_print import CASES, baseline, seed
from tests.test_teaching import draft


@pytest.fixture
def demo(settings):
    project, suite = seed(settings)
    return settings, project, suite


def hosted_settings(settings, **overrides):
    return Settings(
        _env_file=None,
        data_dir=settings.data_dir,
        adviser_base_url="https://adviser.example/v1",
        adviser_model="capable-demo",
        adviser_api_key="adviser-secret",
        **overrides,
    )


def consent(settings, project_id, mode="hosted", **overrides):
    spec = get_adviser(settings.database_path, project_id)
    values = dict(
        expected_revision=spec.revision,
        mode=mode,
        consent=True,
        endpoint="https://adviser.example/v1",
        model="capable-demo",
    )
    values.update(overrides)
    return edit_advice_engine(settings, project_id, AdviceEngineEdit(**values))


def envelope(content, finish="stop"):
    return {
        "choices": [{"finish_reason": finish, "message": {"content": content}}],
        "usage": {"completion_tokens": 42},
    }


def test_fresh_demo_needs_no_engine_and_cases_are_held_out(demo):
    settings, project, suite = demo
    assert len(suite.cases) == len(CASES) == 10
    assert "review pending" in suite.name
    assert get_adviser(settings.database_path, project.id).knowledge_revision
    assert all(
        "owner_rubric" not in run.context for run in teaching.list_tests(settings, project.id)
    )
    assert all(run.latency_ms is None for run in teaching.list_tests(settings, project.id))
    assert len({c.case_sha256 for c in suite.cases}) == 10
    with connect(settings.database_path) as connection:
        assert connection.execute("SELECT count(*) FROM evaluation_holdouts").fetchone()[0] == 10
        assert connection.execute("SELECT count(*) FROM training_examples").fetchone()[0] == 0
    with connect(settings.database_path) as connection:
        for case in suite.cases:
            with pytest.raises(DomainError, match="EVALUATION_HELD_OUT"):
                require_eligible(connection, project.id, [case.case])
    second, _ = seed(settings)
    assert second.id != project.id
    assert evaluations.get_suite(settings, project.id, suite.id) == suite


def test_retired_demo_cannot_create_projects(client):
    assert "Create fresh print demo" not in client.get("/").text
    assert client.post("/print-demo", headers={"origin": "http://testserver"}).status_code == 404
    assert client.get("/api/projects").json() == []


def test_consent_is_project_scoped_revocable_and_provider_bound(demo, monkeypatch):
    settings, project, suite = demo
    config = hosted_settings(settings)
    with pytest.raises(DomainError, match="ADVISER_CONSENT"):
        consent(config, project.id, consent=False)
    with pytest.raises(DomainError, match="ADVISER_CONSENT"):
        consent(config, project.id, model="different")
    approved = consent(config, project.id)
    assert approved.advice_consent.model == "capable-demo"
    assert approved.advice_consent.consented_at
    other, _ = seed(settings)
    assert get_adviser(settings.database_path, other.id).advice_mode == "local_only"
    changed = config.model_copy(update={"adviser_model": "changed-model"})
    with pytest.raises(DomainError, match="ADVISER_CONSENT"):
        asyncio.run(
            teaching.advise(changed, None, project.id, AdviceInput(situation="May we print?"))
        )
    local_only = config.model_copy(update={"adviser_local_only": True})
    with pytest.raises(DomainError, match="ADVISER_LOCAL_ONLY"):
        asyncio.run(
            teaching.advise(local_only, None, project.id, AdviceInput(situation="May we print?"))
        )
    revoked = consent(config, project.id, "local_only")
    assert revoked.advice_consent is None
    assert revoked.advice_mode == "local_only"


def test_consent_route_requires_complete_valid_input(demo):
    settings, project, _ = demo
    with TestClient(create_app(hosted_settings(settings))) as client:
        url = f"/api/projects/{project.id}/advice-engine"
        for body in (
            {},
            {"mode": "hosted", "expected_revision": 2, "extra": True},
            {"mode": "hosted", "expected_revision": "2"},
        ):
            assert client.post(url, json=body).status_code == 422
        spec = get_adviser(settings.database_path, project.id)
        body = dict(
            mode="hosted",
            expected_revision=spec.revision,
            consent=True,
            endpoint="https://adviser.example/v1",
            model="capable-demo",
        )
        assert (
            client.post(url, json=body, headers={"origin": "https://evil.example"}).status_code
            == 403
        )
        assert client.post(url, json=body).status_code == 200
        assert client.post(url, json=body).status_code == 409


def test_hosted_request_and_run_record_real_context_only(demo, monkeypatch):
    settings, project, suite = demo
    config = hosted_settings(settings, adviser_reasoning_effort="high")
    consent(config, project.id)
    calls = []

    def handle(request):
        calls.append(request)
        body = json.loads(request.content)
        context = json.loads(body["messages"][1]["content"])
        evidence = context["retrieved_evidence"][0]
        output = draft(
            recommendation="Ready for production.",
            refs=[evidence["citation_id"]],
            quotes=["final copy is confirmed"],
        )
        return httpx.Response(200, json=envelope(output.model_dump_json()))

    adapter = HostedInference(config, transport=httpx.MockTransport(handle))
    monkeypatch.setattr("quartermaster.inference.HostedInference", lambda _: adapter)
    report = asyncio.run(baseline(config, project.id, suite.id, "hosted", True))
    assert len(calls) == len(report["results"]) == 4
    for request, result in zip(calls, report["results"], strict=True):
        run = result["run"]
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer adviser-secret"
        body = json.loads(request.content)
        assert body["store"] is False and body["max_completion_tokens"] == 2048
        assert "chat_template_kwargs" not in body
        assert run["parameters"] == {**HOSTED_PARAMETERS, "reasoning_effort": "high"}
        assert body["reasoning_effort"] == "high"
        assert run["provider"] == "https://adviser.example/v1"
        assert run["engine_revision"] == "openai-compatible/v1"
        assert run["model_alias"] == "capable-demo"
        assert run["latency_ms"] >= 0
        assert run["response_schema"] == body["response_format"]["json_schema"]["schema"]
        assert result["human_review"]["useful"] is None
        context = json.loads(body["messages"][1]["content"])
        assert "rubric" not in context and "observed_outcome" not in context["case"]
        # Each call sees its own case, never the suite or unseen neighbors.
        assert CASES[8][1] not in request.content.decode()
        assert CASES[9][1] not in request.content.decode()
    assert "PENDING HUMAN REVIEW" in report["gate"]
    assert report["external_cost"] is None


@pytest.mark.parametrize(
    "response,code",
    [
        (httpx.Response(401, text="SECRET raw business text"), "ADVISER_HTTP"),
        (httpx.Response(429, text="SECRET"), "ADVISER_HTTP"),
        (httpx.Response(307, headers={"location": "https://evil.example"}), "ADVISER_HTTP"),
        (httpx.Response(200, text="x" * 65537), "ADVISER_SIZE"),
        (httpx.Response(200, json=envelope("{}", "length")), "ADVISER_COMPLETION"),
        (
            httpx.Response(200, json=envelope('{"behavior":"recommend","behavior":"clarify"}')),
            "ADVISER_JSON",
        ),
        (httpx.Response(200, json=envelope("{}")), "ADVISER_JSON"),
    ],
)
def test_hosted_failures_sanitized_bounded_no_retry(settings, response, code):
    calls = []

    def handle(request):
        calls.append(request)
        return response

    adapter = HostedInference(hosted_settings(settings), transport=httpx.MockTransport(handle))
    with pytest.raises(DomainError, match=code) as exc:
        asyncio.run(
            adapter.advise(
                system="system", context='{"retrieved_evidence":[]}', parameters=ADVICE_PARAMETERS
            )
        )
    assert len(calls) == 1
    assert "SECRET" not in exc.value.message


def test_schema_and_input_limits(settings):
    schema = hosted_schema('{"retrieved_evidence":[]}')
    assert set(schema["required"]) == set(schema["properties"])
    assert set(schema["$defs"]["Advice"]["required"]) == set(
        schema["$defs"]["Advice"]["properties"]
    )
    adapter = HostedInference(hosted_settings(settings))
    with pytest.raises(DomainError, match="ADVISER_INPUT"):
        asyncio.run(
            adapter.advise(
                system="x" * 48000,
                context='{"retrieved_evidence":[]}',
                parameters=ADVICE_PARAMETERS,
            )
        )
    with pytest.raises(ValidationError):
        Settings(_env_file=None, adviser_base_url="http://remote.example/v1")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, adviser_base_url="https://user:secret@remote.example/v1")


def test_case_review_is_owner_action_and_append_only(demo):

    settings, project, suite = demo
    assert suite.reviewed_at is None
    with TestClient(create_app(settings)) as client:
        url = f"/api/projects/{project.id}/evaluation-suites/{suite.id}/review"
        body = dict(
            expected_revision=suite.revision, approved=True, note="Reviewed synthetic cases."
        )
        assert client.post(url, json={**body, "approved": False}).status_code == 422
        assert client.post(url, json={**body, "unexpected": 1}).status_code == 422
        response = client.post(url, json=body)
        assert response.status_code == 200
        assert response.json()["reviewed_at"]
        assert client.post(url, json=body).status_code == 409
    original = evaluations.get_suite(settings, project.id, suite.id, suite.revision)
    assert original.reviewed_at is None
    reviewed = evaluations.get_suite(settings, project.id, suite.id)
    assert reviewed.review_note == "Reviewed synthetic cases."
    assert reviewed.cases == original.cases
    assert len(reviewed.cases) == 10
    # This attestation never creates training examples or builder requests.
    with connect(settings.database_path) as connection:
        assert connection.execute("SELECT count(*) FROM training_examples").fetchone()[0] == 0


def test_legacy_snapshots_keep_identical_serialized_shape(demo):
    # Frozen hashes depend on model_dump, including nested adviser snapshots.
    settings, project, suite = demo
    spec = get_adviser(settings.database_path, project.id)
    assert "advice_mode" not in spec.model_dump(mode="json")
    assert "advice_consent" not in spec.model_dump(mode="json")
    assert "reviewed_at" not in suite.model_dump(mode="json")
    assert "review_note" not in suite.model_dump(mode="json")
    data = json.loads(spec.model_dump_json())
    assert type(spec).model_validate_json(json.dumps(data)).model_dump(mode="json") == data
    data = json.loads(suite.model_dump_json())
    assert type(suite).model_validate_json(json.dumps(data)).model_dump(mode="json") == data
