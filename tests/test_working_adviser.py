"""Product advice, paired unchanged weights and tested-base standalone packages."""

import asyncio
import hashlib
import json
from uuid import UUID, uuid4

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient

from quartermaster import exporting, teaching
from quartermaster.advice_context import ADVICE_SYSTEM, validate_advice
from quartermaster.contracts.advice import Case
from quartermaster.contracts.export import ExportManifest
from quartermaster.contracts.teaching import GroundedAdvice
from quartermaster.errors import DomainError
from quartermaster.export_package import PackageContext, extract_verified, verify_package
from quartermaster.generation import (
    ADVICE_PARAMETERS,
    LEGACY_PARAMETERS,
    PARAMETERS,
    unambiguous_json,
)
from quartermaster.inference import LocalInference, model_alias
from quartermaster.spike.spec import LLAMA_REVISION, MODEL_ID, MODEL_REVISION
from quartermaster.standalone_runtime import create_runtime
from tests import test_teaching
from tests.test_foundation import select_knowledge, upload

workshop = test_teaching.workshop


def fake_base(config):
    root = config.data_dir / "base"
    root.mkdir()
    model = b"GGUF\x03\0\0\0" + b"x" * 1_000_000
    license_text = b"Synthetic test license"
    (root / "model.gguf").write_bytes(model)
    (root / "LICENSE.model").write_bytes(license_text)
    sha = hashlib.sha256(model).hexdigest()
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "quartermaster.local-model/v1",
                "model_id": MODEL_ID,
                "revision": MODEL_REVISION,
                "llama_revision": LLAMA_REVISION,
                "adapter_artifact": None,
                "format": "GGUF-Q8_0",
                "sha256": sha,
                "size_bytes": len(model),
                "license_sha256": hashlib.sha256(license_text).hexdigest(),
            }
        )
    )
    config.local_model_dir = root
    config.local_model_sha256 = sha
    config.export_runtime_image = "sha256:" + "c" * 64


def test_bounded_wire_keeps_reasoning_private_and_profiles_immutable(settings):
    sent = []
    settings.local_base_url = "http://localhost:8080/v1"
    settings.local_model_sha256 = test_teaching.SHA
    draft = test_teaching.draft(quotes=["Known fact"])

    def respond(request):
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": model_alias(test_teaching.SHA)}]})
        sent.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": draft.model_dump_json(),
                            "reasoning_content": "PRIVATE THOUGHTS",
                        },
                    }
                ]
            },
        )

    adapter = LocalInference(settings, transport=httpx.MockTransport(respond))
    result = asyncio.run(
        adapter.advise(system=ADVICE_SYSTEM, context="{}", parameters=ADVICE_PARAMETERS)
    )
    assert "PRIVATE THOUGHTS" not in result.model_dump_json()
    assert all(sent[0][k] == v for k, v in ADVICE_PARAMETERS.items())
    assert sent[0]["response_format"]["json_schema"]["schema"]["properties"]["behavior"][
        "enum"
    ] == ["recommend", "clarify", "abstain"]
    assert LEGACY_PARAMETERS["max_tokens"] == 512 and PARAMETERS["max_tokens"] == 1024
    assert PARAMETERS["chat_template_kwargs"] == {"enable_thinking": False}


def test_context_includes_nonmatching_rules_and_more_than_four_excerpts(workshop):
    client, project, _, _, config = workshop
    ids = []
    for i in range(6):
        source = upload(
            client,
            project,
            f"# Policy {i}\nZygnathous requirement {i}.\n".encode(),
            f"policy{i}.md",
            "knowledge",
        ).json()
        ids.append(source["id"])
    select_knowledge(client, project, ids)
    run = test_teaching.ask(workshop, "What can you advise about this situation?")
    assert run["error"] is None
    assert len(run["evidence"]) == 6
    assert "Zygnathous" in run["context"] and "business_goal" in run["context"]
    assert run["prompt_version"] == "context/v3"
    assert run["system"] == ADVICE_SYSTEM and run["parameters"] == ADVICE_PARAMETERS
    parsed = teaching.get_test(config, project, run["id"])
    assert parsed.case.observed_outcome is None


