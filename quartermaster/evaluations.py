"""Freeze inputs, compare context variants and record human preference separately."""

import asyncio
import hashlib
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import ValidationError

from quartermaster import knowledge, teaching
from quartermaster.advice_context import PROMPT_VERSION, render_context
from quartermaster.contracts.adviser import ModelSpec
from quartermaster.contracts.evaluation import (
    ComparisonRating,
    DeterministicChecks,
    EvaluationCase,
    EvaluationInput,
    EvaluationOutput,
    EvaluationRun,
    EvaluationSuite,
    FrozenPair,
)
from quartermaster.contracts.teaching import GroundedAdvice, TestRun
from quartermaster.db import connect
from quartermaster.errors import DomainError
from quartermaster.generation import checked_parameters
from quartermaster.holdouts import case_fingerprint, near_duplicate
from quartermaster.inference import PARAMETERS, identity, response_schema
from quartermaster.projects import read_spec

RUN_SECONDS = 1200
PREFERENCES = {
    "a_better": "A better",
    "b_better": "B better",
    "same": "Same",
    "both_bad": "Both bad",
}
BEHAVIORS = {
    "any": "Any (manual rubric only)",
    "recommend": "Recommend",
    "clarify": "Ask first",
    "abstain": "Abstain",
}


def digest(value):
    return hashlib.sha256(teaching.encoded(value).encode()).hexdigest()


def read_document(connection, table, model, project_id, record_id, revision=None):
    read_spec(connection, project_id)
    query = f"SELECT document FROM {table} WHERE project_id=? AND id=?"
    args = [str(project_id), str(record_id)]
    if revision is not None:
        query += " AND revision=?"
        args.append(revision)
    row = connection.execute(query + " ORDER BY revision DESC LIMIT 1", args).fetchone()
    if row is None:
        raise DomainError("EVALUATION_MISSING: Open an evaluation from this project.", 404)
    return model.model_validate_json(row[0])


def get_suite(settings, project_id, suite_id, revision=None):
    with connect(settings.database_path) as connection:
        return read_document(
            connection, "evaluation_suites", EvaluationSuite, project_id, suite_id, revision
        )


def get_run(settings, project_id, run_id, revision=None):
    with connect(settings.database_path) as connection:
        return read_document(
            connection, "evaluation_runs", EvaluationRun, project_id, run_id, revision
        )


def list_records(settings, project_id, table, model):
    with connect(settings.database_path) as connection:
        read_spec(connection, project_id)
        rows = connection.execute(
            f"SELECT document FROM {table} t WHERE project_id=? AND revision="
            f"(SELECT MAX(revision) FROM {table} WHERE id=t.id) ORDER BY rowid DESC LIMIT 50",
            (str(project_id),),
        ).fetchall()
    return [model.model_validate_json(row[0]) for row in rows]


def list_suites(settings, project_id):
    return list_records(settings, project_id, "evaluation_suites", EvaluationSuite)


def list_runs(settings, project_id):
    return list_records(settings, project_id, "evaluation_runs", EvaluationRun)


def insert_revision(connection, table, record):
    connection.execute(
        f"INSERT INTO {table} VALUES (?, ?, ?, ?)",
        (str(record.id), str(record.project_id), record.revision, record.model_dump_json()),
    )
    return record


def revised(record, **changes):
    return type(record).model_validate(
        {**record.model_dump(), "revision": record.revision + 1, **changes}
    )


def create_suite(settings, project_id, action):
    with connect(settings.database_path) as connection:
        read_spec(connection, project_id)
        return insert_revision(
            connection,
            "evaluation_suites",
            EvaluationSuite(
                id=uuid4(),
                project_id=project_id,
                name=action.name,
                revision=1,
                created_at=datetime.now(UTC),
                status="draft",
                cases=[],
            ),
        )


def editable(connection, project_id, suite_id, expected):
    suite = read_document(connection, "evaluation_suites", EvaluationSuite, project_id, suite_id)
    if suite.revision != expected or suite.status != "draft":
        raise DomainError(
            "EVALUATION_FROZEN: Reload; frozen suites cannot be edited. Create a new suite.", 409
        )
    return suite


