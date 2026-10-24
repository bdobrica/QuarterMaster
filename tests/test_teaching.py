import asyncio
import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid4

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from quartermaster import teaching
from quartermaster.app import create_app
from quartermaster.config import Settings
from quartermaster.contracts.advice import Advice, Case
from quartermaster.contracts.teaching import GroundedAdvice, Lesson
from quartermaster.db import connect, migrate
from quartermaster.errors import DomainError
from quartermaster.inference import PARAMETERS, LocalInference, model_alias, response_schema
from quartermaster.local_runtime import verify
from quartermaster.sources import blob_path
from tests.test_foundation import MD, select_knowledge, upload

FIXTURE = json.loads((Path(__file__).parent / "fixtures/teaching.json").read_text())
SHA = "a" * 64


def draft(
    *,
    recommendation="May use subject to normal checks.",
    question=None,
    refs=None,
    quotes=None,
    missing=None,
):
    return GroundedAdvice(
        behavior="clarify" if question or missing else "recommend",
        advice=Advice(
            recommendation=recommendation,
            explanation="Based on the supplied facts.",
            evidence_refs=refs or [],
            clarification_question=question,
            limitations=[],
        ),
        supporting_quotes=quotes or [],
        missing_information=missing or [],
    )


class FakeInference:
    def __init__(self):
        self.calls = []
        self.response = None
        self.error = None
        self.hook = None
        self.parameters = []

    async def advise(self, *, system, context, parameters=None):
        self.parameters.append(parameters)
        data = json.loads(context)
        self.calls.append((system, data))
        if self.hook:
            self.hook()
        if self.error:
            raise DomainError(self.error)
        if self.response:
            return self.response
        if data["approved_lessons"]:
            return draft(question="Is any damage reported?", missing=["reported damage status"])
        refs = [item["citation_id"] for item in data["retrieved_evidence"]]
        return draft(quotes=[data["case"]["situation"]], refs=refs)


class FakeBuilder:
    def __init__(self):
        self.calls = []
        self.error = None
        self.hook = None

    async def structured(self, *, system, context, schema):
        self.calls.append((system, json.loads(context)))
        if self.hook:
            self.hook()
        if self.error:
            raise DomainError(self.error)
        return schema.model_validate(FIXTURE["lesson"])


@pytest.fixture
def workshop(settings):
    config = Settings(
        data_dir=settings.data_dir,
        _env_file=None,
        local_base_url="http://127.0.0.1:8080/v1",
        local_model_sha256=SHA,
        builder_base_url="https://provider.example/v1",
        builder_model="fixture",
    )
    inference, builder = FakeInference(), FakeBuilder()
    with TestClient(create_app(config, inference=inference, builder=builder)) as client:
        project = client.post(
            "/api/projects", json={"name": "Workshop", "mission": FIXTURE["mission"]}
        ).json()["id"]
        yield client, project, inference, builder, config


def base(project):
    return f"/api/projects/{project}"


def ask(workshop, situation=None):
    client, project, *_ = workshop
    response = client.post(
        base(project) + "/tests", json={"situation": situation or FIXTURE["baseline"]}
    )
    assert response.status_code == 200, response.text
    return response.json()


