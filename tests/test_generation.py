"""Generation changes must replay old experiments instead of rewriting their budgets."""

import asyncio
import json
from types import SimpleNamespace

import httpx2 as httpx
import pytest
from pydantic import ValidationError

from quartermaster import evaluations, export_smoke, teaching, training_worker
from quartermaster.advice_context import (
    ADVICE_PROMPT_VERSION,
    encoded,
    render_context,
)
from quartermaster.contracts.advice import Case
from quartermaster.contracts.export import ExportManifest
from quartermaster.errors import DomainError
from quartermaster.export_package import (
    MANIFEST,
    PackageContext,
    content_hash,
    sha256,
    verify_package,
)
from quartermaster.generation import (
    ADVICE_PARAMETERS,
    LEGACY_PARAMETERS,
    PARAMETERS,
    checked_parameters,
)
from quartermaster.inference import LocalInference, model_alias
from quartermaster.standalone_runtime import create_runtime
from tests import test_export, test_teaching
from tests.test_evaluations import create, freeze, run_suite, save, suite_path

workshop = test_teaching.workshop
candidate = test_export.candidate


@pytest.mark.parametrize("profile", [LEGACY_PARAMETERS, PARAMETERS])
def test_local_wire_uses_exact_profile_and_does_not_retry(settings, profile):
    payloads = []

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": model_alias(test_teaching.SHA)}]})
        payloads.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"finish_reason": "length", "message": {"content": "PRIVATE"}}]},
        )

    settings.local_base_url = "http://localhost:8080/v1"
    settings.local_model_sha256 = test_teaching.SHA
    adapter = LocalInference(settings, transport=httpx.MockTransport(handler))
    with pytest.raises(DomainError, match="LOCAL_TOKEN_LIMIT") as exc:
        asyncio.run(adapter.advise(system="System", context="{}", parameters=profile))
    assert "PRIVATE" not in str(exc.value)
    assert len(payloads) == 1
    assert all(payloads[0][key] == value for key, value in profile.items())


@pytest.mark.parametrize(
    "changed",
    [
        {**PARAMETERS, "max_tokens": 4096},
        {**PARAMETERS, "seed": 18},
        {**PARAMETERS, "temperature": 0.5},
        {**PARAMETERS, "chat_template_kwargs": {"enable_thinking": True}},
        {**PARAMETERS, "extra": "ignored?"},
        {},
    ],
)
def test_unsupported_parameters_fail_before_transmitting_any_case(settings, changed):
    def must_not_send(request):
        pytest.fail("Unsupported parameters must not transmit a case")

    adapter = LocalInference(settings, transport=httpx.MockTransport(must_not_send))
    with pytest.raises(DomainError, match="LOCAL_PARAMETERS"):
        asyncio.run(adapter.advise(system="private", context="{}", parameters=changed))


def test_profiles_are_copied_and_new_tests_record_larger_budget(workshop):
    copied = checked_parameters()
    copied["chat_template_kwargs"]["enable_thinking"] = True
    assert PARAMETERS["chat_template_kwargs"] == {"enable_thinking": False}
    run = test_teaching.ask(workshop)
    assert run["parameters"] == ADVICE_PARAMETERS
    assert run["parameters"]["max_tokens"] == 2048
    assert workshop[2].parameters[-1] == ADVICE_PARAMETERS


def test_historical_suite_replays_512_and_keeps_frozen_hash(workshop, monkeypatch):
    with monkeypatch.context() as old:
        old.setattr(evaluations, "PARAMETERS", LEGACY_PARAMETERS)
        old.setattr(evaluations, "PROMPT_VERSION", "context/v1")
        assemble = teaching.assemble_snapshot
        old.setattr(
            teaching,
            "assemble_snapshot",
            lambda *args, **kwargs: assemble(*args, prompt_version="context/v1"),
        )
        suite = freeze(workshop, save(workshop, create(workshop)))
    assert suite["inputs"][0]["b"]["parameters"] == LEGACY_PARAMETERS
    inference = workshop[2]
    inference.parameters.clear()
    result = run_suite(workshop, suite)
    assert result["status"] == "completed"
    assert inference.parameters == [LEGACY_PARAMETERS, LEGACY_PARAMETERS]
    assert workshop[0].get(suite_path(workshop, suite)).json() == suite


def test_compact_prompt_keeps_exact_text_and_full_provenance_in_snapshots(workshop):
    from tests.test_foundation import select_knowledge, upload

    client, project, *_ = workshop
    source = upload(
        client,
        project,
        b"# Safety\nInspection and damage must be checked.\n",
        "guide.md",
        "knowledge",
    ).json()
    select_knowledge(client, project, [source["id"]])
    run = test_teaching.ask(workshop)
    lesson = test_teaching.send(
        workshop, test_teaching.prepare(workshop, test_teaching.correct(workshop, run))
    )
    test_teaching.review(workshop, lesson)
    current = test_teaching.ask(workshop)
    parsed = teaching.get_test(workshop[-1], project, current["id"])
    old = teaching.assemble_snapshot(
        workshop[-1],
        parsed.adviser,
        teaching.latest_lessons(workshop[-1], project),
        parsed.case,
        prompt_version="context/v1",
    )
    compact, legacy = json.loads(current["context"]), json.loads(old[1])
    assert current["prompt_version"] == ADVICE_PROMPT_VERSION
    assert old[1] == encoded(legacy)
    assert len(current["context"]) < len(old[1])
    for before, after in zip(
        legacy["retrieved_evidence"], compact["retrieved_evidence"], strict=True
    ):
        assert after == {"citation_id": before["citation_id"], "text": before["text"]}
    assert current["evidence"][0]["source_sha256"] == source["sha256"]
    assert current["evidence"][0]["excerpt_sha256"]
    assert compact["approved_lessons"] == [
        {"text": item["text"]} for item in legacy["approved_lessons"]
    ]
    assert current["lessons"][0]["id"] and current["lessons"][0]["revision"]
    for key in ("case", "mission", "decision_definition"):
        assert compact[key] == legacy[key]
    with pytest.raises(DomainError, match="CONTEXT_VERSION"):
        render_context(legacy, "context/unknown")


