import asyncio
import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from quartermaster import evaluations, teaching
from quartermaster.contracts.advice import Case
from quartermaster.contracts.evaluation import EvaluationRun, EvaluationSuite, SuiteAction
from quartermaster.db import SCHEMA_VERSION, connect, migrate
from quartermaster.errors import DomainError
from quartermaster.holdouts import case_fingerprint, require_eligible
from quartermaster.inference import response_schema
from quartermaster.sources import blob_path
from tests import test_teaching
from tests.test_foundation import select_knowledge, upload
from tests.test_teaching import ask, base, correct, draft, prepare, review, send

workshop = test_teaching.workshop

FIXTURE = json.loads((Path(__file__).parent / "fixtures/evaluation.json").read_text())


def create(workshop, name="Holdouts"):
    client, project, *_ = workshop
    response = client.post(base(project) + "/evaluation-suites", json={"name": name})
    assert response.status_code == 200, response.text
    return response.json()


def suite_path(workshop, suite, action=""):
    return (
        base(workshop[1]) + f"/evaluation-suites/{suite['id']}" + (f"/{action}" if action else "")
    )


def save(workshop, suite, run=None, index=1):
    run = run or ask(workshop, FIXTURE["cases"][index]["situation"])
    result = workshop[0].post(
        suite_path(workshop, suite, "cases"),
        json={
            "expected_revision": suite["revision"],
            "test_id": run["id"],
            "rubric": FIXTURE["cases"][index]["rubric"],
        },
    )
    assert result.status_code == 200, result.text
    return result.json()


def freeze(workshop, suite):
    result = workshop[0].post(
        suite_path(workshop, suite, "freeze"), json={"expected_revision": suite["revision"]}
    )
    assert result.status_code == 200, result.text
    return result.json()


def run_suite(workshop, suite):
    result = workshop[0].post(
        suite_path(workshop, suite, "run"), json={"expected_revision": suite["revision"]}
    )
    assert result.status_code == 200, result.text
    return result.json()


def run_path(workshop, run, suffix=""):
    return base(workshop[1]) + f"/evaluation-runs/{run['id']}" + suffix


def rate(workshop, run, entry, preference="b_better", expected=0):
    return workshop[0].post(
        run_path(workshop, run, f"/ratings/{entry['id']}"),
        json={
            "expected_revision": expected,
            "preference": preference,
            "category": "should_ask",
            "rationale": "  Asking for damage is preferable.\n No business outcome observed.  ",
        },
    )


def test_freeze_rerun_review_loop_preserves_active_adviser(workshop):
    client, project, inference, builder, config = workshop
    source = upload(
        client, project, FIXTURE["knowledge_a"].encode(), "tools.md", "knowledge"
    ).json()
    knowledge = select_knowledge(client, project, [source["id"]]).json()
    before = client.get(base(project)).json()
    suite = save(workshop, create(workshop))
    draft_revision = suite.copy()
    suite = freeze(workshop, suite)
    assert suite["status"] == "frozen"
    assert suite["source_hashes"] == {source["id"]: source["sha256"]}
    assert client.get(suite_path(workshop, suite), params={"revision": 2}).json() == draft_revision
    pair = suite["inputs"][0]
    assert pair["a"]["model_alias"] == pair["b"]["model_alias"]
    assert pair["a"]["parameters"] == pair["b"]["parameters"]
    a, b = json.loads(pair["a"]["context"]), json.loads(pair["b"]["context"])
    assert "mission" not in a and a["retrieved_evidence"] == []
    assert b["mission"] == before["mission"] and b["retrieved_evidence"]
    assert pair["b"]["adviser"]["knowledge_revision"] == knowledge["id"]
    for item in (pair["a"], pair["b"]):
        assert item["response_schema"] == response_schema(item["context"])
        assert "rubric" not in item["context"] and "expected_behavior" not in item["context"]
        assert "observed_outcome" not in item["context"]
    inference.calls.clear()
    run = run_suite(workshop, suite)
    assert run["status"] == "completed" and len(run["outputs"]) == 2
    assert run["weight_improvement_assessed"] is False
    assert len(inference.calls) == 2 and builder.calls == []
    assert all(o["checks"]["schema_valid"] for o in run["outputs"])
    assert all(o["checks"]["citations_valid"] for o in run["outputs"])
    assert all(o["checks"]["expected_behavior_passed"] is False for o in run["outputs"])
    assert all(o["checks"]["unsupported_recommendation"] for o in run["outputs"])
    first_calls = inference.calls.copy()
    select_knowledge(client, project, [], knowledge["id"])
    second = run_suite(workshop, suite)
    assert inference.calls[2:] == first_calls
    assert second["outputs"][1]["advice"] == run["outputs"][1]["advice"]
    assert client.get(run_path(workshop, run)).json() == run
    initial = client.get(run_path(workshop, run), params={"revision": 1}).json()
    assert initial["status"] == "running" and initial["outputs"] == []
    assert rate(workshop, run, suite["cases"][0]).status_code == 200
    ratings = client.get(run_path(workshop, run, "/ratings")).json()
    assert ratings[0]["rationale"].startswith("  ") and ratings[0]["rationale"].endswith("  ")
    assert rate(workshop, run, suite["cases"][0]).status_code == 409
    assert rate(workshop, run, suite["cases"][0], "a_better", 1).status_code == 200
    with connect(config.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM evaluation_ratings").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM feedback").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM lesson_revisions").fetchone()[0] == 0
    page = client.get(f"/projects/{project}/evaluations?run_id={run['id']}")
    assert page.status_code == 200
    assert "0 improved · 1 regressed" in page.text
    assert "A · Base only" in page.text and "B · Base plus context" in page.text
    assert "causal business lift" in page.text and "lines 1–" in page.text
    # Only the explicit knowledge edit changed adviser state; evaluation never does.
    assert client.get(base(project)).json()["lessons_revision"] == before["lessons_revision"]


