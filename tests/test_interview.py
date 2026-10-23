import asyncio
import json
from pathlib import Path
from uuid import uuid4

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from quartermaster.app import create_app
from quartermaster.builder import OpenAICompatible, Probe, credential
from quartermaster.config import Settings
from quartermaster.contracts.interview import Consent, Interpretation, ProviderTest
from quartermaster.db import connect, migrate
from quartermaster.errors import DomainError
from quartermaster.interviews import append_interview, get_interview
from tests.test_foundation import CSV, MD, mapping_for, upload

ORIGIN = {"Origin": "http://testserver"}
FIXTURE = json.loads((Path(__file__).parent / "fixtures/interview.json").read_text())


class FakeBuilder:
    def __init__(self):
        self.calls = []
        self.error = None

    async def structured(self, *, system, context, schema):
        self.calls.append({"system": system, "context": context, "schema": schema.__name__})
        if self.error:
            raise DomainError(self.error)
        if schema is Probe:
            return Probe(ok=True)
        return schema.model_validate(FIXTURE["interpretation"])


@pytest.fixture
def guided(settings):
    config = settings.model_copy(
        update={
            "builder_base_url": Settings(
                builder_base_url="https://provider.example/v1"
            ).builder_base_url,
            "builder_model": "fixture-model",
            "builder_api_key": SecretStr("sensitive-key-fixture"),
        }
    )
    fake = FakeBuilder()
    with TestClient(create_app(config, builder=fake)) as client:
        project = client.post("/api/projects", json={"name": "Workshop", "mission": "Help"}).json()[
            "id"
        ]
        yield client, project, fake, config


def route(project, suffix=""):
    return f"/api/projects/{project}/interview{suffix}"


def complete(client, project):
    state = client.get(route(project)).json()
    for topic, answer in FIXTURE["answers"].items():
        result = client.post(
            route(project, "/answers"),
            json={
                "expected_revision": state["revision"],
                "topic": topic,
                "answer": answer,
            },
        )
        assert result.status_code == 200, result.text
        state = result.json()
    return state


def prepare(client, project, **extra):
    state = client.get(route(project)).json()
    response = client.post(
        route(project, "/prepare"), json={"expected_revision": state["revision"], **extra}
    )
    assert response.status_code == 200, response.text
    return response.json()


def consent(state):
    return {
        "expected_revision": state["revision"],
        "turn_id": state["prepared"]["id"],
        "disclosure_sha256": state["prepared"]["disclosure_sha256"],
        "consent": True,
    }


def test_guided_provider_review_edits_and_pins(guided, caplog):
    client, project, fake, settings = guided
    original = client.get(f"/api/projects/{project}").json()
    complete(client, project)
    state = prepare(client, project)
    assert fake.calls == []
    assert state["readiness"] == "needs_examples"
    result = client.post(route(project, "/send"), json=consent(state))
    assert result.status_code == 200, result.text
    state = result.json()
    assert state["status"] == "review"
    assert state["proposal_origin"] == "AI_DRAFT"
    assert state["consented_at"] is not None
    assert fake.calls[0]["context"] == state["prepared"]["context"]
    assert client.get(f"/api/projects/{project}").json() == original
    edited = dict(FIXTURE["interpretation"], mission="Owner-edited mission")
    result = client.post(
        route(project, "/review"),
        json={
            "expected_revision": state["revision"],
            "action": "apply",
            "edited": edited,
        },
    )
    assert result.status_code == 200, result.text
    state = result.json()
    spec = client.get(f"/api/projects/{project}").json()
    assert state["status"] == "applied"
    assert spec["revision"] == 2
    assert spec["mission"] == "Owner-edited mission"
    assert spec["decision_definition"] == edited["decision_definition"]
    assert spec["model"] == original["model"]
    assert spec["knowledge_revision"] is None
    history = client.get(route(project, "/revisions")).json()
    assert [h["status"] for h in history][-4:] == ["prepared", "sending", "review", "applied"]
    assert history[-2]["proposal"]["mission"] != spec["mission"]
    assert "sensitive-key-fixture" not in json.dumps(history) + caplog.text
    assert state["readiness"] == "needs_examples"
    assert (
        client.post(
            route(project, "/review"),
            json={
                "expected_revision": state["revision"],
                "action": "apply",
            },
        ).status_code
        == 409
    )
    assert len(fake.calls) == 1