def correct(workshop, run=None, category="should_ask"):
    client, project, *_ = workshop
    run = run or ask(workshop)
    response = client.post(
        base(project) + f"/tests/{run['id']}/feedback",
        json={
            "category": category,
            "correction": FIXTURE["correction"],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def lesson_path(project, lesson, suffix):
    return base(project) + f"/lessons/{lesson['id']}/{suffix}"


def prepare(workshop, lesson):
    client, project, *_ = workshop
    result = client.post(
        lesson_path(project, lesson, "prepare"), json={"expected_revision": lesson["revision"]}
    )
    assert result.status_code == 200, result.text
    return result.json()


def consent(lesson):
    return {
        "expected_revision": lesson["revision"],
        "turn_id": lesson["id"],
        "disclosure_sha256": lesson["disclosure"]["disclosure_sha256"],
        "consent": True,
    }


def send(workshop, lesson):
    client, project, *_ = workshop
    result = client.post(lesson_path(project, lesson, "send"), json=consent(lesson))
    assert result.status_code == 200, result.text
    return result.json()


def review(workshop, lesson, action="apply", **extra):
    client, project, *_ = workshop
    result = client.post(
        lesson_path(project, lesson, "review"),
        json={
            "expected_revision": lesson["revision"],
            "action": action,
            **extra,
        },
    )
    assert result.status_code == 200, result.text
    return result.json()


def test_complete_builder_correction_review_unseen_loop(workshop):
    client, project, inference, builder, config = workshop
    original = client.get(base(project)).json()
    run = ask(workshop)
    assert run["response_schema"] == response_schema(run["context"])
    assert run["parameters"]["chat_template_kwargs"] == {"enable_thinking": False}
    assert run["advice"]["clarification_question"] is None
    lesson = correct(workshop, run)
    assert lesson["status"] == "pending" and builder.calls == []
    record = client.get(base(project) + f"/feedback/{lesson['feedback_id']}").json()
    assert record["correction"] == FIXTURE["correction"]
    assert record["case_id"] == run["case"]["case_id"]
    lesson = prepare(workshop, lesson)
    assert builder.calls == []
    disclosure = lesson["disclosure"]
    wire = {k: disclosure[k] for k in ("endpoint", "model", "system", "context", "response_schema")}
    assert (
        hashlib.sha256(teaching.encoded(wire).encode()).hexdigest()
        == disclosure["disclosure_sha256"]
    )
    lesson = send(workshop, lesson)
    assert lesson["origin"] == "AI_DRAFT" and lesson["status"] == "pending"
    assert len(builder.calls) == 1 and lesson["consented_at"]
    assert client.get(base(project)).json() == original
    assert ask(workshop, FIXTURE["unseen"])["lessons"] == []
    applied = review(workshop, lesson)
    assert applied["status"] == "applied"
    result = ask(workshop, FIXTURE["unseen"])
    assert result["advice"]["clarification_question"]
    assert "Withhold" in result["advice"]["recommendation"]
    assert result["lessons"][0]["id"] == applied["id"]
    assert result["adviser"]["model"] == run["adviser"]["model"]
    assert result["model_alias"] == model_alias(SHA)
    assert result["adviser"]["lessons_revision"] == applied["id"]
    history = client.get(base(project) + "/lessons/revisions").json()
    assert [item["status"] for item in history] == [
        "pending",
        "pending",
        "sending",
        "pending",
        "reviewed",
        "applied",
    ]
    assert client.get(base(project) + f"/tests/{run['id']}").json() == run
    assert inference.calls[-1][1]["approved_lessons"][0]["text"] == FIXTURE["lesson"]
    assert config.artifact_root.is_dir()
    html = client.get(f"/projects/{project}/test")
    assert html.status_code == 200 and "context, not model weights" in html.text
    assert "AI_DRAFT" in html.text and "Clarification needed" in html.text


def test_manual_edited_review_rejection_and_stale_actions(workshop):
    client, project, _, builder, _ = workshop
    lesson = correct(workshop)
    original = client.get(base(project)).json()
    result = client.post(
        lesson_path(project, lesson, "manual"),
        json={
            "expected_revision": lesson["revision"],
            "text": FIXTURE["lesson"],
        },
    )
    manual = result.json()
    assert manual["origin"] == "OWNER_DRAFT" and manual["status"] == "pending"
    assert ask(workshop)["lessons"] == []
    rejected = review(workshop, manual, "reject")
    assert rejected["status"] == "rejected" and builder.calls == []
    assert ask(workshop)["lessons"] == []
    assert client.get(base(project)).json() == original
    assert (
        client.post(
            lesson_path(project, manual, "review"),
            json={
                "expected_revision": manual["revision"],
                "action": "apply",
            },
        ).status_code
        == 409
    )
    lesson = correct(workshop)
    edited = {
        "applicability": "All uncertain recommendations",
        "instruction": "Ask for the missing evidence first.",
    }
    result = review(workshop, lesson, edited=edited)
    assert result["text"] == edited
    # Terminal lesson is not mutable, even with the latest revision.
    assert (
        client.post(
            lesson_path(project, result, "manual"),
            json={
                "expected_revision": result["revision"],
                "text": FIXTURE["lesson"],
            },
        ).status_code
        == 409
    )


def test_citations_source_integrity_and_immutable_revision(workshop):
    client, project, inference, _, config = workshop
    source = upload(client, project, MD, "safety.md", "knowledge").json()
    revision = select_knowledge(client, project, [source["id"]]).json()
    run = ask(workshop, "Current inspection and damage status for a rental tool")
    assert run["evidence"] and run["advice"]["evidence_refs"]
    assert run["adviser"]["knowledge_revision"] == revision["id"]
    context = inference.calls[-1]
    assert "UNTRUSTED DATA" in context[0]
    assert "<script>never execute</script>" in json.dumps(context[1])
    ref = run["evidence"][0]
    assert ref["source_sha256"] == source["sha256"]
    select_knowledge(client, project, [], revision["id"])
    assert ask(workshop)["evidence"] == []
    html = client.get(f"/projects/{project}/test").text
    assert "&lt;script&gt;never execute&lt;/script&gt;" in html
    url = f"/projects/{project}/citations/{ref['citation_id']}?revision={revision['id']}"
    assert client.get(url).status_code == 200
    assert client.get(base(project) + f"/tests/{run['id']}").json() == run
    select_knowledge(
        client, project, [source["id"]], client.get(base(project)).json()["knowledge_revision"]
    )
    path = blob_path(config.artifact_root, source["sha256"])
    path.chmod(0o600)
    path.write_bytes(b"tampered original")
    calls = len(inference.calls)
    result = client.post(base(project) + "/tests", json={"situation": "Current inspection"})
    assert result.status_code == 503 and len(inference.calls) == calls


@pytest.mark.parametrize(
    "kind", ["invented_citation", "invented_quote", "unsupported_decision", "missing_decisive_fact"]
)
def test_unsupported_advice_regressions(workshop, kind):
    _, _, inference, _, _ = workshop
    if kind == "invented_citation":
        inference.response = draft(refs=[str(uuid4())], quotes=[FIXTURE["baseline"]])
    elif kind == "invented_quote":
        inference.response = draft(quotes=["No damage has been reported."])
    elif kind == "unsupported_decision":
        inference.response = draft()
    else:
        inference.response = draft(
            recommendation="Definitely use it, it is safe!", missing=["damage status"]
        )
    run = ask(workshop)
    if kind == "missing_decisive_fact":
        assert run["error"] is None
        assert "Definitely" not in run["advice"]["recommendation"]
        assert run["advice"]["clarification_question"] == "Please clarify: damage status"
        assert run["draft"]["advice"]["recommendation"].startswith("Definitely")
    else:
        assert run["advice"] is None and run["error"].startswith("ADVICE_")


def test_failure_snapshot_keeps_context_and_allows_explicit_retry(workshop, caplog):
    client, project, inference, _, _ = workshop
    inference.error = "LOCAL_CONNECTION: Start the service and retry."
    run = ask(workshop)
    assert run["advice"] is None and run["error"]
    assert run["context"] and run["case"]["situation"] == FIXTURE["baseline"]
    assert (
        client.post(
            base(project) + f"/tests/{run['id']}/feedback",
            json={
                "category": "good",
                "correction": "x",
            },
        ).status_code
        == 422
    )
    inference.error = None
    assert ask(workshop)["advice"]
    assert len(inference.calls) == 2
    assert FIXTURE["baseline"] not in caplog.text


def test_local_unconfigured_and_project_isolation(client):
    project = client.post("/api/projects", json={"name": "x", "mission": "Help"}).json()["id"]
    result = client.post(base(project) + "/tests", json={"situation": "Need advice"})
    assert result.status_code == 422 and "LOCAL_CONFIG" in result.text
    assert "Local inference is not configured" in client.get(f"/projects/{project}/test").text


@pytest.mark.parametrize(
    "change",
    [
        {"consent": False},
        {"consent": "true"},
        {"consent": 1},
        {"turn_id": str(uuid4())},
        {"disclosure_sha256": "0" * 64},
        {"expected_revision": 0},
        {"extra": "unsupported"},
    ],
)
def test_lesson_consent_rejects_missing_stale_and_wrong_inputs(workshop, change):
    client, project, _, builder, _ = workshop
    lesson = prepare(workshop, correct(workshop))
    data = {**consent(lesson), **change}
    result = client.post(lesson_path(project, lesson, "send"), json=data)
    assert result.status_code in {409, 422} and builder.calls == []
    assert client.get(base(project) + "/lessons").json()[0] == lesson


def test_builder_draft_data_minimized_busy_and_failure_retry(workshop):
    client, project, _, builder, config = workshop
    run = ask(workshop)
    lesson = prepare(workshop, correct(workshop, run))
    context = json.loads(lesson["disclosure"]["context"])
    assert "observed_outcome" not in context["case"]
    assert set(context) == {"mission", "case", "advice", "feedback_category", "owner_correction"}
    builder.error = "BUILDER_TIMEOUT: Retry explicitly."

    def inspect_sending():
        sending = teaching.get_lesson(config, UUID(project), UUID(lesson["id"]))
        assert sending.status == "sending" and sending.consented_at
        with connect(config.database_path) as connection:
            with pytest.raises(DomainError, match="LESSON_STATE"):
                teaching.checked_lesson(connection, UUID(project), sending.id, sending.revision)

    builder.hook = inspect_sending
    failed = send(workshop, lesson)
    assert failed["status"] == "failed" and "BUILDER_TIMEOUT" in failed["error"]
    assert len(builder.calls) == 1
    builder.error, builder.hook = None, None
    recovered = send(workshop, prepare(workshop, failed))
    assert recovered["status"] == "pending" and recovered["text"]
    assert len(builder.calls) == 2


def test_cross_project_scoping_and_csrf(workshop):
    client, project, _, builder, _ = workshop
    run = ask(workshop)
    lesson = correct(workshop, run)
    other = client.post("/api/projects", json={"name": "Other", "mission": "Help"}).json()["id"]
    assert client.get(base(other) + f"/tests/{run['id']}").status_code == 404
    assert client.get(base(other) + f"/feedback/{lesson['feedback_id']}").status_code == 404
    assert (
        client.post(
            lesson_path(other, lesson, "prepare"), json={"expected_revision": 1}
        ).status_code
        == 404
    )
    for url, data in [
        (base(project) + "/tests", {"situation": "Help"}),
        (lesson_path(project, lesson, "review"), {"expected_revision": 1, "action": "reject"}),
    ]:
        assert (
            client.post(url, json=data, headers={"Origin": "https://foreign.example"}).status_code
            == 403
        )
    assert client.post(f"/projects/{project}/test", data={"situation": "Help"}).status_code == 403
    assert builder.calls == []


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"situation": ""},
        {"situation": 1},
        {"situation": "x", "observed_outcome": "later"},
        {"situation": "x", "extra": 1},
        {"situation": "x", "choices": [1]},
        {"situation": "x" * 4001},
    ],
)
def test_invalid_test_input(workshop, data):
    client, project, inference, *_ = workshop
    assert client.post(base(project) + "/tests", json=data).status_code == 422
    assert inference.calls == []


