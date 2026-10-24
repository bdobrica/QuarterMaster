"""Owner-authored evaluation suites and local, explicit comparison actions."""

from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from quartermaster import evaluations, teaching
from quartermaster.api.foundation import page, settings, validate_form
from quartermaster.api.interview import form_values
from quartermaster.api.routes import require_same_origin
from quartermaster.contracts.evaluation import (
    ComparisonRating,
    EvaluationRun,
    EvaluationSuite,
    RatingInput,
    SaveEvaluationCase,
    SuiteAction,
    SuiteCreate,
    SuiteReview,
)
from quartermaster.projects import get_adviser

router = APIRouter()


def redirect(project_id, run_id=None):
    path = f"/projects/{project_id}/evaluations"
    return RedirectResponse(path + (f"?run_id={run_id}" if run_id else ""), status_code=303)


@router.get("/projects/{project_id}/evaluations")
def evaluation_page(project_id: UUID, request: Request, run_id: UUID | None = None):
    config = settings(request)
    run = evaluations.get_run(config, project_id, run_id) if run_id else None
    suite = (
        evaluations.get_suite(config, project_id, run.suite_id, run.suite_revision) if run else None
    )
    reviews = evaluations.ratings(config, project_id, run_id) if run else []
    runs = evaluations.list_runs(config, project_id)
    earlier = next(
        (r for r in runs if run and r.id != run.id and r.created_at < run.created_at), None
    )
    scope = (
        evaluations.comparison_scope(
            evaluations.get_suite(config, project_id, earlier.suite_id, earlier.suite_revision),
            suite,
        )
        if earlier
        else None
    )
    return page(
        request,
        "evaluations.html",
        project=get_adviser(config.database_path, project_id),
        suites=evaluations.list_suites(config, project_id),
        runs=runs,
        run=run,
        suite=suite,
        reviews={str(r.case_id): r for r in reviews},
        counts=evaluations.summary(suite, run, reviews) if run else None,
        preferences=evaluations.PREFERENCES,
        categories=teaching.CATEGORIES,
        behaviors=evaluations.BEHAVIORS,
        scope=scope,
    )


@router.get("/api/projects/{project_id}/evaluation-suites", response_model=list[EvaluationSuite])
def suites(project_id: UUID, request: Request):
    return evaluations.list_suites(settings(request), project_id)


@router.get(
    "/api/projects/{project_id}/evaluation-suites/{suite_id}", response_model=EvaluationSuite
)
def suite(project_id: UUID, suite_id: UUID, request: Request, revision: int | None = None):
    return evaluations.get_suite(settings(request), project_id, suite_id, revision)


@router.post("/api/projects/{project_id}/evaluation-suites", response_model=EvaluationSuite)
def create(project_id: UUID, action: SuiteCreate, request: Request):
    require_same_origin(request)
    return evaluations.create_suite(settings(request), project_id, action)


@router.post("/projects/{project_id}/evaluation-suites")
async def create_form(project_id: UUID, request: Request):
    data = await form_values(request, {"name"})
    evaluations.create_suite(settings(request), project_id, validate_form(SuiteCreate, data))
    return redirect(project_id)


@router.post(
    "/api/projects/{project_id}/evaluation-suites/{suite_id}/cases", response_model=EvaluationSuite
)
def save_case(project_id: UUID, suite_id: UUID, action: SaveEvaluationCase, request: Request):
    require_same_origin(request)
    return evaluations.save_case(settings(request), project_id, suite_id, action)


@router.post("/projects/{project_id}/evaluation-suites/{suite_id}/cases")
async def save_case_form(project_id: UUID, suite_id: UUID, request: Request):
    data = await form_values(
        request, {"expected_revision", "test_id", "expected_behavior", "expectation"}
    )
    evaluations.save_case(
        settings(request),
        project_id,
        suite_id,
        validate_form(
            SaveEvaluationCase,
            {
                "expected_revision": data.get("expected_revision"),
                "test_id": data.get("test_id"),
                "rubric": {
                    "expected_behavior": data.get("expected_behavior"),
                    "expectation": data.get("expectation"),
                },
            },
        ),
    )
    return redirect(project_id)


