"""Thin routes for the local teaching foundation; parsers/mappings stay outside HTTP."""

import json
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import TypeAdapter, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from quartermaster.api.routes import require_same_origin, templates
from quartermaster.cases import apply_mapping, list_mappings, preview_mapping, saved_cases
from quartermaster.contracts.adviser import AdviserSpec, ProjectEdit
from quartermaster.contracts.sources import (
    CaseMapping,
    DerivedCase,
    Evidence,
    FieldRef,
    Join,
    KnowledgeRevision,
    KnowledgeSelection,
    Label,
    MappingPreview,
    ParseOptions,
    Source,
    TableRef,
)
from quartermaster.errors import DomainError
from quartermaster.ingestion import MAX_UPLOAD
from quartermaster.knowledge import (
    citation,
    current_knowledge,
    knowledge_history,
    revise_knowledge,
    search,
)
from quartermaster.projects import adviser_history, edit_adviser, get_adviser
from quartermaster.sources import (
    blob_path,
    get_source,
    list_sources,
    parsed_source,
    source_bytes,
    upload_source,
)

router = APIRouter()


def settings(request):
    return request.app.state.settings


def page(request, name, **context):
    return templates.TemplateResponse(request=request, name=name, context=context)


def redirect(project_id):
    return RedirectResponse(f"/projects/{project_id}", status_code=303)


def form_error():
    return DomainError("FORM_INVALID: Check the required fields and choices, then submit again.")


def validate_form(model, data):
    try:
        return model.model_validate(data)
    except (ValidationError, TypeError, ValueError):
        raise form_error() from None


@router.get("/api/projects/{project_id}", response_model=AdviserSpec)
def adviser(project_id: UUID, request: Request):
    return get_adviser(settings(request).database_path, project_id)


@router.get("/api/projects/{project_id}/revisions", response_model=list[AdviserSpec])
def revisions(project_id: UUID, request: Request):
    return adviser_history(settings(request).database_path, project_id)


@router.patch("/api/projects/{project_id}", response_model=AdviserSpec)
def update_adviser(project_id: UUID, draft: ProjectEdit, request: Request):
    require_same_origin(request)
    return edit_adviser(settings(request).database_path, project_id, draft)


@router.get("/projects/{project_id}")
def project_page(project_id: UUID, request: Request):
    config = settings(request)
    return page(
        request,
        "project.html",
        project=get_adviser(config.database_path, project_id),
        history=adviser_history(config.database_path, project_id),
        sources=list_sources(config, project_id),
        knowledge=current_knowledge(config, project_id),
        knowledge_history=knowledge_history(config, project_id),
        mappings=list_mappings(config, project_id),
    )


@router.post("/projects/{project_id}")
async def edit_form(project_id: UUID, request: Request):
    require_same_origin(request, form=True)
    async with request.form(max_files=0, max_fields=4, max_part_size=16384) as form:
        data = dict(form)
        try:
            data["expected_revision"] = int(data.get("expected_revision", ""))
        except ValueError:
            raise form_error() from None
        data["business_goal"] = data.get("business_goal") or None
        edit_adviser(settings(request).database_path, project_id, validate_form(ProjectEdit, data))
    return redirect(project_id)


async def receive_upload(project_id, request):
    require_same_origin(request, form=True)
    # This occurs before reading any multipart data, even for an unknown project.
    get_adviser(settings(request).database_path, project_id)
    async with request.form(max_files=1, max_fields=3, max_part_size=16384) as form:
        if set(form) != {"file", "label", "encoding", "delimiter"} or len(form.multi_items()) != 4:
            raise form_error()
        upload = form["file"]
        if not isinstance(upload, UploadFile) or not upload.filename:
            raise form_error()
        try:
            label = TypeAdapter(Label).validate_python(form["label"], strict=True)
            options = ParseOptions(encoding=form["encoding"], delimiter=form["delimiter"])
        except ValidationError:
            raise form_error() from None
        if upload.size is not None and upload.size > MAX_UPLOAD:
            raise DomainError("UPLOAD_SIZE: Choose a nonempty file no larger than 8 MiB.", 413)
        data = await upload.read(MAX_UPLOAD + 1)
        if len(data) > MAX_UPLOAD:
            raise DomainError("UPLOAD_SIZE: Choose a nonempty file no larger than 8 MiB.", 413)
        # Parsing is synchronous CPU/disk work, offloaded by the endpoint below.
        return await run_in_threadpool(
            upload_source, settings(request), project_id, upload.filename, data, label, options
        )