def test_paired_comparison_captures_one_context_and_never_changes_active_model(
    workshop, monkeypatch
):
    client, project, base, _, config = workshop
    config.comparison_base_url = "http://comparison:8080/v1"
    config.comparison_model_sha256 = "b" * 64
    lora = test_teaching.FakeInference()
    monkeypatch.setattr("quartermaster.inference.LocalInference", lambda *a, **k: lora)
    before = client.get(test_teaching.base(project)).json()
    result = client.post(
        test_teaching.base(project) + "/tests",
        json={"situation": "Current inspection; no damage.", "compare_existing": True},
    )
    assert result.status_code == 200
    paired = result.json()
    original = client.get(test_teaching.base(project) + "/tests/" + paired["comparison_of"]).json()
    assert paired["case"] == original["case"]
    assert paired["context"] == original["context"]
    assert paired["parameters"] == original["parameters"] == ADVICE_PARAMETERS
    assert paired["evidence"] == original["evidence"]
    assert paired["lessons"] == original["lessons"]
    assert paired["system"] == original["system"]
    assert paired["response_schema"] == original["response_schema"]
    assert paired["model_role"] == "existing_lora" and original["model_role"] == "base"
    assert paired["model_alias"] == "qm-comparison-" + "b" * 64
    assert len(base.calls) == len(lora.calls) == 1
    assert client.get(test_teaching.base(project)).json() == before


def test_unconfigured_comparison_transmits_nothing(workshop):
    client, project, inference, *_ = workshop
    response = client.post(
        test_teaching.base(project) + "/tests",
        json={"situation": "Known facts.", "compare_existing": True},
    )
    assert response.status_code == 409 and inference.calls == []


def test_base_export_replays_knowledge_and_corrections_without_training(workshop, tmp_path):
    client, project, inference, _, config = workshop
    fake_base(config)
    source = upload(
        client, project, b"# Rule\nInspection is mandatory.\n", "rule.md", "knowledge"
    ).json()
    select_knowledge(client, project, [source["id"]])
    first = test_teaching.ask(workshop)
    pending = test_teaching.correct(workshop, first)
    manual = client.post(
        test_teaching.lesson_path(project, pending, "manual"),
        json={"expected_revision": pending["revision"], "text": test_teaching.FIXTURE["lesson"]},
    ).json()
    test_teaching.review(workshop, manual)
    test = test_teaching.ask(workshop, "Inspection current; damage status unknown.")
    assert test["advice"]["clarification_question"]
    before = client.get(test_teaching.base(project)).json()
    result = client.post(
        test_teaching.base(project) + "/exports/base",
        json={"test_id": test["id"], "acknowledge_contents": True},
    )
    assert result.status_code == 201, result.text
    manifest = ExportManifest.model_validate_json(result.content)
    assert manifest.schema_version == "quartermaster.export/v3"
    assert manifest.candidate_id is None and manifest.training_run_id is None
    assert manifest.suite_id is None and str(manifest.source_test_id) == test["id"]
    root = tmp_path / "standalone"
    extract_verified(exporting.archive_path(config, project, manifest.id), root)
    _, frozen, knowledge, reference = verify_package(root)
    assert frozen.adviser.model.adapter_artifact is None
    assert len(frozen.lessons) == 1 and len(knowledge.sources) == 1
    context = PackageContext(frozen, knowledge, prompt_version=manifest.prompt_version)
    try:
        case = Case.model_validate_json(json.dumps(test["case"]))
        assert context.assemble(case)[1] == test["context"]
    finally:
        context.close()
    with TestClient(create_runtime(root, inference=inference, launch_engine=False)) as runtime:
        reply = runtime.post("/v1/advise", json=reference.case.model_dump(mode="json"))
        assert reply.status_code == 200, reply.text
        assert reply.json()["candidate_id"] is None
        assert inference.parameters[-1] == ADVICE_PARAMETERS
        assert inference.calls[-1][0] == ADVICE_SYSTEM
    assert client.get(test_teaching.base(project)).json() == before
    assert not list(root.rglob("*.sqlite3"))
    assert "not a claim of evaluated model improvement" in (root / "README.md").read_text()


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"test_id": "bad", "acknowledge_contents": True},
        {"acknowledge_contents": "true"},
        {"acknowledge_contents": 1},
        {"acknowledge_contents": False},
    ],
)
def test_base_export_requires_review_and_valid_test(workshop, bad):
    client, project, *_ = workshop
    assert client.post(test_teaching.base(project) + "/exports/base", json=bad).status_code == 422


