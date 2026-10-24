"""Fresh synthetic demo and honest four-case baseline; never trains or calls a builder."""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from quartermaster import evaluations, teaching
from quartermaster.config import Settings, initialize_storage
from quartermaster.contracts.advice import Case
from quartermaster.contracts.adviser import AdviceEngineEdit
from quartermaster.contracts.evaluation import Rubric, SaveEvaluationCase, SuiteCreate
from quartermaster.contracts.project import ProjectCreate
from quartermaster.contracts.sources import KnowledgeSelection, ParseOptions
from quartermaster.contracts.teaching import TestInput, TestRun
from quartermaster.db import connect, migrate
from quartermaster.errors import DomainError
from quartermaster.inference import LocalInference, hosted_identity
from quartermaster.knowledge import revise_knowledge
from quartermaster.projects import create_project, edit_advice_engine, get_adviser
from quartermaster.sources import upload_source

POLICY = """# Print-proof production policy

Recommend ready for production only when final copy is confirmed and the customer
has explicitly approved the print proof in writing. Final copy confirmation is not
proof approval. A production deadline never substitutes for either confirmation.
If either requirement is explicitly absent or the customer says not to print,
recommend hold; do not ask about unrelated facts. If a decisive confirmation is
unknown, ask one short question about that confirmation. If records conflict,
hold and ask which approval record is current before recommending readiness.
A portal e-signature is not currently an accepted form of proof sign-off;
hold until accepted written proof approval is provided or the policy is reviewed.

This is invented demonstration policy, not real print-shop guidance.
"""
MISSION = (
    "Advise whether a print job is ready under our production policy. Give one clear "
    "recommendation with the policy source, or one relevant question about a decisive "
    "missing fact. Never send files to production."
)
# Expectations are owner-review rubrics, never model context or training targets.
CASES = [
    (
        "clear-approval",
        "Job Cedar: final copy is confirmed and the customer approved the print "
        "proof in writing this morning. May we print?",
        "recommend",
        "Ready, citing both required confirmations; no questions.",
    ),
    (
        "explicit-hold",
        "Job Maple: final copy is confirmed. The customer wrote: I have not "
        "approved the proof; do not print yet. May we print?",
        "recommend",
        "Hold, citing explicit lack of approval; no questions.",
    ),
    (
        "missing-approval",
        "Job Birch: final copy is confirmed. We do not know whether the "
        "customer approved the print proof. Is it ready?",
        "clarify",
        "Ask only whether customer proof approval was given in writing.",
    ),
    (
        "missing-copy",
        "Job Ash: the customer approved the print proof in writing. Final copy "
        "confirmation is unknown. Can production begin?",
        "clarify",
        "Ask only whether final copy is confirmed.",
    ),
    (
        "conflicting-evidence",
        "Job Elm: final copy is confirmed. One note says the customer "
        "approved the proof in writing; another says approval was withdrawn. Neither note has "
        "a timestamp. Should we print?",
        "clarify",
        "Hold; ask which approval record is current.",
    ),
    (
        "e-signature-update",
        "Job Willow: final copy is confirmed. The only approval is a "
        "customer e-signature in our proofing portal. May we print?",
        "recommend",
        "Hold under current policy; after an approved policy update, ready with the new source.",
    ),
    (
        "missing-both",
        "Job Hazel: neither final copy confirmation nor customer proof approval "
        "is recorded. Is it ready?",
        "clarify",
        "Ask one concise question requesting the two decisive confirmations.",
    ),
    (
        "deadline-pressure",
        "Job Alder must ship today. Final copy is confirmed; the customer "
        "explicitly refused proof approval. Can urgency let us print?",
        "recommend",
        "Hold; a deadline cannot replace approval.",
    ),
    (
        "unseen-portal-neighbor",
        "A new booklet, job Juniper, has confirmed final copy. Its "
        "customer signed only through the proofing portal. Is this job ready for production?",
        "recommend",
        "Hold now; ready only after portal e-signature is accepted in approved policy.",
    ),
    (
        "unseen-approval-neighbor",
        "A new flyer, job Rowan, has final copy confirmed. The job "
        "ticket leaves written customer proof sign-off blank. Can it go to press?",
        "clarify",
        "Ask only about written proof approval; do not invent a refusal.",
    ),
]


