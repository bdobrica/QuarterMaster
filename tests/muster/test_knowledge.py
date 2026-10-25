import asyncio
import json

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient

from muster import knowledge as kb
from muster.app import create_app
from muster.provider import SchemaProvider
from muster.review import get_review, save_review
from muster.storage import connect, initialize
from tests.muster.test_app import token
from tests.muster.test_extraction import provider_response
from tests.muster.test_review import ready
from tests.muster.test_schema import SETTINGS


def provider_for(result=None, seen=None):
    def handler(request):
        body = json.loads(request.content)
        payload = json.loads(body["messages"][1]["content"])
        if seen is not None:
            seen.append((body, payload))
        return provider_response(
            result
            or {
                "title": "Price guidance",
                "body": "# Price guidance\n\nKeep asking prices separate from owner estimates.",
                "sources": [s["id"] for s in payload["sources"]],
            }
        )

    return SchemaProvider(SETTINGS, httpx.MockTransport(handler))


def test_initial_preview_consent_edit_diff_accept_markdown_and_restart(tmp_path):
    cid, _ = ready(tmp_path, 3)
    seen = []
    provider = provider_for(seen=seen)
    with TestClient(create_app(tmp_path, provider)) as client:
        csrf = token(client.get(f"/collections/{cid}/knowledge"))
        response = client.post(
            f"/collections/{cid}/knowledge/prepare",
            data={"csrf": csrf, "lesson": "Keep my estimates distinct."},
        )
        assert response.status_code == 200 and "Check before sending" in response.text
        assert not seen and kb.articles(tmp_path, cid) == []
        rid = kb.suggestions(tmp_path, cid)[0]["id"]
        url = f"/collections/{cid}/knowledge/suggestions/{rid}"
        response = client.post(url + "/send", data={"csrf": csrf})
        assert response.status_code == 403 and not seen
        response = client.post(url + "/send", data={"csrf": csrf, "consent": "yes"})
        assert response.status_code == 200 and "Needs your decision" in response.text
        assert (
            len(seen) == 1
            and len([s for s in seen[0][1]["sources"] if s["kind"] == "retained page"]) == 3
        )
        assert "image_url" not in json.dumps(seen)
        assert not kb.articles(tmp_path, cid)
        payload = {
            "csrf": csrf,
            "title": "My price guidance",
            "body": "# My price guidance\n\nKeep estimates distinct.\n\nUnknown is allowed.",
        }
        response = client.post(url + "/preview-edit", data=payload)
        assert response.status_code == 200 and "+Unknown is allowed." in response.text
        assert not kb.articles(tmp_path, cid)
        response = client.post(url + "/accept", data=payload)
        assert response.status_code == 200 and "Text you accepted" in response.text
        saved = kb.articles(tmp_path, cid)[0]
        assert saved["body"] == payload["body"]
        assert (tmp_path / saved["path"]).read_text() == payload["body"]
        assert client.post(url + "/accept", data=payload).status_code == 409
        assert (
            client.get(f"/collections/{cid}/knowledge/articles/{saved['id']}/download").text
            == saved["body"]
        )
        request = kb.get_request(tmp_path, cid, rid)
        assert request["consent_at"] and request["resolved_at"] and request["status"] == "accepted"
    with TestClient(create_app(tmp_path, provider)) as client:
        response = client.get(f"/collections/{cid}/knowledge/articles/{saved['id']}")
        assert (
            "Edited by you before acceptance" in response.text
            and "source evidence" in response.text
        )
        assert saved["body"] in response.text
    assert len(seen) == 1