def save_case(settings, project_id, suite_id, action):
    run = teaching.get_test(settings, project_id, action.test_id)
    fingerprint = case_fingerprint(run.case)
    with connect(settings.database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        suite = editable(connection, project_id, suite_id, action.expected_revision)
        if len(suite.cases) >= 10 or any(c.case_sha256 == fingerprint for c in suite.cases):
            raise DomainError(
                "EVALUATION_MEMBERSHIP: Use up to 10 distinct situations per suite.", 409
            )
        # Do not label an already taught case an unseen holdout. Check copies too.
        taught = connection.execute(
            "SELECT t.document FROM test_runs t JOIN feedback f "
            "ON json_extract(f.document, '$.test_id')=t.id WHERE t.project_id=?",
            (str(project_id),),
        ).fetchall()
        from quartermaster.contracts.training import TrainingExample

        training_cases = [
            TrainingExample.model_validate_json(row[0]).case
            for row in connection.execute(
                "SELECT document FROM training_examples WHERE project_id=?", (str(project_id),)
            )
        ]
        prior_cases = [TestRun.model_validate_json(row[0]).case for row in taught]
        if any(near_duplicate(run.case, case) for case in [*prior_cases, *training_cases]):
            raise DomainError(
                "EVALUATION_TAUGHT: This situation already has teaching feedback. "
                "Save a new, unseen situation.",
                409,
            )
        case = EvaluationCase(
            id=uuid4(), test_id=run.id, case=run.case, case_sha256=fingerprint, rubric=action.rubric
        )
        connection.execute(
            "INSERT OR IGNORE INTO evaluation_holdouts VALUES (?, ?, ?, ?)",
            (str(project_id), str(run.case.case_id), fingerprint, str(run.id)),
        )
        return insert_revision(
            connection, "evaluation_suites", revised(suite, cases=[*suite.cases, case])
        )


def snapshot_input(settings, spec, active, case, variant):
    if variant == "base_context":
        _, context, evidence, lessons, omitted = teaching.assemble_snapshot(
            settings, spec, active, case
        )
    else:
        context = render_context(
            {"case": case.decision_input(), "retrieved_evidence": [], "approved_lessons": []},
            PROMPT_VERSION,
        )
        evidence, lessons, omitted = [], [], (0, 0)
    data = dict(
        variant=variant,
        prompt_version=PROMPT_VERSION,
        adviser=spec,
        system=teaching.SYSTEM,
        context=context,
        model_alias=identity(settings),
        parameters=PARAMETERS,
        response_schema=response_schema(context),
        evidence=evidence,
        lessons=lessons,
        omitted_lessons=omitted[0],
        omitted_excerpts=omitted[1],
        input_sha256="0" * 64,
    )
    snapshot = EvaluationInput(**data)
    return EvaluationInput.model_validate(
        {
            **snapshot.model_dump(),
            "input_sha256": digest(snapshot.model_dump(mode="json", exclude={"input_sha256"})),
        }
    )


def freeze_suite(settings, project_id, suite_id, action):
    # Serialize the capture with lesson/knowledge approvals. Originals are immutable;
    # nested readers use the last committed revision, identical to this snapshot.
    with connect(settings.database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        suite = editable(connection, project_id, suite_id, action.expected_revision)
        if not suite.cases:
            raise DomainError("EVALUATION_EMPTY: Save at least one situation before freezing.")
        spec = read_spec(connection, project_id)
        # This screen always compares base weights with/without context. Active
        # candidate weights are compared separately on Train with the same B input.
        spec = type(spec).model_validate({**spec.model_dump(), "model": ModelSpec()})
        active = [
            lesson
            for lesson in teaching.read_latest_lessons(connection, project_id)
            if lesson.status == "applied"
        ]
        revision = (
            knowledge.read_revision(connection, project_id, spec.knowledge_revision)
            if spec.knowledge_revision
            else None
        )
        # Verify every selected original, including sources not retrieved for these cases.
        if revision:
            from quartermaster.sources import read_source, source_bytes

            for source_id in revision.source_ids:
                source = read_source(connection, project_id, source_id)
                source_bytes(settings, source)
                if revision.source_hashes[str(source_id)] != source.sha256:
                    raise DomainError(
                        "EVALUATION_SOURCE: Selected source hashes do not match.", 409
                    )
        inputs = [
            FrozenPair(
                case_id=entry.id,
                a=snapshot_input(settings, spec, active, entry.case, "base_only"),
                b=snapshot_input(settings, spec, active, entry.case, "base_context"),
            )
            for entry in suite.cases
        ]
        frozen = revised(
            suite,
            status="frozen",
            frozen_at=datetime.now(UTC),
            inputs=inputs,
            source_hashes=revision.source_hashes if revision else {},
        )
        frozen = EvaluationSuite.model_validate(
            {
                **frozen.model_dump(),
                "frozen_sha256": digest(frozen.model_dump(mode="json", exclude={"frozen_sha256"})),
            }
        )
        return insert_revision(connection, "evaluation_suites", frozen)


def verify_frozen(suite):
    if suite.status != "frozen" or suite.frozen_sha256 != digest(
        suite.model_dump(mode="json", exclude={"frozen_sha256"})
    ):
        raise DomainError("EVALUATION_INTEGRITY: Freeze a valid suite before running.", 409)
    if [entry.id for entry in suite.cases] != [pair.case_id for pair in suite.inputs]:
        raise DomainError(
            "EVALUATION_INTEGRITY: Suite membership does not match its frozen inputs.", 409
        )
    for pair in suite.inputs:
        for item in (pair.a, pair.b):
            if item.input_sha256 != digest(item.model_dump(mode="json", exclude={"input_sha256"})):
                raise DomainError("EVALUATION_INTEGRITY: Frozen input hash does not match.", 409)


async def evaluate_output(settings, inference, project_id, entry, item):
    draft, advice, error = None, None, None
    schema_valid, citations_valid, support_valid, behavior = False, None, None, None
    try:
        # Recheck accessible original excerpts; never silently substitute current retrieval.
        for evidence in item.evidence:
            current = knowledge.citation(
                settings, project_id, evidence.citation_id, item.adviser.knowledge_revision
            )
            if (
                current["source"].sha256 != evidence.source_sha256
                or current["chunk"].sha256 != evidence.excerpt_sha256
                or current["chunk"].text != evidence.text
            ):
                raise DomainError(
                    "EVALUATION_SOURCE: Frozen citation no longer matches its source.", 409
                )
        async with asyncio.timeout(settings.local_timeout_seconds + 1):
            result = await inference.advise(
                system=item.system, context=item.context, parameters=item.parameters
            )
        draft = GroundedAdvice.model_validate_json(result.model_dump_json())
        schema_valid = True
        citations_valid = set(draft.advice.evidence_refs) <= {
            str(e.citation_id) for e in item.evidence
        }
        draft, advice = teaching.validate_advice(draft, entry.case, item.evidence)
        support_valid = True
        behavior = (
            "clarify"
            if advice.clarification_question
            else ("abstain" if draft.behavior == "abstain" else "recommend")
        )
        if item.omitted_lessons or item.omitted_excerpts:
            advice = type(advice).model_validate(
                {
                    **advice.model_dump(),
                    "limitations": [
                        *advice.limitations[:19],
                        f"Context limits omitted {item.omitted_lessons} lessons "
                        f"and {item.omitted_excerpts} excerpts.",
                    ],
                }
            )
    except DomainError as exc:
        error = exc.message
        if error.startswith("ADVICE_SUPPORT:"):
            support_valid = False
    except (ValidationError, ValueError, TypeError, AttributeError, RecursionError):
        error = "LOCAL_JSON: Model returned invalid advice."
    except TimeoutError:
        error = "LOCAL_TIMEOUT: Evaluation output timed out; start a new run to retry."
    except Exception:
        # An injected adapter is untrusted too; do not expose its exception or lose the run.
        error = (
            "EVALUATION_PROVIDER: Local adapter failed; check configuration and start a new run."
        )
    expected = entry.rubric.expected_behavior
    checks = DeterministicChecks(
        schema_valid=schema_valid,
        citations_valid=citations_valid,
        supporting_facts_valid=support_valid,
        behavior=behavior,
        expected_behavior_passed=None if expected == "any" else behavior == expected,
        unsupported_recommendation=(expected in {"clarify", "abstain"} and behavior == "recommend"),
    )
    return EvaluationOutput(
        case_id=entry.id,
        variant=item.variant,
        created_at=datetime.now(UTC),
        input_sha256=item.input_sha256,
        draft=draft,
        advice=advice,
        error=error,
        checks=checks,
    )


def checkpoint(settings, run, **changes):
    with connect(settings.database_path) as connection:
        return insert_revision(connection, "evaluation_runs", revised(run, **changes))


async def run_suite(settings, inference, project_id, suite_id, action):
    with connect(settings.database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        suite = read_document(
            connection, "evaluation_suites", EvaluationSuite, project_id, suite_id
        )
        if suite.revision != action.expected_revision:
            raise DomainError("EVALUATION_CHANGED: Reload the suite before running.", 409)
        verify_frozen(suite)
        for pair in suite.inputs:
            for item in (pair.a, pair.b):
                checked_parameters(item.parameters)
                if (
                    item.model_alias != identity(settings)
                    or item.response_schema != response_schema(item.context)
                    or item.system != teaching.SYSTEM
                ):
                    raise DomainError(
                        "EVALUATION_RUNTIME: Restore the frozen model and prompt "
                        "implementation before rerunning.",
                        409,
                    )
        busy = connection.execute(
            "SELECT 1 FROM evaluation_runs r WHERE revision=(SELECT MAX(revision) "
            "FROM evaluation_runs WHERE id=r.id) "
            "AND json_extract(document, '$.status')='running' LIMIT 1"
        ).fetchone()
        if busy:
            raise DomainError("EVALUATION_BUSY: Wait for the current evaluation to finish.", 409)
        run = insert_revision(
            connection,
            "evaluation_runs",
            EvaluationRun(
                id=uuid4(),
                project_id=project_id,
                suite_id=suite.id,
                suite_revision=suite.revision,
                suite_sha256=suite.frozen_sha256,
                revision=1,
                created_at=datetime.now(UTC),
                status="running",
                outputs=[],
            ),
        )
    try:
        async with asyncio.timeout(RUN_SECONDS):
            for entry, pair in zip(suite.cases, suite.inputs, strict=True):
                for item in (pair.a, pair.b):
                    output = await evaluate_output(settings, inference, project_id, entry, item)
                    run = checkpoint(settings, run, outputs=[*run.outputs, output])
        return checkpoint(settings, run, status="completed")
    except (TimeoutError, asyncio.CancelledError) as exc:
        run = checkpoint(
            settings,
            run,
            status="interrupted",
            error=(
                "EVALUATION_INTERRUPTED: Completed outputs were retained. "
                "Start a new run explicitly; no automatic retry."
            ),
        )
        if isinstance(exc, asyncio.CancelledError):
            raise
        return run


def recover_evaluations(settings):
    with connect(settings.database_path) as connection:
        rows = connection.execute(
            "SELECT document FROM evaluation_runs r WHERE revision="
            "(SELECT MAX(revision) FROM evaluation_runs WHERE id=r.id)"
        ).fetchall()
        for row in rows:
            run = EvaluationRun.model_validate_json(row[0])
            if run.status == "running":
                insert_revision(
                    connection,
                    "evaluation_runs",
                    revised(
                        run,
                        status="interrupted",
                        error=(
                            "EVALUATION_INTERRUPTED: Application restarted. "
                            "Start a new run explicitly; no automatic retry."
                        ),
                    ),
                )


def ratings(settings, project_id, run_id):
    get_run(settings, project_id, run_id)
    with connect(settings.database_path) as connection:
        rows = connection.execute(
            "SELECT document FROM evaluation_ratings r WHERE run_id=? AND revision="
            "(SELECT MAX(revision) FROM evaluation_ratings "
            "WHERE run_id=r.run_id AND case_id=r.case_id) ORDER BY rowid",
            (str(run_id),),
        ).fetchall()
    return [ComparisonRating.model_validate_json(row[0]) for row in rows]


def rate(settings, project_id, run_id, case_id, action):
    if not action.rationale.strip():
        raise DomainError("EVALUATION_RATIONALE: Explain your preference or the problem.")
    with connect(settings.database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        run = read_document(connection, "evaluation_runs", EvaluationRun, project_id, run_id)
        if {o.variant for o in run.outputs if o.case_id == case_id} != {
            "base_only",
            "base_context",
        }:
            raise DomainError("EVALUATION_PAIR: Rate a case with both saved outputs.", 409)
        row = connection.execute(
            "SELECT MAX(revision) FROM evaluation_ratings WHERE run_id=? AND case_id=?",
            (str(run_id), str(case_id)),
        ).fetchone()
        previous = row[0] or 0
        if previous != action.expected_revision:
            raise DomainError("EVALUATION_RATING_CHANGED: Reload before revising this rating.", 409)
        rating = ComparisonRating(
            run_id=run_id,
            case_id=case_id,
            revision=previous + 1,
            created_at=datetime.now(UTC),
            preference=action.preference,
            category=action.category,
            rationale=action.rationale,
        )
        connection.execute(
            "INSERT INTO evaluation_ratings VALUES (?, ?, ?, ?)",
            (str(run_id), str(case_id), rating.revision, rating.model_dump_json()),
        )
        return rating


def summary(suite, run, reviews):
    counts = {
        "improved": 0,
        "regressed": 0,
        "same": 0,
        "both_bad": 0,
        "unreviewed": len(suite.cases),
    }
    names = {
        "b_better": "improved",
        "a_better": "regressed",
        "same": "same",
        "both_bad": "both_bad",
    }
    for review in reviews:
        counts[names[review.preference]] += 1
        counts["unreviewed"] -= 1
    counts["failed_outputs"] = sum(o.error is not None for o in run.outputs)
    counts["rubric_failures"] = sum(o.checks.expected_behavior_passed is False for o in run.outputs)
    return counts


def comparison_scope(first_suite, second_suite):
    """A descriptive guard, not a quality metric or training-lift estimator."""

    def signature(suite):
        return (
            [(entry.case_sha256, entry.rubric) for entry in suite.cases],
            [(pair.a.input_sha256, pair.b.input_sha256) for pair in suite.inputs],
            suite.source_hashes,
        )

    changed = signature(first_suite) != signature(second_suite)
    return {
        "frozen_inputs_changed": changed,
        "weight_improvement_assessed": False,
        "message": "Frozen inputs differ; context or suite changes confound a weight comparison."
        if changed
        else (
            "Same frozen inputs. This compares base-only with base plus context; "
            "weights are unchanged."
        ),
    }
