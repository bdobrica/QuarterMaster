"""Pure validation of the generic public trainer boundary; no database or provider."""

import hashlib
import json
from uuid import uuid5

from quartermaster.contracts.adviser import ModelSpec
from quartermaster.contracts.prediction import ReviewedExample
from quartermaster.contracts.training import Recipe
from quartermaster.generation import PARAMETERS
from quartermaster.prediction_context import digest, schema_for, serialize, system_for, validate


def dataset_bytes(dataset):
    return json.dumps(
        dataset.model_dump(
            mode="json", exclude={"examples": {"__all__": {"input": {"observed_outcome"}}}}
        ),
        ensure_ascii=False,
        sort_keys=True,
        allow_nan=False,
    ).encode()


def verify_job(job, raw):
    """Pure public boundary, also used inside the trainer without the app database."""
    if (
        job.model != ModelSpec()
        or job.baseline != job.adviser.model
        or job.recipe
        != Recipe(
            preset=job.recipe.preset,
            steps=12 if job.recipe.preset == "quick" else 48,
            seconds=1200 if job.recipe.preset == "quick" else 3600,
        )
        or job.project_id != job.teaching.project_id
        or job.adviser.id != job.project_id
        or job.adviser.outputs != "quartermaster.prediction/v1"
        or job.adviser.knowledge_revision != job.teaching.knowledge_revision
        or hashlib.sha256(dataset_bytes(job.teaching)).hexdigest() != job.teaching_sha256
        or hashlib.sha256(raw).hexdigest() != job.dataset_sha256
        or serialize(job.examples) != raw
        or len(job.examples) != len(job.teaching.examples)
        or len({e.id for e in job.examples}) != len(job.examples)
        or len({(e.case.situation, tuple(e.case.choices)) for e in job.examples})
        != len(job.examples)
    ):
        raise ValueError("PREDICTION_JOB: Frozen teaching or dataset differs")
    taught = {e.owner_decision.id: e for e in job.teaching.examples}
    imports = {i.id: i for i in job.teaching.imports}
    if len(taught) != len(job.examples) or job.source_hashes != {
        str(k.source.id): k.source.sha256 for k in job.teaching.knowledge
    }:
        raise ValueError("PREDICTION_JOB: Duplicate teaching or changed knowledge")
    for entry in job.examples:
        origin = taught[entry.id]
        owner = origin.owner_decision
        if isinstance(origin, ReviewedExample):
            review = origin.review
            if (
                review.target != owner.target
                or review.reasoning != owner.reasoning
                or review.revision != owner.revision
                or review.prediction_id != owner.prediction_id
                or not review.teaching_eligible
                or review.submission.action not in {"accept", "correct"}
                or origin.run.id != owner.prediction_id
                or origin.run.input.case != origin.input
                or origin.run.project_id != job.project_id
                or review.project_id != job.project_id
                or owner.id != uuid5(job.project_id, str(owner.prediction_id))
                or (
                    review.submission.action == "correct"
                    and review.submission.target != owner.target
                )
                or (
                    review.submission.action == "accept"
                    and (
                        origin.run.result.error
                        or origin.run.result.prediction is None
                        or origin.run.result.prediction.target != owner.target
                    )
                )
            ):
                raise ValueError("PREDICTION_JOB: Review differs from its original answer")
        else:
            imported = imports[owner.import_id]
            if (
                imported.project_id != job.project_id
                or owner.manifest_sha256 != imported.manifest_sha256
                or owner.id != uuid5(imported.id, owner.example_id)
                or owner.manifest_sha256 != origin.source.manifest_sha256
                or owner.example_id != origin.source.example_id
            ):
                raise ValueError("PREDICTION_JOB: Collection lineage differs")
        item = entry.input
        data = json.loads(item.context)
        fields = dict(
            system=item.system,
            context=item.context,
            parameters=item.parameters,
            response_schema=item.response_schema,
        )
        context_keys = {
            "mission",
            "business_goal",
            "decision_definition",
            "case",
            "retrieved_evidence",
            "approved_lessons",
            "answer_format",
            "context_omissions",
        }
        if item.prompt_version == "context/v5":
            context_keys.add("prediction_profile")
            if data.get("prediction_profile") != "owner/v2":
                raise ValueError("PREDICTION_JOB: Changed prediction profile")
        if (
            set(data) != context_keys
            or data["mission"] != job.adviser.mission
            or data["business_goal"] != job.adviser.business_goal
            or data["decision_definition"]
            != (
                job.adviser.decision_definition.model_dump(mode="json")
                if job.adviser.decision_definition
                else None
            )
            or data["approved_lessons"] != []
        ):
            raise ValueError("PREDICTION_JOB: Use the captured decision-time context only")
        if (
            owner.project_id != job.project_id
            or entry.case.case_id
            != (origin.run.input.case.case_id if isinstance(origin, ReviewedExample) else owner.id)
            or owner.revision != entry.revision
            or origin.input != entry.case
            or entry.case.observed_outcome is not None
            or entry.target.target != owner.target
            or entry.target.explanation != (owner.reasoning or "The owner's reviewed preference.")
            or entry.target.evidence_refs
            or entry.target.behavior != "answer"
            or item.answer_format != job.answer_format
            or item.system != system_for(item.context)
            or item.parameters != PARAMETERS
            or item.response_schema != schema_for(item.context)
            or item.input_sha256 != digest(fields)
            or data["case"] != entry.case.decision_input()
            or data["answer_format"] != job.answer_format.model_dump(mode="json")
        ):
            raise ValueError("PREDICTION_JOB: Supervision differs from the owner's decision")
        validate(entry.target, item)
        actual = [{"citation_id": str(e.citation_id), "text": e.text} for e in item.evidence]
        if data["retrieved_evidence"] != actual:
            raise ValueError("PREDICTION_JOB: Context evidence differs")
        sources = {k.source.id: k for k in job.teaching.knowledge}
        for evidence in item.evidence:
            source = sources[evidence.source_id]
            if (
                evidence.source_sha256 != source.source.sha256
                or evidence.excerpt_sha256 != hashlib.sha256(evidence.text.encode()).hexdigest()
                or evidence.text not in source.text
            ):
                raise ValueError("PREDICTION_JOB: Evidence is not present in frozen knowledge")
    return job
