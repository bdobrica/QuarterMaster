"""Exercise local editing of failed output and existing collection links."""

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

import pytest
from playwright.async_api import async_playwright, expect

from muster.extraction import prepare_batch
from muster.provider import SchemaProvider
from muster.review import get_review
from muster.storage import connect
from tests.muster.test_extraction import setup
from tests.muster.test_schema import SETTINGS

pytestmark = pytest.mark.skipif(
    os.environ.get("MUSTER_BROWSER_TESTS") != "1",
    reason="Set MUSTER_BROWSER_TESTS=1 with Chromium installed",
)


def test_add_remove_restore_and_manual_recovery_in_browser(tmp_path):
    cid = setup(tmp_path, 1)
    bid = prepare_batch(tmp_path, cid, SchemaProvider(SETTINGS))
    with connect(tmp_path) as db:
        db.execute("UPDATE extraction_batches SET status='failed'")
        db.execute(
            "UPDATE extractions SET status='failed',result=?,error='AI response needs correction'",
            (json.dumps({"values": {"currency": "EUR", "price": 90000}}),),
        )
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
            raise RuntimeError("Test app did not start")

        async def scenario():
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(headless=False)
                page = await browser.new_page(viewport={"width": 1280, "height": 768})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                await page.goto(f"{origin}/collections/{cid}")
                await page.get_by_text("Add links to this collection", exact=True).click()
                await page.locator("#more-links").fill(
                    "https://example.com/0\nhttps://example.com/new"
                )
                await page.get_by_role("button", name="Preview links", exact=True).click()
                await expect(page.get_by_text("1 links to add", exact=True)).to_be_visible()
                await page.get_by_role("button", name="Add 1 links", exact=True).click()
                await expect(page).to_have_url(f"{origin}/collections/{cid}")
                row = page.get_by_role("row").filter(
                    has=page.locator('a[href="https://example.com/0"]')
                )
                await row.get_by_role("button", name="Remove link", exact=True).click()
                await page.locator("summary", has_text="Removed links").click()
                await page.get_by_role("button", name="Restore link", exact=True).click()
                await page.goto(f"{origin}/extraction-batches/{bid}")
                await page.get_by_role(
                    "button", name="Edit available fields manually", exact=True
                ).click()
                await expect(page.locator("#field-currency")).to_have_value("EUR")
                await expect(page.locator("#field-price")).to_have_value("90000")
                await page.locator("#field-price").fill("88000")
                await page.keyboard.press("Control+s")
                await expect(page.locator("#save-state")).to_have_text("Saved")
                assert get_review(tmp_path, cid, 1)["values"]["price"] == 88000
                assert not errors
                await browser.close()

        asyncio.run(scenario())
    finally:
        process.terminate()
        process.wait(timeout=10)
