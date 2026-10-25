"""Opt-in real-browser slice with synthetic pages, configured extraction and local inference.

Run with --run-live --data-dir /absolute/new/directory. No fabricated model responses.
Another configured provider is used for collection only with the explicit
--use-builder-for-collection or --use-adviser-for-collection flag; browser consent
is still required.
This prepares a training request. It never starts or promotes a GPU candidate.
"""

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

from quartermaster.config import Settings


def demo_app():
    from quartermaster.app import create_app

    return create_app(Settings())


def run(args):
    from playwright.sync_api import expect, sync_playwright

    config = Settings()
    if args.data_dir.exists():
        raise SystemExit("Use a new data directory; existing records will not be changed.")
    args.data_dir.mkdir(parents=True)
    base = json.loads((config.local_model_dir / "manifest.json").read_bytes())
    env = os.environ.copy()
    env.update(
        QM_DATA_DIR=str(args.data_dir),
        QM_LOCAL_BASE_URL=args.local_url,
        QM_LOCAL_MODEL_SHA256=base["sha256"],
        QM_LOCAL_MODEL_REVISION=base["revision"],
    )
    if args.use_builder_for_collection or args.use_adviser_for_collection:
        prefix = "adviser" if args.use_adviser_for_collection else "builder"
        provider_url = getattr(config, prefix + "_base_url")
        provider_model = getattr(config, prefix + "_model")
        secret = getattr(config, prefix + "_api_key")
        secret_file = getattr(config, prefix + "_api_key_file")
        key = (
            secret.get_secret_value()
            if secret
            else secret_file.read_text().strip()
            if secret_file
            else ""
        )
        if not provider_url or not provider_model or not key:
            raise SystemExit("Configure the selected provider for this explicit development check.")
        env.update(
            MUSTER_AI_BASE_URL=str(provider_url),
            MUSTER_AI_MODEL=provider_model,
            MUSTER_AI_API_KEY=key,
        )
    elif not config.muster_ai_model:
        raise SystemExit(
            "Configure collection or explicitly use another configured provider for this check."
        )
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    log = (args.data_dir / "server.log").open("w")
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "tests.smoke_stabilization:demo_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--no-access-log",
        ],
        env=env,
        stdout=log,
        stderr=log,
    )
    report = {
        "synthetic_development_data": True,
        "real_browser": True,
        "local_model_revision": base["revision"],
        "local_model_sha256": base["sha256"],
    }
    try:
        for _ in range(100):
            if server.poll() is not None:
                raise RuntimeError("Application startup failed; inspect sanitized server log.")
            try:
                with urlopen(origin + "/healthz", timeout=1):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("Application startup timed out.")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_default_timeout(30000)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(origin)
            page.locator("#name").fill("Apartment judgment rehearsal")
            page.locator("#mission").fill(
                "Help me decide my preferred apartment price in EUR. "
                "I value quiet streets and usable space. My personal judgments and explanations "
                "are preferences, not estimates of market truth. "
                "Apply my taught judgments to comparable apartments."
            )
            page.get_by_role("button", name="Create adviser", exact=True).click()
            page.wait_for_url("**/answer-format")
            pid = page.url.split("/projects/")[1].split("/")[0]
            report["project_id"] = pid
            page.locator("#unit").fill("EUR")
            page.get_by_role("button", name="Save answer settings").click()
            page.get_by_role("navigation", name="Adviser workflow").get_by_role(
                "link", name="Collect", exact=True
            ).click()
            for index, (area, quiet, asking) in enumerate(
                [(60, "yes", 90000), (65, "no", 85000), (70, "yes", 100000)]
            ):
                if index:
                    page.get_by_text("Add a saved page", exact=True).click()
                else:
                    page.locator('form[action="/collect/saved-pages"] input[name=name]').fill(
                        "Apartment pages"
                    )
                page.locator("input[name=page]").set_input_files(
                    {
                        "name": f"apartment-{index + 1}.html",
                        "mimeType": "text/html",
                        "buffer": (
                            f"<!doctype html><title>Development apartment {index + 1}</title>"
                            f"<h1>Apartment {index + 1}</h1>"
                            f"<p>Usable area: {area} square metres.</p>"
                            f"<p>Quiet street: {quiet}.</p><p>Asking price: {asking} EUR, "
                            "an advertisement and not my preferred valuation.</p>"
                        ).encode(),
                    }
                )
                page.locator("input[name=source_url]").fill(
                    f"https://example.com/development/apartment-{index + 1}"
                )
                page.get_by_role("button", name="Add saved page", exact=True).click()
                page.wait_for_url("**/collect/collections/*")
            collection_url = page.url
            page.get_by_role("link", name="Choose useful details", exact=True).click()
            page.locator("input[name=consent]").check()
            page.get_by_role("button", name="Send sample & suggest fields", exact=True).click(
                timeout=180000
            )
            expect(page.get_by_role("button", name="Use these suggested fields")).to_be_visible(
                timeout=180000
            )
            page.get_by_role("button", name="Use these suggested fields").click()
            page.get_by_role("button", name="Accept these fields", exact=True).click()
            report["real_field_suggestion"] = True
            print("Real field suggestion reviewed in Chromium.", flush=True)
            page.goto(collection_url)
            page.get_by_role("button", name="Preview extraction", exact=True).click()
            page.locator("input[name=consent]").check()
            page.get_by_role("button", name="Send & extract details").click()
            deadline = time.monotonic() + 240
            while time.monotonic() < deadline:
                page.reload()
                if page.locator("[data-live=batch-state][data-running=no]").count():
                    break
                page.wait_for_timeout(1000)
            assert page.get_by_role("link", name="Check this example", exact=True).count() == 3, (
                "Extraction did not produce three valid examples."
            )
            report["real_page_extractions"] = 3
            print("Three real extractions completed.", flush=True)
            page.get_by_role("link", name="Check this example", exact=True).first.click()
            for index in range(3):
                # Correct one actual extracted numerical observation through the editor.
                numbers = page.locator('input[name^="value:"][type=number]')
                if index == 0:
                    area_input = next(
                        (el for el in numbers.all() if el.input_value() == "60"), None
                    )
                    assert area_input is not None, "The model did not extract the stated area."
                    area_input.fill("61")
                page.get_by_role("button", name="Save & next", exact=True).click()
                page.wait_for_timeout(500)
            report["extraction_corrected_in_browser"] = True
            page.goto(collection_url)
            page.get_by_role("button", name="Start teaching", exact=True).click()
            page.wait_for_url("**/projects/*/teach/*")
            teaching_url = page.url
            for index, (target, reason) in enumerate(
                [
                    (70000, "I prefer a quiet street even at this size."),
                    (60000, "Noise lowers what I would personally pay."),
                    (80000, "More usable space and quiet fit my priorities."),
                ]
            ):
                page.goto(teaching_url + f"/examples/{index}")
                if index == 0:
                    boxes = page.locator("input[name=input_field]")
                    for box in boxes.all():
                        key = box.get_attribute("value").lower()
                        if not any(
                            word in key for word in ("price", "currency", "eur", "valuation")
                        ):
                            box.check()
                    page.locator("input[name=inputs_available_at_decision]").check()
                assert not page.locator("input[name=unit]").count(), (
                    "Answer format was asked again."
                )
                page.locator("input[name=value]").fill(str(target))
                page.locator("textarea[name=reasoning]").fill(reason)
                page.get_by_role("button", name="Save my answer", exact=True).click()
                expect(page.get_by_role("status")).to_contain_text("Saved your teaching answer")
            report["personal_judgments"] = 3
            page.goto(origin + f"/projects/{pid}/ask")
            page.locator("#situation").fill(
                "An apartment has 64 square metres of usable space and a quiet street. "
                "What would I personally pay?"
            )
            start = time.monotonic()
            page.get_by_role("button", name="Ask my adviser", exact=True).click(timeout=180000)
            expect(
                page.get_by_role("heading", name="Why this fits what you've taught me")
            ).to_be_visible(timeout=180000)
            report["ask_seconds"] = round(time.monotonic() - start, 3)
            result = page.locator("main article").first
            assert result.locator("strong").count(), (
                "Local model did not produce a numerical answer."
            )
            report["base_answer"] = result.locator("strong").first.inner_text()
            page.screenshot(path=str(args.data_dir / "ask.png"), full_page=True)
            page.get_by_role("link", name="Review this answer", exact=True).first.click()
            page.locator("input[name=value]").first.fill("72000")
            page.locator("textarea[name=reasoning]").first.fill(
                "I would pay 72000 EUR: quiet matters to me, "
                "with a modest allowance for more usable space."
            )
            page.get_by_role("button", name="Correct", exact=True).first.click()
            expect(page.get_by_role("status")).to_contain_text(
                "Saved your correction. I'll use it when you next improve your adviser."
            )
            page.screenshot(path=str(args.data_dir / "review.png"), full_page=True)
            page.get_by_role("navigation", name="Adviser workflow").get_by_role(
                "link", name="Teach", exact=True
            ).click()
            expect(page.get_by_text("72000.0", exact=False).first).to_be_visible()
            report["automatic_review_to_teaching"] = True
            page.locator("input[name=acknowledge_resources]").check()
            page.get_by_role("button", name="Improve my adviser", exact=True).click()
            expect(
                page.get_by_text("Improvement prepared; waiting for the local worker.", exact=False)
            ).to_be_attached()
            report["bounded_improvement_requested"] = True
            assert not errors, errors
            browser.close()
        from quartermaster import training

        isolated = Settings(data_dir=args.data_dir, _env_file=None)
        report["training_run_id"] = str(training.runs(isolated, pid)[0].id)
        report["gpu_run_completed"] = False
        report["nontechnical_tester"] = False
        (args.data_dir / "browser-report.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2), flush=True)
    finally:
        server.terminate()
        server.wait(timeout=10)
        log.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-live", action="store_true", required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--local-url", default="http://127.0.0.1:18080/v1")
    parser.add_argument("--use-builder-for-collection", action="store_true")
    parser.add_argument("--use-adviser-for-collection", action="store_true")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
