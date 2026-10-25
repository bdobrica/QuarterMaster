"""Thin generic Ask and explicitly prepared local improvement controls."""

from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool

from quartermaster import muster, prediction_reviews, predictions, training
from quartermaster.api.foundation import page, settings, validate_form
from quartermaster.api.interview import form_values
from quartermaster.api.routes import require_same_origin
from quartermaster.contracts.interview import VersionedAction
from quartermaster.contracts.prediction import (
    ImproveSelection,
    PredictionReview,
    PredictionReviewInput,
    PredictionRun,
    PredictRequest,
)
from quartermaster.contracts.training import Promote, TrainingRun
from quartermaster.projects import configure_answer, get_adviser, use_local_base

router = APIRouter()


def answer_format(data):
    if data.get("kind") == "number":
        return {"kind": "number", "unit": data.get("unit")}
    return {
        "kind": data.get("kind"),
        "choices": [x.strip() for x in data.get("choices", "").splitlines() if x.strip()],
    }


@router.get("/projects/{project_id}/ask")
def ask_page(project_id: UUID, request: Request):
    config = settings(request)
    decisions = muster.decisions(config, project_id)
    candidates = [
        v
        for v in training.versions(config, project_id)
        if v.schema_version == "quartermaster.adviser-version/v2"
    ]
    project = get_adviser(config.database_path, project_id)
    selected = next((v for v in candidates if v.id == project.model.adapter_artifact), None)
    fmt = (
        project.answer_format.model_dump()
        if project.answer_format
        else (selected.answer_format.model_dump() if selected else None)
    )
    if fmt is None and decisions:
        target = decisions[-1].target
        fmt = (
            {"kind": "number", "unit": target.unit}
            if target.kind == "number"
            else {
                "kind": "category",
                "choices": list(
                    dict.fromkeys(d.target.value for d in decisions if d.target.kind == "category")
                ),
            }
        )
    return page(
        request,
        "ask.html",
        project=project,
        local_model_revision=config.local_model_revision,
        answer_format=fmt,
        runs=predictions.history(config, project_id),
        candidates=candidates,
        improvements=training.runs(config, project_id),
        candidate_examples={
            v.id: training.read_job(
                config, training.get_run(config, project_id, v.training_run_id)
            ).examples[:5]
            for v in candidates
        },
    )


@router.post("/api/projects/{project_id}/local-base")
def local_base(project_id: UUID, action: VersionedAction, request: Request):
    require_same_origin(request)
    return use_local_base(settings(request), project_id, action)


@router.post("/projects/{project_id}/local-base")
async def local_base_form(project_id: UUID, request: Request):
    require_same_origin(request, form=True)
    action = validate_form(VersionedAction, await form_values(request, {"expected_revision"}))
    use_local_base(settings(request), project_id, action)
    return RedirectResponse(f"/projects/{project_id}/ask", status_code=303)


@router.post("/api/projects/{project_id}/predictions", response_model=PredictionRun)
async def predict_api(project_id: UUID, action: PredictRequest, request: Request):
    require_same_origin(request)
    return await predictions.ask(settings(request), request.app.state.inference, project_id, action)


@router.post("/projects/{project_id}/ask")
async def predict_form(project_id: UUID, request: Request):
    data = await form_values(request, {"situation", "kind", "unit", "choices"})
    project = get_adviser(settings(request).database_path, project_id)
    action = validate_form(
        PredictRequest,
        {
            "situation": data.get("situation"),
            "answer_format": project.answer_format.model_dump()
            if project.answer_format
            else answer_format(data),
        },
    )
    await predictions.ask(settings(request), request.app.state.inference, project_id, action)
    return RedirectResponse(f"/projects/{project_id}/ask", 303)


@router.post("/api/projects/{project_id}/muster/{import_id}/improve", response_model=TrainingRun)
def improve_api(project_id: UUID, import_id: UUID, action: ImproveSelection, request: Request):
    require_same_origin(request)
    return predictions.prepare(settings(request), project_id, import_id, action)


@router.post("/projects/{project_id}/teach/{import_id}/improve")
async def improve_form(project_id: UUID, import_id: UUID, request: Request):
    data = await form_values(
        request, {"expected_revision", "kind", "unit", "choices", "acknowledge_resources"}
    )
    project = get_adviser(settings(request).database_path, project_id)
    action = validate_form(
        ImproveSelection,
        {
            "expected_revision": data.get("expected_revision"),
            "answer_format": (
                project.answer_format.model_dump() if project.answer_format else answer_format(data)
            ),
            "acknowledge_resources": data.get("acknowledge_resources") == "yes",
        },
    )
    await run_in_threadpool(predictions.prepare, settings(request), project_id, import_id, action)
    return RedirectResponse(f"/projects/{project_id}/ask", 303)


