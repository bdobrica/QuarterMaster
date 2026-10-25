"""Readable versions and reviews do not weaken immutable evidence or holdouts."""

import pytest
from fastapi.testclient import TestClient

from quartermaster import answer_reviews
from quartermaster.app import create_app
from quartermaster.contracts.reviews import AnswerReviewInput
from quartermaster.db import connect
from quartermaster.print_demo import seed
from tests import test_teaching


def test_review_reserved_failure_without_teaching(settings):
    project, suite = seed(settings)
    test_id = suite.cases[0].test_id
    with TestClient(create_app(settings)) as client:
        url = f"/api/projects/{project.id}/tests/{test_id}/review"
        assert client.post(url, json={"expected_revision": 0, "status": "pass"}).status_code == 422
        for revision, status in enumerate(["fail", "pending"]):
            response = client.post(
                url,
                json={
                    "expected_revision": revision,
                    "status": status,
                    "correction": "Ask about the missing approval.",
                },
            )
            assert response.status_code == 200, response.text
            assert response.json()["revision"] == revision + 1
        assert client.post(url, json={"expected_revision": 0, "status": "fail"}).status_code == 409
        assert (
            client.post(
                url, json={"expected_revision": 2, "status": "fail", "extra": 1}
            ).status_code
            == 422
        )
        assert client.post(url, json={"status": "fail"}).status_code == 422
        assert (
            client.post(
                url,
                json={"expected_revision": 2, "status": "fail"},
                headers={"Origin": "https://evil.example"},
            ).status_code
            == 403
        )
        page = client.get(f"/projects/{project.id}/test?test_id={test_id}")
        assert page.status_code == 200
        assert "Correct this answer" in page.text
        assert "Pending review" in page.text
    with connect(settings.database_path) as connection:
        assert connection.execute("SELECT count(*) FROM answer_reviews").fetchone()[0] == 2
        assert connection.execute("SELECT count(*) FROM feedback").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM lesson_revisions").fetchone()[0] == 0


def test_review_project_isolation(settings):
    project, suite = seed(settings)
    from uuid import uuid4

    from quartermaster.errors import DomainError

    with pytest.raises(DomainError):
        answer_reviews.save(
            settings,
            uuid4(),
            suite.cases[0].test_id,
            AnswerReviewInput(expected_revision=0, status="fail"),
        )


def test_readable_knowledge(settings):
    project, _ = seed(settings)
    with TestClient(create_app(settings)) as client:
        response = client.get(f"/projects/{project.id}/knowledge")
        assert response.status_code == 200
        assert "v1.0.0" in response.text
        assert "data-local-time" in response.text
        assert "local-time.js" in response.text
        assert "Current" in response.text


workshop = test_teaching.workshop


def test_saved_question_rerun_preview_preserves_history_and_exclusions(workshop):
    client, project, inference, _, config = workshop
    from tests.test_teaching import ask

    run = ask(workshop, "A new order has confirmed copy but approval is unknown.")
    url = f"/projects/{project}/tests/{run['id']}/save-question"
    response = client.post(
        url,
        data={"expectation": "Ask only whether proof approval exists."},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200
    assert "Saved check questions" in response.text
    from quartermaster.saved_questions import rows

    question = rows(config, project)[0]
    entry = question["entry"]
    rerun = f"/projects/{project}/improvements/rerun"
    calls = len(inference.calls)
    response = client.post(
        rerun, data={"question_ids": str(entry.id)}, headers={"Origin": "http://testserver"}
    )
    assert response.status_code == 200 and "Run 1 requests" in response.text
    assert len(inference.calls) == calls
    assert (
        client.post(
            rerun, data={"question_ids": "unknown"}, headers={"Origin": "http://testserver"}
        ).status_code
        == 422
    )
    response = client.post(
        rerun,
        data={"question_ids": str(entry.id), "confirm": "yes"},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200
    assert len(inference.calls) == calls + 1
    question = rows(config, project)[0]
    assert len(question["history"]) == 2
    assert str(question["run"].id) != run["id"]
    assert question["status"] == "pending"
    # A rerun gets a new ID but still cannot evade the training exclusion.
    response = client.post(
        f"/api/projects/{project}/tests/{question['run'].id}/feedback",
        json={"category": "should_ask", "correction": "Ask about approval."},
    )
    assert response.status_code == 409


def test_failed_answer_correction_is_pending_until_review(workshop):
    client, project, inference, _, config = workshop
    from uuid import UUID

    from quartermaster import teaching
    from tests.test_teaching import ask, base, prepare

    inference.error = "LOCAL_CONNECTION: Start the local model."
    run = ask(workshop)
    response = client.post(
        base(project) + f"/tests/{run['id']}/feedback",
        json={"category": "wrong_call", "correction": "Explain when the service is unavailable."},
    )
    assert response.status_code == 200
    lesson = response.json()
    assert lesson["status"] == "pending"
    assert not any(
        item.status == "applied" for item in teaching.latest_lessons(config, UUID(project))
    )
    lesson = prepare(workshop, lesson)
    import json

    context = json.loads(lesson["disclosure"]["context"])
    assert context["advice"] is None and context["response_error"] == run["error"]
    assert "observed_outcome" not in context["case"]


def test_individual_evaluation_reviews_do_not_create_teaching(workshop):
    from tests.test_evaluations import create, freeze, run_suite, save

    client, project, *_ = workshop
    suite = freeze(workshop, save(workshop, create(workshop)))
    run = run_suite(workshop, suite)
    output = run["outputs"][0]
    key = f"{output['case_id']}:{output['variant']}"
    url = f"/projects/{project}/answers/evaluation/{run['id']}/{key}/review"
    response = client.post(
        url,
        data={"expected_revision": "0", "status": "fail", "correction": "Check the relevant fact."},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200
    assert "Reviewed: Fail" in response.text
    assert "Correct this answer" in response.text


def test_v8_migration_adds_reviews_without_changing_source_history(settings):
    from quartermaster.db import migrate

    seed(settings)
    with connect(settings.database_path) as connection:
        original = [tuple(row) for row in connection.execute("SELECT * FROM knowledge_revisions")]
        connection.execute("DROP TABLE answer_reviews")
        connection.execute("PRAGMA user_version=8")
    migrate(settings.database_path)
    migrate(settings.database_path)
    with connect(settings.database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 9
        assert [
            tuple(row) for row in connection.execute("SELECT * FROM knowledge_revisions")
        ] == original


def test_guided_training_captures_reviewed_checks_and_default_recipe(workshop):
    from tests.test_evaluations import create, save, suite_path
    from tests.test_training import approve, new_example, set_target

    client, project, *_ = workshop
    example = approve(workshop, set_target(workshop, new_example(workshop)))
    suite = save(workshop, create(workshop))
    response = client.post(
        suite_path(workshop, suite, "review"),
        json={
            "expected_revision": suite["revision"],
            "approved": True,
            "note": "Reviewed this independent check question and expected behavior.",
        },
    )
    assert response.status_code == 200
    suite = response.json()
    assert suite["status"] == "draft"
    response = client.post(
        f"/projects/{project}/training-runs",
        data={
            "example_ids": example["id"],
            "suite": f"{suite['id']}:{suite['revision']}",
            "acknowledge_small_data": "yes",
        },
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200, response.text
    assert client.get(suite_path(workshop, suite)).json()["status"] == "frozen"
    runs = client.get(f"/api/projects/{project}/training-runs").json()
    assert len(runs) == 1 and runs[0]["status"] == "queued"
    # Queueing does not execute any GPU work or change the active model.
    assert client.get(f"/api/projects/{project}").json()["model"]["adapter_artifact"] is None