def test_manual_no_provider_and_rejection_leave_active_spec_unchanged(client, project_fixture):
    project = client.post("/api/projects", json=project_fixture).json()["id"]
    original = client.get(f"/api/projects/{project}").json()
    state = complete(client, project)
    response = client.post(route(project, "/manual"), json={"expected_revision": state["revision"]})
    assert response.status_code == 200, response.text
    state = response.json()
    assert state["proposal_origin"] == "OWNER_DRAFT"
    assert state["proposal"]["mission"] == FIXTURE["answers"]["mission"]
    state = client.post(
        route(project, "/review"),
        json={
            "expected_revision": state["revision"],
            "action": "reject",
        },
    ).json()
    assert state["status"] == "rejected"
    assert state["answers"] == FIXTURE["answers"]
    assert client.get(f"/api/projects/{project}").json() == original
    state = client.post(
        route(project, "/manual"), json={"expected_revision": state["revision"]}
    ).json()
    assert (
        client.post(
            route(project, "/review"),
            json={
                "expected_revision": state["revision"],
                "action": "apply",
            },
        ).json()["status"]
        == "applied"
    )


def test_schema_summaries_exclude_rows_targets_and_outcomes(guided):
    client, project, fake, _ = guided
    source = upload(client, project, CSV, label="examples").json()
    mapping = mapping_for(source)
    assert client.post(f"/api/projects/{project}/mappings", json=mapping).status_code == 201
    doc = upload(client, project, MD, name="rules.md", label="knowledge").json()
    complete(client, project)
    state = prepare(client, project)
    context = json.loads(state["prepared"]["context"])
    summaries = context["sources"]["summaries"]
    assert len(summaries) == 2
    assert summaries[0]["sheets"][0]["row_count"] == 2
    assert "ideal_advice" in state["prepared"]["context"]
    for text in ("drill", "overdue", "check first", "withhold", "<script>"):
        assert text not in json.dumps(context["sources"])
    assert context["sources"]["optional_excerpts"] == []
    state = prepare(client, project, excerpt_source_ids=[doc["id"]])
    excerpt = json.loads(state["prepared"]["context"])["sources"]["optional_excerpts"][0]
    assert excerpt["text"] == MD.decode()[:1000]
    assert excerpt["source_sha256"] == doc["sha256"]
    assert excerpt["start"] == 0 and excerpt["end"] == len(excerpt["text"])
    html = client.get(f"/projects/{project}/interview").text
    assert "&lt;script&gt;" in html and "<script>never execute" not in html
    assert "UNTRUSTED DATA" in html
    assert client.get(route(project)).json()["readiness"] == "needs_examples"
    assert fake.calls == []


def test_exact_consent_no_replays_or_stale_context(guided):
    client, project, fake, _ = guided
    complete(client, project)
    state = prepare(client, project)
    payload = consent(state)
    for field, bad in (
        ("consent", False),
        ("consent", 1),
        ("consent", "true"),
        ("turn_id", str(uuid4())),
        ("disclosure_sha256", "0" * 64),
    ):
        response = client.post(route(project, "/send"), json={**payload, field: bad})
        assert response.status_code in (409, 422)
    assert fake.calls == []
    assert client.post(route(project, "/send"), json=payload).json()["status"] == "review"
    assert client.post(route(project, "/send"), json=payload).status_code == 409
    assert len(fake.calls) == 1
    # Editing an answer invalidates the prepared snapshot and its consent.
    state = client.get(route(project)).json()
    state = client.post(
        route(project, "/answers"),
        json={"expected_revision": state["revision"], "topic": "mission", "answer": "Changed"},
    ).json()
    assert state["prepared"] is None and state["proposal"] is None
    assert (
        client.post(
            route(project, "/send"), json={**payload, "expected_revision": state["revision"]}
        ).status_code
        == 409
    )
    state = prepare(client, project)
    spec = client.get(f"/api/projects/{project}").json()
    assert (
        client.patch(
            f"/api/projects/{project}",
            json={
                "name": "New name",
                "mission": "Changed externally",
                "expected_revision": spec["revision"],
            },
        ).status_code
        == 200
    )
    assert client.post(route(project, "/send"), json=consent(state)).status_code == 409
    assert len(fake.calls) == 1


