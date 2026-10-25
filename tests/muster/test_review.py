import asyncio
import json
from copy import deepcopy

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient

from muster.app import create_app
from muster.extraction import Extractor, prepare_batch
from muster.provider import SchemaProvider
from muster.review import ReviewConflict, get_review, review_list, save_review
from muster.storage import connect
from tests.muster.test_app import token
from tests.muster.test_extraction import extracted, provider_response, setup
from tests.muster.test_schema import SETTINGS


def ready(root, count=3):
    collection = setup(root, count)

    def handler(request):
        payload = json.loads(json.loads(request.content)["messages"][1]["content"][0]["text"])
        result = extracted(payload)
        result["values"]["price"] = (
            90000 + int(payload["page"]["source_url"].rsplit("/", 1)[1]) * 1000
        )
        return provider_response(result)

    provider = SchemaProvider(SETTINGS, httpx.MockTransport(handler))

    async def run():
        worker = Extractor(root, provider)
        worker.start(prepare_batch(root, collection, provider))
        await worker.task

    asyncio.run(run())
    return collection, provider


def form(csrf, review, action="autosave", values=None, notes=None, reason=None):
    values = review["values"] if values is None else values
    result = {
        "csrf": csrf,
        "revision": str(review["revision"]),
        "action": action,
        "notes": review["notes"] if notes is None else notes,
        "exclusion_reason": review["exclusion_reason"] if reason is None else reason,
    }
    for field in review["payload"]["fields"]:
        key = field["key"]
        value = values[key]
        if value is None:
            result["unknown:" + key] = "yes"
        else:
            result["value:" + key] = (
                "yes"
                if value is True
                else "no"
                if value is False
                else "\n".join(value)
                if isinstance(value, list)
                else str(value)
            )
    return result


