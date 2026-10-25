import io
import re

from fastapi.testclient import TestClient
from openpyxl import Workbook

from muster.app import create_app
from muster.imports import parse_import
from muster.storage import connect


def token(response):
    return re.search(r'name="csrf" value="([^"]+)"', response.text)[1]


def test_import_restart_and_retry(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        csrf = token(client.get("/"))
        csv = "url,title\n" + "".join(f"https://example.com/{i},Page\n" for i in range(20))
        csv += "https://EXAMPLE.com/0#photo,Duplicate\ninvalid,Bad\n"
        response = client.post(
            "/imports/preview",
            data={"csrf": csrf, "name": "First collection"},
            files={"spreadsheet": ("links.csv", csv)},
        )
        assert response.status_code == 200
        assert "20 links to add" in response.text
        assert "1 repeated links combined" in response.text
        assert "1 invalid rows skipped" in response.text
        action = re.search(r'action="(/imports/[^\"]+/confirm)"', response.text)[1]
        response = client.post(action, data={"csrf": csrf})
        assert response.status_code == 200
        assert response.text.count("Waiting to collect") == 20
        assert client.post(action, data={"csrf": csrf}).status_code == 404
    with connect(tmp_path) as db:
        db.execute("UPDATE jobs SET status='collecting', attempts=1 WHERE id=1")
    with TestClient(create_app(tmp_path)) as client:
        response = client.get("/collections/1")
        assert "First collection" in response.text
        assert "Collection was interrupted" in response.text
        csrf = token(response)
        response = client.post("/collections/1/jobs/1/retry", data={"csrf": csrf})
        assert "Collection was interrupted" not in response.text
        assert response.text.count("Waiting to collect") == 20
        assert client.post("/collections/1/jobs/1/retry", data={"csrf": csrf}).status_code == 409
    with connect(tmp_path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 11
        assert db.execute("SELECT count(*) FROM collections").fetchone()[0] == 1
        assert db.execute("SELECT attempts FROM jobs WHERE id=1").fetchone()[0] == 1


def test_invalid_file_and_local_write_protection(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        csrf = token(client.get("/"))
        for filename, content in [("bad.csv", "title\nMissing URL"), ("bad.xlsx", "broken")]:
            response = client.post(
                "/imports/preview", data={"csrf": csrf}, files={"spreadsheet": (filename, content)}
            )
            assert "Check your import" in response.text
        assert (
            client.post("/imports/preview", data={"links": "https://example.com"}).status_code
            == 403
        )
        assert (
            client.post(
                "/imports/preview", data={"csrf": csrf}, headers={"sec-fetch-site": "cross-site"}
            ).status_code
            == 403
        )
        assert client.get("/", headers={"host": "evil.example"}).status_code == 400
        assert client.get("/collections/999").status_code == 404
    with connect(tmp_path) as db:
        assert db.execute("SELECT count(*) FROM collections").fetchone()[0] == 0


def test_xlsx_paste_and_url_validation():
    workbook = Workbook()
    workbook.active.append(["Title", "url"])
    workbook.active.append(["Page", "https://example.com"])
    output = io.BytesIO()
    workbook.save(output)
    result = parse_import("links.xlsx", output.getvalue(), "")
    assert result["urls"] == ["https://example.com/"]
    result = parse_import(
        "",
        b"",
        "https://example.com\nhttps://example.com/#a\nfile:///etc/passwd\nhttps://u:p@example.com\nhttp://127.0.0.1\nhttp://[::1]\nhttps://example.com:bad",
    )
    assert result["duplicates"] == 1
    assert len(result["invalid"]) == 5


def test_capture_files_are_inert_and_whitelisted(tmp_path):
    import asyncio

    from muster.collector import Collector
    from tests.muster.test_collector import FakeBrowser, seed

    collection = seed(tmp_path, ["https://example.com/listing"])

    async def capture():
        worker = Collector(tmp_path, FakeBrowser, delay=0)
        worker.start(collection)
        await worker.task

    asyncio.run(capture())
    with connect(tmp_path) as db:
        capture_id = db.execute("SELECT id FROM captures").fetchone()[0]
    with TestClient(create_app(tmp_path)) as client:
        response = client.get(f"/captures/{capture_id}")
        assert response.status_code == 200
        assert "Full-page screenshot" in response.text
        response = client.get(f"/captures/{capture_id}/files/page.html")
        assert response.headers["content-disposition"].startswith("attachment")
        assert response.headers["content-security-policy"] == "sandbox; default-src 'none'"
        assert client.get(f"/captures/{capture_id}/files/muster.sqlite3").status_code == 404
        assert client.get("/captures/missing").status_code == 404
        response = client.get(f"/collections/{collection}")
        assert f"/captures/{capture_id}" in response.text
        csrf = token(response)
        assert (
            client.post(f"/collections/{collection}/collect", data={"csrf": csrf}).status_code
            == 409
        )
        assert (
            client.post(
                f"/collections/{collection}/control/continue", data={"csrf": csrf}
            ).status_code
            == 409
        )


def test_listing_fixture_imports_as_twenty_links():
    from pathlib import Path

    content = (Path(__file__).parent / "fixtures/real-estate-url-list.txt").read_text()
    result = parse_import("", b"", content)
    assert len(result["urls"]) == 20
    assert not result["invalid"]
    assert result["duplicates"] == 0


def test_collection_controls_run_worker_and_prevent_retry_of_open_page(tmp_path):
    from muster.collector import Collector
    from tests.muster.test_collector import FakeBrowser, seed, until

    collection = seed(tmp_path, ["https://example.com/login"])
    app = create_app(tmp_path)
    with TestClient(app) as client:
        browser = FakeBrowser(tmp_path)
        app.state.collector = Collector(tmp_path, lambda root: browser, delay=0)
        csrf = token(client.get("/"))
        response = client.post(f"/collections/{collection}/collect", data={"csrf": csrf})
        assert response.status_code == 200
        client.portal.call(until, lambda: app.state.collector.waiting)
        response = client.get(f"/collections/{collection}")
        assert "Continue after checking browser" in response.text
        assert 'http-equiv="refresh"' not in response.text
        assert 'data-live="collection-progress"' in response.text
        assert (
            client.post(f"/collections/{collection}/jobs/1/retry", data={"csrf": csrf}).status_code
            == 409
        )
        assert (
            client.post(f"/collections/{collection}/collect", data={"csrf": csrf}).status_code
            == 409
        )
        response = client.post(f"/collections/{collection}/control/skip", data={"csrf": csrf})
        assert response.status_code == 200
        client.portal.call(until, lambda: not app.state.collector.active)
        response = client.get(f"/collections/{collection}")
        assert "Skipped after an interruption" in response.text
        assert "Retry page" in response.text
        assert "/captures/" in response.text