def test_review_correction_both_and_knowledge_only_do_not_mutate_example(tmp_path):
    cid, _ = ready(tmp_path, 1)
    original = get_review(tmp_path, cid, 1)
    corrected = save_review(
        tmp_path,
        cid,
        1,
        original["revision"],
        original["values"] | {"price": 80000},
        "My estimate differs.",
        "review_next",
    )
    provider = provider_for()
    rid = kb.prepare(
        tmp_path, cid, provider, job_id=1, lesson="Distinguish estimates from asking prices."
    )
    request = kb.get_request(tmp_path, cid, rid)
    user = next(s for s in request["payload"]["sources"] if s["kind"] == "user review")
    assert user["corrections"]["price"]["value"] == 80000 and user["status"] == "reviewed"
    asyncio.run(kb.send(tmp_path, cid, rid, provider))
    result = kb.get_request(tmp_path, cid, rid)["result"]
    kb.resolve(tmp_path, cid, rid, "accept", result["title"], result["body"])
    assert get_review(tmp_path, cid, 1) == corrected
    # Knowledge-only: a separate instruction can produce a second proposal without editing fields/notes.
    other = kb.prepare(
        tmp_path, cid, provider, job_id=1, lesson="A lift matters to my preferences."
    )
    asyncio.run(kb.send(tmp_path, cid, other, provider))
    kb.resolve(tmp_path, cid, other, "dismiss")
    assert get_review(tmp_path, cid, 1) == corrected and len(kb.articles(tmp_path, cid)) == 1
    with TestClient(create_app(tmp_path, provider)) as client:
        response = client.get(f"/collections/{cid}/review/1")
        assert (
            "Knowledge for this example" in response.text and f"/suggestions/{rid}" in response.text
        )


def test_existing_article_diff_dismiss_stale_review_and_article_conflicts(tmp_path):
    cid, _ = ready(tmp_path, 1)
    provider = provider_for()
    aid = kb.save_article(
        tmp_path,
        cid,
        None,
        0,
        "My instructions",
        "# Instructions\n\nNever treat my estimate as the asking price.",
    )
    old = kb.article(tmp_path, cid, aid)
    rid = kb.prepare(tmp_path, cid, provider, aid, 1)
    asyncio.run(kb.send(tmp_path, cid, rid, provider))
    suggestion = kb.get_request(tmp_path, cid, rid)
    assert "-Never treat" in kb.diff(suggestion)
    kb.resolve(tmp_path, cid, rid, "dismiss")
    assert kb.article(tmp_path, cid, aid) == old
    rid = kb.prepare(tmp_path, cid, provider, aid, 1)
    asyncio.run(kb.send(tmp_path, cid, rid, provider))
    kb.save_article(
        tmp_path,
        cid,
        aid,
        old["revision"],
        "My instructions",
        old["body"] + "\n\nPreserve my new instruction.",
    )
    with pytest.raises(kb.KnowledgeConflict):
        kb.resolve(tmp_path, cid, rid, "accept", "AI replacement", "Wrong replacement")
    with pytest.raises(kb.KnowledgeConflict):
        kb.save_article(tmp_path, cid, aid, old["revision"], "Stale tab", "Lost user edits")
    assert "Preserve my new instruction." in kb.article(tmp_path, cid, aid)["body"]
    rid2 = kb.prepare(tmp_path, cid, provider, job_id=1)
    record = get_review(tmp_path, cid, 1)
    save_review(tmp_path, cid, 1, record["revision"], record["values"], "Changed after preview")
    with pytest.raises(kb.KnowledgeConflict):
        asyncio.run(kb.send(tmp_path, cid, rid2, provider))
    kb.resolve(tmp_path, cid, rid2, "dismiss")


def test_invalid_model_sources_failed_request_retry_and_interruption(tmp_path):
    cid, _ = ready(tmp_path, 1)
    bad = provider_for(
        {"title": "Unsupported", "body": "Unsupported claim", "sources": ["capture:invented"]}
    )
    rid = kb.prepare(tmp_path, cid, bad)
    asyncio.run(kb.send(tmp_path, cid, rid, bad))
    assert kb.get_request(tmp_path, cid, rid)["status"] == "failed" and not kb.articles(
        tmp_path, cid
    )
    good = provider_for()
    asyncio.run(kb.send(tmp_path, cid, rid, good))
    assert kb.get_request(tmp_path, cid, rid)["status"] == "suggested"
    rid2 = kb.prepare(tmp_path, cid, good)
    with connect(tmp_path) as db:
        db.execute("UPDATE knowledge_requests SET status='sending' WHERE id=?", (rid2,))
    initialize(tmp_path)
    assert kb.get_request(tmp_path, cid, rid2)["status"] == "failed"
    assert kb.get_request(tmp_path, cid, rid)["status"] == "suggested"


