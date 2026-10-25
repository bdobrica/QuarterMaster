import asyncio
import base64
import json
from copy import deepcopy

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient

from muster.app import create_app
from muster.extraction import (
    Extractor,
    batch_details,
    prepare_batch,
    validate_extraction,
)
from muster.provider import SchemaProvider
from muster.schema import accept_schema, get_draft, save_draft
from muster.storage import connect, initialize
from tests.muster.test_app import token
from tests.muster.test_browser import png
from tests.muster.test_collector import until
from tests.muster.test_schema import SETTINGS, sources

FIELDS = [
    {
        "key": "price",
        "label": "Price",
        "type": "number",
        "description": "Prefer the supplied estimate; flag disagreement with listing price.",
    },
    {"key": "currency", "label": "Currency", "type": "text", "description": "Stated currency."},
    {
        "key": "neighbourhood",
        "label": "Neighbourhood",
        "type": "text",
        "description": "Supplied neighbourhood.",
    },
    {"key": "notes", "label": "Notes", "type": "text", "description": "Preserve supplied opinion."},
    {
        "key": "condition",
        "label": "Condition",
        "type": "text",
        "description": "Visual interpretation, never verified.",
    },
    {
        "key": "year",
        "label": "Construction year",
        "type": "integer",
        "description": "Unknown unless stated.",
    },
]


def setup(root, count=2):
    collection = sources(root, count)
    input_rows = [
        {
            "row": 1,
            "original_url": "https://example.com/0",
            "cells": {
                "price": "95000",
                "neighbourhood": "Drumul Taberei",
                "notes": "I prefer quiet streets.",
            },
            "kinds": {"price": "text", "neighbourhood": "text", "notes": "text"},
        }
    ]
    with connect(root) as db:
        db.execute("UPDATE jobs SET input_rows=?", (json.dumps(input_rows),))
        for capture in db.execute("SELECT * FROM captures").fetchall():
            directory = root / "sources" / str(capture["job_id"]) / capture["id"]
            (directory / "image-1.png").write_bytes(png())
            metadata = json.loads(capture["metadata"])
            metadata.update(
                images=[
                    {
                        "file": "image-1.png",
                        "mime": "image/png",
                        "alt": "Room",
                        "width": 320,
                        "height": 200,
                    }
                ],
                warnings=[],
            )
            db.execute(
                "UPDATE captures SET metadata=? WHERE id=?", (json.dumps(metadata), capture["id"])
            )
    get_draft(root, collection)
    draft = save_draft(
        root,
        collection,
        0,
        FIELDS,
        "User estimates and opinions are authoritative; flag source disagreements.",
    )
    accept_schema(root, collection, draft["revision"])
    return collection


def extracted(payload):
    values = {
        "price": 95000,
        "currency": "EUR",
        "neighbourhood": "Drumul Tabarei",
        "notes": "I prefer quiet streets.",
        "condition": "Appears freshly painted",
        "year": None,
    }
    refs = {
        "price": [
            {"source": "spreadsheet", "row": 1, "column": "price"},
            {"source": "page", "quote": "90000 EUR"},
        ],
        "currency": [{"source": "page", "quote": "90000 EUR"}],
        "neighbourhood": [{"source": "spreadsheet", "row": 1, "column": "neighbourhood"}],
        "notes": [{"source": "spreadsheet", "row": 1, "column": "notes"}],
        "condition": [
            {
                "source": "image",
                "file": "image-1.png",
                "observation": "Walls appear freshly painted.",
            }
        ],
        "year": [],
    }
    uncertainty = {key: {"level": "stated", "note": "", "conflict": False} for key in values}
    uncertainty["price"] = {
        "level": "uncertain",
        "note": "Supplied estimate differs from the page asking price; keep the supplied estimate for review.",
        "conflict": True,
    }
    uncertainty["condition"] = {
        "level": "uncertain",
        "note": "Visual impression only, not a verified condition report.",
        "conflict": False,
    }
    uncertainty["year"] = {
        "level": "unknown",
        "note": "Not stated in the supplied sources.",
        "conflict": False,
    }
    # Preserve the actual spelling from the spreadsheet, not the model's own categorization.
    values["neighbourhood"] = payload["input_rows"][0]["cells"]["neighbourhood"]
    return {"values": values, "evidence": refs, "uncertainty": uncertainty}