@router.post(
    "/api/projects/{project_id}/evaluation-suites/{suite_id}/freeze", response_model=EvaluationSuite
)
def freeze(project_id: UUID, suite_id: UUID, action: SuiteAction, request: Request):
    require_same_origin(request)
    return evaluations.freeze_suite(settings(request), project_id, suite_id, action)


@router.post("/projects/{project_id}/evaluation-suites/{suite_id}/freeze")
async def freeze_form(project_id: UUID, suite_id: UUID, request: Request):
    data = await form_values(request, {"expected_revision"})
    evaluations.freeze_suite(
        settings(request), project_id, suite_id, validate_form(SuiteAction, data)
    )
    return redirect(project_id)


@router.post(
    "/api/projects/{project_id}/evaluation-suites/{suite_id}/run", response_model=EvaluationRun
)
async def run(project_id: UUID, suite_id: UUID, action: SuiteAction, request: Request):
    require_same_origin(request)
    return await evaluations.run_suite(
        settings(request), request.app.state.inference, project_id, suite_id, action
    )


@router.post("/projects/{project_id}/evaluation-suites/{suite_id}/run")
async def run_form(project_id: UUID, suite_id: UUID, request: Request):
    data = await form_values(request, {"expected_revision"})
    run = await evaluations.run_suite(
        settings(request),
        request.app.state.inference,
        project_id,
        suite_id,
        validate_form(SuiteAction, data),
    )
    return redirect(project_id, run.id)


@router.get("/api/projects/{project_id}/evaluation-runs", response_model=list[EvaluationRun])
def runs(project_id: UUID, request: Request):
    return evaluations.list_runs(settings(request), project_id)


@router.get("/api/projects/{project_id}/evaluation-runs/{run_id}", response_model=EvaluationRun)
def get_run(project_id: UUID, run_id: UUID, request: Request, revision: int | None = None):
    return evaluations.get_run(settings(request), project_id, run_id, revision)


@router.get(
    "/api/projects/{project_id}/evaluation-runs/{run_id}/ratings",
    response_model=list[ComparisonRating],
)
def ratings(project_id: UUID, run_id: UUID, request: Request):
    return evaluations.ratings(settings(request), project_id, run_id)


@router.post(
    "/api/projects/{project_id}/evaluation-runs/{run_id}/ratings/{case_id}",
    response_model=ComparisonRating,
)
def rate(project_id: UUID, run_id: UUID, case_id: UUID, action: RatingInput, request: Request):
    require_same_origin(request)
    return evaluations.rate(settings(request), project_id, run_id, case_id, action)


@router.post("/projects/{project_id}/evaluation-runs/{run_id}/ratings/{case_id}")
async def rate_form(project_id: UUID, run_id: UUID, case_id: UUID, request: Request):
    data = await form_values(request, {"expected_revision", "preference", "category", "rationale"})
    evaluations.rate(
        settings(request), project_id, run_id, case_id, validate_form(RatingInput, data)
    )
    return redirect(project_id, run_id)


@router.post(
    "/api/projects/{project_id}/evaluation-suites/{suite_id}/review", response_model=EvaluationSuite
)
def review_suite(project_id: UUID, suite_id: UUID, action: SuiteReview, request: Request):
    require_same_origin(request)
    return evaluations.review_suite(settings(request), project_id, suite_id, action)


@router.post("/projects/{project_id}/evaluation-suites/{suite_id}/review")
async def review_suite_form(project_id: UUID, suite_id: UUID, request: Request):
    data = await form_values(request, {"expected_revision", "approved", "note"})
    data["approved"] = data.get("approved") == "yes"
    evaluations.review_suite(
        settings(request), project_id, suite_id, validate_form(SuiteReview, data)
    )
    return redirect(project_id)