@router.post("/api/projects/{project_id}/sources", status_code=201, response_model=Source)
async def upload_api(project_id: UUID, request: Request):
    return await receive_upload(project_id, request)


@router.post("/projects/{project_id}/sources")
async def upload_form(project_id: UUID, request: Request):
    source = await receive_upload(project_id, request)
    return RedirectResponse(f"/projects/{project_id}/sources/{source.id}", status_code=303)


@router.get("/api/projects/{project_id}/sources", response_model=list[Source])
def sources_api(project_id: UUID, request: Request):
    return list_sources(settings(request), project_id)


@router.get("/api/projects/{project_id}/sources/{source_id}", response_model=Source)
def source_api(project_id: UUID, source_id: UUID, request: Request):
    return get_source(settings(request), project_id, source_id)


@router.get("/projects/{project_id}/sources/{source_id}")
def source_page(project_id: UUID, source_id: UUID, request: Request):
    source = get_source(settings(request), project_id, source_id)
    markdown = parsed_source(settings(request), source).markdown if source.kind == "md" else None
    return page(request, "source.html", source=source, markdown=markdown)


@router.get("/projects/{project_id}/sources/{source_id}/original")
def download(project_id: UUID, source_id: UUID, request: Request):
    source = get_source(settings(request), project_id, source_id)
    source_bytes(settings(request), source)
    return FileResponse(
        blob_path(settings(request).artifact_root, source.sha256),
        media_type="application/octet-stream",
        filename=f"{source.id}.{source.kind}",
        headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"},
    )


@router.post("/api/projects/{project_id}/mappings/preview", response_model=MappingPreview)
def mapping_preview_api(project_id: UUID, mapping: CaseMapping, request: Request):
    require_same_origin(request)
    return preview_mapping(settings(request), project_id, mapping)


@router.post("/api/projects/{project_id}/mappings", status_code=201)
def mapping_api(project_id: UUID, mapping: CaseMapping, request: Request):
    require_same_origin(request)
    return apply_mapping(settings(request), project_id, mapping)


@router.get("/api/projects/{project_id}/mappings")
def mappings_api(project_id: UUID, request: Request):
    return list_mappings(settings(request), project_id)


@router.get(
    "/api/projects/{project_id}/mappings/{mapping_id}/cases", response_model=list[DerivedCase]
)
def cases_api(project_id: UUID, mapping_id: UUID, request: Request):
    return saved_cases(settings(request), project_id, mapping_id)


def mapping_choices(config, project_id):
    sources = list_sources(config, project_id)
    tables = [
        TableRef(source_id=s.id, sheet=t.name)
        for s in sources
        if s.label != "knowledge"
        for t in s.sheets
        if t.fields
    ]
    fields = [
        FieldRef(source_id=s.id, sheet=t.name, field=f.name)
        for s in sources
        if s.label != "knowledge"
        for t in s.sheets
        for f in t.fields
    ]
    names = {s.id: f"{s.display_name} (upload {index + 1})" for index, s in enumerate(sources)}
    return tables, fields, names


@router.get("/projects/{project_id}/mappings/new")
def mapping_page(project_id: UUID, request: Request):
    tables, fields, names = mapping_choices(settings(request), project_id)
    return page(
        request,
        "mapping.html",
        project=get_adviser(settings(request).database_path, project_id),
        tables=tables,
        fields=fields,
        names=names,
    )