@pytest.mark.parametrize(
    "error",
    [
        "BUILDER_TIMEOUT: Retry explicitly.",
        "BUILDER_JSON: Invalid JSON.",
        "BUILDER_RATE_LIMIT: Wait then retry.",
    ],
)
def test_failures_preserve_answers_and_require_fresh_consent(guided, error):
    client, project, fake, _ = guided
    before = complete(client, project)
    state = prepare(client, project)
    fake.error = error
    payload = consent(state)
    state = client.post(route(project, "/send"), json=payload).json()
    assert state["status"] == "failed" and state["error"] == error
    assert state["answers"] == before["answers"]
    assert state["proposal"] is None
    assert client.get(f"/projects/{project}/interview").status_code == 200
    assert (
        client.post(
            route(project, "/send"), json={**payload, "expected_revision": state["revision"]}
        ).status_code
        == 409
    )
    fake.error = None
    state = prepare(client, project)
    assert client.post(route(project, "/send"), json=consent(state)).json()["status"] == "review"
    assert len(fake.calls) == 2


def test_restart_marks_pending_failed_without_resending(guided):
    client, project, fake, config = guided
    complete(client, project)
    state = prepare(client, project)
    with connect(config.database_path) as connection:
        from datetime import UTC, datetime

        previous = get_interview(config, project)
        append_interview(connection, previous, status="sending", consented_at=datetime.now(UTC))
    with TestClient(create_app(config, builder=fake)) as restarted:
        recovered = restarted.get(route(project)).json()
        assert recovered["status"] == "failed" and "BUILDER_INTERRUPTED" in recovered["error"]
        assert recovered["answers"] == state["answers"]
    assert fake.calls == []


def test_stale_review_does_not_overwrite_project(guided):
    client, project, _, _ = guided
    complete(client, project)
    state = prepare(client, project)
    state = client.post(route(project, "/send"), json=consent(state)).json()
    client.patch(
        f"/api/projects/{project}",
        json={"name": "Keep this", "mission": "New mission", "expected_revision": 1},
    )
    assert (
        client.post(
            route(project, "/review"),
            json={"expected_revision": state["revision"], "action": "apply"},
        ).status_code
        == 409
    )
    assert client.get(f"/api/projects/{project}").json()["name"] == "Keep this"


@pytest.mark.parametrize(
    "suffix,payload",
    [
        ("/answers", {}),
        ("/answers", {"expected_revision": 0, "topic": "unknown", "answer": "x"}),
        ("/answers", {"expected_revision": True, "topic": "mission", "answer": "x"}),
        ("/answers", {"expected_revision": 0, "topic": "mission", "answer": " "}),
        ("/answers", {"expected_revision": 0, "topic": "mission", "answer": "x" * 4001}),
        ("/manual", {"expected_revision": 0, "extra": "sensitive-invalid"}),
        ("/prepare", {"expected_revision": 0, "excerpt_source_ids": ["bad"]}),
        ("/review", {"expected_revision": 0, "action": "approve"}),
        ("/send", {"expected_revision": 0, "consent": True}),
    ],
)
def test_invalid_contracts_leave_interview_unchanged(guided, suffix, payload):
    client, project, fake, _ = guided
    before = client.get(route(project)).json()
    response = client.post(route(project, suffix), json=payload)
    assert response.status_code == 422
    assert "sensitive-invalid" not in response.text
    assert client.get(route(project)).json() == before
    assert fake.calls == []


