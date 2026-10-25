import asyncio
import hashlib
import json
import sqlite3
import subprocess
import sys
import zipfile

import pytest
from fastapi.testclient import TestClient

from muster import knowledge as kb
from muster import publication as pub
from muster.app import create_app
from muster.review import get_review, save_review
from muster.storage import connect, initialize
from tests.muster.test_app import token
from tests.muster.test_browser import png
from tests.muster.test_knowledge import provider_for
from tests.muster.test_review import ready


def reviewed(root, count=2):
    cid, _ = ready(root, count)
    with connect(root) as db:
        captures = db.execute("SELECT * FROM captures").fetchall()
    for c in captures:
        (root / "sources" / str(c["job_id"]) / c["id"] / "screenshot.png").write_bytes(png())
    for jid in range(1, count + 1):
        r = get_review(root, cid, jid)
        save_review(
            root,
            cid,
            jid,
            r["revision"],
            r["values"] | {"price": 80000 + jid},
            "Human checked",
            "review_next",
        )
    return cid


def tree(folder):
    return {
        p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in folder.rglob("*")
        if p.is_file()
    }


def test_publish_knowledge_evidence_download_restart_consumer_and_immutable_versions(tmp_path):
    cid = reviewed(tmp_path)
    provider = provider_for()
    rid = kb.prepare(tmp_path, cid, provider, job_id=1, lesson="Keep my estimates separate.")
    asyncio.run(kb.send(tmp_path, cid, rid, provider))
    result = kb.get_request(tmp_path, cid, rid)["result"]
    kb.resolve(tmp_path, cid, rid, "accept", result["title"], result["body"])
    aid = kb.articles(tmp_path, cid)[0]["id"]
    with TestClient(create_app(tmp_path)) as client:
        url = f"/collections/{cid}/publish"
        response = client.get(url)
        csrf = token(response)
        assert "All included examples are reviewed" in response.text
        fingerprint = pub.overview(tmp_path, cid)["fingerprint"]
        assert client.post(url, data={"csrf": csrf, "fingerprint": fingerprint}).status_code == 400
        response = client.post(
            url, data={"csrf": csrf, "fingerprint": fingerprint, "confirm": "yes"}
        )
        assert response.status_code == 200 and "v1 is ready" in response.text
        location = response.url.path
        pid = location.rsplit("/", 1)[1]
        published = pub.get_publication(tmp_path, cid, pid)
        folder = tmp_path / published["path"]
        before = tree(folder)
        archive = client.get(location + "/download")
        assert archive.status_code == 200
        import io

        with zipfile.ZipFile(io.BytesIO(archive.content)) as z:
            assert len(z.namelist()) == len(before)
            assert not any("browser-profile" in path or "sqlite" in path for path in z.namelist())
            assert all(b"secret-test-key" not in z.read(path) for path in z.namelist())
        manifest = pub.validate_bundle(folder)
        records = [
            json.loads(line) for line in (folder / "examples.jsonl").read_text().splitlines()
        ]
        assert records[0]["values"]["price"] == 80001
        provenance = json.loads((folder / records[0]["provenance"]).read_text())
        assert provenance["corrections"]["price"]["source"] == "user"
        assert provenance["original_result"]["values"]["price"] != 80001
        history = json.loads((folder / manifest["knowledge"][0]["provenance"]).read_text())
        assert (
            history[0]["suggestion"]["payload"]["sources"]
            and history[0]["suggestion"]["consent_at"]
        )
        # A separate Python process can inspect the bundle using only the standard library.
        from pathlib import Path

        checker = Path(__file__).resolve().parents[2] / "scripts" / "muster" / "check_bundle.py"
        subprocess.run([sys.executable, "-I", str(checker), str(folder)], check=True, cwd="/tmp")
        # A repeated stale submit cannot accidentally create another version.
        assert (
            client.post(
                url, data={"csrf": csrf, "fingerprint": fingerprint, "confirm": "yes"}
            ).status_code
            == 409
        )
        r = get_review(tmp_path, cid, 1)
        save_review(
            tmp_path, cid, 1, r["revision"], r["values"] | {"price": 70000}, "New draft correction"
        )
        kb.save_article(tmp_path, cid, aid, 1, "New guidance", "New draft instruction.")
        assert (
            tree(folder) == before and client.get(location + "/download").content == archive.content
        )
        assert pub.overview(tmp_path, cid)["warnings"]
        r = get_review(tmp_path, cid, 1)
        save_review(tmp_path, cid, 1, r["revision"], r["values"], r["notes"], "review_next")
        v2 = pub.publish(tmp_path, cid, pub.overview(tmp_path, cid)["fingerprint"])
        assert pub.get_publication(tmp_path, cid, v2)["version"] == 2
        assert tree(folder) == before
        with connect(tmp_path) as db:
            with pytest.raises(sqlite3.IntegrityError):
                db.execute("UPDATE publications SET version=4 WHERE id=?", (pid,))
    initialize(tmp_path)
    assert pub.get_publication(tmp_path, cid, pid)["manifest"] == manifest