def test_changed_source_and_changed_connection_never_send(tmp_path):
    cid, _ = ready(tmp_path, 1)
    seen = []
    provider = provider_for(seen=seen)
    rid = kb.prepare(tmp_path, cid, provider, job_id=1)
    request = kb.get_request(tmp_path, cid, rid)
    source = next(s for s in request["payload"]["sources"] if s["kind"] == "retained page")
    path = tmp_path / "sources" / "1" / source["capture_id"] / "page.html"
    path.write_text("Changed original")
    asyncio.run(kb.send(tmp_path, cid, rid, provider))
    assert not seen and kb.get_request(tmp_path, cid, rid)["status"] == "failed"
    from muster.provider import ProviderSettings

    other = SchemaProvider(ProviderSettings("http://127.0.0.1:9876/v1", "other-model"))
    with pytest.raises(kb.KnowledgeConflict):
        asyncio.run(kb.send(tmp_path, cid, rid, other))
    assert not seen


def test_manual_articles_no_provider_safe_text_and_collection_isolation(tmp_path):
    cid, _ = ready(tmp_path, 1)
    with TestClient(create_app(tmp_path)) as client:
        csrf = token(client.get(f"/collections/{cid}/knowledge/new"))
        body = '# Preferences\n\n<script>alert("bad")</script>\n\nUser judgment wins.'
        response = client.post(
            f"/collections/{cid}/knowledge/save",
            data={
                "csrf": csrf,
                "revision": 0,
                "title": "Preferences",
                "body": body.replace("\n", "\r\n"),
            },
        )
        assert (
            response.status_code == 200
            and "&lt;script&gt;" in response.text
            and "<script>alert" not in response.text
        )
        aid = kb.articles(tmp_path, cid)[0]["id"]
        assert client.get(f"/collections/999/knowledge/articles/{aid}").status_code == 404
        assert client.get("/collections/999/knowledge").status_code == 404
        assert (
            client.post(
                f"/collections/{cid}/knowledge/save", data={"revision": 1, "body": "Bypass"}
            ).status_code
            == 403
        )
        response = client.post(
            f"/collections/{cid}/knowledge/save",
            data={
                "csrf": csrf,
                "article_id": aid,
                "revision": 0,
                "title": "Stale",
                "body": "Keep my typed text",
            },
        )
        assert response.status_code == 409 and "Keep my typed text" in response.text
        assert kb.article(tmp_path, cid, aid)["body"] == body
        assert client.get(f"/collections/{cid}/knowledge?job_id=bad").status_code == 400


def test_late_response_cannot_replace_new_user_instruction(tmp_path):
    cid, _ = ready(tmp_path, 1)
    aid = kb.save_article(tmp_path, cid, None, 0, "Preferences", "Preserve this instruction.")

    def handler(request):
        kb.save_article(tmp_path, cid, aid, 1, "Preferences", "New user instruction while waiting.")
        return provider_response(
            {"title": "Bad replacement", "body": "Old stale content", "sources": ["guidance"]}
        )

    provider = SchemaProvider(SETTINGS, httpx.MockTransport(handler))
    rid = kb.prepare(tmp_path, cid, provider, aid)
    asyncio.run(kb.send(tmp_path, cid, rid, provider))
    with pytest.raises(kb.KnowledgeConflict):
        kb.resolve(tmp_path, cid, rid, "accept", "Bad replacement", "Old stale content")
    assert kb.article(tmp_path, cid, aid)["body"] == "New user instruction while waiting."