def test_all_preference_counts_separate_and_unreviewed(workshop):
    client, project, *_ = workshop
    suite = create(workshop)
    for index in range(5):
        suite = save(workshop, suite, ask(workshop, f"Unseen case {index}; damage status unknown."))
    suite = freeze(workshop, suite)
    run = run_suite(workshop, suite)
    for entry, preference in zip(
        suite["cases"], ["b_better", "a_better", "same", "both_bad"], strict=False
    ):
        assert rate(workshop, run, entry, preference).status_code == 200
    reviews = evaluations.ratings(workshop[-1], UUID(project), UUID(run["id"]))
    summary = evaluations.summary(
        EvaluationSuite.model_validate_json(json.dumps(suite)),
        EvaluationRun.model_validate_json(json.dumps(run)),
        reviews,
    )
    assert {
        k: summary[k] for k in ("improved", "regressed", "same", "both_bad", "unreviewed")
    } == dict.fromkeys(("improved", "regressed", "same", "both_bad", "unreviewed"), 1)
    assert client.get(f"/projects/{project}/evaluations?run_id={run['id']}").status_code == 200


def test_holdout_blocks_feedback_and_training_selection_including_copies(workshop):
    client, project, inference, builder, config = workshop
    original = ask(workshop, FIXTURE["cases"][1]["situation"])
    suite = save(workshop, create(workshop), original)
    copy = ask(workshop, "  " + original["case"]["situation"].upper().replace(" ", "  "))
    for test in (original, copy):
        result = client.post(
            base(project) + f"/tests/{test['id']}/feedback",
            json={"category": "wrong_call", "correction": "Use for training"},
        )
        assert result.status_code == 409 and "EVALUATION_HELD_OUT" in result.text
        case = Case.model_validate_json(json.dumps({**test["case"], "observed_outcome": "later"}))
        with (
            connect(config.database_path) as connection,
            pytest.raises(DomainError, match="EVALUATION_HELD_OUT"),
        ):
            require_eligible(connection, project, [case])
    with connect(config.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM feedback").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM lesson_revisions").fetchone()[0] == 0
        safe = Case(case_id=uuid4(), situation="A distinct training candidate.")
        require_eligible(connection, project, [safe])
    assert builder.calls == [] and suite["cases"][0]["held_out"]


def test_already_taught_situation_cannot_be_reserved_as_unseen(workshop):
    client, *_ = workshop
    original = ask(workshop)
    correct(workshop, original)
    copy = ask(workshop, original["case"]["situation"].lower())
    suite = create(workshop)
    for run in (original, copy):
        result = client.post(
            suite_path(workshop, suite, "cases"),
            json={
                "expected_revision": 1,
                "test_id": run["id"],
                "rubric": FIXTURE["cases"][1]["rubric"],
            },
        )
        assert result.status_code == 409 and "EVALUATION_TAUGHT" in result.text