def test_completion_exclusions_failed_pages_and_unresolved_suggestions(tmp_path):
    cid = reviewed(tmp_path, 2)
    with connect(tmp_path) as db:
        db.execute(
            "INSERT INTO jobs(collection_id,url,status,error) VALUES(?,?,'blocked','Access restricted')",
            (cid, "https://example.com/blocked"),
        )
    provider = provider_for()
    rid = kb.prepare(tmp_path, cid, provider, lesson="A reusable lesson")
    state = pub.overview(tmp_path, cid)
    assert len(state["pending"]) == 1 and not state["problems"]
    assert len(state["warnings"]) == 2
    pid = pub.publish(tmp_path, cid, state["fingerprint"])
    published = pub.get_publication(tmp_path, cid, pid)
    assert published["manifest"]["counts"]["omitted"] == 1
    assert published["manifest"]["counts"]["pending_knowledge"] == 1
    assert published["manifest"]["counts"]["articles"] == 0
    assert kb.get_request(tmp_path, cid, rid)["status"] == "preview"
    with TestClient(create_app(tmp_path)) as client:
        url = f"/collections/{cid}/publish"
        csrf = token(client.get(url))
        exclude = url + "/exclusions/3/exclude"
        assert client.post(exclude, data={"reason": "No access"}).status_code == 403
        assert client.post(exclude, data={"csrf": csrf, "reason": ""}).status_code == 400
        assert (
            client.post(
                exclude, data={"csrf": csrf, "reason": "Site access restricted."}
            ).status_code
            == 200
        )
        assert "Site access restricted." in client.get(url).text
        assert (
            client.post(
                "/collections/999/publish/exclusions/3/exclude",
                data={"csrf": csrf, "reason": "Wrong collection"},
            ).status_code
            == 404
        )
        kb.resolve(tmp_path, cid, rid, "dismiss")
        # Existing review exclusions also count, without a second exclusion decision.
        r = get_review(tmp_path, cid, 2)
        save_review(
            tmp_path, cid, 2, r["revision"], r["values"], r["notes"], "exclude", "Not relevant."
        )
        state = pub.overview(tmp_path, cid)
        assert state["included"] == 1 and state["excluded"] == 2 and not state["problems"]
        pid = pub.publish(tmp_path, cid, state["fingerprint"])
        manifest = pub.get_publication(tmp_path, cid, pid)["manifest"]
        decisions = json.loads(
            (
                tmp_path / pub.get_publication(tmp_path, cid, pid)["path"] / manifest["decisions"]
            ).read_text()
        )
        assert (
            len(decisions["excluded"]) == 2
            and decisions["knowledge_suggestions"][0]["status"] == "dismissed"
        )
        assert client.post(url + "/exclusions/2/include", data={"csrf": csrf}).status_code == 200
        assert get_review(tmp_path, cid, 2)["status"] == "needs_review"
        assert client.post(url + "/exclusions/3/include", data={"csrf": csrf}).status_code == 200
        assert pub.overview(tmp_path, cid)["excluded"] == 0


def test_stale_snapshot_missing_changed_sources_and_tampered_bundle(tmp_path):
    cid = reviewed(tmp_path, 1)
    state = pub.overview(tmp_path, cid)
    kb.save_article(tmp_path, cid, None, 0, "My instruction", "Preserve it.")
    with pytest.raises(pub.PublicationConflict, match="draft changed"):
        pub.publish(tmp_path, cid, state["fingerprint"])
    with connect(tmp_path) as db:
        capture = db.execute("SELECT * FROM captures").fetchone()
    folder = tmp_path / "sources" / "1" / capture["id"]
    original = (folder / "page.html").read_bytes()
    (folder / "page.html").write_bytes(b"Changed original")
    with pytest.raises(ValueError, match="differs"):
        pub.publish(tmp_path, cid, pub.overview(tmp_path, cid)["fingerprint"])
    assert list((tmp_path / "publications" / str(cid)).iterdir()) == []
    (folder / "page.html").write_bytes(original)
    screenshot = (folder / "screenshot.png").read_bytes()
    (folder / "screenshot.png").unlink()
    with pytest.raises(ValueError, match="missing"):
        pub.publish(tmp_path, cid, pub.overview(tmp_path, cid)["fingerprint"])
    (folder / "screenshot.png").write_bytes(screenshot)
    image = (folder / "image-1.png").read_bytes()
    (folder / "image-1.png").write_bytes(b"Changed image")
    with pytest.raises(ValueError, match="image changed"):
        pub.publish(tmp_path, cid, pub.overview(tmp_path, cid)["fingerprint"])
    (folder / "image-1.png").write_bytes(image)
    pid = pub.publish(tmp_path, cid, pub.overview(tmp_path, cid)["fingerprint"])
    p = pub.get_publication(tmp_path, cid, pid)
    output = tmp_path / p["path"]
    with TestClient(create_app(tmp_path)) as client:
        assert client.get(f"/collections/999/publications/{pid}").status_code == 404
        archive = output.with_suffix(".zip")
        archive.write_bytes(b"Broken zip")
        assert client.get(f"/collections/{cid}/publications/{pid}/download").status_code == 409
        (output / "examples.jsonl").write_text("Tampered")
        with pytest.raises(ValueError, match="checksum"):
            pub.validate_bundle(output)
        assert client.get(f"/collections/{cid}/publications/{pid}").status_code == 409