def test_incomplete_scope_and_invalid_excerpt_choices(guided):
    client, project, fake, _ = guided
    for suffix in ("/manual", "/prepare"):
        response = client.post(route(project, suffix), json={"expected_revision": 0})
        assert response.status_code == 422 and "INTERVIEW_INCOMPLETE" in response.text
    assert client.get(route(uuid4())).status_code == 404
    other = client.post("/api/projects", json={"name": "Other", "mission": "Other"}).json()["id"]
    doc = upload(client, other, MD, name="private.md", label="knowledge").json()
    table = upload(client, project).json()
    complete(client, project)
    for ids in ([doc["id"]], [table["id"]], [str(uuid4())], [doc["id"], doc["id"]]):
        state = client.get(route(project)).json()
        assert (
            client.post(
                route(project, "/prepare"),
                json={
                    "expected_revision": state["revision"],
                    "excerpt_source_ids": ids,
                },
            ).status_code
            == 422
        )
    assert fake.calls == []


@pytest.mark.parametrize("suffix", ["/answers", "/manual", "/prepare", "/send", "/review"])
def test_mutations_reject_cross_origin(guided, suffix):
    client, project, fake, _ = guided
    payload = {"expected_revision": 0}
    if suffix == "/answers":
        payload.update(topic="mission", answer="x")
    elif suffix == "/send":
        payload.update(turn_id=str(uuid4()), disclosure_sha256="0" * 64, consent=True)
    elif suffix == "/review":
        payload.update(action="reject")
    assert (
        client.post(
            route(project, suffix), json=payload, headers={"Origin": "https://evil.test"}
        ).status_code
        == 403
    )
    assert client.post(f"/projects/{project}/interview{suffix}", data={}).status_code == 403
    assert fake.calls == []


def test_provider_probe_is_explicit_and_generic(guided):
    client, project, fake, _ = guided
    assert client.get("/healthz").status_code == 200
    assert client.get(f"/projects/{project}/interview").status_code == 200
    assert fake.calls == []
    for payload in ({}, {"consent": False}, {"consent": 1}, {"consent": "true"}):
        assert client.post("/api/builder/test", json=payload).status_code == 422
    assert (
        client.post(
            "/api/builder/test", json={"consent": True}, headers={"Origin": "https://evil.test"}
        ).status_code
        == 403
    )
    assert client.post("/api/builder/test", json={"consent": True}).json()["status"] == "ok"
    assert len(fake.calls) == 1 and fake.calls[0]["schema"] == "Probe"
    assert "Workshop" not in fake.calls[0]["context"]
    assert FIXTURE["answers"]["mission"] not in fake.calls[0]["context"]


def test_browser_manual_flow_and_edit_review(client, project_fixture):
    project = client.post("/api/projects", json=project_fixture).json()["id"]
    assert "/interview" in client.get(f"/projects/{project}").text
    state = client.get(route(project)).json()
    for topic, value in FIXTURE["answers"].items():
        response = client.post(
            f"/projects/{project}/interview/answers",
            data={
                "expected_revision": str(state["revision"]),
                "topic": topic,
                "answer": value,
            },
            headers=ORIGIN,
        )
        assert response.status_code == 200, response.text
        state = client.get(route(project)).json()
    response = client.post(
        f"/projects/{project}/interview/manual",
        data={
            "expected_revision": str(state["revision"]),
        },
        headers=ORIGIN,
    )
    assert response.status_code == 200 and "OWNER_DRAFT" in response.text
    state = client.get(route(project)).json()
    edited = {
        **FIXTURE["answers"],
        "name": "Edited owner name",
        "action": "apply",
        "expected_revision": str(state["revision"]),
    }
    response = client.post(f"/projects/{project}/interview/review", data=edited, headers=ORIGIN)
    assert response.status_code == 200, response.text
    assert "Your reviewed specification was saved" in response.text
    assert client.get(f"/api/projects/{project}").json()["name"] == "Edited owner name"
    assert client.get(f"/projects/{project}").status_code == 200


