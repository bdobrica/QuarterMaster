import asyncio
import json
import re

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient

from muster import knowledge as kb
from muster import publication as pub
from muster.app import create_app
from muster.extraction import Extractor, batch_details, prepare_batch
from muster.provider import SchemaProvider
from muster.review import get_review, review_list, save_review
from muster.storage import connect, initialize
from tests.muster.test_app import token
from tests.muster.test_browser import png
from tests.muster.test_extraction import extracted, provider_response, setup
from tests.muster.test_publication import reviewed, tree
from tests.muster.test_schema import SETTINGS


@pytest.mark.parametrize("response_available", [True, False])
def test_manual_recovery_keeps_partial_values_without_ai_and_can_publish(
    tmp_path, response_available
):
    cid = setup(tmp_path, 1)
    calls = []

    def handler(request):
        calls.append(request)
        payload = json.loads(json.loads(request.content)["messages"][1]["content"][0]["text"])
        result = extracted(payload)
        result["values"]["price"] = "invalid number"
        result["uncertainty"]["year"]["level"] = "stated"
        return provider_response(result)

    provider = SchemaProvider(SETTINGS, httpx.MockTransport(handler))
    bid = prepare_batch(tmp_path, cid, provider)

    async def run():
        worker = Extractor(tmp_path, provider)
        worker.start(bid)
        await worker.task

    asyncio.run(run())
    attempt = batch_details(tmp_path, bid)["attempts"][0]
    assert (
        attempt["status"] == "failed"
        and json.loads(attempt["result"])["values"]["currency"] == "EUR"
    )
    if not response_available:
        with connect(tmp_path) as db:
            db.execute("UPDATE extractions SET result=NULL WHERE id=?", (attempt["id"],))
    with TestClient(create_app(tmp_path, provider)) as client:
        page = client.get(f"/extraction-batches/{bid}")
        csrf = token(page)
        url = f"/extractions/{attempt['id']}/edit-manually"
        assert client.post(url).status_code == 403
        response = client.post(url, data={"csrf": csrf})
        assert (
            response.status_code == 200 and "Recovered from a failed AI extraction" in response.text
        )
        r = get_review(tmp_path, cid, 1)
        assert r["values"]["price"] is None
        assert r["values"]["currency"] == ("EUR" if response_available else None)
        assert len(calls) == 1
        assert all(not refs for refs in r["result"]["evidence"].values())
        values = r["values"] | {"price": 88000}
        save_review(tmp_path, cid, 1, r["revision"], values, "Manually completed", "review_next")
        client.post(url, data={"csrf": csrf})  # Double submit must not overwrite human edits.
        assert get_review(tmp_path, cid, 1)["values"]["price"] == 88000
        assert len(calls) == 1
    with connect(tmp_path) as db:
        original = db.execute("SELECT * FROM extractions WHERE id=?", (attempt["id"],)).fetchone()
        assert original["status"] == "failed"
        capture = db.execute("SELECT * FROM captures").fetchone()
    (tmp_path / "sources" / "1" / capture["id"] / "screenshot.png").write_bytes(png())
    pid = pub.publish(tmp_path, cid, pub.overview(tmp_path, cid)["fingerprint"])
    bundle = pub.get_publication(tmp_path, cid, pid)
    assert bundle["manifest"]["counts"]["examples"] == 1
    result_path = tmp_path / bundle["path"] / "provenance/examples/1.json"
    assert (
        json.loads(result_path.read_text())["input"]["manual_recovery"]["attempt_id"]
        == attempt["id"]
    )


