import asyncio
import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from muster.app import create_app
from muster.extraction import Extractor, batch_details, prepare_batch
from muster.knowledge import articles, save_article
from muster.publication import get_publication, overview, publish
from muster.rebuild import rebuild
from muster.review import get_review, review_list, save_review
from muster.schema import accept_schema, get_draft, save_draft
from muster.storage import connect, initialize
from tests.muster.test_app import token
from tests.muster.test_review import ready


def test_rebuild_reextracts_without_revisiting_and_preserves_annotations(tmp_path):
    cid, provider = ready(tmp_path, 2)
    from tests.muster.test_browser import png

    with connect(tmp_path) as db:
        captures = db.execute("SELECT * FROM captures").fetchall()
    for c in captures:
        (tmp_path / "sources" / str(c["job_id"]) / c["id"] / "screenshot.png").write_bytes(png())
    original = get_review(tmp_path, cid, 1)
    save_review(
        tmp_path,
        cid,
        1,
        original["revision"],
        original["values"] | {"price": 777},
        "My subjective observation.",
        "review_next",
    )
    save_article(tmp_path, cid, None, 0, "My rule", "Prefer the user’s judgment.")
    pub = publish(tmp_path, cid, overview(tmp_path, cid)["fingerprint"])
    folder = tmp_path / get_publication(tmp_path, cid, pub)["path"]
    hashes = {
        str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in folder.rglob("*")
        if p.is_file()
    }
    with TestClient(create_app(tmp_path, provider)) as client:
        page = client.get(f"/collections/{cid}/rebuild")
        response = client.post(
            f"/collections/{cid}/rebuild",
            data={"csrf": token(page), "name": "Changed fields"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        new_cid = int(response.headers["location"].split("/")[2])
        assert "Choose what to collect" in client.get(response.headers["location"]).text
    draft = get_draft(tmp_path, new_cid)
    assert not draft["accepted_at"]
    # Add a field without modifying the original contract.
    fields = draft["fields"] + [
        {"key": "extra", "label": "Extra", "type": "text", "description": "New observation."}
    ]
    draft = save_draft(tmp_path, new_cid, draft["revision"], fields, draft["guidance"])
    accept_schema(tmp_path, new_cid, draft["revision"])
    import httpx2 as httpx

    from muster.provider import SchemaProvider
    from tests.muster.test_extraction import extracted, provider_response
    from tests.muster.test_schema import SETTINGS

    def handler(request):
        payload = json.loads(json.loads(request.content)["messages"][1]["content"][0]["text"])
        result = extracted(payload)
        result["values"]["extra"] = None
        result["evidence"]["extra"] = []
        result["uncertainty"]["extra"] = {
            "level": "unknown",
            "note": "Not stated.",
            "conflict": False,
        }
        return provider_response(result)

    provider = SchemaProvider(SETTINGS, httpx.MockTransport(handler))
    batch = prepare_batch(tmp_path, new_cid, provider)
    preview = batch_details(tmp_path, batch)
    assert len(preview["attempts"]) == 2
    assert (
        preview["attempts"][0]["payload"]["prior_observations"]["review"]["notes"]
        == "My subjective observation."
    )

    async def run():
        worker = Extractor(tmp_path, provider)
        worker.start(batch)
        await worker.task

    asyncio.run(run())
    rows = review_list(tmp_path, new_cid, {})["rows"]
    new = get_review(tmp_path, new_cid, rows[0]["id"])
    assert new["values"]["price"] == 777 and new["values"]["extra"] is None
    assert new["notes"] == "My subjective observation." and new["status"] == "needs_review"
    assert new["corrections"]["price"]["restored_from_job"] == 1
    assert articles(tmp_path, new_cid)[0]["body"] == "Prefer the user’s judgment."
    assert get_review(tmp_path, cid, 1)["status"] == "reviewed"
    assert get_draft(tmp_path, cid)["schema_id"] == original["schema_id"]
    assert hashes == {
        str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in folder.rglob("*")
        if p.is_file()
    }
    publish(tmp_path, new_cid, overview(tmp_path, new_cid)["fingerprint"])
    initialize(tmp_path)
    assert get_review(tmp_path, new_cid, rows[0]["id"])["notes"] == "My subjective observation."


def test_rebuild_missing_source_rolls_back_and_active_work_refused(tmp_path):
    cid, provider = ready(tmp_path, 2)
    with connect(tmp_path) as db:
        db.execute("UPDATE jobs SET status='collecting' WHERE id=1")
    with pytest.raises(ValueError, match="Stop"):
        rebuild(tmp_path, cid, "New draft")
    with connect(tmp_path) as db:
        db.execute("UPDATE jobs SET status='captured' WHERE id=1")
        cap = db.execute("SELECT * FROM captures WHERE job_id=2").fetchone()
    import shutil

    shutil.rmtree(tmp_path / "sources" / "2" / cap["id"])
    with pytest.raises(ValueError, match="missing"):
        rebuild(tmp_path, cid, "New draft")
    with connect(tmp_path) as db:
        assert db.execute("SELECT count(*) FROM collections").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 2
    assert not (tmp_path / "sources" / "3").exists()


def test_rebuild_failed_extraction_manual_recovery_keeps_human_work(tmp_path):
    from muster.extraction import recover_manually

    cid, provider = ready(tmp_path, 1)
    original = get_review(tmp_path, cid, 1)
    save_review(
        tmp_path,
        cid,
        1,
        original["revision"],
        original["values"] | {"price": 777},
        "Keep my experience.",
        "review_next",
    )
    new_cid = rebuild(tmp_path, cid, "Recovered rebuild")
    draft = get_draft(tmp_path, new_cid)
    accept_schema(tmp_path, new_cid, draft["revision"])
    batch = prepare_batch(tmp_path, new_cid, provider)
    with connect(tmp_path) as db:
        db.execute(
            "UPDATE extractions SET status='failed',result=?,error='Missing evidence' WHERE batch_id=?",
            (json.dumps({"values": {"price": 42}}), batch),
        )
        attempt = db.execute("SELECT id FROM extractions WHERE batch_id=?", (batch,)).fetchone()[
            "id"
        ]
    cid, jid = recover_manually(tmp_path, attempt)
    review = get_review(tmp_path, cid, jid)
    assert review["values"]["price"] == 777
    assert review["notes"] == "Keep my experience." and review["status"] == "needs_review"
    assert review["result"]["values"]["price"] == 42