def test_freeze_locks_membership_and_rejects_stale_actions(workshop):
    client, *_ = workshop
    empty = create(workshop)
    assert (
        client.post(
            suite_path(workshop, empty, "freeze"), json={"expected_revision": 1}
        ).status_code
        == 422
    )
    suite = save(workshop, empty)
    assert (
        client.post(
            suite_path(workshop, suite, "freeze"), json={"expected_revision": 1}
        ).status_code
        == 409
    )
    assert (
        client.post(suite_path(workshop, suite, "run"), json={"expected_revision": 2}).status_code
        == 409
    )
    original = client.get(suite_path(workshop, suite)).json()
    suite = freeze(workshop, suite)
    for action in ("freeze", "run"):
        assert (
            client.post(
                suite_path(workshop, suite, action), json={"expected_revision": 2}
            ).status_code
            == 409
        )
    result = client.post(
        suite_path(workshop, suite, "cases"),
        json={
            "expected_revision": 3,
            "test_id": original["cases"][0]["test_id"],
            "rubric": FIXTURE["cases"][1]["rubric"],
        },
    )
    assert result.status_code == 409


@pytest.mark.parametrize(
    "mode", ["clarify", "recommend", "abstain", "citation", "quote", "json", "timeout", "exception"]
)
def test_deterministic_checks_and_durable_failures(workshop, mode):
    client, project, inference, *_ = workshop
    suite = freeze(workshop, save(workshop, create(workshop)))
    entry = suite["cases"][0]
    if mode == "clarify":
        inference.response = draft(question="Is damage reported?", missing=["damage status"])
    elif mode == "abstain":
        inference.response = draft().model_copy(update={"behavior": "abstain"})
    elif mode == "citation":
        inference.response = draft(refs=[str(uuid4())], quotes=[entry["case"]["situation"]])
    elif mode == "quote":
        inference.response = draft(quotes=["A fact that does not appear in the situation"])
    elif mode == "json":
        inference.response = object()
    elif mode in {"timeout", "exception"}:

        def fail():
            raise TimeoutError() if mode == "timeout" else RuntimeError("sensitive case text")

        inference.hook = fail
    run = run_suite(workshop, suite)
    assert run["status"] == "completed" and len(run["outputs"]) == 2
    for output in run["outputs"]:
        checks = output["checks"]
        if mode in {"clarify", "recommend", "abstain"}:
            assert output["error"] is None
            assert checks["behavior"] == mode
            assert checks["expected_behavior_passed"] == (mode == "clarify")
            assert checks["unsupported_recommendation"] == (mode == "recommend")
        else:
            assert output["error"] and "sensitive case text" not in output["error"]
            assert output["advice"] is None and checks["expected_behavior_passed"] is False
            if mode == "citation":
                assert checks["citations_valid"] is False
            elif mode == "quote":
                assert checks["schema_valid"] and checks["citations_valid"]
                assert checks["supporting_facts_valid"] is False
            else:
                assert checks["schema_valid"] is False
    assert client.get(run_path(workshop, run)).json() == run


def test_context_changes_are_never_claimed_as_training_lift(workshop):
    client, project, *_ = workshop
    first = upload(client, project, FIXTURE["knowledge_a"].encode(), "tools.md", "knowledge").json()
    old_knowledge = select_knowledge(client, project, [first["id"]]).json()
    first_suite = freeze(workshop, save(workshop, create(workshop, "Before knowledge change")))
    first_run = run_suite(workshop, first_suite)
    second = upload(
        client, project, FIXTURE["knowledge_b"].encode(), "tools-new.md", "knowledge"
    ).json()
    select_knowledge(client, project, [second["id"]], old_knowledge["id"])
    second_suite = freeze(workshop, save(workshop, create(workshop, "After knowledge change")))
    second_run = run_suite(workshop, second_suite)
    assert first_suite["source_hashes"] != second_suite["source_hashes"]
    scope = evaluations.comparison_scope(
        EvaluationSuite.model_validate_json(json.dumps(first_suite)),
        EvaluationSuite.model_validate_json(json.dumps(second_suite)),
    )
    assert scope["frozen_inputs_changed"] and not scope["weight_improvement_assessed"]
    page = client.get(f"/projects/{project}/evaluations?run_id={second_run['id']}")
    assert "confound a weight comparison" in page.text
    assert "weights do not change" in page.text
    assert client.get(run_path(workshop, first_run)).json() == first_run


