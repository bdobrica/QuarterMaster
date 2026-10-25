"""Opt-in integrated browser rehearsal with local fixtures and no provider calls."""

import json
import os
import subprocess
import sys

import pytest

from muster.knowledge import save_article
from muster.publication import overview, publish
from tests.muster.test_publication import reviewed

pytestmark = pytest.mark.live


def test_collect_to_personal_teaching_in_browser(tmp_path, project_fixture):
    root = tmp_path / "data" / "muster"
    cid = reviewed(root, 2)
    save_article(root, cid, None, 0, "Owner guidance", "Prefer convenient transport.")
    publish(root, cid, overview(root, cid)["fingerprint"])
    env = {
        key: value for key, value in os.environ.items() if not key.startswith(("QM_", "MUSTER_"))
    }
    env.update(
        QM_DATA_DIR=str(tmp_path / "data"),
        MUSTER_AI_BASE_URL="",
        MUSTER_AI_MODEL="",
        MUSTER_AI_API_KEY="",
    )
    # Child isolates genuine loopback/browser I/O from the CPU suite's no-network guard.
    script = r"""
import json, os, socket, subprocess, sys, time
from pathlib import Path
from urllib.request import urlopen
from playwright.sync_api import sync_playwright, expect
import muster
assert Path(muster.__file__).resolve().is_relative_to(Path.cwd().resolve())
with socket.socket() as reserve:
    reserve.bind(('127.0.0.1', 0))
    port = reserve.getsockname()[1]
origin = f'http://127.0.0.1:{port}'
command = [sys.executable, '-m', 'uvicorn', 'quartermaster.app:app',
           '--host', '127.0.0.1', '--port', str(port), '--no-access-log']
server = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
try:
    for _ in range(100):
        if server.poll() is not None:
            raise AssertionError('Local app failed startup: ' + server.stderr.read().decode())
        try:
            with urlopen(origin+'/healthz', timeout=1): break
        except OSError: time.sleep(.1)
    else: raise AssertionError('Local app did not start')
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        errors=[]
        page.on('pageerror', lambda error: errors.append(str(error)))
        response=context.request.post(origin+'/api/projects', data=json.loads(sys.argv[1]))
        assert response.ok
        pid=response.json()['id']
        page.goto(origin+'/collect/collections/1/review')
        page.locator('a[href^="/collect/collections/1/review/1"]').first.click()
        expect(page.locator('#review-form')).to_have_attribute(
            'action', __import__('re').compile(r'^/collect/'))
        page.locator('textarea[name=notes]').fill('Checked inside QuarterMaster')
        page.get_by_role('button',name='Save & next',exact=True).click()
        page.wait_for_url('**/collect/collections/1/review/2*')
        page.goto(origin+f'/projects/{pid}/teach')
        page.get_by_role('button',name='Inspect this collection').click()
        page.get_by_role('button',name='Use these articles in advice').click()
        page.get_by_role('link',name=__import__('re').compile('Example 1 ·')).click()
        boxes=page.locator('input[name=input_field]')
        for box in boxes.all():
            if box.get_attribute('value')!='price': box.check()
        page.locator('input[name=inputs_available_at_decision]').check()
        page.locator('input[name=value]').fill('72000')
        page.locator('input[name=unit]').fill('EUR')
        page.locator('textarea[name=reasoning]').fill('My preferred valuation')
        page.get_by_role('button',name='Save my answer').click()
        expect(page.get_by_role('status')).to_contain_text('Saved your teaching answer')
        page.goto(page.url.split('/examples/')[0])
        with page.expect_download() as download:
            page.get_by_role('button',name='Download reviewed teaching data').click()
        data=json.loads(Path(download.value.path()).read_text())
        assert data['examples'][0]['owner_decision']['target']=={
            'kind':'number','value':72000.0,'unit':'EUR'}
        assert not errors, errors
        browser.close()
    print('Integrated Collect -> knowledge -> personal teaching -> stable dataset passed.')
finally:
    server.terminate()
    server.wait(timeout=10)
"""
    result = subprocess.run(
        [sys.executable, "-c", script, json.dumps(project_fixture)],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