@pytest.mark.parametrize("category", list(teaching.CATEGORIES))
def test_feedback_categories_preserve_raw_text(workshop, category):
    client, project, *_ = workshop
    lesson = correct(workshop, category=category)
    feedback = client.get(base(project) + f"/feedback/{lesson['feedback_id']}").json()
    assert feedback["category"] == category and feedback["correction"] == FIXTURE["correction"]


def test_case_outcome_not_in_context_or_builder(workshop):
    client, project, *_, config = workshop
    case = Case(
        case_id=uuid4(), situation="Decision facts", observed_outcome="PRIVATE LATER RESULT"
    )
    _, context, _, _, _ = teaching.assemble(config, UUID(project), case)
    assert "PRIVATE LATER RESULT" not in context and "observed_outcome" not in context
    assert (
        client.post(
            base(project) + "/tests", json={"situation": "x", "observed_outcome": "later"}
        ).status_code
        == 422
    )


def test_recovery_and_v3_migration_preserve_history(workshop):
    client, project, *_, config = workshop
    lesson = prepare(workshop, correct(workshop))
    with connect(config.database_path) as connection:
        state = Lesson.model_validate_json(json.dumps(lesson))
        teaching.append_lesson(connection, state, status="sending")
    teaching.recover_lessons(config)
    teaching.recover_lessons(config)
    latest = teaching.get_lesson(config, UUID(project), UUID(lesson["id"]))
    assert latest.status == "failed" and "BUILDER_INTERRUPTED" in latest.error
    before = client.get(base(project)).json()
    with connect(config.database_path) as connection:
        for table in (
            "reliability_runs",
            "reliability_reviews",
            "training_examples",
            "training_runs",
            "adviser_versions",
            "evaluation_suites",
            "evaluation_runs",
            "evaluation_ratings",
            "evaluation_holdouts",
        ):
            connection.execute(f"DROP TABLE {table}")
        connection.execute("DROP TABLE test_runs")
        connection.execute("DROP TABLE feedback")
        connection.execute("DROP TABLE lesson_revisions")
        connection.execute("PRAGMA user_version=3")
    migrate(config.database_path)
    assert client.get(base(project)).json() == before
    assert client.get("/healthz").status_code == 200