def test_recovery_retains_checkpoints_and_does_not_retry(workshop):
    client, project, inference, *_ = workshop
    suite = freeze(workshop, save(workshop, create(workshop)))
    run = run_suite(workshop, suite)
    config = workshop[-1]
    parsed = EvaluationRun.model_validate_json(json.dumps(run))
    evaluations.checkpoint(config, parsed, status="running", outputs=parsed.outputs[:1])
    before = len(inference.calls)
    evaluations.recover_evaluations(config)
    evaluations.recover_evaluations(config)
    latest = client.get(run_path(workshop, run)).json()
    assert latest["status"] == "interrupted" and len(latest["outputs"]) == 1
    assert len(inference.calls) == before
    assert rate(workshop, latest, suite["cases"][0]).status_code == 409
    new_run = run_suite(workshop, suite)
    assert new_run["id"] != run["id"] and len(inference.calls) == before + 2


def test_cancellation_and_total_timeout_are_durable(workshop, monkeypatch):
    _, project, inference, *_ = workshop
    suite = freeze(workshop, save(workshop, create(workshop)))
    config = workshop[-1]
    inference.calls.clear()

    async def cancel(*, system, context):
        inference.calls.append(context)
        raise asyncio.CancelledError

    inference.advise = cancel
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            evaluations.run_suite(
                config,
                inference,
                UUID(project),
                UUID(suite["id"]),
                SuiteAction(expected_revision=suite["revision"]),
            )
        )
    assert evaluations.list_runs(config, UUID(project))[0].status == "interrupted"
    assert len(inference.calls) == 1

    async def slow(*, system, context):
        await asyncio.sleep(10)

    inference.advise = slow
    monkeypatch.setattr(evaluations, "RUN_SECONDS", 0.01)
    result = asyncio.run(
        evaluations.run_suite(
            config,
            inference,
            UUID(project),
            UUID(suite["id"]),
            SuiteAction(expected_revision=suite["revision"]),
        )
    )
    assert result.status == "interrupted" and result.outputs == []


def test_runtime_mismatch_hash_tampering_and_missing_source_fail_closed(workshop):
    client, project, inference, _, config = workshop
    source = upload(
        client, project, FIXTURE["knowledge_a"].encode(), "tools.md", "knowledge"
    ).json()
    select_knowledge(client, project, [source["id"]])
    suite = freeze(workshop, save(workshop, create(workshop)))
    calls = len(inference.calls)
    original_sha = config.local_model_sha256
    config.local_model_sha256 = "b" * 64
    assert (
        client.post(
            suite_path(workshop, suite, "run"), json={"expected_revision": suite["revision"]}
        ).status_code
        == 409
    )
    config.local_model_sha256 = original_sha
    assert len(inference.calls) == calls
    parsed = EvaluationSuite.model_validate_json(json.dumps(suite))
    bad = parsed.model_copy(update={"name": "tampered"})
    with pytest.raises(DomainError, match="EVALUATION_INTEGRITY"):
        evaluations.verify_frozen(bad)
    blob_path(config.artifact_root, source["sha256"]).unlink()
    run = run_suite(workshop, suite)
    assert run["outputs"][0]["error"] is None
    assert run["outputs"][1]["error"] and run["outputs"][1]["advice"] is None
    assert len(inference.calls) == calls + 1


def test_outcomes_and_owner_rubric_never_enter_requests(workshop):
    client, project, inference, _, config = workshop
    run = ask(workshop, FIXTURE["cases"][1]["situation"])
    # Model an imported Case carrying an optional separate outcome. Only the fixture
    # setup edits this row; application test/evaluation APIs never update history.
    run["case"]["observed_outcome"] = "PRIVATE_LATER_OUTCOME"
    with connect(config.database_path) as connection:
        connection.execute(
            "UPDATE test_runs SET document=? WHERE id=?", (json.dumps(run), run["id"])
        )
    suite = freeze(workshop, save(workshop, create(workshop), run))
    inference.calls.clear()
    result = run_suite(workshop, suite)
    assert suite["cases"][0]["case"]["observed_outcome"] == "PRIVATE_LATER_OUTCOME"
    assert all("PRIVATE_LATER_OUTCOME" not in json.dumps(call) for call in inference.calls)
    assert all("expected_behavior" not in json.dumps(call) for call in inference.calls)
    assert (
        "PRIVATE_LATER_OUTCOME"
        in client.get(f"/projects/{project}/evaluations?run_id={result['id']}").text
    )


