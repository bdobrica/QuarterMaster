"""Local export review/download routes. Runtime verification is an explicit host command."""

from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from quartermaster import exporting, training
from quartermaster.api.foundation import page, settings, validate_form
from quartermaster.api.interview import form_values
from quartermaster.api.routes import require_same_origin
from quartermaster.contracts.export import ExportManifest, ExportSelection
from quartermaster.projects import get_adviser

router = APIRouter()
API = "/api/projects/{project_id}/exports"
WEB = "/projects/{project_id}/export"


@router.get(WEB)
def export_page(project_id: UUID, request: Request):
    config = settings(request)
    return page(
        request,
        "export.html",
        project=get_adviser(config.database_path, project_id),
        candidates=training.versions(config, project_id),
        exports=exporting.list_exports(config, project_id),
        image=config.export_runtime_image,
    )


@router.get(API, response_model=list[ExportManifest])
def exports(project_id: UUID, request: Request):
    return exporting.list_exports(settings(request), project_id)


@router.post(API, response_model=ExportManifest, status_code=201)
def create(project_id: UUID, action: ExportSelection, request: Request):
    require_same_origin(request)
    return exporting.create_export(settings(request), project_id, action)


@router.post(WEB)
async def create_form(project_id: UUID, request: Request):
    data = await form_values(request, {"candidate_id", "acknowledge_contents"})
    data["acknowledge_contents"] = data.get("acknowledge_contents") == "on"
    action = validate_form(ExportSelection, data)
    await run_in_threadpool(exporting.create_export, settings(request), project_id, action)
    return RedirectResponse(f"/projects/{project_id}/export", status_code=303)


@router.get(API + "/{export_id}", response_model=ExportManifest)
def manifest(project_id: UUID, export_id: UUID, request: Request):
    return exporting.get_export(settings(request), project_id, export_id)


@router.get(API + "/{export_id}/download")
def download(project_id: UUID, export_id: UUID, request: Request):
    path = exporting.archive_path(settings(request), project_id, export_id)
    return FileResponse(path, media_type="application/x-tar", filename=f"adviser-{export_id}.tar")
