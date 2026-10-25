"""Opt-in integration check: actual headed Chromium against a controlled local site."""

import asyncio
import os
import struct
import threading
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from muster.browser import BrowserSession
from muster.collector import Collector
from muster.storage import connect
from tests.muster.test_collector import seed, until

pytestmark = pytest.mark.skipif(
    os.environ.get("MUSTER_BROWSER_TESTS") != "1",
    reason="Set MUSTER_BROWSER_TESTS=1 with Chromium and a desktop installed",
)


def png():
    def chunk(name, payload):
        return (
            struct.pack(">I", len(payload))
            + name
            + payload
            + struct.pack(">I", zlib.crc32(name + payload))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 320, 200, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress((b"\0" + b"\x30\x70\xb0" * 320) * 200))
        + chunk(b"IEND", b"")
    )


class Site(BaseHTTPRequestHandler):
    hits = []

    def do_GET(self):
        self.hits.append(self.path)
        status, mime = 200, "text/html"
        if self.path == "/robots.txt":
            mime, content = "text/plain", b"User-agent: *\nDisallow: /denied\n"
        elif self.path in ("/photo.png", "/map.png", "/recommendation.png"):
            mime, content = "image/png", png()
        elif self.path == "/login":
            content = (
                b'<title>Sign in</title><h1>Sign in</h1><input type="password" value="test-secret">'
            )
        elif self.path == "/blocked":
            status, content = 403, b"<title>Access denied</title><h1>Access denied</h1>"
        elif self.path == "/missing":
            status, content = 404, b"<title>Missing</title><h1>This listing is gone</h1>"
        else:
            content = b'<title>Example listing</title><h1>Two bedroom apartment</h1><p>Source evidence</p><div data-testid="gallery"><img src="/photo.png" alt="Living room"></div><div class="gm-style"><img src="/map.png" alt="Map tile"></div><aside><img src="/recommendation.png" alt="Other listing"></aside><div style="height:1500px">More page</div>'
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, *args):
        pass


def test_headed_capture_login_skip_and_robots(tmp_path, monkeypatch):
    # The production collector rejects localhost. Only this controlled test allows its exact origin.
    server = ThreadingHTTPServer(("127.0.0.1", 0), Site)
    Site.hits = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"

    async def test_url(url):
        return url.startswith(origin + "/")

    monkeypatch.setattr("muster.browser.public_url", test_url)

    async def scenario():
        collection = seed(
            tmp_path, [origin + path for path in ("/login", "/blocked", "/missing", "/denied")]
        )
        browser = BrowserSession(tmp_path)
        worker = Collector(tmp_path, lambda root: browser, delay=0)
        worker.start(collection)
        try:
            await until(lambda: worker.waiting)
            with connect(tmp_path) as db:
                first = db.execute("SELECT * FROM captures WHERE job_id=1").fetchone()
            html = (tmp_path / "sources/1" / first["id"] / "page.html").read_text()
            assert "test-secret" not in html
            await browser.page.set_content(
                "<title>Just a moment</title><p>Verify that you are human</p>"
            )
            assert "needs your attention" in await browser.attention()
            # Simulate the user completing sign-in and navigating to the listing.
            await browser.page.goto(origin + "/listing")
            worker.control(collection, "continue")
            await until(lambda: worker.waiting and worker.job_id == 2)
            worker.control(collection, "skip")
            await asyncio.wait_for(worker.task, 45)
            assert browser.closed.is_set()
            with connect(tmp_path) as db:
                assert [row[0] for row in db.execute("SELECT status FROM jobs ORDER BY id")] == [
                    "captured",
                    "failed",
                    "failed",
                    "blocked",
                ]
                captures = db.execute("SELECT * FROM captures ORDER BY captured_at").fetchall()
                assert len(captures) == 4
                import json

                success = next(
                    json.loads(row["metadata"]) for row in captures if row["status"] == "captured"
                )
                assert success["http_status"] == 200
                assert success["source_url"] == origin + "/login"
                assert success["final_url"] == origin + "/listing"
                assert len(success["images"]) == 1
                assert success["images"][0]["alt"] == "Living room"
                directory = tmp_path / "sources/1" / success["id"]
                assert (directory / success["images"][0]["file"]).read_bytes() == png()
                assert (directory / "screenshot.png").read_bytes().startswith(b"\x89PNG")
                assert "Source evidence" in (directory / "page.html").read_text()
            assert "/denied" not in Site.hits
        finally:
            await worker.close()

    try:
        asyncio.run(scenario())
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
