"""Reviewed collection targets enter the existing bounded queue; local typed Ask."""

import asyncio
import hashlib
from uuid import uuid4

from pydantic import ValidationError

from quartermaster import evaluations, knowledge, muster, training
from quartermaster.contracts.advice import Case
from quartermaster.contracts.prediction import (
    Prediction,
    PredictionJob,
    PredictionResult,
    PredictionRun,
    ReviewTeachingDataset,
    SupervisedPrediction,
    TeachingDataset,
)
from quartermaster.contracts.training import TrainingRun
from quartermaster.db import connect
from quartermaster.errors import DomainError
from quartermaster.holdouts import case_fingerprint, require_eligible
from quartermaster.inference import LocalInference
from quartermaster.prediction_context import (
    assemble,
    serialize,
    validate,
)
from quartermaster.prediction_jobs import recipe_for, verify_job
from quartermaster.projects import read_spec, require_answer_format


def prepare(settings, project_id, import_id, action):
    teaching_sha, path = muster.freeze_teaching(settings, project_id, import_id)
    try:
        raw_dataset = path.read_bytes()
        import json

        contract = (
            ReviewTeachingDataset
            if json.loads(raw_dataset)["schema_version"] == "quartermaster.teaching-dataset/v2"
            else TeachingDataset
        )
        dataset = contract.model_validate_json(raw_dataset)
    except ValidationError:
        raise DomainError(
            "TEACHING_DATASET: Use a collection with at most 100 reviewed answers. "
            "If its saved data is damaged, restore the unchanged teaching snapshot.",
            409,
        ) from None
    with connect(settings.database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        spec = read_spec(connection, project_id)
        require_answer_format(spec, action.answer_format)
        if (
            spec.revision != action.expected_revision
            or spec.knowledge_revision != dataset.knowledge_revision
        ):
            raise DomainError("PROJECT_CHANGED: Reload before preparing an improvement.", 409)
        require_eligible(connection, project_id, [e.input for e in dataset.examples])
        if len({case_fingerprint(e.input) for e in dataset.examples}) != len(dataset.examples):
            raise DomainError(
                "TEACHING_DUPLICATE: Some taught examples have identical selected details. "
                "Choose details that distinguish those situations before training.",
                409,
            )
        latest = muster.decisions(settings, project_id, import_id)
        from quartermaster.prediction_reviews import teaching

        reviewed = teaching(settings, project_id)
        if [*latest, *[e.owner_decision for e in reviewed]] != [
            e.owner_decision for e in dataset.examples
        ]:
            raise DomainError("MUSTER_DECISION_CHANGED: Teaching changed; prepare again.", 409)
        if spec.model.adapter_artifact:
            baseline = training.get_version(settings, project_id, spec.model.adapter_artifact)
            if (
                baseline.schema_version != "quartermaster.adviser-version/v2"
                or baseline.answer_format != action.answer_format
            ):
                raise DomainError(
                    "PREDICTION_MODEL: Retain the base before changing the answer format.", 409
                )
        queued = connection.execute(
            "SELECT COUNT(*) FROM training_runs r WHERE revision=(SELECT MAX(revision) "
            "FROM training_runs WHERE id=r.id) AND json_extract(document,'$.status')='queued'"
        ).fetchone()[0]
        if queued >= 10:
            raise DomainError("TRAINING_QUEUE: Cancel an unused waiting improvement first.", 409)
        rows = []
        for e in dataset.examples:
            target = e.owner_decision.target
            fmt = action.answer_format
            if (
                target.kind != fmt.kind
                or (target.kind == "number" and target.unit != fmt.unit)
                or (target.kind == "category" and target.value not in fmt.choices)
            ):
                raise DomainError(
                    "TEACHING_FORMAT: All taught answers must fit the selected unit or choices."
                )
            item = assemble(spec, e.input, fmt, knowledge.advice_search(settings, spec, e.input))
            verify_evidence(settings, spec, item)
            if len(e.owner_decision.reasoning) > 600:
                raise DomainError(
                    "TEACHING_EXPLANATION: Shorten your reason to 600 characters before training."
                )
            rows.append(
                SupervisedPrediction(
                    id=e.owner_decision.id,
                    revision=e.owner_decision.revision,
                    input=item,
                    target=Prediction(
                        behavior="answer",
                        target=target,
                        explanation=e.owner_decision.reasoning
                        or "The owner's reviewed preference.",
                        evidence_refs=[],
                        question=None,
                        limitations=[],
                    ),
                )
            )
        raw = serialize(rows)
        spec = spec.model_copy(update={"outputs": "quartermaster.prediction/v1"})
        job = PredictionJob(
            id=uuid4(),
            project_id=project_id,
            created_at=training.now(),
            adviser=spec,
            model=spec.model.model_copy(update={"adapter_artifact": None}),
            baseline=spec.model,
            answer_format=action.answer_format,
            teaching=dataset,
            teaching_sha256=teaching_sha,
            examples=rows,
            dataset_sha256=hashlib.sha256(raw).hexdigest(),
            source_hashes={str(k.source.id): k.source.sha256 for k in dataset.knowledge},
            recipe=recipe_for(spec.model, action.preset),
        )
        verify_job(job, raw)
        folder = training.directory(settings, job.id) / "input"
        folder.mkdir(parents=True, exist_ok=False, mode=0o700)
        (folder / "train.jsonl").write_bytes(raw)
        (folder / "job.json").write_text(job.model_dump_json())
        return evaluations.insert_revision(
            connection,
            "training_runs",
            TrainingRun(
                id=job.id,
                project_id=project_id,
                revision=1,
                created_at=job.created_at,
                updated_at=training.now(),
                status="queued",
                job_sha256=training.hash_file(folder / "job.json"),
                dataset_sha256=job.dataset_sha256,
                log=["Reviewed answers prepared. Waiting for the explicitly enabled local worker."],
            ),
        )


async def generate(adapter, item):
    try:
        async with asyncio.timeout(180):
            prediction = await adapter.predict(
                system=item.system, context=item.context, parameters=item.parameters
            )
        prediction = validate(prediction, item)
        return PredictionResult(prediction=prediction, error=None, input_sha256=item.input_sha256)
    except (Exception, asyncio.CancelledError) as exc:
        if isinstance(exc, asyncio.CancelledError):
            raise
        return PredictionResult(
            prediction=None,
            input_sha256=item.input_sha256,
            error=(
                exc.message
                if isinstance(exc, DomainError)
                else "LOCAL_TIMEOUT: Your adviser took too long. Wait for other local work "
                "to finish or shorten the question, then try again explicitly."
                if isinstance(exc, TimeoutError)
                else "PREDICTION_FAILED: No valid answer was returned. Try again explicitly."
            ),
        )


async def ask(settings, adapter, project_id, action):
    with connect(settings.database_path) as connection:
        spec = read_spec(connection, project_id)
        require_answer_format(spec, action.answer_format)
    spec = spec.model_copy(update={"outputs": "quartermaster.prediction/v1"})
    prompt_version = None
    # This path uses the local engine only. Hosted advice consent is a separate contract.
    if spec.model.adapter_artifact:
        version = training.get_version(settings, project_id, spec.model.adapter_artifact)
        if (
            version.schema_version != "quartermaster.adviser-version/v2"
            or version.answer_format != action.answer_format
        ):
            raise DomainError(
                "PREDICTION_MODEL: Select a compatible adviser version or retain the base.", 409
            )
        from quartermaster.training_artifacts import verify_candidate

        verify_candidate(settings, version)
        run = training.get_run(settings, project_id, version.training_run_id)
        job = training.read_job(settings, run)
        if spec.model.model_copy(update={"adapter_artifact": None}) != job.model:
            raise DomainError(
                "PREDICTION_MODEL: This version belongs to a different base model.", 409
            )
        prompt_version = job.examples[0].input.prompt_version
        if run.status != "completed" or run.candidate_id != version.id or not version.smoke_passed:
            raise DomainError("CANDIDATE_STATE: Select a completed adviser version.", 409)
        if settings.candidate_base_url is None:
            raise DomainError("CANDIDATE_CONFIG: Start the local candidate runtime.", 409)
        adapter = LocalInference(
            settings,
            alias=f"qm-candidate-{version.model_sha256}",
            base_url=str(settings.candidate_base_url).rstrip("/") + f"/{version.id}/v1",
        )
    elif spec.model.base_revision != settings.local_model_revision:
        raise DomainError(
            "LOCAL_MODEL_CHANGED: A different local model is installed. "
            "Open Advanced on Ask to use it while keeping your teaching and previous versions.",
            409,
        )
    case = Case(case_id=uuid4(), situation=action.situation)
    item = assemble(
        spec,
        case,
        action.answer_format,
        knowledge.advice_search(settings, spec, case),
        reviewed_preferences=related(settings, project_id, case, action.answer_format),
        prompt_version=prompt_version,
    )
    verify_evidence(settings, spec, item)
    result = await generate(adapter, item)
    run = PredictionRun(
        id=uuid4(),
        project_id=project_id,
        created_at=training.now(),
        adviser=spec,
        input=item,
        result=result,
    )
    with connect(settings.database_path) as connection:
        connection.execute(
            "INSERT INTO prediction_runs VALUES (?, ?, ?)",
            (str(run.id), str(project_id), run.model_dump_json()),
        )
    return run


def history(settings, project_id, limit=50):
    with connect(settings.database_path) as connection:
        read_spec(connection, project_id)
        rows = connection.execute(
            "SELECT document FROM prediction_runs WHERE project_id=? ORDER BY rowid DESC LIMIT ?",
            (str(project_id), -1 if limit is None else limit),
        )
        return [PredictionRun.model_validate_json(row[0]) for row in rows]


def verify_evidence(settings, spec, item):
    for evidence in item.evidence:
        current = knowledge.citation(
            settings, spec.id, evidence.citation_id, spec.knowledge_revision
        )
        if (
            current["source"].sha256 != evidence.source_sha256
            or current["chunk"].sha256 != evidence.excerpt_sha256
            or current["chunk"].text != evidence.text
        ):
            raise DomainError("PREDICTION_SOURCE: Restore the cited source and excerpt.", 409)


def related(settings, project_id, case, answer_format):
    """Small lexical selection from all latest reviewed decisions, excluding reserved cases."""
    import re

    from quartermaster.prediction_reviews import eligible, teaching

    candidates = []
    for decision in muster.decisions(settings, project_id):
        item = muster.get_import(settings, project_id, decision.import_id)
        bundle = muster.imported_bundle(settings, item)
        record = muster.example(bundle, decision.example_id)
        muster.verify_record_evidence(bundle, record)
        candidates.append((muster.decision_case(item, record, decision.input_fields), decision))
    candidates.extend((e.input, e.owner_decision) for e in teaching(settings, project_id))

    def words(text):
        return set(re.findall(r"\w+", text.casefold()))

    query = words(case.situation)
    ranked = []
    with connect(settings.database_path) as connection:
        # Never supply a reserved query to related-teaching routing either.
        if not eligible(connection, project_id, case):
            return []
        for situation, decision in candidates:
            target = decision.target
            if (
                target.kind != answer_format.kind
                or (target.kind == "number" and target.unit != answer_format.unit)
                or (target.kind == "category" and target.value not in answer_format.choices)
                or not eligible(connection, project_id, situation)
            ):
                continue
            score = len(query & words(situation.situation))
            if score:
                ranked.append((score, str(decision.created_at), situation, decision))
    ranked.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return [
        dict(
            situation=s.situation[:1200],
            target=d.target.model_dump(mode="json"),
            reasoning=d.reasoning[:600],
            decision_id=str(d.id),
            revision=d.revision,
            meaning="Owner preference, not a verified source fact or observed outcome",
        )
        for _, _, s, d in ranked[:3]
    ]