def call_local(settings, handler):
    config = settings.model_copy(
        update={
            "local_base_url": Settings(local_base_url="http://localhost:8080/v1").local_base_url,
            "local_model_sha256": SHA,
        }
    )
    provider = LocalInference(config, transport=httpx.MockTransport(handler))
    return asyncio.run(provider.advise(system="Advisory instructions", context="{}"))


def envelope(content):
    return {"choices": [{"finish_reason": "stop", "message": {"content": content}}]}


def test_local_adapter_wire_and_pin_check(settings):
    requests = []

    def handler(request):
        requests.append(request)
        assert "authorization" not in request.headers
        if request.method == "GET":
            assert request.url.path == "/v1/models"
            return httpx.Response(200, json={"data": [{"id": model_alias(SHA)}]})
        body = json.loads(request.content)
        assert body["model"] == model_alias(SHA)
        assert all(body[k] == v for k, v in PARAMETERS.items())
        assert body["chat_template_kwargs"] == {"enable_thinking": False}
        assert body["response_format"]["json_schema"]["schema"] == response_schema("{}")
        return httpx.Response(
            200, json=envelope(draft(question="What is missing?").model_dump_json())
        )

    assert call_local(settings, handler).advice.clarification_question
    assert len(requests) == 2


@pytest.mark.parametrize(
    "kind",
    [
        "wrong_model",
        "redirect",
        "http",
        "oversize",
        "truncated",
        "extra_field",
        "bad_type",
        "bad_json",
        "timeout",
        "connection",
    ],
)
def test_local_adapter_rejects_bad_servers_without_retry(settings, kind):
    calls = []

    def handler(request):
        calls.append(request)
        if kind == "timeout":
            raise httpx.ReadTimeout("private details")
        if kind == "connection":
            raise httpx.ConnectError("private details")
        if kind == "redirect":
            return httpx.Response(302, headers={"Location": "https://external.example"})
        if kind == "http":
            return httpx.Response(503, text="private details")
        if kind == "oversize":
            return httpx.Response(200, content=b"x" * 65537)
        if request.method == "GET":
            return httpx.Response(
                200, json={"data": [{"id": "other" if kind == "wrong_model" else model_alias(SHA)}]}
            )
        payload = draft(question="What is missing?").model_dump(mode="json")
        if kind == "extra_field":
            payload["advice"]["tool_call"] = "forbidden"
        if kind == "bad_type":
            payload["advice"]["evidence_refs"] = "not a list"
        result = envelope("not-json" if kind == "bad_json" else json.dumps(payload))
        if kind == "truncated":
            result["choices"][0]["finish_reason"] = "length"
        return httpx.Response(200, json=result)

    with pytest.raises(DomainError, match="LOCAL_") as exc:
        call_local(settings, handler)
    assert "private details" not in str(exc.value)
    assert len(calls) <= 2
    if kind == "wrong_model":
        assert len(calls) == 1  # No case transmitted to an unexpected model.


