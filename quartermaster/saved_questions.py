"""A table view of existing protected questions and immutable advice runs."""

from quartermaster import answer_reviews, evaluations, teaching
from quartermaster.contracts.teaching import TestRun
from quartermaster.db import connect
from quartermaster.holdouts import case_fingerprint


def rows(settings, project_id):
    suites = evaluations.list_suites(settings, project_id)
    with connect(settings.database_path) as connection:
        records = connection.execute(
            "SELECT document FROM test_runs WHERE project_id=? ORDER BY rowid DESC",
            (str(project_id),),
        ).fetchall()
    runs = [TestRun.model_validate_json(row[0]) for row in records]
    ratings = answer_reviews.reviews(settings, project_id)
    result, seen = [], set()
    for suite in suites:
        for entry in suite.cases:
            fingerprint = case_fingerprint(entry.case)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            history = [run for run in runs if case_fingerprint(run.case) == fingerprint]
            latest = (
                history[0] if history else teaching.get_test(settings, project_id, entry.test_id)
            )
            rating = ratings.get(str(latest.id))
            result.append(
                {
                    "entry": entry,
                    "suite": suite,
                    "run": latest,
                    "history": history,
                    "status": rating.status if rating else "pending",
                }
            )
    return result


def save_question(settings, project_id, action):
    from quartermaster.contracts.evaluation import SuiteCreate

    with connect(settings.database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        suite = next(
            (
                s
                for s in evaluations.list_suites(settings, project_id)
                if s.name == "Saved questions" and s.status == "draft" and len(s.cases) < 10
            ),
            None,
        )
        if suite is None:
            suite = evaluations.create_suite(
                settings, project_id, SuiteCreate(name="Saved questions"), connection=connection
            )
        action = action.model_copy(update={"expected_revision": suite.revision})
        return evaluations.save_case(settings, project_id, suite.id, action, connection=connection)
