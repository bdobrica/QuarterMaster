"""Guided teaching routes; every external request is a separate explicit action."""

from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from quartermaster import interviews
from quartermaster.api.foundation import form_error, page, settings, validate_form
from quartermaster.api.routes import require_same_origin
from quartermaster.builder import provider_identity, test_provider
from quartermaster.contracts.interview import (
    Answer,
    Consent,
    Interview,
    Prepare,
    ProviderTest,
    Review,
    VersionedAction,
)
from quartermaster.errors import DomainError
from quartermaster.projects import get_adviser
from quartermaster.sources import list_sources

router = APIRouter()


def redirect(project_id):
    return RedirectResponse(f"/projects/{project_id}/interview", status_code=303)


def interview_page(project_id, request, provider_message=None):
    config = settings(request)
    state = interviews.get_interview(config, project_id)
    try:
        endpoint, model = provider_identity(config)
    except DomainError:
        endpoint, model = None, None
    return page(
        request,
        "interview.html",
        project=get_adviser(config.database_path, project_id),
        state=state,
        questions=interviews.QUESTIONS,
        complete=all(v is not None for v in state.answers.model_dump().values()),
        next_topic=next((k for k, v in state.answers.model_dump().items() if v is None), None),
        history=interviews.interview_history(config, project_id),
        sources=list_sources(config, project_id),
        endpoint=endpoint,
        model=model,
        provider_message=provider_message,
    )


async def form_values(request, allowed):
    require_same_origin(request, form=True)
    async with request.form(max_files=0, max_fields=15, max_part_size=16384) as form:
        if set(form) - set(allowed) or len(form.multi_items()) != len(form):
            raise form_error()
        data = dict(form)
    try:
        if "expected_revision" in allowed:
            data["expected_revision"] = int(data.get("expected_revision", ""))
    except (ValueError, TypeError):
        raise form_error() from None
    return data


@router.get("/projects/{project_id}/interview")
def guided_page(project_id: UUID, request: Request):
    return interview_page(project_id, request)


@router.get("/api/projects/{project_id}/interview", response_model=Interview)
def get_state(project_id: UUID, request: Request):
    return interviews.get_interview(settings(request), project_id)


@router.get("/api/projects/{project_id}/interview/revisions", response_model=list[Interview])
def get_history(project_id: UUID, request: Request):
    return interviews.interview_history(settings(request), project_id)


@router.post("/api/builder/test")
async def provider_test(action: ProviderTest, request: Request):
    require_same_origin(request)
    return await test_provider(request.app.state.builder)


@router.post("/projects/{project_id}/interview/provider-test")
async def provider_test_form(project_id: UUID, request: Request):
    data = await form_values(request, {"consent"})
    validate_form(ProviderTest, {"consent": data.get("consent") == "yes"})
    get_adviser(settings(request).database_path, project_id)
    try:
        result = await test_provider(request.app.state.builder)
        message = result["detail"]
    except DomainError as exc:
        message = exc.message
    return interview_page(project_id, request, message)


@router.post("/api/projects/{project_id}/interview/answers", response_model=Interview)
def save_answer(project_id: UUID, action: Answer, request: Request):
    require_same_origin(request)
    return interviews.answer(settings(request), project_id, action)


@router.post("/projects/{project_id}/interview/answers")
async def answer_form(project_id: UUID, request: Request):
    data = await form_values(request, {"expected_revision", "topic", "answer"})
    interviews.answer(settings(request), project_id, validate_form(Answer, data))
    return redirect(project_id)


@router.post("/api/projects/{project_id}/interview/manual", response_model=Interview)
def manual_draft(project_id: UUID, action: VersionedAction, request: Request):
    require_same_origin(request)
    return interviews.manual_draft(settings(request), project_id, action)


@router.post("/projects/{project_id}/interview/manual")
async def manual_form(project_id: UUID, request: Request):
    data = await form_values(request, {"expected_revision"})
    interviews.manual_draft(settings(request), project_id, validate_form(VersionedAction, data))
    return redirect(project_id)


@router.post("/api/projects/{project_id}/interview/prepare", response_model=Interview)
def prepare(project_id: UUID, action: Prepare, request: Request):
    require_same_origin(request)
    return interviews.prepare(settings(request), project_id, action)


@router.post("/projects/{project_id}/interview/prepare")
async def prepare_form(project_id: UUID, request: Request):
    data = await form_values(request, {"expected_revision", "excerpt_0", "excerpt_1", "excerpt_2"})
    ids = [value for key, value in data.items() if key.startswith("excerpt_") and value]
    action = validate_form(
        Prepare, {"expected_revision": data["expected_revision"], "excerpt_source_ids": ids}
    )
    interviews.prepare(settings(request), project_id, action)
    return redirect(project_id)


@router.post("/api/projects/{project_id}/interview/send", response_model=Interview)
async def send(project_id: UUID, action: Consent, request: Request):
    require_same_origin(request)
    return await interviews.send(settings(request), request.app.state.builder, project_id, action)


@router.post("/projects/{project_id}/interview/send")
async def send_form(project_id: UUID, request: Request):
    data = await form_values(
        request, {"expected_revision", "turn_id", "disclosure_sha256", "consent"}
    )
    data["consent"] = data.get("consent") == "yes"
    await interviews.send(
        settings(request), request.app.state.builder, project_id, validate_form(Consent, data)
    )
    return redirect(project_id)


@router.post("/api/projects/{project_id}/interview/review", response_model=Interview)
def review(project_id: UUID, action: Review, request: Request):
    require_same_origin(request)
    return interviews.review(settings(request), project_id, action)


@router.post("/projects/{project_id}/interview/review")
async def review_form(project_id: UUID, request: Request):
    fields = {
        "name",
        "mission",
        "business_goal",
        "available_choices",
        "target_behavior",
        "case_grain",
        "decision_inputs",
        "success_and_harm",
    }
    data = await form_values(request, fields | {"action", "expected_revision"})
    edited = None
    if data.get("action") == "apply":
        edited = {
            "name": data.get("name"),
            "mission": data.get("mission"),
            "business_goal": data.get("business_goal") or None,
            "decision_definition": {
                k: data.get(k) for k in fields - {"name", "mission", "business_goal"}
            },
        }
    action = validate_form(
        Review,
        {
            "expected_revision": data["expected_revision"],
            "action": data.get("action"),
            "edited": edited,
        },
    )
    interviews.review(settings(request), project_id, action)
    return redirect(project_id)