@router.post("/projects/{project_id}/ask/versions/{version_id}")
async def select_form(project_id: UUID, version_id: UUID, request: Request):
    data = await form_values(request, {"expected_revision", "acknowledge_regressions"})
    data["acknowledge_regressions"] = data.get("acknowledge_regressions") == "yes"
    await run_in_threadpool(
        training.promote, settings(request), project_id, version_id, validate_form(Promote, data)
    )
    return RedirectResponse(f"/projects/{project_id}/ask", 303)


@router.post("/projects/{project_id}/ask/base")
async def base_form(project_id: UUID, request: Request):
    data = await form_values(request, {"expected_revision"})
    training.retain_base(settings(request), project_id, validate_form(VersionedAction, data))
    return RedirectResponse(f"/projects/{project_id}/ask", 303)


@router.get("/projects/{project_id}/answer-format")
def format_page(project_id: UUID, request: Request):
    return page(
        request,
        "configure_answer.html",
        project=get_adviser(settings(request).database_path, project_id),
    )


@router.post("/projects/{project_id}/answer-format")
async def format_form(project_id: UUID, request: Request):
    from pydantic import TypeAdapter, ValidationError

    from quartermaster.api.foundation import form_error
    from quartermaster.contracts.answers import AnswerFormat

    data = await form_values(request, {"expected_revision", "kind", "unit", "choices"})
    try:
        fmt = TypeAdapter(AnswerFormat).validate_python(answer_format(data))
        revision = int(data.get("expected_revision", ""))
    except (ValueError, ValidationError):
        raise form_error() from None
    configure_answer(settings(request).database_path, project_id, fmt, revision)
    return RedirectResponse(f"/projects/{project_id}/teach", 303)


@router.get("/projects/{project_id}/review")
def review_page(project_id: UUID, request: Request):
    config = settings(request)
    histories = {}
    for record in prediction_reviews.history(config, project_id):
        histories.setdefault(record.prediction_id, []).append(record)
    runs = predictions.history(config, project_id, limit=None)
    from quartermaster.contracts.advice import Case
    from quartermaster.holdouts import near_duplicate

    conflicts = {}
    for run in runs:
        entries = histories.get(run.id, [])
        latest_target = next((r.target for r in reversed(entries) if r.target), None)
        if latest_target:
            conflicts[run.id] = [
                p
                for p in predictions.related(
                    config, project_id, run.input.case, run.input.answer_format
                )
                if p["target"] != latest_target.model_dump(mode="json")
                and near_duplicate(
                    run.input.case, Case(case_id=run.input.case.case_id, situation=p["situation"])
                )
            ]
    return page(
        request,
        "prediction_reviews.html",
        project=get_adviser(config.database_path, project_id),
        runs=runs,
        conflicts=conflicts,
        histories=histories,
    )


@router.post(
    "/api/projects/{project_id}/predictions/{run_id}/reviews", response_model=PredictionReview
)
def review_api(project_id: UUID, run_id: UUID, action: PredictionReviewInput, request: Request):
    require_same_origin(request)
    return prediction_reviews.save(settings(request), project_id, run_id, action)


@router.post("/projects/{project_id}/review/{run_id}")
async def review_form(project_id: UUID, run_id: UUID, request: Request):
    from quartermaster.api.foundation import form_error
    from quartermaster.db import connect

    data = await form_values(request, {"expected_revision", "action", "value", "reasoning"})
    target = None
    if data.get("action") == "correct":
        with connect(settings(request).database_path) as connection:
            run = prediction_reviews.read_run(connection, project_id, run_id)
        fmt = run.input.answer_format
        try:
            target = {
                "kind": fmt.kind,
                "value": float(data.get("value", ""))
                if fmt.kind == "number"
                else data.get("value"),
            }
        except ValueError:
            raise form_error() from None
        if fmt.kind == "number":
            target["unit"] = fmt.unit
    action = validate_form(
        PredictionReviewInput,
        {
            "expected_revision": data.get("expected_revision"),
            "action": data.get("action"),
            "target": target,
            "reasoning": data.get("reasoning", ""),
        },
    )
    record = prediction_reviews.save(settings(request), project_id, run_id, action)
    notice = "reserved" if record.target and not record.teaching_eligible else action.action
    return RedirectResponse(f"/projects/{project_id}/review?saved={notice}#answer-{run_id}", 303)


@router.post("/projects/{project_id}/improve")
async def improve_all_form(project_id: UUID, request: Request):
    from quartermaster.errors import DomainError

    data = await form_values(request, {"expected_revision", "acknowledge_resources"})
    spec = get_adviser(settings(request).database_path, project_id)
    if spec.answer_format is None:
        raise DomainError("ANSWER_SETTINGS: Save your adviser's answer settings first.")
    action = validate_form(
        ImproveSelection,
        {
            "expected_revision": data.get("expected_revision"),
            "answer_format": spec.answer_format.model_dump(),
            "acknowledge_resources": data.get("acknowledge_resources") == "yes",
        },
    )
    await run_in_threadpool(predictions.prepare, settings(request), project_id, None, action)
    return RedirectResponse(f"/projects/{project_id}/ask", 303)