def test_browser_provider_flow(guided):
    client, project, fake, _ = guided
    state = complete(client, project)
    response = client.post(
        f"/projects/{project}/interview/prepare",
        data={
            "expected_revision": str(state["revision"]),
            "excerpt_0": "",
            "excerpt_1": "",
            "excerpt_2": "",
        },
        headers=ORIGIN,
    )
    assert response.status_code == 200 and "Review external-data disclosure" in response.text
    assert fake.calls == []
    state = client.get(route(project)).json()
    data = consent(state)
    data["consent"] = "yes"
    data["expected_revision"] = str(data["expected_revision"])
    response = client.post(f"/projects/{project}/interview/send", data=data, headers=ORIGIN)
    assert response.status_code == 200 and "AI_DRAFT" in response.text
    state = client.get(route(project)).json()
    assert (
        client.post(
            f"/projects/{project}/interview/review",
            data={
                "action": "reject",
                "expected_revision": str(state["revision"]),
            },
            headers=ORIGIN,
        ).status_code
        == 200
    )
    response = client.post(
        f"/projects/{project}/interview/provider-test", data={"consent": "yes"}, headers=ORIGIN
    )
    assert response.status_code == 200 and "No business data was sent" in response.text


def envelope(content, **overrides):
    return {"choices": [{"finish_reason": "stop", "message": {"content": content}, **overrides}]}


def call_provider(config, handler, *, context="synthetic fixture", schema=Interpretation):
    provider = OpenAICompatible(config, transport=httpx.MockTransport(handler))
    return asyncio.run(provider.structured(system="Return JSON", context=context, schema=schema))


def test_adapter_wire_schema_and_secret_file(settings, tmp_path):
    key_file = tmp_path / "provider-secret"
    key_file.write_text("synthetic-key-from-file\n")
    config = Settings(
        data_dir=settings.data_dir,
        builder_base_url="https://provider.example/v1/",
        builder_model="configured-model",
        builder_api_key_file=key_file,
        _env_file=None,
    )
    calls = []

    def handler(request):
        calls.append(request)
        assert str(request.url) == "https://provider.example/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer synthetic-key-from-file"
        body = json.loads(request.content)
        assert body["model"] == "configured-model"
        assert body["max_completion_tokens"] == 2048
        assert body["store"] is False and body["stream"] is False
        assert body["response_format"]["type"] == "json_schema"
        schema = body["response_format"]["json_schema"]["schema"]
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(Interpretation.model_fields)
        assert "synthetic-key-from-file" not in request.content.decode()
        return httpx.Response(200, json=envelope(json.dumps(FIXTURE["interpretation"])))

    assert call_provider(config, handler).mission == FIXTURE["interpretation"]["mission"]
    assert len(calls) == 1


@pytest.mark.parametrize(
    "body",
    [
        None,
        [],
        {},
        {"choices": []},
        {"choices": [None]},
        envelope("not JSON"),
        envelope("{}"),
        envelope("{}", finish_reason="length"),
        envelope("{}", message=None),
        envelope("{}", message={"refusal": "do not log me"}),
        envelope(json.dumps({**FIXTURE["interpretation"], "training_examples": ["do not accept"]})),
        envelope(json.dumps({**FIXTURE["interpretation"], "mission": 123})),
    ],
)
def test_adapter_invalid_json_sanitized_without_automatic_retry(guided, body, caplog):
    _, _, _, config = guided
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=body)

    with pytest.raises(DomainError, match="BUILDER_JSON") as exc:
        call_provider(config, handler)
    assert len(calls) == 1
    assert "do not log me" not in str(exc.value) + caplog.text


@pytest.mark.parametrize(
    "status,code",
    [
        (302, "BUILDER_HTTP"),
        (401, "BUILDER_AUTH"),
        (403, "BUILDER_AUTH"),
        (429, "BUILDER_RATE_LIMIT"),
        (500, "BUILDER_HTTP"),
        (400, "BUILDER_HTTP"),
    ],
)
def test_adapter_http_errors_do_not_leak_or_retry(guided, status, code, caplog):
    _, _, _, config = guided
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            status, text="sensitive-provider-error", headers={"Location": "https://elsewhere.test"}
        )

    with pytest.raises(DomainError, match=code) as exc:
        call_provider(config, handler)
    assert len(calls) == 1
    assert "sensitive-provider-error" not in caplog.text + str(exc.value)