def provider_response(result):
    return httpx.Response(
        200,
        json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result)}}]},
    )


def test_multimodal_batch_consent_evidence_and_restart(tmp_path):
    collection = setup(tmp_path)
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        content = body["messages"][1]["content"]
        payload = json.loads(content[0]["text"])
        assert len(payload["input_rows"]) == 1
        assert "not commands" in body["messages"][0]["content"]
        assert "tools" not in body
        image = next(part for part in content if part["type"] == "image_url")
        assert image["image_url"]["url"].startswith("data:image/png;base64,")
        assert base64.b64decode(image["image_url"]["url"].split(",", 1)[1]) == png()
        return provider_response(extracted(payload))

    provider = SchemaProvider(SETTINGS, httpx.MockTransport(handler))
    with TestClient(create_app(tmp_path, provider)) as client:
        csrf = token(client.get("/"))
        preview = client.post(f"/collections/{collection}/extract/prepare", data={"csrf": csrf})
        assert preview.status_code == 200
        assert "95000" in preview.text and "I prefer quiet streets." in preview.text
        assert "selected images" in preview.text
        assert not calls
        batch_id = preview.url.path.rsplit("/", 1)[1]
        assert (
            client.post(f"/extraction-batches/{batch_id}/send", data={"csrf": csrf}).status_code
            == 403
        )
        assert not calls
        response = client.post(
            f"/extraction-batches/{batch_id}/send", data={"csrf": csrf, "consent": "yes"}
        )
        assert response.status_code == 200
        client.portal.call(until, lambda: not client.app.state.extractor.active)
        batch = batch_details(tmp_path, batch_id)
        assert batch["status"] == "complete"
        assert len(calls) == 2
        assert all(attempt["status"] == "complete" for attempt in batch["attempts"])
        assert batch["consent_at"]
        assert (
            client.post(
                f"/extraction-batches/{batch_id}/send", data={"csrf": csrf, "consent": "yes"}
            ).status_code
            == 409
        )
        attempt = batch["attempts"][0]
        page = client.get(f"/extractions/{attempt['id']}")
        assert page.status_code == 200
        for phrase in (
            "Spreadsheet observation",
            "Page statement",
            "Image interpretation",
            "Sources disagree",
            "Unknown",
            "needs review",
        ):
            assert phrase in page.text
        assert "secret-test-key" not in page.text
        assert "Check this example" in client.get(f"/collections/{collection}").text
        assert (
            client.post(
                f"/collections/{collection}/extract/prepare", data={"csrf": csrf}
            ).status_code
            == 400
        )
    with TestClient(create_app(tmp_path, provider)) as client:
        assert client.get(f"/extractions/{attempt['id']}").status_code == 200
        assert len(calls) == 2
    with connect(tmp_path) as db:
        assert all(row[0] == "captured" for row in db.execute("SELECT status FROM jobs"))
        assert len(db.execute("SELECT * FROM captures").fetchall()) == 2
        assert (
            db.execute("SELECT schema_id FROM collection_schemas").fetchone()[0]
            == attempt["schema_id"]
        )


