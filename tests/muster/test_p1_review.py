import asyncio

import pytest
from fastapi.testclient import TestClient

from muster.app import create_app
from muster.collector import Collector
from muster.extraction import Extractor, batch_details, prepare_batch, select_images
from muster.review import ReviewConflict, bulk_status, get_review, review_list
from muster.storage import connect
from tests.muster.test_app import token
from tests.muster.test_collector import FakeBrowser, seed
from tests.muster.test_review import ready


def test_bulk_actions_atomic_conflicts_and_duplicates(tmp_path):
    cid, provider = ready(tmp_path, 3)
    rows = review_list(tmp_path, cid, {})["rows"]
    selections = [(row["id"], row["review_revision"]) for row in rows]
    with connect(tmp_path) as db:
        db.execute("INSERT INTO publication_exclusions VALUES(1,'Old exclusion','2026-01-01')")
    bulk_status(tmp_path, cid, selections, "reviewed")
    with connect(tmp_path) as db:
        assert db.execute("SELECT count(*) FROM publication_exclusions").fetchone()[0] == 0
    assert review_list(tmp_path, cid, {})["counts"]["reviewed"] == 3
    with pytest.raises(ReviewConflict):
        bulk_status(tmp_path, cid, [(1, 1), (2, 0)], "excluded", "Duplicate")
    assert get_review(tmp_path, cid, 1)["status"] == "reviewed"
    with connect(tmp_path) as db:
        db.execute(
            "UPDATE captures SET final_url='https://example.com/same?utm_source=one' WHERE job_id=1"
        )
        db.execute(
            "UPDATE captures SET final_url='https://example.com/same?utm_source=two' WHERE job_id=2"
        )
    rows = review_list(tmp_path, cid, {})["rows"]
    assert (
        rows[0]["duplicate_ids"] == [2]
        and rows[1]["duplicate_ids"] == [1]
        and not rows[2]["duplicate_ids"]
    )
    with TestClient(create_app(tmp_path, provider)) as client:
        page = client.get(f"/collections/{cid}/review")
        assert "Possible duplicate" in page.text
        response = client.post(
            f"/collections/{cid}/review/bulk",
            data={
                "csrf": token(page),
                "selection": ["1:1", "2:1"],
                "action": "excluded",
                "reason": "Same destination",
            },
        )
        assert response.status_code == 200
    assert get_review(tmp_path, cid, 1)["status"] == "excluded"
    assert get_review(tmp_path, cid, 3)["status"] == "reviewed"


def test_image_selection_creates_separate_consent_preview(tmp_path):
    cid, provider = ready(tmp_path, 1)
    batch = prepare_batch(tmp_path, cid, provider, job_id=1)
    old = batch_details(tmp_path, batch)
    assert old["attempts"][0]["payload"]["images"]
    with TestClient(create_app(tmp_path, provider)) as client:
        page = client.get("/extraction-batches/" + batch)
        assert "Choose images for this example" in page.text
        page = client.post(
            "/extractions/" + old["attempts"][0]["id"] + "/images", data={"csrf": token(page)}
        )
        assert page.status_code == 200
        new_id = page.url.path.rsplit("/", 1)[1]
    new = batch_details(tmp_path, new_id)
    assert new_id != batch and not new["attempts"][0]["payload"]["images"]
    assert (
        batch_details(tmp_path, batch)["attempts"][0]["payload"]["images"]
        == old["attempts"][0]["payload"]["images"]
    )
    with pytest.raises(ValueError, match="four"):
        select_images(tmp_path, new["attempts"][0]["id"], ["../../secret"])

    async def run():
        worker = Extractor(tmp_path, provider)
        worker.start(new_id)
        await worker.task

    asyncio.run(run())
    with pytest.raises(ValueError, match="already sent"):
        select_images(tmp_path, new["attempts"][0]["id"], [])


def test_navigation_failure_retains_failed_evidence_and_collection_has_no_refresh(tmp_path):
    cid = seed(tmp_path, ["https://example.com/crash"])

    async def run():
        worker = Collector(tmp_path, FakeBrowser, delay=0)
        worker.start(cid)
        await worker.task

    asyncio.run(run())
    with connect(tmp_path) as db:
        capture = db.execute("SELECT * FROM captures").fetchone()
        assert capture["status"] == "failed"
        assert db.execute("SELECT status FROM jobs").fetchone()[0] == "failed"
    assert (tmp_path / "sources" / "1" / capture["id"] / "page.html").is_file()
    with TestClient(create_app(tmp_path)) as client:
        client.app.state.collector.collection_id = cid

        # Render active state without starting any navigation.
        class Task:
            def done(self):
                return False

            def cancel(self):
                pass

        worker = client.app.state.collector
        worker.task = Task()
        page = client.get(f"/collections/{cid}")
        worker.task = None
        assert 'http-equiv="refresh"' not in page.text
        assert 'data-live="collection-progress"' in page.text
        assert "/static/extraction.js" in page.text