def test_adapter_timeouts_connection_and_size_bounds(guided):
    _, _, _, config = guided
    for error, code in (
        (httpx.ReadTimeout("sensitive"), "BUILDER_TIMEOUT"),
        (httpx.ConnectError("sensitive"), "BUILDER_CONNECTION"),
    ):

        def fail(request, error=error):
            raise error

        with pytest.raises(DomainError, match=code):
            call_provider(config, fail)

    async def slow(request):
        await asyncio.sleep(2)

    bounded = config.model_copy(update={"builder_timeout_seconds": 1})
    with pytest.raises(DomainError, match="BUILDER_TIMEOUT"):
        call_provider(bounded, slow)
    with pytest.raises(DomainError, match="BUILDER_SIZE"):
        call_provider(config, lambda r: httpx.Response(200, content=b"x" * 65537))
    with pytest.raises(DomainError, match="BUILDER_JSON"):
        call_provider(config, lambda r: httpx.Response(200, content=b"[" * 2000 + b"]" * 2000))
    calls = []
    with pytest.raises(DomainError, match="BUILDER_INPUT"):
        call_provider(config, lambda r: calls.append(r), context="x" * 65537)
    assert not calls


def test_key_validation_and_unconfigured_manual_default(settings, tmp_path):
    assert credential(settings) is None
    for changes in (
        {"builder_api_key": SecretStr("key\nvalue")},
        {"builder_api_key_file": tmp_path / "missing"},
        {"builder_api_key_file": tmp_path},
        {"builder_api_key": SecretStr("key"), "builder_api_key_file": tmp_path / "secret"},
    ):
        with pytest.raises(DomainError, match="BUILDER_KEY"):
            credential(settings.model_copy(update=changes))
    big = tmp_path / "big-secret"
    big.write_bytes(b"x" * 4097)
    with pytest.raises(DomainError, match="BUILDER_KEY"):
        credential(settings.model_copy(update={"builder_api_key_file": big}))


@pytest.mark.parametrize(
    "value",
    [
        "https://user:key@example.test/v1",
        "https://example.test/v1?key=secret",
        "https://example.test/v1#secret",
        "http://remote.example/v1",
    ],
)
def test_provider_settings_reject_credentials_and_insecure_remote_urls(value):
    with pytest.raises(ValidationError):
        Settings(builder_base_url=value, _env_file=None)


def test_compatible_loopback_and_bounded_timeout_settings():
    assert Settings(builder_base_url="http://127.0.0.1:8080/v1", _env_file=None).builder_base_url
    for timeout in (0, 31):
        with pytest.raises(ValidationError):
            Settings(builder_timeout_seconds=timeout, _env_file=None)
    for model in (" ", "x" * 201):
        with pytest.raises(ValidationError):
            Settings(builder_model=model, _env_file=None)


def test_v2_migration_preserves_existing_documents(guided):
    client, project, _, config = guided
    before = client.get(f"/api/projects/{project}").json()
    with connect(config.database_path) as connection:
        raw = connection.execute("SELECT document FROM adviser_revisions").fetchall()[0][0]
        connection.execute("DROP TABLE interview_revisions")
        connection.execute("PRAGMA user_version=2")
    migrate(config.database_path)
    assert client.get(f"/api/projects/{project}").json() == before
    with connect(config.database_path) as connection:
        assert connection.execute("SELECT document FROM adviser_revisions").fetchall()[0][0] == raw
        assert connection.execute("SELECT COUNT(*) FROM interview_revisions").fetchone()[0] == 0


@pytest.mark.parametrize("value", [False, "true", 1, None])
def test_strict_consent_contract(value):
    with pytest.raises(ValidationError):
        ProviderTest(consent=value)
    with pytest.raises(ValidationError):
        Consent(expected_revision=1, turn_id=uuid4(), disclosure_sha256="0" * 64, consent=value)


