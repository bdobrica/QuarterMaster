"""Headed publish/download check at laptop size; all content is synthetic/local."""

import asyncio
import os
import socket
import subprocess
import sys
import time
import zipfile
from urllib.request import urlopen

import pytest
from playwright.async_api import async_playwright, expect

from muster import publication as pub
from muster.knowledge import save_article
from tests.muster.test_publication import reviewed

pytestmark = pytest.mark.skipif(
    os.environ.get("MUSTER_BROWSER_TESTS") != "1",
    reason="Set MUSTER_BROWSER_TESTS=1 with Chromium and a desktop installed",
)


def test_publish_exclude_download_and_next_draft_in_browser(tmp_path):
    cid = reviewed(tmp_path)
    save_article(tmp_path, cid, None, 0, "Preferences", "# Preferences\n\nPreserve user estimates.")
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    process = subprocess.Popen(
        [sys.executable, "-m", "muster", "--port", str(port)],
        env=dict(os.environ, MUSTER_DATA_DIR=str(tmp_path)),
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
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=False)
                page = await browser.new_page(
                    viewport={"width": 1280, "height": 768}, accept_downloads=True
                )
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                await page.goto(f"{origin}/collections/{cid}")
                await page.get_by_role("link", name="Publish collection", exact=True).click()
                await expect(
                    page.get_by_role("heading", name="Publish collection", exact=True)
                ).to_be_visible()
                row = page.get_by_role("row").filter(has_text="https://example.com/1")
                await row.locator("summary").click()
                await row.get_by_label("Reason").fill("Outside my target area.")
                await row.get_by_role("button", name="Exclude link", exact=True).click()
                await expect(
                    page.get_by_text("Outside my target area.", exact=True)
                ).to_be_visible()
                await page.get_by_role("checkbox").check()
                await page.screenshot(path=str(tmp_path / "publish-ready.png"), full_page=False)
                await page.get_by_role("button", name="Publish collection", exact=True).click()
                await expect(page.get_by_role("heading")).to_contain_text("v1 is ready")
                version = pub.overview(tmp_path, cid)["versions"][0]
                folder = tmp_path / version["path"]
                before = (folder / "manifest.json").read_bytes()
                async with page.expect_download() as event:
                    await page.get_by_role("link", name="Download published collection").click()
                download = await event.value
                output = tmp_path / "downloaded.zip"
                await download.save_as(output)
                with zipfile.ZipFile(output) as z:
                    assert z.read(f"collection-{cid}-v1/manifest.json") == before
                await page.screenshot(path=str(tmp_path / "published.png"), full_page=False)
                await page.get_by_role("link", name="Working draft and published versions").click()
                await page.get_by_role("button", name="Include again", exact=True).click()
                assert (folder / "manifest.json").read_bytes() == before
                assert not errors
                await browser.close()

        asyncio.run(scenario())
    finally:
        process.terminate()
        process.wait(timeout=10)
