"""Typed feedback is durable supervision; notes/checks never become labels."""

import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from quartermaster import prediction_reviews, predictions, training
from quartermaster.app import create_app
from quartermaster.db import connect, migrate
from quartermaster.holdouts import case_fingerprint
from quartermaster.projects import get_adviser
from tests.test_muster_integration import collection as collection
from tests.test_predictions import CATEGORY, NUMBER, Adapter, selection, setup


def ask(client, project, fmt=NUMBER, text="A quiet apartment near transit, 62 square metres"):
    result = client.post(
        f"/api/projects/{project}/predictions",
        json={
            "situation": text,
            "answer_format": fmt,
        },
    )
    assert result.status_code == 200, result.text
    return result.json()


def review(client, project, run, action, revision=0, **extra):
    return client.post(
        f"/api/projects/{project}/predictions/{run['id']}/reviews",
        json={
            "expected_revision": revision,
            "action": action,
            **extra,
        },
    )


@pytest.mark.parametrize("fmt", [NUMBER, CATEGORY])
def test_review_to_teaching_and_training_survives_restart(client, settings, collection, fmt):
    project, item, target = setup(settings, collection, fmt)
    client.app.state.inference = Adapter(target)
    run = ask(client, project, fmt)
    accepted = review(client, project, run, "accept")
    assert accepted.status_code == 200
    assert accepted.json()["teaching_eligible"]
    assert review(client, project, run, "accept").json() == accepted.json()
    corrected = dict(target, value=71000.0 if fmt == NUMBER else "Decline")
    correction = review(
        client,
        project,
        run,
        "correct",
        1,
        target=corrected,
        reasoning="My personal preference; no market benchmark needed.",
    )
    assert correction.status_code == 200
    assert review(client, project, run, "skip", 0).status_code == 409
    assert (
        review(client, project, run, "note", 2, reasoning="Keep this distinction").status_code
        == 200
    )
    assert review(client, project, run, "skip", 3).status_code == 200
    assert len(prediction_reviews.history(settings, project)) == 4
    evidence = prediction_reviews.teaching(settings, project)
    assert len(evidence) == 1 and evidence[0].owner_decision.target.model_dump() == corrected
    assert evidence[0].run.model_dump(mode="json") == run
    assert evidence[0].owner_decision.revision == 2
    frozen = predictions.prepare(settings, project, item.id, selection(settings, project, fmt))
    job = training.read_job(settings, frozen)
    assert job.teaching.schema_version.endswith("/v2")
    assert len(job.examples) == 2
    assert job.examples[-1].target.target.model_dump() == corrected
    before = (training.directory(settings, frozen.id) / "input/job.json").read_bytes()
    with TestClient(create_app(settings, inference=Adapter(target))) as restarted:
        assert "Keep this distinction" in restarted.get(f"/projects/{project}/review").text
        assert "My personal preference" in restarted.get(f"/projects/{project}/teach").text
        assert len(prediction_reviews.teaching(settings, project)) == 1
    assert (training.directory(settings, frozen.id) / "input/job.json").read_bytes() == before
    # Future revisions never rewrite already frozen supervision.
    assert review(client, project, run, "correct", 4, target=target).status_code == 200
    assert training.read_job(settings, frozen) == job


def test_notes_skips_failures_and_reserved_checks(client, settings, collection):
    project, item, target = setup(settings, collection)
    client.app.state.inference = Adapter(target, fail="error")
    failed = ask(client, project)
    assert review(client, project, failed, "accept").status_code == 422
    assert review(client, project, failed, "note", reasoning="Try again").status_code == 200
    assert review(client, project, failed, "skip", 1).status_code == 200
    assert not prediction_reviews.teaching(settings, project)
    assert review(client, project, failed, "correct", 2, target=target).status_code == 200
    assert len(prediction_reviews.teaching(settings, project)) == 1
    held_case = predictions.history(settings, project)[0].input.case
    with connect(settings.database_path) as db:
        db.execute(
            "INSERT INTO evaluation_holdouts VALUES (?, ?, ?, ?)",
            (str(project), str(held_case.case_id), case_fingerprint(held_case), str(uuid4())),
        )
    assert not prediction_reviews.teaching(settings, project)
    assert not predictions.related(
        settings, project, held_case, selection(settings, project).answer_format
    )
    # Exact copied cases cannot bypass the reservation by changing their IDs/casing.
    client.app.state.inference = Adapter(target)
    copied = ask(client, project, text="  A QUIET apartment near transit, 62 square metres  ")
    saved = review(client, project, copied, "correct", target=target)
    assert saved.status_code == 200 and not saved.json()["teaching_eligible"]
    assert not prediction_reviews.teaching(settings, project)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"expected_revision": 0, "action": "note"},
        {
            "expected_revision": 0,
            "action": "skip",
            "target": {"kind": "number", "value": 2, "unit": "EUR"},
        },
        {"expected_revision": 0, "action": "accept", "extra": True},
        {"expected_revision": 0, "action": "correct"},
    ],
)
def test_invalid_reviews_add_no_records(client, settings, collection, payload):
    project, _, target = setup(settings, collection)
    client.app.state.inference = Adapter(target)
    run = ask(client, project)
    result = client.post(f"/api/projects/{project}/predictions/{run['id']}/reviews", json=payload)
    assert result.status_code == 422
    assert prediction_reviews.history(settings, project) == []