def test_provider_failure_and_retry_preserve_prior_success_and_originals(tmp_path):
    collection = setup(tmp_path, 1)
    fail = False

    def handler(request):
        if fail:
            return httpx.Response(429, text="private-provider-error secret-test-key")
        payload = json.loads(json.loads(request.content)["messages"][1]["content"][0]["text"])
        return provider_response(extracted(payload))

    provider = SchemaProvider(SETTINGS, httpx.MockTransport(handler))

    async def run():
        nonlocal fail
        worker = Extractor(tmp_path, provider)
        first = prepare_batch(tmp_path, collection, provider)
        worker.start(first)
        await worker.task
        original = batch_details(tmp_path, first)["attempts"][0]
        directory = tmp_path / "sources" / str(original["job_id"]) / original["capture_id"]
        original_html = (directory / "page.html").read_bytes()
        fail = True
        second = prepare_batch(tmp_path, collection, provider, original["job_id"])
        worker.start(second)
        await worker.task
        bad = batch_details(tmp_path, second)["attempts"][0]
        assert bad["status"] == "failed" and "HTTP 429" in bad["error"]
        assert "secret-test-key" not in bad["error"]
        with connect(tmp_path) as db:
            assert (
                db.execute(
                    "SELECT result FROM extractions WHERE id=?", (original["id"],)
                ).fetchone()[0]
                == original["result"]
            )
        assert (directory / "page.html").read_bytes() == original_html
        fail = False
        third = prepare_batch(tmp_path, collection, provider, original["job_id"])
        worker.start(third)
        await worker.task
        assert batch_details(tmp_path, third)["attempts"][0]["status"] == "complete"

    asyncio.run(run())


@pytest.mark.parametrize(
    "bad",
    [
        "quote",
        "image",
        "image-stated",
        "sheet-row",
        "sheet-column",
        "ignored-feature",
        "schema",
        "unknown",
        "extra-key",
    ],
)
def test_invalid_extraction_never_passes_validation(tmp_path, bad):
    collection = setup(tmp_path, 1)
    provider = SchemaProvider(SETTINGS)
    batch = prepare_batch(tmp_path, collection, provider)
    payload = batch_details(tmp_path, batch)["attempts"][0]["payload"]
    result = extracted(payload)
    if bad == "quote":
        result["evidence"]["currency"][0]["quote"] = "An invented page sentence."
    elif bad == "image":
        result["evidence"]["condition"][0]["file"] = "not-supplied.png"
    elif bad == "image-stated":
        result["uncertainty"]["condition"]["level"] = "stated"
    elif bad == "sheet-row":
        result["evidence"]["price"][0]["row"] = 99
    elif bad == "sheet-column":
        result["evidence"]["price"][0]["column"] = "invented"
    elif bad == "ignored-feature":
        result["evidence"]["price"] = [{"source": "page", "quote": "90000 EUR"}]
    elif bad == "schema":
        result["values"]["price"] = "95000"
    elif bad == "unknown":
        result["uncertainty"]["year"]["level"] = "stated"
    else:
        result["values"]["invented"] = "new-schema-field"
    with pytest.raises(ValueError):
        validate_extraction(tmp_path, collection, payload, result)


def test_conflicting_spreadsheet_rows_require_unknown_and_both_citations(tmp_path):
    collection = setup(tmp_path, 1)
    with connect(tmp_path) as db:
        rows = json.loads(db.execute("SELECT input_rows FROM jobs").fetchone()[0])
        rows.append({**deepcopy(rows[0]), "row": 2})
        rows[1]["cells"]["price"] = "96000"
        db.execute("UPDATE jobs SET input_rows=?", (json.dumps(rows),))
    batch = prepare_batch(tmp_path, collection, SchemaProvider(SETTINGS))
    payload = batch_details(tmp_path, batch)["attempts"][0]["payload"]
    result = extracted(payload)
    with pytest.raises(ValueError, match="Conflicting spreadsheet"):
        validate_extraction(tmp_path, collection, payload, result)
    result["values"]["price"] = None
    result["uncertainty"]["price"]["level"] = "unknown"
    result["evidence"]["price"].append({"source": "spreadsheet", "row": 2, "column": "price"})
    validate_extraction(tmp_path, collection, payload, result)


