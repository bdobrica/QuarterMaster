"""Explicit opt-in end-to-end M6 GPU check on hash-matched, human-reviewed synthetic data."""

import argparse
import json
import subprocess
from pathlib import Path
from uuid import uuid4

from quartermaster import evaluations, teaching, training
from quartermaster.config import Settings, initialize_storage
from quartermaster.contracts.advice import Case
from quartermaster.contracts.evaluation import SaveEvaluationCase, SuiteAction, SuiteCreate
from quartermaster.contracts.interview import VersionedAction
from quartermaster.contracts.project import ProjectCreate
from quartermaster.contracts.teaching import (
    FeedbackInput,
    GroundedAdvice,
    LessonReview,
    ManualLesson,
    TestRun,
)
from quartermaster.contracts.training import ExampleReview, ExampleTarget, TrainingSelection
from quartermaster.db import connect, migrate
from quartermaster.inference import PARAMETERS, model_alias, response_schema
from quartermaster.local_runtime import verify
from quartermaster.projects import create_project, get_adviser
from quartermaster.training_worker import DockerEngine, execute_next, recover

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/training/train.json"
REVIEW = FIXTURE.with_name("review.json")


def fixture_review(fixture=FIXTURE, review=REVIEW):
    record = json.loads(review.read_bytes())
    if (
        record.get("schema_version") != "quartermaster.training-fixture-review/v1"
        or record.get("fixture_sha256") != training.hash_file(fixture)
        or record.get("review_state") != "approved"
        or not record.get("reviewer")
    ):
        raise SystemExit(
            "TRAINING_REVIEW: Explicit owner approval matching the exact fixture is required."
        )
    return json.loads(fixture.read_bytes())