@router.post("/projects/{project_id}/mappings/preview")
async def mapping_preview_form(project_id: UUID, request: Request):
    require_same_origin(request, form=True)
    tables, fields, names = mapping_choices(settings(request), project_id)
    async with request.form(max_files=0, max_fields=2200, max_part_size=16384) as form:

        def selected(choices, name):
            try:
                index = int(form[name])
                if index < 0:
                    raise ValueError
                return choices[index]
            except (ValueError, IndexError, KeyError, TypeError):
                raise form_error() from None

        joins = []
        if form.get("join_table"):
            right_table = selected(tables, "join_table")
            left = selected(fields, "left_key")
            right = selected(fields, "right_key")
            if (right.source_id, right.sheet) != (right_table.source_id, right_table.sheet):
                raise DomainError("JOIN_RIGHT: Choose a right key from the joined table.")
            joins = [Join(table=right_table, left=left, right_key=right.field)]
        data = {
            "primary": selected(tables, "primary"),
            "grain": form.get("grain"),
            "decision_time": form.get("decision_time"),
            "joins": joins,
            "inputs": [],
            "outcomes": [],
            "targets": [],
            "confirmed": True,
            "inputs_available_at_decision": form.get("available") == "yes",
        }
        roles = {"input": "inputs", "outcome": "outcomes", "target": "targets"}
        for index, field in enumerate(fields):
            role = form.get(f"role_{index}", "ignore")
            if role not in {*roles, "ignore"}:
                raise form_error()
            if role in roles:
                data[roles[role]].append(field)
        mapping = validate_form(CaseMapping, data)
    preview = await run_in_threadpool(preview_mapping, settings(request), project_id, mapping)

    def display_fields(values):
        rows = []
        for reference, value in values.items():
            source_id, sheet, field = json.loads(reference)
            rows.append(
                {
                    "source_id": source_id,
                    "name": names[UUID(source_id)],
                    "sheet": sheet,
                    "field": field,
                    "value": value,
                }
            )
        return rows

    entries = [
        {
            "item": item,
            "groups": [
                ("Decision input", display_fields(json.loads(item.case.situation)["fields"])),
                (
                    "Later observed outcome",
                    display_fields(json.loads(item.case.observed_outcome or "{}")),
                ),
                ("Unreviewed target candidate", display_fields(item.target_candidate)),
            ],
        }
        for item in preview.samples
    ]
    return page(
        request, "mapping_review.html", project_id=project_id, preview=preview, entries=entries
    )


@router.post("/projects/{project_id}/mappings")
async def mapping_confirm_form(project_id: UUID, request: Request):
    require_same_origin(request, form=True)
    async with request.form(max_files=0, max_fields=2, max_part_size=65536) as form:
        if form.get("confirm") != "yes":
            raise DomainError("MAPPING_REVIEW: Review the preview and confirm before saving cases.")
        try:
            mapping = CaseMapping.model_validate_json(form.get("mapping", ""))
        except (ValidationError, TypeError):
            raise form_error() from None
    await run_in_threadpool(apply_mapping, settings(request), project_id, mapping)
    return redirect(project_id)


@router.get("/api/projects/{project_id}/knowledge", response_model=KnowledgeRevision | None)
def knowledge_api(project_id: UUID, request: Request):
    return current_knowledge(settings(request), project_id)


@router.get(
    "/api/projects/{project_id}/knowledge/revisions", response_model=list[KnowledgeRevision]
)
def knowledge_revisions_api(project_id: UUID, request: Request):
    return knowledge_history(settings(request), project_id)


@router.post(
    "/api/projects/{project_id}/knowledge", status_code=201, response_model=KnowledgeRevision
)
def knowledge_select_api(project_id: UUID, selection: KnowledgeSelection, request: Request):
    require_same_origin(request)
    return revise_knowledge(settings(request), project_id, selection)


@router.post("/projects/{project_id}/knowledge")
async def knowledge_select_form(project_id: UUID, request: Request):
    require_same_origin(request, form=True)
    async with request.form(max_files=0, max_fields=102, max_part_size=1024) as form:
        if set(form) - {"source_id", "expected_revision"}:
            raise form_error()
        try:
            selection = KnowledgeSelection.model_validate_json(
                json.dumps(
                    {
                        "source_ids": form.getlist("source_id"),
                        "expected_revision": form.get("expected_revision") or None,
                    }
                )
            )
        except ValidationError:
            raise form_error() from None
    await run_in_threadpool(revise_knowledge, settings(request), project_id, selection)
    return redirect(project_id)


@router.get("/api/projects/{project_id}/knowledge/search", response_model=list[Evidence])
def search_api(project_id: UUID, request: Request, q: str = "", revision: UUID | None = None):
    return search(settings(request), project_id, q, revision)


@router.get("/projects/{project_id}/knowledge/search")
def search_page(project_id: UUID, request: Request, q: str = "", revision: UUID | None = None):
    return page(
        request,
        "search.html",
        project_id=project_id,
        query=q,
        results=search(settings(request), project_id, q, revision),
    )


@router.get("/api/projects/{project_id}/citations/{citation_id}", response_model=Evidence)
def citation_api(
    project_id: UUID, citation_id: UUID, request: Request, revision: UUID | None = None
):
    return citation(settings(request), project_id, citation_id, revision)


@router.get("/projects/{project_id}/citations/{citation_id}")
def citation_page(
    project_id: UUID, citation_id: UUID, request: Request, revision: UUID | None = None
):
    return page(
        request,
        "citation.html",
        project_id=project_id,
        **citation(settings(request), project_id, citation_id, revision),
    )
