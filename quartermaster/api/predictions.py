"""Thin generic Ask and explicitly prepared local improvement controls."""

from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool

from quartermaster import muster, predictions, training
from quartermaster.api.foundation import page, settings, validate_form
from quartermaster.api.interview import form_values
from quartermaster.api.routes import require_same_origin
from quartermaster.contracts.interview import VersionedAction
from quartermaster.contracts.prediction import ImproveSelection, PredictionRun, PredictRequest
from quartermaster.contracts.training import Promote, TrainingRun
from quartermaster.projects import get_adviser

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
    fmt = selected.answer_format.model_dump() if selected else None
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


@router.post("/api/projects/{project_id}/predictions", response_model=PredictionRun)
async def predict_api(project_id: UUID, action: PredictRequest, request: Request):
    require_same_origin(request)
    return await predictions.ask(settings(request), request.app.state.inference, project_id, action)


@router.post("/projects/{project_id}/ask")
async def predict_form(project_id: UUID, request: Request):
    data = await form_values(request, {"situation", "kind", "unit", "choices"})
    action = validate_form(
        PredictRequest, {"situation": data.get("situation"), "answer_format": answer_format(data)}
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
    action = validate_form(
        ImproveSelection,
        {
            "expected_revision": data.get("expected_revision"),
            "answer_format": answer_format(data),
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