def seed(settings, fixture, alias):
    project = create_project(
        settings.database_path,
        ProjectCreate(name="Synthetic Milestone 6 workflow check", mission=fixture["mission"]),
    )
    spec = get_adviser(settings.database_path, project.id)

    def saved_test(case):
        # This is fixture setup, not a claimed live pre-training inference. Its
        # placeholder response exists only to exercise correction/suite saving.
        context = teaching.encoded(
            {"case": case.decision_input(), "retrieved_evidence": [], "approved_lessons": []}
        )
        draft = GroundedAdvice.model_validate(
            {
                "behavior": "abstain",
                "missing_information": [],
                "supporting_quotes": [],
                "advice": {
                    "recommendation": "Synthetic setup placeholder.",
                    "explanation": "Not a model inference.",
                    "evidence_refs": [],
                    "clarification_question": None,
                    "limitations": ["Fixture setup only."],
                },
            }
        )
        record = TestRun(
            id=uuid4(),
            project_id=project.id,
            created_at=training.now(),
            case=case,
            adviser=spec,
            system=teaching.SYSTEM,
            context=context,
            model_alias=alias,
            parameters=PARAMETERS,
            response_schema=response_schema(context),
            evidence=[],
            lessons=[],
            draft=draft,
            advice=draft.advice,
            error=None,
        )
        with connect(settings.database_path) as connection:
            connection.execute(
                "INSERT INTO test_runs VALUES (?,?,?)",
                (str(record.id), str(project.id), record.model_dump_json()),
            )
        return record

    suite = evaluations.create_suite(
        settings, project.id, SuiteCreate(name="Unseen synthetic checks")
    )
    for entry in fixture["evaluation"]:
        case = Case.model_validate_json(json.dumps(entry["case"]))
        record = saved_test(case)
        suite = evaluations.save_case(
            settings,
            project.id,
            suite.id,
            SaveEvaluationCase(
                expected_revision=suite.revision, test_id=record.id, rubric=entry["rubric"]
            ),
        )
    # The exact same mission/context snapshot is used before and after weights.
    # No applied lessons are present yet, so they cannot encode training situations.
    suite = evaluations.freeze_suite(
        settings, project.id, suite.id, SuiteAction(expected_revision=suite.revision)
    )
    examples = []
    for entry in fixture["training"]:
        case = Case.model_validate_json(json.dumps(entry["case"]))
        target = GroundedAdvice.model_validate_json(json.dumps(entry["target"]))
        record = saved_test(case)
        lesson = teaching.feedback(
            settings,
            project.id,
            record.id,
            FeedbackInput(
                category="should_ask" if target.behavior == "clarify" else "wrong_call",
                correction="Use the explicitly owner-reviewed synthetic target.",
            ),
        )
        lesson = teaching.manual_lesson(
            settings,
            project.id,
            lesson.id,
            ManualLesson(
                expected_revision=lesson.revision,
                text={
                    "applicability": "Rental-tool use decisions.",
                    "instruction": fixture["mission"],
                },
            ),
        )
        lesson = teaching.review_lesson(
            settings,
            project.id,
            lesson.id,
            LessonReview(expected_revision=lesson.revision, action="apply"),
        )
        example = training.from_lesson(
            settings, project.id, lesson.id, VersionedAction(expected_revision=lesson.revision)
        )
        # Provenance stays AI_DRAFT even though the human-approved fixture is set
        # up offline, without an external builder call.
        with connect(settings.database_path) as connection:
            example = training.append_example(connection, example, origin="AI_DRAFT")
        example = training.set_target(
            settings,
            project.id,
            example.id,
            ExampleTarget(expected_revision=example.revision, target=target),
        )
        example = training.review_example(
            settings,
            project.id,
            example.id,
            ExampleReview(expected_revision=example.revision, action="approve"),
        )
        examples.append(example.id)
    return training.freeze_dataset(
        settings,
        project.id,
        TrainingSelection(
            example_ids=examples,
            suite_id=suite.id,
            suite_revision=suite.revision,
            preset="quick",
            acknowledge_small_data=True,
        ),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-gpu", action="store_true", required=True)
    parser.add_argument("--gpu-mode", choices=["nvidia", "wsl"], default="nvidia")
    parser.add_argument(
        "--base",
        type=Path,
        default=ROOT / "data/spike/base-2fc06364715b967f1860aea9cf38778875588b17",
    )
    parser.add_argument("--base-gguf", type=Path, default=ROOT / "data/local-model")
    parser.add_argument("--output", type=Path, default=ROOT / "data/training-smoke")
    args = parser.parse_args()
    fixture = fixture_review()
    record = verify(args.base_gguf)
    settings = Settings(
        data_dir=args.output / str(uuid4()),
        _env_file=None,
        local_base_url="http://127.0.0.1:8080/v1",
        local_model_sha256=record["sha256"],
    )
    initialize_storage(settings)
    migrate(settings.database_path)
    run = seed(settings, fixture, model_alias(record["sha256"]))
    print(f"Synthetic workflow artifacts: {settings.data_dir}", flush=True)
    # Fixed local builds only; image IDs are resolved and frozen before GPU dispatch.
    for target, tag in (
        ("trainer", "quartermaster-trainer:m6"),
        ("runtime", "quartermaster-runtime:m6"),
    ):
        subprocess.run(
            ["docker", "build", "-f", "trainer/Dockerfile", "--target", target, "-t", tag, "."],
            cwd=ROOT,
            check=True,
            timeout=1800,
        )

    def image_id(tag):
        return subprocess.check_output(
            ["docker", "image", "inspect", tag, "--format", "{{.Id}}"], text=True, timeout=30
        ).strip()

    engine = DockerEngine(
        settings,
        args.base,
        args.base_gguf,
        image_id("quartermaster-trainer:m6"),
        image_id("quartermaster-runtime:m6"),
        args.gpu_mode,
    )
    recover(settings, engine)
    result = execute_next(settings, engine)
    if result.status != "completed":
        raise SystemExit(f"Synthetic workflow {result.status}: {result.error}")
    version = training.get_version(settings, run.project_id, result.candidate_id)
    (settings.data_dir / "verification.json").write_text(version.model_dump_json(indent=2) + "\n")
    print(
        "Reviewed synthetic workflow completed; candidate remains unpromoted. "
        "Inspect every frozen rubric and output. No quality improvement is implied."
    )


if __name__ == "__main__":
    main()