def test_invalid_values_media_paths_and_missing_knowledge_abort_atomically(tmp_path):
    cid = reviewed(tmp_path, 1)
    aid = kb.save_article(tmp_path, cid, None, 0, "Instructions", "Original instruction.")
    article = kb.article(tmp_path, cid, aid)
    (tmp_path / article["path"]).write_text("Unreviewed file edit")
    with pytest.raises(ValueError, match="knowledge revision"):
        pub.publish(tmp_path, cid, pub.overview(tmp_path, cid)["fingerprint"])
    (tmp_path / article["path"]).write_text(article["body"])
    with connect(tmp_path) as db:
        capture = db.execute("SELECT * FROM captures").fetchone()
        metadata = json.loads(capture["metadata"])
        metadata["images"][0]["file"] = "../../browser-profile/cookies"
        db.execute("UPDATE captures SET metadata=?", (json.dumps(metadata),))
    with pytest.raises(ValueError, match="invalid media"):
        pub.publish(tmp_path, cid, pub.overview(tmp_path, cid)["fingerprint"])
    with connect(tmp_path) as db:
        db.execute("UPDATE captures SET metadata=?", (capture["metadata"],))
        db.execute("UPDATE reviews SET values_json='{}'")
    from jsonschema import ValidationError

    with pytest.raises(ValidationError):
        pub.publish(tmp_path, cid, pub.overview(tmp_path, cid)["fingerprint"])
    assert not list((tmp_path / "publications").rglob("manifest.json"))


def test_schema_samples_and_excluded_knowledge_sources_remain_self_contained(tmp_path):
    import httpx2 as httpx

    from muster.extraction import Extractor, prepare_batch
    from muster.provider import SchemaProvider
    from muster.schema import (
        accept_schema,
        apply_suggestion,
        get_draft,
        prepare_request,
        send_request,
    )
    from tests.muster.test_extraction import provider_response
    from tests.muster.test_schema import FIELDS, SETTINGS, sources

    cid = sources(tmp_path, 2)
    with connect(tmp_path) as db:
        captures = db.execute("SELECT * FROM captures").fetchall()
    for c in captures:
        (tmp_path / "sources" / str(c["job_id"]) / c["id"] / "screenshot.png").write_bytes(png())
    schema_provider = SchemaProvider(
        SETTINGS, httpx.MockTransport(lambda request: provider_response({"fields": FIELDS}))
    )
    draft = get_draft(tmp_path, cid)
    rid = prepare_request(tmp_path, cid, draft["revision"], schema_provider)
    asyncio.run(send_request(tmp_path, cid, rid, schema_provider))
    draft = apply_suggestion(tmp_path, cid, rid)
    accept_schema(tmp_path, cid, draft["revision"])
    output = {
        "values": {"price": 90000, "currency": "EUR"},
        "evidence": {
            key: [{"source": "page", "quote": "90000 EUR"}] for key in ("price", "currency")
        },
        "uncertainty": {
            key: {"level": "stated", "note": "", "conflict": False} for key in ("price", "currency")
        },
    }
    provider = SchemaProvider(
        SETTINGS, httpx.MockTransport(lambda request: provider_response(output))
    )

    async def extract():
        worker = Extractor(tmp_path, provider)
        worker.start(prepare_batch(tmp_path, cid, provider))
        await worker.task

    asyncio.run(extract())
    for jid in (1, 2):
        r = get_review(tmp_path, cid, jid)
        save_review(tmp_path, cid, jid, r["revision"], r["values"], "", "review_next")
    knowledge_provider = provider_for()
    kr = kb.prepare(
        tmp_path,
        cid,
        knowledge_provider,
        job_id=2,
        lesson="Retain useful knowledge from an excluded example.",
    )
    asyncio.run(kb.send(tmp_path, cid, kr, knowledge_provider))
    suggestion = kb.get_request(tmp_path, cid, kr)["result"]
    kb.resolve(tmp_path, cid, kr, "accept", suggestion["title"], suggestion["body"])
    pub.exclude(tmp_path, cid, 2, "Useful guidance, but not a training example.")
    pid = pub.publish(tmp_path, cid, pub.overview(tmp_path, cid)["fingerprint"])
    result = pub.get_publication(tmp_path, cid, pid)
    folder = tmp_path / result["path"]
    assert result["manifest"]["counts"]["examples"] == 1
    assert {source["job_id"] for source in result["manifest"]["sources"]} == {1, 2}
    decisions = json.loads((folder / "provenance/decisions.json").read_text())
    assert decisions["schema"]["proposal"]["id"] == rid
    assert len(decisions["schema"]["proposal"]["payload"]["samples"]) == 2
    history = json.loads((folder / result["manifest"]["knowledge"][0]["provenance"]).read_text())
    assert history[0]["suggestion"]["job_id"] == 2


