"""Test and correction routes; local advice and external lesson drafting are separate."""

from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from quartermaster import answer_reviews, evaluations, teaching
from quartermaster.api.foundation import page, settings, validate_form
from quartermaster.api.interview import form_values
from quartermaster.api.routes import require_same_origin
from quartermaster.contracts.adviser import AdviceEngineEdit, AdviserSpec
from quartermaster.contracts.interview import VersionedAction
from quartermaster.contracts.reviews import AnswerReviewInput
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
from quartermaster.projects import edit_advice_engine, get_adviser

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
        hosted_ready=bool(
            config.adviser_base_url and config.adviser_model and not config.adviser_local_only
        ),
        hosted_endpoint=str(config.adviser_base_url).rstrip("/")
        if config.adviser_base_url
        else None,
        hosted_model=config.adviser_model,
        hosted_effort=config.adviser_reasoning_effort,
        comparison_ready=bool(config.comparison_base_url and config.comparison_model_sha256),
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
    data = await form_values(request, {"situation", "compare_existing"})
    data["compare_existing"] = data.get("compare_existing") == "on"
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


@router.post("/api/projects/{project_id}/advice-engine", response_model=AdviserSpec)
def advice_engine(project_id: UUID, action: AdviceEngineEdit, request: Request):
    require_same_origin(request)
    return edit_advice_engine(settings(request), project_id, action)


@router.post("/projects/{project_id}/advice-engine")
async def advice_engine_form(project_id: UUID, request: Request):
    data = await form_values(request, {"expected_revision", "mode", "consent", "endpoint", "model"})
    data["consent"] = data.get("consent") == "yes"
    edit_advice_engine(settings(request), project_id, validate_form(AdviceEngineEdit, data))
    return redirect(project_id)


@router.post("/api/projects/{project_id}/tests/{test_id}/review")
def review_api(project_id: UUID, test_id: UUID, action: AnswerReviewInput, request: Request):
    require_same_origin(request)
    return answer_reviews.save(settings(request), project_id, test_id, action)


@router.post("/projects/{project_id}/tests/{test_id}/review")
async def answer_review_form(project_id: UUID, test_id: UUID, request: Request):
    data = await form_values(request, {"expected_revision", "status", "correction", "return_to"})
    destination = data.pop("return_to", "answer")
    if destination not in {"answer", "questions"}:
        from quartermaster.api.foundation import form_error

        raise form_error()
    answer_reviews.save(
        settings(request), project_id, test_id, validate_form(AnswerReviewInput, data)
    )
    path = (
        "improvements" if destination == "questions" else f"test?test_id={test_id}#test-{test_id}"
    )
    return RedirectResponse(f"/projects/{project_id}/{path}", 303)


@router.get("/projects/{project_id}/improvements")
def improvements_page(project_id: UUID, request: Request, status: str = "all"):
    from quartermaster.saved_questions import rows

    if status not in {"all", "pending", "pass", "fail"}:
        from quartermaster.errors import DomainError

        raise DomainError("REVIEW_FILTER: Choose All, Pending, Pass or Fail.")
    config = settings(request)
    questions = rows(config, project_id)
    return page(
        request,
        "improvements.html",
        project=get_adviser(config.database_path, project_id),
        questions=[row for row in questions if status == "all" or row["status"] == status],
        status=status,
    )


@router.post("/projects/{project_id}/improvements/rerun")
async def rerun_questions(project_id: UUID, request: Request):
    from quartermaster.api.foundation import form_error
    from quartermaster.saved_questions import rows

    require_same_origin(request, form=True)
    async with request.form(max_files=0, max_fields=12, max_part_size=1024) as form:
        if set(form) - {"question_ids", "confirm"} or len(form.getlist("confirm")) > 1:
            raise form_error()
        ids = form.getlist("question_ids")
        if not ids or len(ids) > 10 or len(ids) != len(set(ids)):
            raise form_error()
        confirm = form.get("confirm")
        if confirm not in {None, "yes"}:
            raise form_error()
    questions = {str(row["entry"].id): row for row in rows(settings(request), project_id)}
    if any(key not in questions for key in ids):
        raise form_error()
    selected = [questions[key] for key in ids]
    if confirm != "yes":
        return page(
            request,
            "question_rerun.html",
            project=get_adviser(settings(request).database_path, project_id),
            questions=selected,
        )
    for row in selected:
        case = row["entry"].case
        await teaching.advise(
            settings(request),
            request.app.state.inference,
            project_id,
            TestInput(situation=case.situation, choices=case.choices),
        )
    return RedirectResponse(f"/projects/{project_id}/improvements", 303)


@router.post("/projects/{project_id}/answers/{kind}/{run_id}/{key}/review")
async def output_review_form(project_id: UUID, kind: str, run_id: UUID, key: str, request: Request):
    data = await form_values(request, {"expected_revision", "status", "correction"})
    answer_reviews.save(
        settings(request),
        project_id,
        run_id,
        validate_form(AnswerReviewInput, data),
        kind=kind,
        key=key,
    )
    destinations = {
        "evaluation": f"evaluations?run_id={run_id}",
        "candidate": "train",
        "diagnostic": f"reliability?run_id={run_id}",
    }
    return RedirectResponse(f"/projects/{project_id}/{destinations[kind]}", 303)


@router.post("/projects/{project_id}/tests/{test_id}/save-question")
async def save_question_form(project_id: UUID, test_id: UUID, request: Request):
    from quartermaster.contracts.evaluation import SaveEvaluationCase
    from quartermaster.saved_questions import save_question

    data = await form_values(request, {"expectation"})
    config = settings(request)
    # Validate before creating any check set; saving is an explicit training exclusion.
    action = validate_form(
        SaveEvaluationCase,
        {
            "expected_revision": 1,
            "test_id": test_id,
            "rubric": {"expected_behavior": "any", "expectation": data.get("expectation")},
        },
    )
    save_question(config, project_id, action)
    return RedirectResponse(f"/projects/{project_id}/improvements", 303)
