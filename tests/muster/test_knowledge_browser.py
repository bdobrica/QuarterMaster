"""Opt-in headed end-to-end knowledge approval with a local simulated provider."""

import asyncio
import json
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import urlopen

import pytest
from playwright.async_api import async_playwright, expect

from muster import knowledge as kb
from muster.review import get_review
from tests.muster.test_review import ready

pytestmark = pytest.mark.skipif(
    os.environ.get("MUSTER_BROWSER_TESTS") != "1",
    reason="Set MUSTER_BROWSER_TESTS=1 with Chromium and a desktop installed",
)


def test_knowledge_consent_diff_review_correction_accept_edit_and_dismiss(tmp_path):
    cid, _ = ready(tmp_path, 2)
    requests = []

    class Provider(BaseHTTPRequestHandler):
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            payload = json.loads(request["messages"][1]["content"])
            requests.append(payload)
            current = payload["article"]
            body = (
                current["body"]
                if current
                else "# Price guidance\n\nKeep asking prices separate from estimates."
            ) + "\n\nCheck original sources when values disagree."
            result = {
                "title": "Price guidance",
                "body": body,
                "sources": [s["id"] for s in payload["sources"]],
            }
            data = json.dumps(
                {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result)}}]}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    env = dict(
        os.environ,
        MUSTER_DATA_DIR=str(tmp_path),
        MUSTER_AI_BASE_URL=f"http://127.0.0.1:{server.server_port}/v1",
        MUSTER_AI_MODEL="local-test",
        MUSTER_AI_API_KEY="",
    )
    process = subprocess.Popen(
        [sys.executable, "-m", "muster", "--port", str(port)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        for _ in range(200):
            if process.poll() is not None:
                raise RuntimeError(process.stdout.read().decode())
            try:
                with urlopen(origin, timeout=1):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("Local test app did not start")

        async def scenario():
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(headless=False)
                page = await browser.new_page(viewport={"width": 1280, "height": 768})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                await page.goto(f"{origin}/collections/{cid}/review/1")
                await page.locator("#field-price").fill("81000")
                await page.locator("summary", has_text="Knowledge for this example").click()
                await page.get_by_role(
                    "link", name="Suggest a knowledge change", exact=True
                ).click()
                await expect(page).to_have_url(f"{origin}/collections/{cid}/knowledge?job_id=1")
                assert get_review(tmp_path, cid, 1)["values"]["price"] == 81000
                await page.locator("#lesson").fill(
                    "Keep my estimate separate from the asking price."
                )
                await page.get_by_role(
                    "button", name="Preview knowledge suggestion", exact=True
                ).click()
                assert not requests and kb.articles(tmp_path, cid) == []
                await page.get_by_role("checkbox").check()
                await page.get_by_role("button", name="Send & suggest knowledge").click()
                await expect(page.locator("#knowledge-diff")).to_contain_text(
                    "+Keep asking prices separate"
                )
                assert len(requests) == 1 and kb.articles(tmp_path, cid) == []
                await page.screenshot(path=str(tmp_path / "knowledge-diff.png"), full_page=False)
                await page.locator("#body").fill(
                    "# Price guidance\n\nKeep asking prices separate from my estimates.\n\nMy instruction stays authoritative."
                )
                await page.get_by_role("button", name="Preview edited diff").click()
                await expect(page.locator("#knowledge-diff")).to_contain_text(
                    "+My instruction stays authoritative."
                )
                await page.get_by_role("button", name="Accept article change").first.click()
                await page.get_by_role("link", name="Open accepted article").click()
                await expect(page.locator("#body")).to_have_value(
                    "# Price guidance\n\nKeep asking prices separate from my estimates.\n\nMy instruction stays authoritative."
                )
                aid = kb.articles(tmp_path, cid)[0]["id"]
                await page.locator("#body").fill("# Price guidance\n\nManual instruction wins.")
                await page.get_by_role("button", name="Save article").click()
                await expect(page.locator("#body")).to_have_value(
                    "# Price guidance\n\nManual instruction wins."
                )
                await page.goto(f"{origin}/collections/{cid}/knowledge?job_id=1")
                await page.locator("#article-choice").select_option(aid)
                await page.get_by_role("button", name="Preview knowledge suggestion").click()
                await page.get_by_role("checkbox").check()
                await page.get_by_role("button", name="Send & suggest knowledge").click()
                await expect(page.locator("#knowledge-diff")).to_contain_text(
                    "Manual instruction wins."
                )
                await page.get_by_role("button", name="Dismiss suggestion").first.click()
                assert (
                    kb.article(tmp_path, cid, aid)["body"]
                    == "# Price guidance\n\nManual instruction wins."
                )
                assert get_review(tmp_path, cid, 1)["values"]["price"] == 81000
                await page.screenshot(path=str(tmp_path / "knowledge-browser.png"), full_page=True)
                assert not errors
                await browser.close()

        asyncio.run(scenario())
    finally:
        process.terminate()
        process.wait(timeout=10)
        server.shutdown()
        server.server_close()
