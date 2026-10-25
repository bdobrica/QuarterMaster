"""Opt-in real browser check of the complete 20-example review loop."""

import asyncio
import json
import os
import re
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

import pytest
from playwright.async_api import async_playwright, expect

from muster.review import get_review
from muster.storage import connect
from tests.muster.test_browser import png
from tests.muster.test_review import ready

pytestmark = pytest.mark.skipif(
    os.environ.get("MUSTER_BROWSER_TESTS") != "1",
    reason="Set MUSTER_BROWSER_TESTS=1 with Chromium and a desktop installed",
)


def test_twenty_record_keyboard_autosave_recovery_and_conflicts(tmp_path):
    collection, _ = ready(tmp_path, 20)
    # A second retained image verifies gallery navigation independently of the model's image subset.
    with connect(tmp_path) as db:
        for capture in db.execute("SELECT * FROM captures").fetchall():
            directory = tmp_path / "sources" / str(capture["job_id"]) / capture["id"]
            (directory / "image-2.png").write_bytes(png())
            metadata = json.loads(capture["metadata"])
            metadata["images"].append(
                {
                    "file": "image-2.png",
                    "mime": "image/png",
                    "alt": "Second test image",
                    "width": 320,
                    "height": 200,
                }
            )
            db.execute(
                "UPDATE captures SET metadata=? WHERE id=?", (json.dumps(metadata), capture["id"])
            )
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
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
                with urlopen(origin, timeout=1) as response:
                    assert response.status == 200
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("Local test app did not start")

        async def scenario():
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(headless=False)
                context = await browser.new_context(viewport={"width": 1280, "height": 768})
                page = await context.new_page()
                page.set_default_timeout(10000)
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("dialog", lambda dialog: asyncio.create_task(dialog.accept()))
                await page.goto(f"{origin}/collections/{collection}/review?status=needs_review")
                await page.locator("tr[data-open-url]").first.focus()
                await page.keyboard.press("Enter")
                await page.wait_for_url(re.compile(r"/review/1\?"))
                await page.locator("#field-price").fill("88000")
                await page.locator("#review-notes").fill("Human correction one")
                # Navigate before the debounce fires; pending edits must be saved as a draft.
                await page.get_by_role("button", name="Next", exact=True).click()
                await page.wait_for_url(re.compile(r"/review/2\?"), timeout=10000)
                assert get_review(tmp_path, collection, 1)["values"]["price"] == 88000
                assert get_review(tmp_path, collection, 1)["status"] == "needs_review"
                await page.keyboard.press("Alt+ArrowLeft")
                await page.wait_for_url(re.compile(r"/review/1\?"))
                assert float(await page.locator("#field-price").input_value()) == 88000
                toolbar = await page.locator(".review-toolbar").bounding_box()
                notes = await page.locator("#review-notes").bounding_box()
                assert toolbar["y"] + toolbar["height"] <= 768
                assert notes["y"] + notes["height"] <= 768
                source_panel = await page.locator(".review-source").bounding_box()
                assert notes["y"] + notes["height"] <= source_panel["y"] + source_panel["height"]
                await page.screenshot(path=str(tmp_path / "review-detail.png"))
                await page.keyboard.press("Control+Enter")
                await page.wait_for_url(re.compile(r"/review/2\?"))
                await page.locator("#field-price").fill("87000")
                await page.locator("#review-notes").fill("Human correction two")
                await page.locator('[name="unknown:year"]').uncheck()
                await page.locator("#field-year").fill("1982")
                await page.get_by_role("button", name="Next image", exact=True).click()
                await expect(page.locator("#gallery-caption")).to_have_text("2 / 2")
                await expect(page.locator("#save-state")).to_have_text("Saved")
                assert get_review(tmp_path, collection, 2)["values"]["year"] == 1982
                await page.keyboard.press("Control+Enter")
                await page.wait_for_url(re.compile(r"/review/3\?"))
                for index in range(3, 21):
                    await page.keyboard.press("Control+Enter")
                    await page.wait_for_url(
                        re.compile(rf"/review/{index + 1}\?")
                        if index < 20
                        else re.compile(r"/review\?")
                    )
                assert "20 reviewed" in await page.locator("body").inner_text()
                await page.goto(f"{origin}/collections/{collection}/review")
                await page.locator("#review-search").fill("Human correction")
                await page.get_by_role("button", name="Filter examples").click()
                assert await page.locator("tr[data-open-url]").count() == 2
                await page.get_by_role("link", name="Price", exact=True).click()
                first = await page.locator("tr[data-open-url]").first.get_attribute("data-open-url")
                assert "/review/2?" in first
                await page.screenshot(path=str(tmp_path / "review-list.png"))
                # A failed local save is journaled, survives reload, and is recovered without changing the schema.
                await page.goto(f"{origin}/collections/{collection}/review/3")
                pattern = "**/review/3*"

                async def interrupt(route):
                    await (
                        route.abort()
                    ) if route.request.method == "POST" else await route.continue_()

                await page.route(pattern, interrupt)
                await page.locator("#review-notes").fill("Recovered interrupted edit")
                await expect(page.locator("#save-state")).to_contain_text("connection interrupted")
                await page.unroute(pattern)
                await page.reload()
                await expect(page.locator("#review-notes")).to_have_value(
                    "Recovered interrupted edit"
                )
                await expect(page.locator("#save-state")).to_have_text("Saved")
                assert get_review(tmp_path, collection, 3)["notes"] == "Recovered interrupted edit"
                assert get_review(tmp_path, collection, 3)["status"] == "needs_review"
                # Stale tabs cannot overwrite one another. Recovering a stale draft requires an explicit choice.
                await page.goto(f"{origin}/collections/{collection}/review/4")
                second = await context.new_page()
                await second.goto(f"{origin}/collections/{collection}/review/4")
                save_started = asyncio.Event()
                release_save = asyncio.Event()

                async def delayed_save(route):
                    if route.request.method == "POST":
                        save_started.set()
                        await release_save.wait()
                    await route.continue_()

                await page.route("**/review/4*", delayed_save)
                await page.locator("#review-notes").fill("First tab judgment")
                await save_started.wait()
                await second.locator("#review-notes").fill("Second tab judgment")
                release_save.set()
                await expect(page.locator("#save-state")).to_have_text("Saved")
                journal = await second.locator("#review-form").evaluate(
                    "form => JSON.parse(localStorage.getItem(form.dataset.reviewKey))"
                )
                assert any(
                    entry["name"] == "notes" and entry["value"] == "Second tab judgment"
                    for entry in journal["entries"]
                )
                await page.unroute("**/review/4*")
                await expect(second.locator("#review-conflict")).to_be_visible()
                assert get_review(tmp_path, collection, 4)["notes"] == "First tab judgment"
                await second.get_by_role("button", name="Reload saved copy").click()
                await expect(second.locator("#draft-recovery")).to_be_visible()
                await expect(second.locator("#review-notes")).to_have_value("First tab judgment")
                await second.get_by_role("button", name="Restore local draft").click()
                await expect(second.locator("#save-state")).to_have_text("Saved")
                assert get_review(tmp_path, collection, 4)["notes"] == "Second tab judgment"
                assert not errors, errors
                await browser.close()

        asyncio.run(scenario())
    finally:
        process.terminate()
        process.communicate(timeout=10)
    # New app instances load saved reviews without making any provider calls.
    from fastapi.testclient import TestClient

    from muster.app import create_app

    with TestClient(create_app(tmp_path)) as client:
        assert "88000" in client.get(f"/collections/{collection}/review/1").text
        assert get_review(tmp_path, collection, 1)["status"] == "reviewed"