def test_add_remove_restore_preserves_sources_schema_and_versions(tmp_path):
    cid = reviewed(tmp_path, 2)
    before_schema = None
    pid = pub.publish(tmp_path, cid, pub.overview(tmp_path, cid)["fingerprint"])
    folder = tmp_path / pub.get_publication(tmp_path, cid, pid)["path"]
    before = tree(folder)
    with TestClient(create_app(tmp_path)) as client:
        home = client.get(f"/collections/{cid}")
        csrf = token(home)
        with connect(tmp_path) as db:
            before_schema = dict(db.execute("SELECT * FROM collection_schemas").fetchone())
            original_captures = db.execute("SELECT count(*) FROM captures").fetchone()[0]
        response = client.post(
            "/imports/preview",
            data={
                "csrf": csrf,
                "collection_id": cid,
                "links": "https://example.com/0\nhttps://example.com/new",
            },
        )
        assert "1 links to add" in response.text
        action = re.search(r'action="(/imports/[^\"]+/confirm)"', response.text)[1]
        response = client.post(action, data={"csrf": csrf})
        assert response.url.path == f"/collections/{cid}"
        remove = f"/collections/{cid}/jobs/1/remove"
        assert client.post(remove).status_code == 403
        assert client.post("/collections/999/jobs/1/remove", data={"csrf": csrf}).status_code == 404
        assert client.post(remove, data={"csrf": csrf}).status_code == 200
        assert 1 not in [r["id"] for r in review_list(tmp_path, cid, {})["rows"]]
        state = pub.overview(tmp_path, cid)
        assert 1 not in [r["id"] for r in state["jobs"]]
        with connect(tmp_path) as db:
            assert db.execute("SELECT count(*) FROM captures").fetchone()[0] == original_captures
            assert dict(db.execute("SELECT * FROM collection_schemas").fetchone()) == before_schema
            assert db.execute("SELECT count(*) FROM collections").fetchone()[0] == 1
            assert db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 3
            db.execute("UPDATE extraction_batches SET status='running'")
        assert (
            client.post(f"/collections/{cid}/jobs/1/restore", data={"csrf": csrf}).status_code
            == 409
        )
        with connect(tmp_path) as db:
            db.execute("UPDATE extraction_batches SET status='complete'")
        assert (
            client.post(f"/collections/{cid}/jobs/1/restore", data={"csrf": csrf}).status_code
            == 200
        )
        assert get_review(tmp_path, cid, 1)["status"] == "reviewed"
        assert tree(folder) == before


def test_windows_knowledge_line_endings_publish_without_ignoring_real_edits(tmp_path):
    cid = reviewed(tmp_path, 1)
    aid = kb.save_article(
        tmp_path, cid, None, 0, "My criteria", "# My criteria\n\nMy choices matter.\n"
    )
    article = kb.article(tmp_path, cid, aid)
    path = tmp_path / article["path"]
    assert b"\r\n" not in path.read_bytes()
    path.write_bytes(article["body"].replace("\n", "\r\n").encode())
    pid = pub.publish(tmp_path, cid, pub.overview(tmp_path, cid)["fingerprint"])
    published = pub.get_publication(tmp_path, cid, pid)
    saved = tmp_path / published["path"] / f"knowledge/{aid}.md"
    assert saved.read_bytes() == article["body"].encode()
    path.write_bytes(b"A real change")
    with pytest.raises(ValueError, match="knowledge revision"):
        pub.publish(tmp_path, cid, pub.overview(tmp_path, cid)["fingerprint"])
    path.unlink()
    with pytest.raises(ValueError, match="knowledge revision"):
        pub.publish(tmp_path, cid, pub.overview(tmp_path, cid)["fingerprint"])


def test_upgrade_existing_v8_collection_retains_schema_reviews_and_knowledge(tmp_path):
    cid = reviewed(tmp_path, 1)
    kb.save_article(tmp_path, cid, None, 0, "My rule", "My original guidance.")
    with connect(tmp_path) as db:
        original = dict(db.execute("SELECT * FROM collection_schemas").fetchone())
        db.execute("ALTER TABLE jobs DROP COLUMN removed")
        db.execute("ALTER TABLE import_previews DROP COLUMN collection_id")
        db.execute("DROP TABLE rebuild_observations")
        db.execute("DROP TABLE connector_calls")
        db.execute("DROP TABLE connector_permissions")
        db.execute("PRAGMA user_version=8")
    initialize(tmp_path)
    with connect(tmp_path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 11
        assert dict(db.execute("SELECT * FROM collection_schemas").fetchone()) == original
        assert db.execute("SELECT removed FROM jobs").fetchone()[0] == 0
    assert get_review(tmp_path, cid, 1)["status"] == "reviewed"
    assert kb.articles(tmp_path, cid)[0]["body"] == "My original guidance."
