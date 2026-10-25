from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from quartermaster.builder import preview_estimate
from quartermaster.contracts.project import Project, ProjectCreate
from quartermaster.db import check_schema, connect
from quartermaster.projects import create_project, list_projects

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parents[1] / "ui" / "templates")
templates.env.globals["provider_estimate"] = preview_estimate


def require_same_origin(request: Request, *, form: bool = False) -> None:
    origin = request.headers.get("origin")
    expected = str(request.base_url).rstrip("/")
    if (form and origin is None) or (origin is not None and origin != expected):
        raise HTTPException(403, "Open the local application and submit the form again.")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "Open the local application and submit the form again.")


@router.get("/healthz")
def health(request: Request):
    with connect(request.app.state.settings.database_path) as connection:
        check_schema(connection)
    if not request.app.state.settings.artifact_root.is_dir():
        raise HTTPException(503, "STORAGE_UNAVAILABLE: Restore the configured data directory.")
    return {"status": "ok"}


@router.get("/")
def landing(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"projects": list_projects(request.app.state.settings.database_path)},
    )


@router.get("/examples")
def examples(request: Request):
    return templates.TemplateResponse(request=request, name="examples.html", context={})


@router.get("/help")
def help_page(request: Request):
    return templates.TemplateResponse(request=request, name="help.html", context={})


@router.get("/api/projects", response_model=list[Project])
def projects(request: Request):
    return list_projects(request.app.state.settings.database_path)


@router.post("/api/projects", response_model=Project, status_code=201)
def new_project(draft: ProjectCreate, request: Request):
    require_same_origin(request)
    return create_project(request.app.state.settings.database_path, draft)


@router.post("/projects")
async def project_form(request: Request):
    require_same_origin(request, form=True)
    async with request.form(max_fields=3, max_files=0, max_part_size=16384) as form:
        try:
            data = dict(form)
            data["business_goal"] = data.get("business_goal") or None
            draft = ProjectCreate.model_validate(data)
        except ValidationError:
            # Do not reflect untrusted field values or validation inputs in the error.
            return templates.TemplateResponse(
                request=request,
                name="project_error.html",
                context={},
                status_code=422,
            )
    create_project(request.app.state.settings.database_path, draft)
    if request.headers.get("hx-request") == "true":
        return templates.TemplateResponse(
            request=request,
            name="projects.html",
            context={"projects": list_projects(request.app.state.settings.database_path)},
        )
    return RedirectResponse("/", status_code=303)


async def validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "detail": "REQUEST_INVALID: Check required fields, types and supported schema versions."
        },
    )