def test_api_and_form_scope_validation_and_escaping(workshop):
    client, project, *_ = workshop
    suite = save(workshop, create(workshop, "<script>bad()</script>"))
    other = client.post(
        "/api/projects", json={"name": "Other", "mission": "A different mission"}
    ).json()["id"]
    assert client.get(base(other) + f"/evaluation-suites/{suite['id']}").status_code == 404
    assert client.get(f"/projects/{project}/test").status_code == 200
    assert client.get(f"/projects/{project}/evaluations").text.count("&lt;script&gt;") >= 1
    for payload in ({}, {"name": ""}, {"name": "x", "extra": True}, {"name": 1}):
        assert client.post(base(project) + "/evaluation-suites", json=payload).status_code == 422
    assert (
        client.post(
            base(project) + "/evaluation-suites",
            json={"name": "Cross-site"},
            headers={"Origin": "https://hostile.example"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/projects/{project}/evaluation-suites",
            data={"name": "Cross-site"},
            headers={"Origin": "https://hostile.example"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            suite_path(workshop, suite, "freeze"), json={"expected_revision": "2"}
        ).status_code
        == 422
    )
    frozen = freeze(workshop, suite)
    run = run_suite(workshop, frozen)
    assert client.get(base(other) + f"/evaluation-runs/{run['id']}").status_code == 404
    assert client.get(f"/projects/{other}/evaluations?run_id={run['id']}").status_code == 404
    assert (
        client.post(
            run_path(workshop, run, f"/ratings/{frozen['cases'][0]['id']}"),
            json={
                "expected_revision": 0,
                "preference": "b_better",
                "category": "should_ask",
                "rationale": "x",
                "observed_outcome": "business lift",
            },
        ).status_code
        == 422
    )
    for contract, document in ((EvaluationSuite, frozen), (EvaluationRun, run)):
        with pytest.raises(ValidationError):
            contract.model_validate_json(json.dumps({**document, "extra": "bad"}))
        parsed = contract.model_validate_json(json.dumps(document))
        with pytest.raises(ValidationError):
            parsed.revision = 99


def test_populated_v4_migration_preserves_all_old_rows_and_originals(workshop):
    client, project, *_, config = workshop
    source = upload(
        client, project, FIXTURE["knowledge_a"].encode(), "tools.md", "knowledge"
    ).json()
    select_knowledge(client, project, [source["id"]])
    correct(workshop)
    tables = (
        "projects",
        "adviser_revisions",
        "sources",
        "case_mappings",
        "derived_cases",
        "knowledge_revisions",
        "knowledge_members",
        "chunks",
        "chunks_fts",
        "interview_revisions",
        "test_runs",
        "feedback",
        "lesson_revisions",
    )

    def snapshot(connection):
        return {
            table: [
                tuple(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY rowid")
            ]
            for table in tables
        }

    original = blob_path(config.artifact_root, source["sha256"]).read_bytes()
    with connect(config.database_path) as connection:
        before = snapshot(connection)
        for table in (
            "training_examples",
            "training_runs",
            "adviser_versions",
            "evaluation_suites",
            "evaluation_runs",
            "evaluation_ratings",
            "evaluation_holdouts",
        ):
            connection.execute(f"DROP TABLE {table}")
        connection.execute("PRAGMA user_version=4")
    migrate(config.database_path)
    migrate(config.database_path)
    with connect(config.database_path) as connection:
        assert snapshot(connection) == before
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 6
    assert blob_path(config.artifact_root, source["sha256"]).read_bytes() == original


def test_reviewed_lesson_snapshot_and_active_adviser_remain_unchanged(workshop):
    client, project, inference, *_ = workshop
    lesson = correct(workshop, ask(workshop, "Mixer inspection is current; condition is unknown."))
    lesson = review(workshop, send(workshop, prepare(workshop, lesson)))
    suite = freeze(workshop, save(workshop, create(workshop)))
    pair = suite["inputs"][0]
    assert pair["a"]["lessons"] == []
    assert pair["b"]["lessons"][0]["id"] == lesson["id"]
    before = client.get(base(project)).json()
    inference.calls.clear()
    run = run_suite(workshop, suite)
    assert not run["outputs"][0]["checks"]["expected_behavior_passed"]
    assert run["outputs"][1]["checks"]["expected_behavior_passed"]
    assert rate(workshop, run, suite["cases"][0]).status_code == 200
    assert client.get(base(project)).json() == before
    # A later unrelated approved correction cannot alter an earlier suite's request.
    new = correct(workshop, ask(workshop, "A new polisher scenario requiring review."))
    review(workshop, send(workshop, prepare(workshop, new)))
    inference.calls.clear()
    run_suite(workshop, suite)
    assert len(inference.calls[1][1]["approved_lessons"]) == 1
    assert inference.calls[1][1]["approved_lessons"][0]["id"] == lesson["id"]


def test_holdout_cannot_enter_a_prepared_builder_request(workshop):
    client, project, _, builder, config = workshop
    original = ask(workshop)
    lesson = prepare(workshop, correct(workshop, original))
    # Defence for imported/legacy state. Normal save_case rejects this taught case.
    case = Case.model_validate_json(json.dumps(original["case"]))
    with connect(config.database_path) as connection:
        connection.execute(
            "INSERT INTO evaluation_holdouts VALUES (?, ?, ?, ?)",
            (project, str(case.case_id), case_fingerprint(case), original["id"]),
        )
    path = base(project) + f"/lessons/{lesson['id']}"
    assert (
        client.post(path + "/prepare", json={"expected_revision": lesson["revision"]}).status_code
        == 409
    )
    result = client.post(
        path + "/send",
        json={
            "expected_revision": lesson["revision"],
            "turn_id": lesson["id"],
            "disclosure_sha256": lesson["disclosure"]["disclosure_sha256"],
            "consent": True,
        },
    )
    assert result.status_code == 409 and "EVALUATION_HELD_OUT" in result.text
    assert builder.calls == []
    assert (
        teaching.get_lesson(config, UUID(project), UUID(lesson["id"])).revision
        == lesson["revision"]
    )


def test_busy_evaluation_does_not_issue_another_request(workshop):
    client, _, inference, *_ = workshop
    suite = freeze(workshop, save(workshop, create(workshop)))
    run = run_suite(workshop, suite)
    parsed = EvaluationRun.model_validate_json(json.dumps(run))
    evaluations.checkpoint(workshop[-1], parsed, status="running")
    count = len(inference.calls)
    response = client.post(
        suite_path(workshop, suite, "run"), json={"expected_revision": suite["revision"]}
    )
    assert response.status_code == 409 and "EVALUATION_BUSY" in response.text
    assert len(inference.calls) == count


def test_membership_bound_duplicates_and_atomic_holdout_creation(workshop):
    client, _, _, _, config = workshop
    suite = create(workshop)
    original = ask(workshop, "Distinct situation 0.")
    suite = save(workshop, suite, original)
    body = {
        "expected_revision": suite["revision"],
        "test_id": original["id"],
        "rubric": FIXTURE["cases"][1]["rubric"],
    }
    assert client.post(suite_path(workshop, suite, "cases"), json=body).status_code == 409
    for index in range(1, 10):
        suite = save(workshop, suite, ask(workshop, f"Distinct situation {index}."))
    extra = ask(workshop, "One too many holdouts.")
    body.update(expected_revision=suite["revision"], test_id=extra["id"])
    assert client.post(suite_path(workshop, suite, "cases"), json=body).status_code == 409
    with connect(config.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM evaluation_holdouts").fetchone()[0] == 10
        require_eligible(
            connection, workshop[1], [Case.model_validate_json(json.dumps(extra["case"]))]
        )


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"expected_behavior": "unknown", "expectation": "x"},
        {"expected_behavior": "clarify", "expectation": ""},
        {"expected_behavior": "clarify", "expectation": "x", "extra": True},
    ],
)
def test_invalid_rubric_does_not_reserve_case(workshop, bad):
    client, _, _, _, config = workshop
    suite = create(workshop)
    original = ask(workshop)
    response = client.post(
        suite_path(workshop, suite, "cases"),
        json={"expected_revision": suite["revision"], "test_id": original["id"], "rubric": bad},
    )
    assert response.status_code == 422
    with connect(config.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM evaluation_holdouts").fetchone()[0] == 0