def test_reference_quotes_require_their_accessible_citations(workshop):
    client, project, _, _, config = workshop
    source = upload(
        client, project, b"# Rule\nInspection is mandatory.\n", "rule.md", "knowledge"
    ).json()
    select_knowledge(client, project, [source["id"]])
    case = Case(case_id=UUID(project), situation="Inspection is current.")
    _, _, evidence, *_ = teaching.assemble(config, project, case)
    draft = test_teaching.draft(quotes=["Inspection is mandatory."])
    with pytest.raises(DomainError, match="supporting citation"):
        validate_advice(draft, case, evidence, bounded=True)
    with_ref = GroundedAdvice.model_validate(
        {
            **draft.model_dump(),
            "advice": {
                **draft.advice.model_dump(),
                "evidence_refs": [str(evidence[0].citation_id)],
            },
        }
    )
    assert validate_advice(with_ref, case, evidence, bounded=True)[1].evidence_refs


def test_repeated_json_keys_are_rejected_at_any_depth():
    for raw in (
        '{"behavior":"recommend","behavior":"abstain"}',
        '{"advice":{"recommendation":"one","recommendation":"two"}}',
    ):
        with pytest.raises(ValueError, match="Repeated JSON key"):
            unambiguous_json(raw)
    assert unambiguous_json('{"advice":{"recommendation":"one"}}') == {
        "advice": {"recommendation": "one"}
    }


@pytest.mark.parametrize("content", [None, "[" * 2000])
def test_malformed_bounded_completions_have_actionable_errors(settings, content):
    settings.local_base_url = "http://localhost:8080/v1"
    settings.local_model_sha256 = test_teaching.SHA

    def respond(request):
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": model_alias(test_teaching.SHA)}]})
        return httpx.Response(
            200, json={"choices": [{"finish_reason": "stop", "message": {"content": content}}]}
        )

    adapter = LocalInference(settings, transport=httpx.MockTransport(respond))
    with pytest.raises(DomainError, match="LOCAL_JSON"):
        asyncio.run(
            adapter.advise(system=ADVICE_SYSTEM, context="{}", parameters=ADVICE_PARAMETERS)
        )


@pytest.mark.parametrize("ack", [False, "true", 1])
def test_base_export_acknowledgement_cannot_be_coerced(workshop, ack):
    client, project, *_ = workshop
    response = client.post(
        test_teaching.base(project) + "/exports/base",
        json={
            "test_id": str(uuid4()),
            "acknowledge_contents": ack,
        },
    )
    assert response.status_code == 422


def test_failed_test_cannot_be_exported_or_used_across_projects(workshop):
    client, project, inference, _, config = workshop
    fake_base(config)
    inference.error = "LOCAL_TOKEN_LIMIT: No complete advice."
    run = test_teaching.ask(workshop)
    payload = {"test_id": run["id"], "acknowledge_contents": True}
    response = client.post(test_teaching.base(project) + "/exports/base", json=payload)
    assert response.status_code == 409 and "EXPORT_TEST" in response.text
    other = client.post("/api/projects", json={"name": "Other", "mission": "Advise."}).json()["id"]
    assert client.post(test_teaching.base(other) + "/exports/base", json=payload).status_code == 404