@pytest.mark.parametrize(
    "url",
    [
        "https://api.example/v1",
        "http://192.168.1.1/v1",
        "http://localhost:8080/v1?secret=x",
        "http://user:pass@localhost/v1",
    ],
)
def test_local_endpoint_configuration_restricts_external_transmission(url):
    with pytest.raises(ValidationError):
        Settings(local_base_url=url)


def test_runtime_manifest_pins_hashes_and_rejects_merged_artifact(tmp_path):
    from quartermaster import local_runtime
    from quartermaster.spike import spec

    assert local_runtime.MODEL_REVISION == spec.MODEL_REVISION
    assert local_runtime.LLAMA_REVISION == spec.LLAMA_REVISION
    model = tmp_path / "model.gguf"
    model.write_bytes(b"GGUF\x03\x00\x00\x00" + b"x" * 1_000_000)
    license_file = tmp_path / "LICENSE.model"
    license_file.write_text("Synthetic license fixture")
    record = {
        "schema_version": "quartermaster.local-model/v1",
        "model_id": spec.MODEL_ID,
        "revision": spec.MODEL_REVISION,
        "llama_revision": spec.LLAMA_REVISION,
        "adapter_artifact": None,
        "format": "GGUF-Q8_0",
        "size_bytes": model.stat().st_size,
        "sha256": local_runtime.sha256(model),
        "license_sha256": local_runtime.sha256(license_file),
    }
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(record))
    assert verify(tmp_path) == record
    for key, value in [
        ("adapter_artifact", "merged"),
        ("revision", "other"),
        ("sha256", "0" * 64),
        ("format", "unknown"),
    ]:
        manifest.write_text(json.dumps({**record, key: value}))
        with pytest.raises(ValueError):
            verify(tmp_path)
    manifest.write_text(json.dumps(record))
    model.unlink()
    model.symlink_to(license_file)
    with pytest.raises(ValueError):
        verify(tmp_path)


