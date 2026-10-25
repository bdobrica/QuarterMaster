"""Append-only answer reviews; never create lessons or training inputs."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

from quartermaster.contracts.reviews import AnswerReview
from quartermaster.db import connect
from quartermaster.errors import DomainError
from quartermaster.projects import read_spec
from quartermaster.teaching import get_test


def history(settings, project_id):
    with connect(settings.database_path) as connection:
        read_spec(connection, project_id)
        rows = connection.execute(
            "SELECT document FROM answer_reviews WHERE project_id=? ORDER BY rowid",
            (str(project_id),),
        ).fetchall()
    return [AnswerReview.model_validate_json(row[0]) for row in rows]


def reviews(settings, project_id):
    return {str(review.answer_id): review for review in history(settings, project_id)}


def answer_id(kind, run_id, key=""):
    return (
        run_id if kind == "test" else uuid5(NAMESPACE_URL, f"quartermaster/{kind}/{run_id}/{key}")
    )


def resolve(settings, project_id, kind, run_id, key):
    if kind == "test" and not key:
        return get_test(settings, project_id, run_id)
    from quartermaster import evaluations, reliability, training

    output = None
    if kind == "evaluation":
        run = evaluations.get_run(settings, project_id, run_id)
        output = next((o for o in run.outputs if f"{o.case_id}:{o.variant}" == key), None)
    elif kind == "candidate":
        run = training.get_version(settings, project_id, run_id)
        for pair in run.comparisons:
            for label in ("baseline", "candidate"):
                if key == f"{pair.case_id}:{label}":
                    output = getattr(pair, label)
    elif kind == "diagnostic":
        run = reliability.get_run(settings, project_id, run_id)
        output = next((o for o in run.outputs if o.arm == key), None)
    if output is None:
        raise DomainError("REVIEW_MISSING: Open a completed answer from this project.", 404)
    return SimpleNamespace(
        id=answer_id(kind, run_id, key), error=output.error, advice=output.advice
    )


def save(settings, project_id, test_id, action, *, kind="test", key=""):
    run = resolve(settings, project_id, kind, test_id, key)
    if action.status == "pass" and (run.error or run.advice is None):
        raise DomainError(
            "REVIEW_FAILED: This response failed to produce advice. Choose Fail or Pending."
        )
    with connect(settings.database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        revision = connection.execute(
            "SELECT coalesce(max(revision), 0) FROM answer_reviews WHERE answer_id=?",
            (str(run.id),),
        ).fetchone()[0]
        if revision != action.expected_revision:
            raise DomainError("REVIEW_STALE: Reload this answer before reviewing it again.", 409)
        record = AnswerReview(
            project_id=project_id,
            answer_id=run.id,
            source_kind=kind,
            source_id=test_id,
            source_key=key,
            revision=revision + 1,
            created_at=datetime.now(UTC),
            **action.model_dump(),
        )
        connection.execute(
            "INSERT INTO answer_reviews VALUES (?, ?, ?, ?)",
            (str(run.id), str(project_id), record.revision, record.model_dump_json()),
        )
    return record
