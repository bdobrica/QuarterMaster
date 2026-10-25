"""Atomic typed feedback capture and derived teaching selection. No provider or GPU work."""

from datetime import UTC, datetime
from uuid import uuid5

from quartermaster.contracts.prediction import (
    PredictionReview,
    PredictionRun,
    ReviewedDecision,
    ReviewedExample,
)
from quartermaster.db import connect
from quartermaster.errors import DomainError
from quartermaster.holdouts import require_eligible
from quartermaster.projects import read_spec, require_target


def read_run(connection, project_id, run_id):
    read_spec(connection, project_id)
    row = connection.execute(
        "SELECT document FROM prediction_runs WHERE id=? AND project_id=?",
        (str(run_id), str(project_id)),
    ).fetchone()
    if row is None:
        raise DomainError("PREDICTION_MISSING: Choose an answer from this adviser.", 404)
    return PredictionRun.model_validate_json(row[0])


def history(settings, project_id):
    with connect(settings.database_path) as connection:
        read_spec(connection, project_id)
        return [
            PredictionReview.model_validate_json(row[0])
            for row in connection.execute(
                "SELECT document FROM prediction_reviews WHERE project_id=? ORDER BY rowid",
                (str(project_id),),
            )
        ]


def eligible(connection, project_id, case):
    try:
        require_eligible(connection, project_id, [case])
        return True
    except DomainError as exc:
        if exc.message.startswith(("EVALUATION_HELD_OUT:", "EVALUATION_NEAR_DUPLICATE:")):
            return False
        raise


def save(settings, project_id, run_id, action):
    with connect(settings.database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        run = read_run(connection, project_id, run_id)
        row = connection.execute(
            "SELECT document FROM prediction_reviews WHERE answer_id=? "
            "ORDER BY revision DESC LIMIT 1",
            (str(run_id),),
        ).fetchone()
        previous = PredictionReview.model_validate_json(row[0]) if row else None
        revision = previous.revision if previous else 0
        if previous and action == previous.submission:
            return previous  # An identical retry after a lost response is idempotent.
        if revision != action.expected_revision:
            raise DomainError(
                "REVIEW_CHANGED: Reload this answer before saving another review.", 409
            )
        target = action.target
        if action.action == "accept":
            prediction = run.result.prediction
            if run.result.error or prediction is None or prediction.target is None:
                raise DomainError(
                    "REVIEW_NO_ANSWER: Correct this response with your own answer instead."
                )
            target = prediction.target
        if target is not None:
            require_target(
                run.adviser.model_copy(update={"answer_format": run.input.answer_format}), target
            )
        reasoning = action.reasoning
        if action.action == "accept" and not reasoning:
            reasoning = run.result.prediction.explanation
        record = PredictionReview(
            project_id=project_id,
            prediction_id=run_id,
            revision=revision + 1,
            created_at=datetime.now(UTC),
            submission=action,
            target=target,
            reasoning=reasoning,
            teaching_eligible=target is not None
            and eligible(connection, project_id, run.input.case),
        )
        connection.execute(
            "INSERT INTO prediction_reviews VALUES (?, ?, ?, ?)",
            (str(run_id), str(project_id), record.revision, record.model_dump_json()),
        )
    return record


def teaching(settings, project_id):
    # Notes and skips carry no target. They never approve a prediction or erase an
    # earlier explicit judgment. Latest explicit targets supersede previous ones.
    latest = {}
    for review in history(settings, project_id):
        if review.target is not None:
            latest[review.prediction_id] = review
    result = []
    with connect(settings.database_path) as connection:
        for review in latest.values():
            run = read_run(connection, project_id, review.prediction_id)
            if not review.teaching_eligible or not eligible(connection, project_id, run.input.case):
                continue
            decision = ReviewedDecision(
                id=uuid5(
                    project_id if hasattr(project_id, "bytes") else run.project_id, str(run.id)
                ),
                project_id=project_id,
                prediction_id=run.id,
                revision=review.revision,
                created_at=review.created_at,
                target=review.target,
                reasoning=review.reasoning,
            )
            result.append(
                ReviewedExample(
                    input=run.input.case, owner_decision=decision, run=run, review=review
                )
            )
    return result