def test_context_budget_never_truncates_case_and_excludes_pending(workshop):
    client, project, *_, config = workshop
    for _ in range(10):
        lesson = correct(workshop)
        review(
            workshop,
            lesson,
            edited={"applicability": "Rental tools", "instruction": "Ask first. " * 300},
        )
    situation = "Rental tools: " + "x" * 3500
    run = ask(workshop, situation)
    assert json.loads(run["context"])["case"]["situation"] == situation
    assert len(run["context"].encode()) <= teaching.MAX_CONTEXT_BYTES
    assert len(run["lessons"]) < 10
    assert any("omitted" in x for x in run["advice"]["limitations"])
    assert len(teaching.latest_lessons(config, UUID(project))) == 10


def test_review_contract_no_model_or_training_fields(workshop):
    client, project, *_ = workshop
    lesson = correct(workshop)
    for edited in [
        {"applicability": "All", "instruction": "Ask", "model": {}},
        {"applicability": 1, "instruction": "Ask"},
    ]:
        assert (
            client.post(
                lesson_path(project, lesson, "review"),
                json={
                    "expected_revision": lesson["revision"],
                    "action": "apply",
                    "edited": edited,
                },
            ).status_code
            == 422
        )


def test_abstention_is_valid_without_support_or_a_question(workshop):
    _, _, inference, *_ = workshop
    inference.response = GroundedAdvice(
        behavior="abstain",
        advice=Advice(
            recommendation="Cannot decide",
            explanation="Insufficient evidence.",
            evidence_refs=[],
            clarification_question=None,
            limitations=["No basis for comparison"],
        ),
        supporting_quotes=[],
        missing_information=[],
    )
    result = ask(workshop)
    assert result["error"] is None
    assert result["advice"]["recommendation"].startswith("Unable to recommend")


