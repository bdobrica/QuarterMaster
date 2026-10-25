"""Article-first knowledge pages and explicit draft / consent / review operations."""

import difflib
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from quartermaster import knowledge_editing as editing
from quartermaster.api.foundation import page, settings, validate_form
from quartermaster.api.interview import form_values
from quartermaster.api.routes import require_same_origin
from quartermaster.contracts.knowledge import (
    KnowledgeDraft,
    KnowledgeProposal,
    KnowledgeReplay,
    KnowledgeRequest,
    KnowledgeReview,
    KnowledgeSend,
)
from quartermaster.contracts.teaching import TestRun
from quartermaster.knowledge import current_knowledge, knowledge_history, search
from quartermaster.projects import get_adviser
from quartermaster.sources import get_source, source_bytes
from quartermaster.teaching import list_tests

router = APIRouter()


def redirect(project_id):
    return RedirectResponse(f"/projects/{project_id}/knowledge", status_code=303)


@router.get("/projects/{project_id}/knowledge")
def knowledge_page(project_id: UUID, request: Request, q: str = "", article: UUID | None = None):
    config = settings(request)
    revision = current_knowledge(config, project_id)
    articles = []
    for sid in revision.source_ids if revision else []:
        source = get_source(config, project_id, sid)
        articles.append(
            {"source": source, "text": source_bytes(config, source).decode("utf-8-sig")}
        )
    selected = next((item for item in articles if item["source"].id == article), None)
    pending = editing.proposals(config, project_id)
    diffs = {
        item.id: "\n".join(
            difflib.unified_diff(
                item.before.splitlines(),
                item.content.text.splitlines(),
                fromfile="Before (active when drafted)",
                tofile="After (proposed)",
                lineterm="",
            )
        )
        for item in pending
        if item.content
    }
    return page(
        request,
        "knowledge.html",
        project=get_adviser(config.database_path, project_id),
        knowledge=revision,
        articles=articles,
        selected=selected,
        proposals=pending,
        diffs=diffs,
        history=knowledge_history(config, project_id),
        summaries={
            p.applied_revision: p.content.title for p in pending if p.applied_revision and p.content
        },
        query=q,
        results=search(config, project_id, q),
        runs=list_tests(config, project_id),
    )


@router.post(
    "/api/projects/{project_id}/knowledge/proposals",
    response_model=KnowledgeProposal,
    status_code=201,
)
def manual_api(project_id: UUID, action: KnowledgeDraft, request: Request):
    require_same_origin(request)
    return editing.draft(settings(request), project_id, action)


@router.post(
    "/api/projects/{project_id}/knowledge/proposals/prepare",
    response_model=KnowledgeProposal,
    status_code=201,
)
def prepare_api(project_id: UUID, action: KnowledgeRequest, request: Request):
    require_same_origin(request)
    return editing.draft(settings(request), project_id, action, ai=True)


@router.get(
    "/api/projects/{project_id}/knowledge/proposals", response_model=list[KnowledgeProposal]
)
def proposals_api(project_id: UUID, request: Request):
    return editing.proposals(settings(request), project_id)


@router.post(
    "/api/projects/{project_id}/knowledge/proposals/{proposal_id}/send",
    response_model=KnowledgeProposal,
)
async def send_api(project_id: UUID, proposal_id: UUID, action: KnowledgeSend, request: Request):
    require_same_origin(request)
    return await editing.send(
        settings(request), request.app.state.builder, project_id, proposal_id, action
    )


@router.post(
    "/api/projects/{project_id}/knowledge/proposals/{proposal_id}/review",
    response_model=KnowledgeProposal,
)
def review_api(project_id: UUID, proposal_id: UUID, action: KnowledgeReview, request: Request):
    require_same_origin(request)
    return editing.review(settings(request), project_id, proposal_id, action)


@router.post("/projects/{project_id}/knowledge/proposals")
async def draft_form(project_id: UUID, request: Request):
    data = await form_values(
        request,
        {"source_id", "expected_revision", "title", "text", "instruction", "mode"},
        integer_revision=False,
    )
    ai = data.pop("mode", "") == "ai"
    for key in ("source_id", "expected_revision"):
        data[key] = data.get(key) or None
    if ai:
        data.pop("title", None)
        data.pop("text", None)
    else:
        data.pop("instruction", None)
    editing.draft(
        settings(request),
        project_id,
        validate_form(KnowledgeRequest if ai else KnowledgeDraft, data),
        ai=ai,
    )
    return redirect(project_id)


@router.post("/projects/{project_id}/knowledge/proposals/{proposal_id}/send")
async def send_form(project_id: UUID, proposal_id: UUID, request: Request):
    data = await form_values(
        request, {"expected_revision", "turn_id", "disclosure_sha256", "consent"}
    )
    data["consent"] = data.get("consent") == "yes"
    await editing.send(
        settings(request),
        request.app.state.builder,
        project_id,
        proposal_id,
        validate_form(KnowledgeSend, data),
    )
    return redirect(project_id)


@router.post("/projects/{project_id}/knowledge/proposals/{proposal_id}/review")
async def review_form(project_id: UUID, proposal_id: UUID, request: Request):
    data = await form_values(request, {"expected_revision", "action"})
    editing.review(settings(request), project_id, proposal_id, validate_form(KnowledgeReview, data))
    return redirect(project_id)


@router.post(
    "/api/projects/{project_id}/knowledge/proposals/{proposal_id}/replay",
    response_model=list[list[TestRun]],
)
async def replay_api(
    project_id: UUID, proposal_id: UUID, action: KnowledgeReplay, request: Request
):
    require_same_origin(request)
    return await editing.replay(
        settings(request), request.app.state.inference, project_id, proposal_id, action
    )


@router.post("/projects/{project_id}/knowledge/proposals/{proposal_id}/replay")
async def replay_form(project_id: UUID, proposal_id: UUID, request: Request):
    data = await form_values(request, {"original_test", "unseen_situation"})
    runs = await editing.replay(
        settings(request),
        request.app.state.inference,
        project_id,
        proposal_id,
        validate_form(KnowledgeReplay, data),
    )
    return page(
        request,
        "knowledge_replay.html",
        project=get_adviser(settings(request).database_path, project_id),
        pairs=runs,
    )


@router.get("/projects/{project_id}/knowledge/replay/{after_id}")
def saved_replay(project_id: UUID, after_id: UUID, request: Request):
    from quartermaster.teaching import get_test

    after = get_test(settings(request), project_id, after_id)
    before = get_test(settings(request), project_id, after.comparison_of)
    return page(
        request,
        "knowledge_replay.html",
        project=get_adviser(settings(request).database_path, project_id),
        pairs=[[before, after]],
    )
