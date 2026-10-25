import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from muster.collector import Collector
from muster.storage import connect, initialize


def seed(root, paths):
    initialize(root)
    with connect(root) as db:
        collection = db.execute("INSERT INTO collections(name) VALUES('Test collection')").lastrowid
        db.executemany(
            "INSERT INTO jobs(collection_id,url) VALUES(?,?)",
            [(collection, path) for path in paths],
        )
    return collection


async def until(predicate):
    async with asyncio.timeout(30):
        while not predicate():
            await asyncio.sleep(0.01)


class FakeBrowser:
    def __init__(self, root):
        self.root = root
        self.page = SimpleNamespace(url="")
        self.policy_error = None
        self.closed = asyncio.Event()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def allowed(self, url):
        return 0

    async def visit(self, url):
        self.page.url = url
        if url.endswith("/crash"):
            raise TimeoutError()

    async def attention(self):
        return "Sign in manually" if self.page.url.endswith("/login") else None

    async def snapshot(self, job_id, status, error=None):
        capture_id = uuid4().hex
        directory = self.root / "sources" / str(job_id) / capture_id
        directory.mkdir(parents=True)
        (directory / "page.html").write_text("<p>Retained original</p>")
        (directory / "screenshot.png").write_bytes(b"screenshot")
        return {
            "id": capture_id,
            "captured_at": datetime.now(UTC).isoformat(),
            "final_url": self.page.url,
            "status": status,
            "error": error,
            "images": [],
            "warnings": [],
            "title": "Test",
        }


def test_pause_continue_failure_retry_and_originals(tmp_path):
    async def scenario():
        collection = seed(tmp_path, ["https://example.com/login", "https://example.com/crash"])
        browser = FakeBrowser(tmp_path)
        worker = Collector(tmp_path, lambda root: browser, delay=0)
        worker.start(collection)
        await until(lambda: worker.waiting)
        try:
            worker.start(collection)
            raise AssertionError("Starting two workers should fail")
        except ValueError:
            pass
        with connect(tmp_path) as db:
            assert db.execute("SELECT status FROM jobs WHERE id=1").fetchone()[0] == "blocked"
            first = db.execute("SELECT * FROM captures").fetchone()
        original = (tmp_path / "sources/1" / first["id"] / "page.html").read_bytes()
        browser.page.url = (
            "https://example.com/listing"  # Manual navigation/sign-in in the managed browser.
        )
        worker.control(collection, "continue")
        await worker.task
        with connect(tmp_path) as db:
            assert [row[0] for row in db.execute("SELECT status FROM jobs ORDER BY id")] == [
                "captured",
                "failed",
            ]
            assert db.execute("SELECT count(*) FROM captures WHERE job_id=1").fetchone()[0] == 2
            db.execute("UPDATE jobs SET url='https://example.com/retry',status='queued' WHERE id=2")
        worker.start(collection)
        await worker.task
        with connect(tmp_path) as db:
            assert db.execute("SELECT status,attempts FROM jobs WHERE id=2").fetchone()[:] == (
                "captured",
                2,
            )
            meta = json.loads(
                db.execute(
                    "SELECT metadata FROM captures WHERE job_id=2 ORDER BY captured_at DESC,id DESC LIMIT 1"
                ).fetchone()[0]
            )
            assert meta["source_url"] == "https://example.com/retry"
        assert (tmp_path / "sources/1" / first["id"] / "page.html").read_bytes() == original

    asyncio.run(scenario())


def test_stop_retains_capture_and_leaves_remaining_queue(tmp_path):
    async def scenario():
        collection = seed(tmp_path, ["https://example.com/login", "https://example.com/later"])
        worker = Collector(tmp_path, FakeBrowser, delay=0)
        worker.start(collection)
        await until(lambda: worker.waiting)
        await worker.close()
        with connect(tmp_path) as db:
            assert [row[0] for row in db.execute("SELECT status FROM jobs ORDER BY id")] == [
                "failed",
                "queued",
            ]
            assert db.execute("SELECT count(*) FROM captures").fetchone()[0] == 1
        initialize(tmp_path)
        with connect(tmp_path) as db:
            assert db.execute("SELECT count(*) FROM captures").fetchone()[0] == 1

    asyncio.run(scenario())


def test_browser_start_failure_is_actionable(tmp_path):
    class MissingBrowser(FakeBrowser):
        async def __aenter__(self):
            raise RuntimeError("missing binary")

    async def scenario():
        collection = seed(tmp_path, ["https://example.com/"])
        worker = Collector(tmp_path, MissingBrowser, delay=0)
        worker.start(collection)
        await worker.task
        with connect(tmp_path) as db:
            job = db.execute("SELECT * FROM jobs").fetchone()
            assert job["status"] == "failed"
            assert "python -m playwright install chromium" in job["error"]

    asyncio.run(scenario())


def test_closing_browser_during_manual_pause_does_not_hang(tmp_path):
    async def scenario():
        collection = seed(tmp_path, ["https://example.com/login", "https://example.com/later"])
        browser = FakeBrowser(tmp_path)
        worker = Collector(tmp_path, lambda root: browser, delay=0)
        worker.start(collection)
        await until(lambda: worker.waiting)
        browser.closed.set()
        await asyncio.wait_for(worker.task, 2)
        with connect(tmp_path) as db:
            assert [row[0] for row in db.execute("SELECT status FROM jobs ORDER BY id")] == [
                "failed",
                "queued",
            ]

    asyncio.run(scenario())


def test_upgrade_keeps_existing_imports(tmp_path):
    collection = seed(tmp_path, ["https://example.com/listing"])
    # Reproduce a v1 database containing imported jobs, before captures existed.
    with connect(tmp_path) as db:
        db.execute("DROP TABLE knowledge_requests")
        db.execute("DROP TABLE knowledge_revisions")
        db.execute("DROP TABLE knowledge_articles")
        db.execute("DROP TABLE reviews")
        db.execute("DROP TABLE extractions")
        db.execute("DROP TABLE extraction_batches")
        db.execute("DROP TABLE schema_requests")
        db.execute("DROP TABLE collection_schemas")
        db.execute("DROP TABLE captures")
        db.execute("ALTER TABLE jobs DROP COLUMN input_rows")
        db.execute("ALTER TABLE jobs DROP COLUMN removed")
        db.execute("ALTER TABLE import_previews DROP COLUMN collection_id")
        db.execute("DROP TABLE publications")
        db.execute("DROP TABLE publication_exclusions")
        db.execute("DROP TABLE rebuild_observations")
        db.execute("DROP TABLE connector_calls")
        db.execute("DROP TABLE connector_permissions")
        db.execute("PRAGMA user_version=1")
    initialize(tmp_path)
    with connect(tmp_path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 11
        assert db.execute("SELECT collection_id,url,status FROM jobs").fetchone()[:] == (
            collection,
            "https://example.com/listing",
            "queued",
        )
        assert db.execute("SELECT count(*) FROM captures").fetchone()[0] == 0