def test_busy_request_blocks_second_call_and_answer_edits(guided):
    client, project, fake, config = guided
    complete(client, project)
    state = prepare(client, project)
    with connect(config.database_path) as connection:
        pending = append_interview(connection, get_interview(config, project), status="sending")
    for suffix, payload in (
        ("/answers", {"topic": "mission", "answer": "cannot overwrite"}),
        ("/manual", {}),
        ("/prepare", {}),
        (
            "/send",
            {
                "turn_id": state["prepared"]["id"],
                "disclosure_sha256": state["prepared"]["disclosure_sha256"],
                "consent": True,
            },
        ),
    ):
        response = client.post(
            route(project, suffix),
            json={
                "expected_revision": pending.revision,
                **payload,
            },
        )
        assert response.status_code == 409 and "INTERVIEW_BUSY" in response.text
    assert fake.calls == []


def test_provider_config_change_invalidates_disclosure(guided):
    client, project, fake, config = guided
    complete(client, project)
    state = prepare(client, project)
    config.builder_model = "changed-model"
    assert client.post(route(project, "/send"), json=consent(state)).status_code == 409
    assert fake.calls == []


def test_excerpt_and_summary_bounds_and_original_integrity(guided):
    from quartermaster.sources import blob_path

    client, project, fake, config = guided
    markdown = ("# Policy\n" + "α" * 1500).encode()
    doc = upload(client, project, markdown, name="long.md", label="knowledge").json()
    headers = ["field_" + str(i) for i in range(40)]
    upload(
        client,
        project,
        (",".join(headers) + "\n" + ",".join(["private-cell"] * 40) + "\n").encode(),
    )
    complete(client, project)
    state = prepare(client, project, excerpt_source_ids=[doc["id"]])
    context = json.loads(state["prepared"]["context"])["sources"]
    assert len(context["optional_excerpts"][0]["text"]) == 1000
    sheet = context["summaries"][1]["sheets"][0]
    assert sheet["field_count"] == 40 and len(sheet["fields"]) == 30
    assert "private-cell" not in json.dumps(context)
    blob_path(config.artifact_root, doc["sha256"]).unlink()
    state = client.get(route(project)).json()
    response = client.post(
        route(project, "/prepare"),
        json={
            "expected_revision": state["revision"],
            "excerpt_source_ids": [doc["id"]],
        },
    )
    assert response.status_code == 503 and "SOURCE_UNAVAILABLE" in response.text
    assert fake.calls == []


def test_preview_budget_uses_utf8_bytes_and_preserves_saved_answers(guided):
    client, project, fake, _ = guided
    state = complete(client, project)
    for topic in (
        "mission",
        "business_goal",
        "target_behavior",
        "success_and_harm",
        "decision_inputs",
    ):
        state = client.post(
            route(project, "/answers"),
            json={
                "expected_revision": state["revision"],
                "topic": topic,
                "answer": "界" * 4000,
            },
        ).json()
    response = client.post(
        route(project, "/prepare"), json={"expected_revision": state["revision"]}
    )
    assert response.status_code == 422 and "BUILDER_INPUT" in response.text
    assert client.get(route(project)).json() == state
    assert fake.calls == []


@pytest.mark.parametrize(
    "change",
    [
        {"model": {"base_model_id": "arbitrary"}},
        {"training_examples": []},
        {"decision_definition": {}},
        {"name": 123},
        {"mission": None},
    ],
)
def test_review_schema_cannot_change_model_or_invent_labels(guided, change):
    client, project, _, _ = guided
    state = complete(client, project)
    state = client.post(
        route(project, "/manual"), json={"expected_revision": state["revision"]}
    ).json()
    response = client.post(
        route(project, "/review"),
        json={
            "expected_revision": state["revision"],
            "action": "apply",
            "edited": {**FIXTURE["interpretation"], **change},
        },
    )
    assert response.status_code == 422
    assert client.get(route(project)).json() == state
    assert client.get(f"/api/projects/{project}").json()["revision"] == 1
