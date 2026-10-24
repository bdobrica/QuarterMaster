"""Test and correction routes; local advice and external lesson drafting are separate."""

from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from quartermaster import evaluations, teaching
from quartermaster.api.foundation import page, settings, validate_form
from quartermaster.api.interview import form_values
from quartermaster.api.routes import require_same_origin
from quartermaster.contracts.interview import VersionedAction
from quartermaster.contracts.teaching import (
    Feedback,
    FeedbackInput,
    Lesson,
    LessonReview,
    LessonSend,
    ManualLesson,
    TestInput,
    TestRun,
)
from quartermaster.db import connect
from quartermaster.holdouts import case_fingerprint
from quartermaster.projects import get_adviser

router = APIRouter()


def redirect(project_id):
    return RedirectResponse(f"/projects/{project_id}/test", status_code=303)


@router.get("/projects/{project_id}/test")
def test_page(project_id: UUID, request: Request, test_id: UUID | None = None):
    config = settings(request)
    lessons = teaching.latest_lessons(config, project_id)
    runs = (
        [teaching.get_test(config, project_id, test_id)]
        if test_id
        else teaching.list_tests(config, project_id)
    )
    with connect(config.database_path) as connection:
        held_out = {
            row[0]
            for row in connection.execute(
                "SELECT case_sha256 FROM evaluation_holdouts WHERE project_id=?", (str(project_id),)
            )
        }
    return page(
        request,
        "test.html",
        project=get_adviser(config.database_path, project_id),
        runs=runs,
        held_out_tests={str(run.id) for run in runs if case_fingerprint(run.case) in held_out},
        selected_test=test_id,
        suites=[s for s in evaluations.list_suites(config, project_id) if s.status == "draft"],
        behaviors=evaluations.BEHAVIORS,
        lessons=list(reversed(lessons)),
        categories=teaching.CATEGORIES,
        feedback={
            str(lesson.id): teaching.get_feedback(config, project_id, lesson.feedback_id)
            for lesson in lessons
        },
        local_ready=config.local_base_url is not None and config.local_model_sha256 is not None,
    )


@router.get("/api/projects/{project_id}/tests", response_model=list[TestRun])
def tests(project_id: UUID, request: Request):
    return teaching.list_tests(settings(request), project_id)


@router.get("/api/projects/{project_id}/tests/{test_id}", response_model=TestRun)
def get_test(project_id: UUID, test_id: UUID, request: Request):
    return teaching.get_test(settings(request), project_id, test_id)


@router.post("/api/projects/{project_id}/tests", response_model=TestRun)
async def advise(project_id: UUID, action: TestInput, request: Request):
    require_same_origin(request)
    return await teaching.advise(settings(request), request.app.state.inference, project_id, action)


@router.post("/projects/{project_id}/test")
async def advise_form(project_id: UUID, request: Request):
    data = await form_values(request, {"situation"})
    await teaching.advise(
        settings(request), request.app.state.inference, project_id, validate_form(TestInput, data)
    )
    return redirect(project_id)


@router.post("/api/projects/{project_id}/tests/{test_id}/feedback", response_model=Lesson)
def feedback(project_id: UUID, test_id: UUID, action: FeedbackInput, request: Request):
    require_same_origin(request)
    return teaching.feedback(settings(request), project_id, test_id, action)


@router.post("/projects/{project_id}/tests/{test_id}/feedback")
async def feedback_form(project_id: UUID, test_id: UUID, request: Request):
    data = await form_values(request, {"category", "correction"})
    teaching.feedback(settings(request), project_id, test_id, validate_form(FeedbackInput, data))
    return redirect(project_id)


@router.get("/api/projects/{project_id}/lessons", response_model=list[Lesson])
def lessons(project_id: UUID, request: Request):
    return teaching.latest_lessons(settings(request), project_id)


@router.get("/api/projects/{project_id}/lessons/revisions", response_model=list[Lesson])
def lesson_history(project_id: UUID, request: Request):
    return teaching.lesson_history(settings(request), project_id)


@router.get("/api/projects/{project_id}/feedback/{feedback_id}", response_model=Feedback)
def get_feedback(project_id: UUID, feedback_id: UUID, request: Request):
    return teaching.get_feedback(settings(request), project_id, feedback_id)


@router.post("/api/projects/{project_id}/lessons/{lesson_id}/prepare", response_model=Lesson)
def prepare(project_id: UUID, lesson_id: UUID, action: VersionedAction, request: Request):
    require_same_origin(request)
    return teaching.prepare_lesson(settings(request), project_id, lesson_id, action)


@router.post("/projects/{project_id}/lessons/{lesson_id}/prepare")
async def prepare_form(project_id: UUID, lesson_id: UUID, request: Request):
    data = await form_values(request, {"expected_revision"})
    teaching.prepare_lesson(
        settings(request), project_id, lesson_id, validate_form(VersionedAction, data)
    )
    return redirect(project_id)


@router.post("/api/projects/{project_id}/lessons/{lesson_id}/manual", response_model=Lesson)
def manual(project_id: UUID, lesson_id: UUID, action: ManualLesson, request: Request):
    require_same_origin(request)
    return teaching.manual_lesson(settings(request), project_id, lesson_id, action)


@router.post("/projects/{project_id}/lessons/{lesson_id}/manual")
async def manual_form(project_id: UUID, lesson_id: UUID, request: Request):
    data = await form_values(request, {"expected_revision", "applicability", "instruction"})
    teaching.manual_lesson(
        settings(request),
        project_id,
        lesson_id,
        validate_form(
            ManualLesson,
            {
                "expected_revision": data["expected_revision"],
                "text": {k: data.get(k) for k in ("applicability", "instruction")},
            },
        ),
    )
    return redirect(project_id)


@router.post("/api/projects/{project_id}/lessons/{lesson_id}/send", response_model=Lesson)
async def send(project_id: UUID, lesson_id: UUID, action: LessonSend, request: Request):
    require_same_origin(request)
    return await teaching.send_lesson(
        settings(request), request.app.state.builder, project_id, lesson_id, action
    )


@router.post("/projects/{project_id}/lessons/{lesson_id}/send")
async def send_form(project_id: UUID, lesson_id: UUID, request: Request):
    data = await form_values(
        request, {"expected_revision", "turn_id", "disclosure_sha256", "consent"}
    )
    data["consent"] = data.get("consent") == "yes"
    await teaching.send_lesson(
        settings(request),
        request.app.state.builder,
        project_id,
        lesson_id,
        validate_form(LessonSend, data),
    )
    return redirect(project_id)


@router.post("/api/projects/{project_id}/lessons/{lesson_id}/review", response_model=Lesson)
def review(project_id: UUID, lesson_id: UUID, action: LessonReview, request: Request):
    require_same_origin(request)
    return teaching.review_lesson(settings(request), project_id, lesson_id, action)


@router.post("/projects/{project_id}/lessons/{lesson_id}/review")
async def review_form(project_id: UUID, lesson_id: UUID, request: Request):
    data = await form_values(
        request, {"expected_revision", "action", "applicability", "instruction"}
    )
    edited = (
        {k: data.get(k) for k in ("applicability", "instruction")}
        if data.get("action") == "apply"
        else None
    )
    teaching.review_lesson(
        settings(request),
        project_id,
        lesson_id,
        validate_form(
            LessonReview,
            {
                "expected_revision": data["expected_revision"],
                "action": data.get("action"),
                "edited": edited,
            },
        ),
    )
    return redirect(project_id)
