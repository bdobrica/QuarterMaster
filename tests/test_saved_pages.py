"""Uploaded originals reuse the bundled collector's extraction and publication contract."""

import asyncio
import hashlib
import json

import pytest

from muster.extraction import Extractor, batch_details, prepare_batch
from muster.provider import ProviderSettings
from muster.review import get_review, save_review
from muster.saved_pages import save_page
from muster.schema import accept_schema, get_draft, save_draft
from muster.storage import connect as collect_db
from quartermaster import muster
from tests.muster.test_app import token

FIELDS = [{"key": "area", "label": "Floor area", "type": "number", "description": "Area as stated"}]
PAGE = b'<!doctype html><h1>Apartment</h1><p>Area 60</p><script>throw "must not execute"</script>'


class Provider:
    settings = ProviderSettings("https://provider.example/v1", "development-model", "test-key")

    async def extract(self, payload, images):
        assert not images
        assert "must not execute" not in payload["page"]["text"]
        return {
            "values": {"area": 60},
            "evidence": {"area": [{"source": "page", "quote": "Area 60"}]},
            "uncertainty": {
                "area": {"level": "stated", "note": "Source statement", "conflict": False}
            },
        }


def test_saved_page_to_checked_teaching_handoff(client, settings, project_fixture):
    pid = client.post("/api/projects", json=project_fixture).json()["id"]
    client.get(f"/projects/{pid}/collect")
    csrf = token(client.get("/collect/"))
    reply = client.post(
        "/collect/saved-pages",
        data={"csrf": csrf, "name": "Apartments"},
        files={"page": ("apartment.html", PAGE, "text/html")},
    )
    assert reply.status_code == 200, reply.text
    root = settings.muster_storage
    with collect_db(root) as db:
        capture = db.execute("SELECT * FROM captures").fetchone()
        cid = db.execute("SELECT id FROM collections").fetchone()[0]
    retained = root / "sources" / str(capture["job_id"]) / capture["id"] / "page.html"
    assert retained.read_bytes() == PAGE
    assert json.loads(capture["metadata"])["upload_sha256"] == hashlib.sha256(PAGE).hexdigest()
    assert muster.collection_owner(settings, cid) == pid
    # No screenshot is manufactured for an uploaded page.
    assert not retained.with_name("screenshot.png").exists()
    draft = get_draft(root, cid)
    draft = save_draft(root, cid, draft["revision"], FIELDS, "Keep source observations separate.")
    accept_schema(root, cid, draft["revision"])

    async def extract():
        provider = Provider()
        batch = prepare_batch(root, cid, provider)
        worker = Extractor(root, provider)
        worker.start(batch)
        await worker.task
        assert batch_details(root, batch)["status"] == "complete"

    asyncio.run(extract())
    assert client.post(f"/collect/collections/{cid}/teach", data={"csrf": csrf}).status_code == 409
    review = get_review(root, cid, capture["job_id"])
    # A correction is an owner observation, not fabricated extraction provenance.
    save_review(
        root,
        cid,
        capture["job_id"],
        review["revision"],
        {"area": 62},
        "Measured area",
        "review_next",
    )
    page = client.get(f"/collect/collections/{cid}/review/{capture['job_id']}")
    assert page.status_code == 200 and "Saved page text" in page.text
    from muster.knowledge import save_article
    from quartermaster.knowledge import current_knowledge

    save_article(root, cid, None, 0, "My policy", "I prefer quiet streets.")
    reply = client.post(f"/collect/collections/{cid}/teach", data={"csrf": csrf})
    assert reply.status_code == 200, reply.text
    assert current_knowledge(settings, pid).source_ids
    assert "62" in client.get(reply.url.path + "/examples/0").text
    imports = muster.imports(settings, pid)
    assert len(imports) == 1
    assert client.post(f"/collect/collections/{cid}/teach", data={"csrf": csrf}).status_code == 200
    assert len(muster.imports(settings, pid)) == 1
    with collect_db(root) as db:
        assert db.execute("SELECT count(*) FROM publications").fetchone()[0] == 1
    bundle = muster.imported_bundle(settings, imports[0])
    assert (bundle.root / bundle.examples[0]["source"]["path"] / "page.html").read_bytes() == PAGE
    assert bundle.examples[0]["values"]["area"] == 62
    assert bundle.examples[0]["evidence"]["area"][0]["quote"] == "Area 60"
    assert (
        client.get("/collect/captures/" + capture["id"] + "/files/page.html")
        .headers["content-disposition"]
        .startswith("attachment")
    )


@pytest.mark.parametrize(
    "filename,content,url",
    [
        ("source.svg", PAGE, ""),
        ("source.html", b"", ""),
        ("source.html", b"<script>only scripts</script>", ""),
        ("source.html", PAGE, "javascript:alert(1)"),
        ("source.html", PAGE, "https://user:secret@example.com/"),
    ],
)
def test_saved_page_rejects_bad_input_without_records(client, settings, filename, content, url):
    with pytest.raises(ValueError):
        save_page(settings.muster_storage, "Test", filename, content, url)
    with collect_db(settings.muster_storage) as db:
        assert db.execute("SELECT count(*) FROM captures").fetchone()[0] == 0


def test_identical_upload_is_idempotent_but_different_bytes_need_new_collection(client, settings):
    root = settings.muster_storage
    cid = save_page(root, "Test", "one.html", PAGE, "https://example.com/apartment")
    assert save_page(root, "Test", "one.html", PAGE, "https://example.com/apartment", cid) == cid
    with pytest.raises(ValueError, match="different saved page"):
        save_page(
            root, "Test", "one.html", PAGE + b"<p>changed</p>", "https://example.com/apartment", cid
        )
    with collect_db(root) as db:
        assert db.execute("SELECT count(*) FROM captures").fetchone()[0] == 1