def test_review_scope_and_wrong_target(client, settings, collection, project_fixture):
    project, _, target = setup(settings, collection)
    client.app.state.inference = Adapter(target)
    run = ask(client, project)
    other = client.post("/api/projects", json=project_fixture).json()["id"]
    assert review(client, other, run, "accept").status_code == 404
    assert (
        review(client, project, run, "correct", target=dict(target, unit="hours")).status_code
        == 409
    )
    assert not prediction_reviews.history(settings, project)


def test_configure_once_and_reuse_in_owner_forms(client, settings, collection):
    project, item, target = setup(settings, collection)
    spec = get_adviser(settings.database_path, project)
    result = client.post(
        f"/projects/{project}/answer-format",
        data={
            "expected_revision": spec.revision,
            "kind": "number",
            "unit": "EUR",
            "choices": "",
        },
        headers={"Origin": "http://testserver"},
    )
    assert result.status_code == 200
    spec = get_adviser(settings.database_path, project)
    assert spec.answer_format.unit == "EUR"
    result = client.post(
        f"/projects/{project}/answer-format",
        data={
            "expected_revision": spec.revision,
            "kind": "number",
            "unit": "hours",
            "choices": "",
        },
        headers={"Origin": "http://testserver"},
    )
    assert result.status_code == 409
    client.app.state.inference = Adapter(target)
    result = client.post(
        f"/projects/{project}/ask",
        data={"situation": "Another apartment"},
        headers={"Origin": "http://testserver"},
    )
    assert result.status_code == 200
    assert '<select name="kind"' not in result.text
    assert '<input id="unit"' not in result.text
    result = client.get(f"/projects/{project}/teach/{item.id}/examples/0")
    assert '<input name="unit"' not in result.text
    assert 'value="currency" checked' in result.text
    assert (
        client.post(
            f"/api/projects/{project}/predictions",
            json={
                "situation": "Another situation",
                "answer_format": {"kind": "number", "unit": "hours"},
            },
        ).status_code
        == 409
    )


def test_v11_migration_preserves_every_existing_document(client, settings, collection):
    project, _, target = setup(settings, collection)
    client.app.state.inference = Adapter(target)
    ask(client, project)
    with connect(settings.database_path) as db:
        tables = [
            r[0]
            for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT IN ('prediction_reviews','collection_projects')"
            )
        ]
        before = {t: [tuple(r) for r in db.execute(f'SELECT * FROM "{t}"')] for t in tables}
        db.execute("DROP TABLE prediction_reviews")
        db.execute("DROP TABLE collection_projects")
        db.execute("PRAGMA user_version=11")
    migrate(settings.database_path)
    with connect(settings.database_path) as db:
        assert before == {t: [tuple(r) for r in db.execute(f'SELECT * FROM "{t}"')] for t in tables}


@pytest.mark.parametrize("configured", [False, True])
def test_related_preferences_are_distinct_from_sources(client, settings, collection, configured):
    project, _, target = setup(settings, collection)
    if configured:
        from quartermaster.contracts.answers import NumberAnswer
        from quartermaster.projects import configure_answer

        spec = get_adviser(settings.database_path, project)
        configure_answer(
            settings.database_path, project, NumberAnswer(kind="number", unit="EUR"), spec.revision
        )
    adapter = Adapter(target)
    client.app.state.inference = adapter
    first = ask(client, project)
    review(client, project, first, "correct", target=target, reasoning="I value quiet surroundings")
    ask(client, project, text="A quiet apartment with a balcony")
    context = json.loads(adapter.calls[-1]["context"])
    preferences = context[
        "previous_owner_decisions" if configured else "reviewed_owner_preferences"
    ]
    evidence = context["source_excerpts" if configured else "retrieved_evidence"]
    assert preferences[0]["reasoning"] == "I value quiet surroundings"
    assert "preference" in preferences[0]["meaning"]
    assert evidence
    assert all("reasoning" not in source for source in evidence)
    assert "Earlier personal judgments used" in client.get(f"/projects/{project}/ask").text
    reply = client.get(f"/projects/{project}/knowledge?review={first['id']}")
    assert "Scope: describe when this preference should apply" in reply.text


def test_conflicting_nearby_review_is_visible_without_overwriting_history(
    client, settings, collection
):
    project, _, target = setup(settings, collection)
    client.app.state.inference = Adapter(target)
    first = ask(client, project)
    assert review(client, project, first, "correct", target=target).status_code == 200
    second = ask(client, project)
    changed = dict(target, value=69000.0)
    assert review(client, project, second, "correct", target=changed).status_code == 200
    page = client.get(f"/projects/{project}/review")
    assert "You made a different choice in a similar situation" in page.text
    assert len(prediction_reviews.teaching(settings, project)) == 2
    from quartermaster.errors import DomainError

    with pytest.raises(DomainError, match="TEACHING_DUPLICATE"):
        predictions.prepare(settings, project, None, selection(settings, project))