@pytest.mark.parametrize("profile", [LEGACY_PARAMETERS, PARAMETERS])
def test_candidate_docker_adapter_replays_same_profile_without_retry(profile):
    requests = []

    def command(args, timeout, body):
        requests.append(json.loads(body))
        return json.dumps(test_teaching.envelope(test_teaching.draft().model_dump_json()))

    engine = SimpleNamespace(command=command, settings=object())
    adapter = training_worker.DockerInference(engine, object(), "bounded-container", "alias")
    # This adapter test does not model job state; ordinary training tests cover cancellation.
    from unittest.mock import patch

    with patch.object(training_worker, "check_cancel"):
        asyncio.run(adapter.advise(system="System", context="{}", parameters=profile))
    assert len(requests) == 1
    assert all(requests[0][key] == value for key, value in profile.items())


def test_export_captures_budget_and_rejects_missing_or_unknown_v2_profile(workshop, candidate):
    manifest, _ = test_export.package(workshop, candidate)
    assert manifest.schema_version == "quartermaster.export/v2"
    assert manifest.inference_parameters == PARAMETERS
    assert "source_test_id" not in manifest.model_dump()
    assert "source_test_sha256" not in manifest.model_dump()
    document = manifest.model_dump()
    for value in (None, {**PARAMETERS, "max_tokens": 100000}, {}, ADVICE_PARAMETERS):
        with pytest.raises(ValidationError):
            ExportManifest.model_validate({**document, "inference_parameters": value})
    document.pop("inference_parameters")
    with pytest.raises(ValidationError):
        ExportManifest.model_validate(document)
    historical = ExportManifest.model_validate(
        {**document, "schema_version": "quartermaster.export/v1", "prompt_version": "context/v1"}
    )
    assert historical.inference_parameters == LEGACY_PARAMETERS
    with pytest.raises(ValidationError):
        ExportManifest.model_validate(
            {**historical.model_dump(), "inference_parameters": PARAMETERS}
        )


@pytest.mark.parametrize("legacy", [True, False])
def test_runtime_uses_manifest_budget_not_current_default(workshop, candidate, tmp_path, legacy):
    _, _, root = test_export.extracted(workshop, candidate, tmp_path)
    if legacy:
        manifest, config, material, reference = verify_package(root)
        context = PackageContext(config, material, prompt_version="context/v1")
        case = Case.model_validate(reference.case.model_dump())
        reference_path = root / "reference.json"
        reference_path.write_text(
            reference.model_copy(
                update={
                    "context_sha256": content_hash(context.assemble(case)[1]),
                }
            ).model_dump_json()
        )
        context.close()
        path = root / MANIFEST
        record = json.loads(path.read_bytes())
        record["schema_version"] = "quartermaster.export/v1"
        record["prompt_version"] = "context/v1"
        record.pop("inference_parameters")
        record["files"]["reference.json"] = {
            "sha256": sha256(reference_path),
            "size_bytes": reference_path.stat().st_size,
        }
        path.write_text(json.dumps(record))
    inference = test_teaching.FakeInference()
    from fastapi.testclient import TestClient

    with TestClient(create_runtime(root, inference=inference, launch_engine=False)) as client:
        response = client.post("/v1/advise", json={"situation": "Current inspection; no damage."})
        assert response.status_code == 200, response.text
    assert inference.parameters == [LEGACY_PARAMETERS if legacy else PARAMETERS]


@pytest.mark.parametrize(
    ("image_contract", "package_contract", "supported"),
    [
        ("quartermaster.export/v1", "quartermaster.export/v1", True),
        ("quartermaster.export/v2", "quartermaster.export/v1", True),
        ("quartermaster.export/v2", "quartermaster.export/v2", True),
        ("quartermaster.export/v1", "quartermaster.export/v2", False),
    ],
)
def test_runtime_image_contract_compatibility(
    monkeypatch, image_contract, package_contract, supported
):
    monkeypatch.setattr(
        export_smoke,
        "command",
        lambda args: json.dumps(
            [
                {
                    "Id": test_export.IMAGE,
                    "Config": {
                        "Labels": {
                            "org.opencontainers.image.revision": export_smoke.LLAMA_REVISION,
                            "io.quartermaster.export-contract": image_contract,
                        }
                    },
                }
            ]
        ),
    )
    if supported:
        export_smoke.verify_image(test_export.IMAGE, package_contract)
    else:
        with pytest.raises(DomainError, match="EXPORT_IMAGE"):
            export_smoke.verify_image(test_export.IMAGE, package_contract)
