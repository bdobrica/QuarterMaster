"""Collection handoff and personal teaching; browser/extraction controls live in Collect."""

from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, RedirectResponse

from quartermaster import muster
from quartermaster.api.foundation import form_error, page, settings, validate_form
from quartermaster.api.routes import require_same_origin
from quartermaster.contracts.muster import (
    DecisionInput,
    ImportCollection,
    MusterImport,
    OwnerDecision,
    UseKnowledge,
)
from quartermaster.errors import DomainError
from quartermaster.knowledge import current_knowledge
from quartermaster.projects import get_adviser

router = APIRouter()


def link(project_id, import_id=None):
    return f"/projects/{project_id}/teach" + (f"/{import_id}" if import_id else "")


@router.get("/projects/{project_id}/teach")
def teaching_page(project_id: UUID, request: Request):
    config = settings(request)
    return page(
        request,
        "muster_collections.html",
        project=get_adviser(config.database_path, project_id),
        publications=muster.publications(config),
        imports=muster.imports(config, project_id),
    )


@router.get("/projects/{project_id}/teach/{import_id}")
def collection_page(project_id: UUID, import_id: UUID, request: Request):
    config = settings(request)
    item = muster.get_import(config, project_id, import_id)
    bundle = muster.imported_bundle(config, item)
    return page(
        request,
        "muster_collection.html",
        project=get_adviser(config.database_path, project_id),
        item=item,
        bundle=bundle,
        knowledge=current_knowledge(config, project_id),
        decisions={d.example_id: d for d in muster.decisions(config, project_id, import_id)},
    )


def example_context(config, project_id, import_id, index):
    item = muster.get_import(config, project_id, import_id)
    bundle = muster.imported_bundle(config, item)
    if not 0 <= index < len(bundle.examples):
        raise DomainError("MUSTER_EXAMPLE_MISSING: Choose a saved example.", 404)
    return item, bundle, bundle.examples[index]


@router.get("/projects/{project_id}/teach/{import_id}/examples/{index}")
def example_page(project_id: UUID, import_id: UUID, index: int, request: Request):
    config = settings(request)
    item, bundle, record = example_context(config, project_id, import_id, index)
    decision = next(
        (
            d
            for d in muster.decisions(config, project_id, import_id)
            if d.example_id == record["id"]
        ),
        None,
    )
    return page(
        request,
        "muster_example.html",
        project=get_adviser(config.database_path, project_id),
        item=item,
        record=record,
        fields=bundle.schema["properties"],
        index=index,
        count=len(bundle.examples),
        decision=decision,
    )


@router.get("/api/projects/{project_id}/muster", response_model=list[MusterImport])
def list_api(project_id: UUID, request: Request):
    return muster.imports(settings(request), project_id)


@router.post("/api/projects/{project_id}/muster", response_model=MusterImport)
def import_api(project_id: UUID, action: ImportCollection, request: Request):
    require_same_origin(request)
    return muster.import_collection(settings(request), project_id, action.publication)


@router.post("/projects/{project_id}/teach/import")
async def import_form(project_id: UUID, request: Request):
    require_same_origin(request, form=True)
    async with request.form(max_files=0, max_fields=1) as form:
        action = validate_form(ImportCollection, dict(form))
    from starlette.concurrency import run_in_threadpool

    item = await run_in_threadpool(
        muster.import_collection, settings(request), project_id, action.publication
    )
    return RedirectResponse(link(project_id, item.id), 303)


@router.post("/projects/{project_id}/teach/{import_id}/knowledge")
async def knowledge_form(project_id: UUID, import_id: UUID, request: Request):
    require_same_origin(request, form=True)
    async with request.form(max_files=0, max_fields=1) as form:
        action = validate_form(
            UseKnowledge, {"expected_revision": form.get("expected_revision") or None}
        )
    from starlette.concurrency import run_in_threadpool

    await run_in_threadpool(muster.use_knowledge, settings(request), project_id, import_id, action)
    return RedirectResponse(link(project_id, import_id), 303)


@router.post(
    "/api/projects/{project_id}/muster/{import_id}/examples/{index}/decision",
    response_model=OwnerDecision,
)
def decision_api(
    project_id: UUID, import_id: UUID, index: int, action: DecisionInput, request: Request
):
    require_same_origin(request)
    _, _, record = example_context(settings(request), project_id, import_id, index)
    return muster.save_decision(settings(request), project_id, import_id, record["id"], action)


@router.post("/projects/{project_id}/teach/{import_id}/examples/{index}")
async def decision_form(project_id: UUID, import_id: UUID, index: int, request: Request):
    require_same_origin(request, form=True)
    async with request.form(max_files=0, max_fields=40, max_part_size=16384) as form:
        try:
            target = {"kind": form.get("kind"), "value": form.get("value")}
            if target["kind"] == "number":
                target.update(value=float(target["value"]), unit=form.get("unit"))
            action = validate_form(
                DecisionInput,
                {
                    "expected_revision": int(form.get("expected_revision", "")),
                    "input_fields": form.getlist("input_field"),
                    "inputs_available_at_decision": form.get("inputs_available_at_decision")
                    == "yes",
                    "target": target,
                    "reasoning": form.get("reasoning", ""),
                },
            )
        except (ValueError, TypeError):
            raise form_error() from None
    from starlette.concurrency import run_in_threadpool

    def save():
        _, _, record = example_context(settings(request), project_id, import_id, index)
        muster.save_decision(settings(request), project_id, import_id, record["id"], action)

    await run_in_threadpool(save)
    return RedirectResponse(f"{link(project_id, import_id)}/examples/{index}?saved=yes", 303)


@router.post("/projects/{project_id}/teach/{import_id}/dataset")
def dataset_form(project_id: UUID, import_id: UUID, request: Request):
    require_same_origin(request, form=True)
    digest, path = muster.freeze_teaching(settings(request), project_id, import_id)
    return FileResponse(
        path, media_type="application/json", filename=f"reviewed-teaching-{digest[:12]}.json"
    )


@router.get("/projects/{project_id}/teach/{import_id}/files/{name:path}")
def evidence_file(project_id: UUID, import_id: UUID, name: str, request: Request):
    item = muster.get_import(settings(request), project_id, import_id)
    bundle = muster.imported_bundle(settings(request), item)
    if name != "manifest.json" and name not in bundle.manifest["checksums"]:
        raise DomainError("MUSTER_FILE_MISSING: Choose a file from the saved publication.", 404)
    if name != "manifest.json":
        muster.verify_file(bundle, name)
    # All files, including HTML/SVG/media, download as data on this origin.
    return FileResponse(
        bundle.root / name,
        media_type="application/octet-stream",
        filename="muster-evidence" + (".json" if name.endswith(".json") else ".bin"),
        headers={
            "Content-Security-Policy": "sandbox; default-src 'none'",
            "X-Content-Type-Options": "nosniff",
        },
    )
