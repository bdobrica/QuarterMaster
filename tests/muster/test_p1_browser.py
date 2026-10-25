"""P1 controls through a real local browser; no external website/provider calls."""

import asyncio
import os
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

import pytest
from playwright.async_api import async_playwright, expect

from muster.extraction import prepare_batch
from muster.review import get_review
from tests.muster.test_review import ready

pytestmark = pytest.mark.skipif(
    os.environ.get("MUSTER_BROWSER_TESTS") != "1", reason="Set MUSTER_BROWSER_TESTS=1"
)


def test_bulk_images_and_rebuild_in_visible_browser(tmp_path):
    cid, provider = ready(tmp_path, 2)
    bid = prepare_batch(tmp_path, cid, provider, job_id=1)
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    env = dict(
        os.environ,
        MUSTER_DATA_DIR=str(tmp_path),
        MUSTER_AI_BASE_URL="",
        MUSTER_AI_MODEL="",
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
            raise RuntimeError("App did not start")

        async def scenario():
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=False)
                page = await browser.new_page(viewport={"width": 1280, "height": 768})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                await page.goto(f"{origin}/collections/{cid}/review")
                await page.get_by_role("checkbox", name="Select example 1", exact=True).check()
                await page.locator("#bulk-review select").select_option("reviewed")
                await page.get_by_role("button", name="Apply to selected examples").click()
                assert get_review(tmp_path, cid, 1)["status"] == "reviewed"
                assert get_review(tmp_path, cid, 2)["status"] == "needs_review"
                await page.goto(f"{origin}/extraction-batches/{bid}")
                await page.get_by_text(
                    "Page text, spreadsheet details and selected images", exact=True
                ).click()
                await page.get_by_text("Choose images for this example", exact=True).click()
                await page.locator('input[name=image][value="image-1.png"]').uncheck()
                await page.get_by_role("button", name="Save image selection").click()
                await page.get_by_text(
                    "Page text, spreadsheet details and selected images", exact=True
                ).click()
                await expect(
                    page.get_by_text(
                        "No images will be sent; visual details must remain unknown.", exact=True
                    )
                ).to_be_visible()
                await page.goto(f"{origin}/collections/{cid}/fields")
                await page.get_by_role(
                    "link", name="start a new draft with Rebuild examples"
                ).click()
                await page.locator("input[name=name]").fill("Browser rebuild")
                await page.get_by_role("button", name="Create draft from retained sources").click()
                await expect(
                    page.get_by_role("heading", name="Choose what to collect")
                ).to_be_visible()
                await expect(page.get_by_role("button", name="Accept these fields")).to_be_visible()
                assert not errors
                await browser.close()

        asyncio.run(scenario())
    finally:
        process.terminate()
        process.wait(timeout=10)