def test_question_with_decisive_draft_is_withheld(workshop):
    _, _, inference, *_ = workshop
    inference.response = draft(
        recommendation="Definitely use the tool!", question="Is there any damage?"
    )
    result = ask(workshop)
    assert result["advice"]["recommendation"].startswith("Withhold")


@pytest.mark.parametrize(
    "change",
    [
        {"category": "unknown"},
        {"category": 1},
        {"correction": ""},
        {"correction": "   "},
        {"correction": 1},
        {"correction": "x" * 4001},
        {"training_label": "approved"},
    ],
)
def test_invalid_feedback_cannot_create_lessons(workshop, change):
    client, project, *_ = workshop
    run = ask(workshop)
    result = client.post(
        base(project) + f"/tests/{run['id']}/feedback",
        json={
            "category": "good",
            "correction": "Keep asking",
            **change,
        },
    )
    assert result.status_code == 422
    assert client.get(base(project) + "/lessons").json() == []


def test_changed_provider_requires_new_disclosure(workshop):
    _, project, _, builder, config = workshop
    lesson = prepare(workshop, correct(workshop))
    from quartermaster.contracts.teaching import LessonSend

    changed = config.model_copy(update={"builder_model": "different"})
    with pytest.raises(DomainError, match="LESSON_CONSENT"):
        asyncio.run(
            teaching.send_lesson(
                changed,
                builder,
                UUID(project),
                UUID(lesson["id"]),
                LessonSend.model_validate(consent(lesson)),
            )
        )
    assert builder.calls == []


def test_approval_during_inference_preserves_original_snapshot(workshop):
    client, project, inference, _, config = workshop
    lesson = correct(workshop)

    def apply_after_snapshot():
        inference.hook = None
        from quartermaster.contracts.teaching import LessonReview

        teaching.review_lesson(
            config,
            UUID(project),
            UUID(lesson["id"]),
            LessonReview.model_validate(
                {
                    "expected_revision": lesson["revision"],
                    "action": "apply",
                    "edited": FIXTURE["lesson"],
                }
            ),
        )

    inference.hook = apply_after_snapshot
    before = ask(workshop)
    assert before["lessons"] == [] and before["adviser"]["lessons_revision"] is None
    after = ask(workshop)
    assert after["lessons"] and after["adviser"]["lessons_revision"]
    assert client.get(base(project) + f"/tests/{before['id']}").json() == before


def test_local_busy_rejected_without_queueing(settings):
    config = settings.model_copy(
        update={
            "local_base_url": Settings(local_base_url="http://localhost:8080/v1").local_base_url,
            "local_model_sha256": SHA,
        }
    )
    provider = LocalInference(config)

    async def run():
        async with provider.lock:
            with pytest.raises(DomainError, match="LOCAL_BUSY"):
                await provider.advise(system="Help", context="{}")

    asyncio.run(run())