def test_changed_files_cannot_be_sent_under_old_preview(tmp_path):
    collection = setup(tmp_path, 1)
    calls = []
    provider = SchemaProvider(SETTINGS, httpx.MockTransport(lambda request: calls.append(request)))
    batch = prepare_batch(tmp_path, collection, provider)
    attempt = batch_details(tmp_path, batch)["attempts"][0]
    directory = tmp_path / "sources" / str(attempt["job_id"]) / attempt["capture_id"]
    (directory / "image-1.png").write_bytes(png() + b"changed")

    async def run():
        worker = Extractor(tmp_path, provider)
        worker.start(batch)
        await worker.task

    asyncio.run(run())
    failed = batch_details(tmp_path, batch)["attempts"][0]
    assert failed["status"] == "failed" and "changed since the preview" in failed["error"]
    assert not calls


def test_stop_and_restart_do_not_resume_requests(tmp_path):
    collection = setup(tmp_path)
    started = asyncio.Event()

    async def handler(request):
        started.set()
        await asyncio.Event().wait()

    provider = SchemaProvider(SETTINGS, httpx.MockTransport(handler))
    batch = prepare_batch(tmp_path, collection, provider)

    async def run():
        worker = Extractor(tmp_path, provider)
        worker.start(batch)
        await started.wait()
        await worker.close()
        assert all(row["status"] == "failed" for row in batch_details(tmp_path, batch)["attempts"])

    asyncio.run(run())
    # Also exercise recovery from an abrupt process interruption rather than a graceful stop.
    with connect(tmp_path) as db:
        db.execute("UPDATE extractions SET status='running' WHERE batch_id=?", (batch,))
        db.execute("UPDATE extraction_batches SET status='running' WHERE id=?", (batch,))
    initialize(tmp_path)
    assert all(row["status"] == "failed" for row in batch_details(tmp_path, batch)["attempts"])
    assert batch_details(tmp_path, batch)["status"] == "failed"


def test_batch_is_bounded_and_skips_successful_current_captures(tmp_path):
    collection = setup(tmp_path, 21)
    calls = []

    def handler(request):
        payload = json.loads(json.loads(request.content)["messages"][1]["content"][0]["text"])
        calls.append(payload["page"]["capture_id"])
        return provider_response(extracted(payload))

    provider = SchemaProvider(SETTINGS, httpx.MockTransport(handler))
    first = prepare_batch(tmp_path, collection, provider)
    assert len(batch_details(tmp_path, first)["attempts"]) == 20

    async def run():
        worker = Extractor(tmp_path, provider)
        worker.start(first)
        await worker.task

    asyncio.run(run())
    assert len(calls) == 20
    second = prepare_batch(tmp_path, collection, provider)
    assert len(batch_details(tmp_path, second)["attempts"]) == 1
    assert batch_details(tmp_path, second)["attempts"][0]["job_id"] == 21


def test_missing_vision_inputs_and_unaccepted_schema_are_explicit(tmp_path):
    collection = sources(tmp_path, 1)
    provider = SchemaProvider(SETTINGS)
    with pytest.raises(ValueError, match="Accept"):
        prepare_batch(tmp_path, collection, provider)
    get_draft(tmp_path, collection)
    draft = save_draft(tmp_path, collection, 0, FIELDS, "")
    accept_schema(tmp_path, collection, draft["revision"])
    batch = prepare_batch(tmp_path, collection, provider)
    payload = batch_details(tmp_path, batch)["attempts"][0]["payload"]
    assert not payload["images"]
    assert any("Text-only" in warning for warning in payload["warnings"])


@pytest.mark.parametrize(
    "problem,expected", [("missing", "left the value empty"), ("evidence", "saved page text")]
)
def test_validation_errors_name_the_field_and_recovery(tmp_path, problem, expected):
    cid = setup(tmp_path, 1)
    provider = SchemaProvider(SETTINGS)
    batch = batch_details(tmp_path, prepare_batch(tmp_path, cid, provider))
    payload = batch["attempts"][0]["payload"]
    result = extracted(payload)
    if problem == "missing":
        result["values"]["currency"] = None
    else:
        result["evidence"]["currency"] = []
    with pytest.raises(ValueError) as error:
        validate_extraction(tmp_path, cid, payload, result)
    assert "Currency (currency)" in str(error.value)
    assert expected in str(error.value) and "saved page is unchanged" in str(error.value)