def test_review_twenty_values_filter_sort_and_save_next(tmp_path):
    collection, provider = ready(tmp_path, 20)
    listing = review_list(tmp_path, collection, {})
    assert len(listing["rows"]) == 20
    assert listing["counts"]["needs_review"] == 20
    sorted_rows = review_list(tmp_path, collection, {"sort": "field:price", "direction": "desc"})[
        "rows"
    ]
    assert [row["values"]["price"] for row in sorted_rows] == list(range(109000, 89999, -1000))
    first = get_review(tmp_path, collection, 1)
    original = deepcopy(first["result"])
    with TestClient(create_app(tmp_path, provider)) as client:
        csrf = token(client.get(f"/collections/{collection}/review/1"))
        for index in range(1, 21):
            review = get_review(tmp_path, collection, index)
            values = review["values"] | ({"price": 88000, "year": 1985} if index in (1, 2) else {})
            response = client.post(
                f"/collections/{collection}/review/{index}?status=needs_review",
                data=form(
                    csrf,
                    review,
                    "review_next",
                    values,
                    notes="Human correction" if index in (1, 2) else "",
                ),
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert (
                f"/review/{index + 1}?" in response.headers["location"]
                if index < 20
                else "/review?" in response.headers["location"]
            )
        assert review_list(tmp_path, collection, {"status": "needs_review"})["rows"] == []
        assert len(review_list(tmp_path, collection, {"status": "reviewed"})["rows"]) == 20
        assert len(review_list(tmp_path, collection, {"q": "Human correction"})["rows"]) == 2
    after = get_review(tmp_path, collection, 1)
    assert after["result"] == original
    assert after["values"]["price"] == 88000
    assert after["corrections"]["price"]["source"] == "user"
    assert after["reviewed_at"]
    with TestClient(create_app(tmp_path, provider)) as client:
        assert "88000" in client.get(f"/collections/{collection}/review/1").text
        assert "20 reviewed" in client.get(f"/collections/{collection}/review").text


def test_autosave_keeps_draft_and_edits_reopen_review(tmp_path):
    collection, provider = ready(tmp_path)
    with TestClient(create_app(tmp_path, provider)) as client:
        csrf = token(client.get(f"/collections/{collection}/review/1"))
        review = get_review(tmp_path, collection, 1)
        payload = form(
            csrf, review, values=review["values"] | {"price": 0}, notes="Keep my judgment."
        )
        response = client.post(
            f"/collections/{collection}/review/1",
            data=payload,
            headers={"Accept": "application/json"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "needs_review"
        review = get_review(tmp_path, collection, 1)
        assert review["values"]["price"] == 0
        assert review["notes"] == "Keep my judgment."
        response = client.post(
            f"/collections/{collection}/review/1",
            data=form(csrf, review, "review_next"),
            headers={"Accept": "application/json"},
        )
        assert response.json()["status"] == "reviewed"
        review = get_review(tmp_path, collection, 1)
        response = client.post(
            f"/collections/{collection}/review/1",
            data=form(csrf, review, notes="New judgment."),
            headers={"Accept": "application/json"},
        )
        assert response.json()["status"] == "needs_review"
        assert get_review(tmp_path, collection, 1)["reviewed_at"] is None


def test_stale_tab_invalid_types_and_exclusion_do_not_lose_saved_values(tmp_path):
    collection, provider = ready(tmp_path)
    with TestClient(create_app(tmp_path, provider)) as client:
        csrf = token(client.get(f"/collections/{collection}/review/1"))
        review = get_review(tmp_path, collection, 1)
        response = client.post(
            f"/collections/{collection}/review/1",
            data=form(csrf, review, notes="First tab wins."),
            headers={"Accept": "application/json"},
        )
        assert response.status_code == 200
        response = client.post(
            f"/collections/{collection}/review/1",
            data=form(csrf, review, notes="Stale tab."),
            headers={"Accept": "application/json"},
        )
        assert response.status_code == 409
        assert get_review(tmp_path, collection, 1)["notes"] == "First tab wins."
        review = get_review(tmp_path, collection, 1)
        bad = form(csrf, review)
        bad["value:price"] = "not a number"
        response = client.post(
            f"/collections/{collection}/review/1", data=bad, headers={"Accept": "application/json"}
        )
        assert response.status_code == 400 and response.json()["field"] == "price"
        assert get_review(tmp_path, collection, 1)["revision"] == review["revision"]
        response = client.post(
            f"/collections/{collection}/review/1",
            data=form(csrf, review, "exclude"),
            headers={"Accept": "application/json"},
        )
        assert response.status_code == 400
        response = client.post(
            f"/collections/{collection}/review/1",
            data=form(csrf, review, "exclude", reason="Duplicate property."),
            headers={"Accept": "application/json"},
        )
        assert response.json()["status"] == "excluded"
        review = get_review(tmp_path, collection, 1)
        assert (
            review_list(tmp_path, collection, {"status": "excluded"})["rows"][0]["exclusion_reason"]
            == "Duplicate property."
        )
        response = client.post(
            f"/collections/{collection}/review/1",
            data=form(csrf, review, "include"),
            headers={"Accept": "application/json"},
        )
        assert response.json()["status"] == "needs_review"
        assert (
            client.get(f"/collections/{collection}/review?sort=field:invented").status_code == 400
        )
        assert client.get(f"/collections/{collection}/review/999").status_code == 404


def test_new_model_attempt_never_replaces_human_review(tmp_path):
    collection, provider = ready(tmp_path, 1)
    review = get_review(tmp_path, collection, 1)
    saved = save_review(
        tmp_path,
        collection,
        1,
        review["revision"],
        review["values"] | {"price": 75000},
        "Owner judgment.",
        "review_next",
    )

    async def run():
        worker = Extractor(tmp_path, provider)
        worker.start(prepare_batch(tmp_path, collection, provider, 1))
        await worker.task

    asyncio.run(run())
    current = get_review(tmp_path, collection, 1)
    assert current["extraction_id"] == saved["extraction_id"]
    assert current["values"]["price"] == 75000
    assert current["status"] == "reviewed"
    assert current["newer_id"] and current["newer_id"] != current["extraction_id"]
    with TestClient(create_app(tmp_path, provider)) as client:
        assert (
            "Your corrections and review status are preserved"
            in client.get(f"/collections/{collection}/review/1").text
        )


def test_navigation_still_works_when_autosave_removes_current_search_match(tmp_path):
    collection, provider = ready(tmp_path)
    with TestClient(create_app(tmp_path, provider)) as client:
        csrf = token(client.get(f"/collections/{collection}/review/1"))
        review = get_review(tmp_path, collection, 1)
        values = review["values"] | {"notes": "Changed the matching field."}
        client.post(
            f"/collections/{collection}/review/1?q=quiet",
            data=form(csrf, review, values=values),
            headers={"Accept": "application/json"},
        )
        # Search also includes original input context, so use a uniquely added review note for a true disappearing match.
        for job_id in (1, 2, 3):
            record = get_review(tmp_path, collection, job_id)
            save_review(
                tmp_path,
                collection,
                job_id,
                record["revision"],
                record["values"],
                "temporary-match",
            )
        review = get_review(tmp_path, collection, 1)
        client.post(
            f"/collections/{collection}/review/1?q=temporary-match",
            data=form(csrf, review, notes="No match now."),
            headers={"Accept": "application/json"},
        )
        review = get_review(tmp_path, collection, 1)
        response = client.post(
            f"/collections/{collection}/review/1?q=temporary-match",
            data=form(csrf, review, "next"),
            headers={"Accept": "application/json"},
        )
        assert "/review/2?" in response.json()["redirect"]


def test_list_distinguishes_uncollected_failed_and_extraction_states(tmp_path):
    collection, provider = ready(tmp_path, 1)
    with connect(tmp_path) as db:
        db.execute(
            "INSERT INTO jobs(collection_id,url,status,error) VALUES(?,?,'failed','Blocked visit')",
            (collection, "https://example.com/failed"),
        )
        db.execute(
            "INSERT INTO jobs(collection_id,url,status) VALUES(?,?,'queued')",
            (collection, "https://example.com/waiting"),
        )
        db.execute(
            "INSERT INTO jobs(collection_id,url,status) VALUES(?,?,'captured')",
            (collection, "https://example.com/not-extracted"),
        )
    listing = review_list(tmp_path, collection, {})
    assert {row["state"] for row in listing["rows"]} == {
        "needs_review",
        "failed",
        "queued",
        "captured",
    }


def test_duplicate_unload_save_is_idempotent_but_different_stale_values_conflict(tmp_path):
    collection, _ = ready(tmp_path, 1)
    review = get_review(tmp_path, collection, 1)
    saved = save_review(
        tmp_path,
        collection,
        1,
        review["revision"],
        review["values"],
        "Last edit before reload.",
        "autosave",
    )
    replay = save_review(
        tmp_path,
        collection,
        1,
        review["revision"],
        review["values"],
        "Last edit before reload.",
        "autosave",
    )
    assert replay["revision"] == saved["revision"]
    with pytest.raises(ReviewConflict):
        save_review(
            tmp_path,
            collection,
            1,
            review["revision"],
            review["values"],
            "Different stale draft.",
            "autosave",
        )


def test_typed_controls_keep_false_zero_lists_and_explicit_unknown():
    from starlette.datastructures import FormData

    from muster.review import ReviewInputError, form_values

    fields = [
        {"key": key, "label": key, "type": kind}
        for key, kind in [
            ("amount", "number"),
            ("rooms", "integer"),
            ("lift", "boolean"),
            ("date", "date"),
            ("tags", "text_list"),
            ("opinion", "text"),
        ]
    ]
    data = FormData(
        {
            "value:amount": "0",
            "value:rooms": "0",
            "value:lift": "no",
            "value:date": "2026-10-25",
            "value:tags": "quiet\n\nneeds work",
            "unknown:opinion": "yes",
        }
    )
    values = form_values(fields, data)
    assert values == {
        "amount": 0,
        "rooms": 0,
        "lift": False,
        "date": "2026-10-25",
        "tags": ["quiet", "needs work"],
        "opinion": None,
    }
    with pytest.raises(ReviewInputError):
        form_values(fields, FormData(dict(data) | {"value:rooms": "1.5"}))