def test_generation_schema_limits_refs_and_question_by_behavior():
    citation = str(uuid4())
    result = response_schema(json.dumps({"retrieved_evidence": [{"citation_id": citation}]}))
    for branch in result["oneOf"]:
        props = branch["properties"]
        behavior = props["behavior"]["const"]
        advice_props = props["advice"]["properties"]
        assert advice_props["evidence_refs"]["items"]["enum"] == [citation]
        question_type = "string" if behavior == "clarify" else "null"
        assert advice_props["clarification_question"]["type"] == question_type
        if behavior == "recommend":
            assert props["supporting_quotes"]["minItems"] == 1
            assert props["missing_information"]["maxItems"] == 0
        else:
            assert props["supporting_quotes"]["maxItems"] == 0


def test_safe_clarification_discards_unused_draft_support(workshop):
    _, _, inference, *_ = workshop
    inference.response = draft(
        recommendation="Definitely use it!",
        missing=["damage status"],
        quotes=["A fabricated claim that must never reach displayed advice."],
    )
    result = ask(workshop)
    assert result["advice"]["recommendation"].startswith("Withhold")
    assert result["advice"]["clarification_question"] == "Please clarify: damage status"
    assert "fabricated claim" not in json.dumps(result["advice"])


def test_v3_upgrade_preserves_populated_teaching_metadata_and_originals(workshop):
    from tests.test_foundation import mapping_for

    client, project, *_, config = workshop
    table = upload(client, project).json()
    doc = upload(client, project, MD, "safety.md", "knowledge").json()
    assert client.post(base(project) + "/mappings", json=mapping_for(table)).status_code == 201
    assert select_knowledge(client, project, [doc["id"]]).status_code == 201
    assert (
        client.post(
            base(project) + "/interview/answers",
            json={
                "expected_revision": 0,
                "topic": "mission",
                "answer": "Keep this mission locally",
            },
        ).status_code
        == 200
    )
    tables = [
        "projects",
        "adviser_revisions",
        "sources",
        "case_mappings",
        "derived_cases",
        "knowledge_revisions",
        "knowledge_members",
        "chunks",
        "chunks_fts",
        "interview_revisions",
    ]
    originals = {
        source["sha256"]: blob_path(config.artifact_root, source["sha256"]).read_bytes()
        for source in (table, doc)
    }
    with connect(config.database_path) as connection:
        before = {
            table: [
                tuple(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY rowid")
            ]
            for table in tables
        }
        assert all(before.values())
        for table in (
            "reliability_runs",
            "reliability_reviews",
            "training_examples",
            "training_runs",
            "adviser_versions",
            "test_runs",
            "feedback",
            "lesson_revisions",
            "evaluation_suites",
            "evaluation_runs",
            "evaluation_ratings",
            "evaluation_holdouts",
        ):
            connection.execute(f"DROP TABLE {table}")
        connection.execute("PRAGMA user_version=3")
    migrate(config.database_path)
    with connect(config.database_path) as connection:
        after = {
            table: [
                tuple(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY rowid")
            ]
            for table in tables
        }
    assert before == after
    assert all(
        blob_path(config.artifact_root, digest).read_bytes() == content
        for digest, content in originals.items()
    )
    assert client.get("/healthz").status_code == 200


def test_saved_test_deep_link_and_project_scope(workshop):
    client, project, *_ = workshop
    run = ask(workshop)
    html = client.get(f"/projects/{project}/test?test_id={run['id']}")
    assert html.status_code == 200 and FIXTURE["baseline"] in html.text
    assert "Back to recent tests" in html.text
    other = client.post("/api/projects", json={"name": "Other", "mission": "Help"}).json()["id"]
    assert client.get(f"/projects/{other}/test?test_id={run['id']}").status_code == 404