def seed(settings):
    """Always creates a new project; existing projects/artifacts remain untouched."""
    initialize_storage(settings)
    migrate(settings.database_path)
    project = create_project(
        settings.database_path,
        ProjectCreate(
            name="Synthetic print-proof demo",
            mission=MISSION,
        ),
    )
    source = upload_source(
        settings, project.id, "print-policy.md", POLICY.encode(), "knowledge", ParseOptions()
    )
    revise_knowledge(
        settings, project.id, KnowledgeSelection(source_ids=[source.id], expected_revision=None)
    )
    suite = evaluations.create_suite(
        settings, project.id, SuiteCreate(name="Print demo · owner review pending")
    )
    for _slug, situation, behavior, expectation in CASES:
        case = Case(case_id=uuid4(), situation=situation)
        spec, context, evidence, lessons, _ = teaching.assemble(settings, project.id, case)
        run = TestRun(
            id=uuid4(),
            project_id=project.id,
            created_at=datetime.now(UTC),
            case=case,
            adviser=spec,
            system="",
            context=context,
            model_alias="not-run",
            parameters={},
            response_schema={},
            evidence=evidence,
            lessons=lessons,
            draft=None,
            advice=None,
            error="DEMO_NOT_RUN: Saved synthetic case; no inference attempted.",
        )
        with connect(settings.database_path) as connection:
            connection.execute(
                "INSERT INTO test_runs VALUES (?, ?, ?)",
                (str(run.id), str(project.id), run.model_dump_json()),
            )
        suite = evaluations.save_case(
            settings,
            project.id,
            suite.id,
            SaveEvaluationCase(
                expected_revision=suite.revision,
                test_id=run.id,
                rubric=Rubric(expected_behavior=behavior, expectation=expectation),
            ),
        )
    return project, suite


async def baseline(settings, project_id, suite_id, engine, consent_external=False):
    suite = evaluations.get_suite(settings, project_id, suite_id)
    spec = get_adviser(settings.database_path, project_id)
    endpoint, model = hosted_identity(settings) if engine == "hosted" else (None, None)
    edit_advice_engine(
        settings,
        project_id,
        AdviceEngineEdit(
            expected_revision=spec.revision,
            mode="hosted" if engine == "hosted" else "local_only",
            consent=consent_external,
            endpoint=endpoint,
            model=model,
        ),
    )
    results = []
    for case in suite.cases[:4]:
        run = await teaching.advise(
            settings,
            LocalInference(settings),
            project_id,
            TestInput(situation=case.case.situation, choices=case.case.choices),
        )
        results.append(
            {
                "run": run.model_dump(mode="json"),
                "owner_rubric": case.rubric.model_dump(mode="json"),
                "human_review": {
                    "useful": None,
                    "sources_support_claims": None,
                    "only_necessary_questions": None,
                    "notes": "",
                },
            }
        )
    return {
        "schema_version": "quartermaster.print-baseline/v1",
        "engine": engine,
        "created_at": datetime.now(UTC).isoformat(),
        "project_id": str(project_id),
        "suite_id": str(suite_id),
        "results": results,
        "cases_reviewed_at": suite.reviewed_at.isoformat() if suite.reviewed_at else None,
        "external_cost": None,
        "cost_note": "Not reported; check actual provider billing.",
        "gate": "PENDING HUMAN REVIEW: JSON validity alone does not establish usefulness.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=UUID)
    parser.add_argument("--suite", type=UUID)
    parser.add_argument("--engine", choices=["local", "hosted"])
    parser.add_argument(
        "--consent-external",
        action="store_true",
        help="Consent to sending this synthetic project's mission, cases, policy and routines.",
    )
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    settings = Settings()
    try:
        if args.engine:
            if not args.project or not args.suite or not args.report:
                parser.error("Baseline requires --project, --suite and --report.")
            # Never overwrite a historical baseline report.
            with args.report.open("x", encoding="utf-8") as stream:
                report = asyncio.run(
                    baseline(settings, args.project, args.suite, args.engine, args.consent_external)
                )
                json.dump(report, stream, ensure_ascii=False, indent=2)
            print(f"Baseline saved to {args.report}; review actual answers and cited excerpts.")
        else:
            project, suite = seed(settings)
            print(f"Project: {project.id}\nSuite: {suite.id}\nOpen /projects/{project.id}/test")
            print("10 synthetic held-out cases saved. Owner review pending; no model calls made.")
    except DomainError as exc:
        parser.exit(1, exc.message + "\n")


if __name__ == "__main__":
    main()
