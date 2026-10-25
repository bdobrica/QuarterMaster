"""Progress updates preserve source inspection without recollecting pages."""

import asyncio
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from playwright.async_api import async_playwright, expect

from muster.app import create_app
from muster.extraction import prepare_batch
from muster.provider import SchemaProvider
from muster.storage import connect
from tests.muster.test_extraction import setup
from tests.muster.test_schema import SETTINGS

pytestmark = pytest.mark.skipif(
    os.environ.get("MUSTER_BROWSER_TESTS") != "1",
    reason="Set MUSTER_BROWSER_TESTS=1 with Chromium installed",
)


def test_extraction_progress_preserves_open_details_and_does_not_navigate(tmp_path):
    cid = setup(tmp_path, 2)
    provider = SchemaProvider(SETTINGS)
    bid = prepare_batch(tmp_path, cid, provider)
    with connect(tmp_path) as db:
        db.execute("UPDATE extraction_batches SET status='running' WHERE id=?", (bid,))
        db.execute("UPDATE extractions SET status='running' WHERE batch_id=?", (bid,))
    # No worker is launched. Serve saved UI states through a controlled browser route.
    with TestClient(create_app(tmp_path, provider)) as client:
        with connect(tmp_path) as db:
            db.execute("UPDATE extraction_batches SET status='running' WHERE id=?", (bid,))
            db.execute(
                "UPDATE extractions SET status='running',error=NULL WHERE batch_id=?", (bid,)
            )
        running = client.get(f"/extraction-batches/{bid}").text
        with connect(tmp_path) as db:
            db.execute("UPDATE extraction_batches SET status='failed' WHERE id=?", (bid,))
            db.execute(
                "UPDATE extractions SET status='failed',error='AI result for Currency: source reference missing.' WHERE batch_id=?",
                (bid,),
            )
        finished = client.get(f"/extraction-batches/{bid}").text
    script = (Path(__file__).resolve().parents[2] / "muster/static/extraction.js").read_text()

    async def scenario():
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=False)
            page = await browser.new_page(viewport={"width": 1100, "height": 700})
            visits = []
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))

            async def serve(route):
                request = route.request
                if request.url.endswith("/static/extraction.js"):
                    await route.fulfill(content_type="text/javascript", body=script)
                elif "/extraction-batches/" in request.url:
                    visits.append(request.is_navigation_request())
                    await route.fulfill(
                        content_type="text/html", body=running if len(visits) == 1 else finished
                    )
                else:
                    await route.fulfill(status=404, body="No external requests in this test")

            await page.route("**/*", serve)
            await page.goto(f"http://localhost/extraction-batches/{bid}")
            details = page.locator("details").first
            await details.locator(":scope > summary").click()
            await page.evaluate("window.preservedPage = true")
            await expect(page.locator('[data-live="heading"]')).to_have_text(
                "Check extraction results", timeout=12000
            )
            assert await details.evaluate("(element) => element.open")
            assert await page.evaluate("window.preservedPage")
            assert visits == [True, False]
            await expect(page.get_by_role("button", name="Stop extraction")).to_have_count(0)
            assert await page.locator('table a[target="_blank"]').count() == 2
            assert not errors
            await browser.close()

    asyncio.run(scenario())