def test_publish_unreviewed_examples_preserves_status_and_pending_knowledge(tmp_path):
    cid = reviewed(tmp_path, 2)
    r = get_review(tmp_path, cid, 2)
    save_review(tmp_path, cid, 2, r["revision"], r["values"], "My draft judgment")
    provider = provider_for()
    rid = kb.prepare(
        tmp_path,
        cid,
        provider,
        lesson="Missing information lowers my valuation; it does not rule out a candidate.",
    )
    asyncio.run(kb.send(tmp_path, cid, rid, provider))
    state = pub.overview(tmp_path, cid)
    assert state["unreviewed"] == 1 and not state["problems"]
    with TestClient(create_app(tmp_path)) as client:
        url = f"/collections/{cid}/publish"
        page = client.get(url)
        assert "All included examples are reviewed" not in page.text
        assert "You can publish now" in page.text
        response = client.post(
            url, data={"csrf": token(page), "fingerprint": state["fingerprint"], "confirm": "yes"}
        )
        assert response.status_code == 200 and "v1 is ready" in response.text
        pid = response.url.path.rsplit("/", 1)[1]
    result = pub.get_publication(tmp_path, cid, pid)
    folder = tmp_path / result["path"]
    records = [json.loads(line) for line in (folder / "examples.jsonl").read_text().splitlines()]
    assert [r["review_status"] for r in records] == ["reviewed", "unreviewed"]
    assert records[1]["notes"] == "My draft judgment"
    assert result["manifest"]["counts"]["unreviewed"] == 1
    assert result["manifest"]["knowledge"] == []
    assert kb.get_request(tmp_path, cid, rid)["status"] == "suggested"
    assert get_review(tmp_path, cid, 2)["status"] == "needs_review"
    import subprocess
    import sys
    from pathlib import Path

    subprocess.run(
        [
            sys.executable,
            "-I",
            str(Path(__file__).resolve().parents[2] / "scripts/muster/check_bundle.py"),
            str(folder),
        ],
        check=True,
        cwd="/tmp",
    )


def test_existing_windows_publication_paths_open_and_download_without_changes(tmp_path):
    cid = reviewed(tmp_path, 1)
    pid = pub.publish(tmp_path, cid, pub.overview(tmp_path, cid)["fingerprint"])
    original = pub.get_publication(tmp_path, cid, pid)
    folder = tmp_path / original["path"]
    before = tree(folder)
    archive = folder.with_suffix(".zip").read_bytes()
    # Reproduce metadata written by older Windows versions, then restore immutability.
    with connect(tmp_path) as db:
        trigger = db.execute(
            "SELECT sql FROM sqlite_master WHERE name='publication_no_update'"
        ).fetchone()[0]
        db.execute("DROP TRIGGER publication_no_update")
        legacy = original["path"].replace("/", "\\")
        db.execute("UPDATE publications SET path=? WHERE id=?", (legacy, pid))
        db.execute(trigger)
    with TestClient(create_app(tmp_path)) as client:
        url = f"/collections/{cid}/publications/{pid}"
        response = client.get(url)
        assert response.status_code == 200 and "v1 is ready" in response.text
        assert client.get(url + "/download").content == archive
    assert tree(folder) == before
    with connect(tmp_path) as db:
        assert (
            db.execute("SELECT path FROM publications WHERE id=?", (pid,)).fetchone()[0] == legacy
        )
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE publications SET path=? WHERE id=?", (original["path"], pid))
    # Legacy compatibility must not allow escaping the expected publication directory.
    with pytest.raises(ValueError, match="Invalid bundle reference"):
        pub.safe_path(tmp_path, "sources\\1\\page.html")
    (folder / "schema.json").write_bytes(b"changed")
    with TestClient(create_app(tmp_path)) as client:
        response = client.get(url)
        assert response.status_code == 409
        assert "checksum" in response.json()["detail"]
