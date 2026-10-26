"""Normalize repeated accessible refs while retaining strict evidence and JSON boundaries."""

import asyncio
import json
from uuid import uuid4

import httpx2 as httpx
import pytest
from pydantic import ValidationError

from quartermaster import predictions, training
from quartermaster.contracts.prediction import Prediction
from quartermaster.inference import LocalInference
from tests.test_muster_integration import collection as collection
from tests.test_predictions import CATEGORY, NUMBER, selection, setup


@pytest.mark.parametrize("fmt", [NUMBER, CATEGORY])
@pytest.mark.parametrize("kind", ["same-excerpt", "unknown", "mixed", "oversized"])
@pytest.mark.parametrize("runtime", ["local", "worker"])
def test_reference_normalization_never_hides_missing_sources_or_changes_an_answer(
    settings, collection, fmt, kind, runtime, monkeypatch
):
    project, item, _ = setup(settings, collection, fmt)
    queued = predictions.prepare(settings, project, item.id, selection(settings, project, fmt))
    example = training.read_job(settings, queued).examples[0]
    reference = str(example.input.evidence[0].citation_id)
    unknown = str(uuid4())
    data = example.target.model_dump(mode="json")
    data["evidence_refs"] = {
        "same-excerpt": [reference, reference],
        "unknown": [unknown, unknown],
        "mixed": [reference, reference, unknown],
        "oversized": [reference] * 4,
    }[kind]
    # Direct public contract validation stays strict, including duplicate references.
    with pytest.raises(ValidationError):
        Prediction.model_validate(data)

    def serve(request):
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": "alias"}]})
        return httpx.Response(
            200,
            json={
                "model": "alias",
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(data)}}],
            },
        )

    adapter = LocalInference(
        settings,
        alias="alias",
        base_url="http://127.0.0.1:8080/v1",
        transport=httpx.MockTransport(serve),
    )
    if runtime == "worker":
        from quartermaster.training_worker import DockerInference

        adapter = DockerInference(None, None, "not-started", "alias")

        async def complete(system, context, parameters, schema):
            assert schema == example.input.response_schema
            return json.dumps(data)

        monkeypatch.setattr(adapter, "complete", complete)
    result = asyncio.run(predictions.generate(adapter, example.input))
    assert result.input_sha256 == example.input.input_sha256
    if kind == "same-excerpt":
        assert result.error is None
        assert result.prediction.target == example.target.target
        assert result.prediction.explanation == example.target.explanation
        assert [str(r) for r in result.prediction.evidence_refs] == [reference]
    else:
        assert result.error and result.prediction is None
