"""Explicit development comparisons; no training, promotion or external builder calls."""

from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError

from quartermaster import reliability
from quartermaster.api.foundation import page, settings, validate_form
from quartermaster.api.interview import form_values
from quartermaster.api.routes import require_same_origin
from quartermaster.contracts.reliability import (
    Arm,
    FieldClaimCheck,
    FieldClaims,
    QualityReview,
    QualityReviewInput,
    ReliabilityInput,
    ReliabilityRun,
)
from quartermaster.errors import DomainError
from quartermaster.field_claims import check_claims
from quartermaster.projects import get_adviser

router = APIRouter()


@router.get("/projects/{project_id}/reliability")
def experiment_page(project_id: UUID, request: Request, run_id: UUID | None = None):
    config = settings(request)
    run = reliability.get_run(config, project_id, run_id) if run_id else None
    return page(
        request,
        "reliability.html",
        project=get_adviser(config.database_path, project_id),
        runs=reliability.list_runs(config, project_id),
        run=run,
        reviews={r.arm: r for r in reliability.reviews(config, project_id, run_id)} if run else {},
    )


@router.get("/api/projects/{project_id}/reliability-runs", response_model=list[ReliabilityRun])
def runs(project_id: UUID, request: Request):
    return reliability.list_runs(settings(request), project_id)


@router.get("/api/projects/{project_id}/reliability-runs/{run_id}", response_model=ReliabilityRun)
def get_run(project_id: UUID, run_id: UUID, request: Request):
    return reliability.get_run(settings(request), project_id, run_id)


@router.get("/api/projects/{project_id}/reliability-runs/{run_id}/diagnostics")
def diagnostics(project_id: UUID, run_id: UUID, request: Request):
    run = reliability.get_run(settings(request), project_id, run_id)
    return [
        {
            "arm": output.arm,
            "citation_count": output.citation_count,
            "citation_status": output.citation_status,
            "sentence_endings_valid": output.sentence_endings_valid,
        }
        for output in run.outputs
    ]


@router.post(
    "/api/projects/{project_id}/reliability-runs/{run_id}/check-claims",
    response_model=FieldClaimCheck,
)
def claims(project_id: UUID, run_id: UUID, action: FieldClaims, request: Request):
    require_same_origin(request)
    run = reliability.get_run(settings(request), project_id, run_id)
    return check_claims(run, action)


@router.post("/projects/{project_id}/reliability/{run_id}/check-claims")
async def claims_form(project_id: UUID, run_id: UUID, request: Request):
    data = await form_values(request, {"claims"})
    try:
        action = FieldClaims.model_validate_json(data.get("claims", ""))
    except ValidationError:
        raise DomainError(
            "FIELD_CLAIMS: Supply distinct fields, exact state/value/unit and citation UUIDs."
        ) from None
    config = settings(request)
    run = reliability.get_run(config, project_id, run_id)
    return page(
        request,
        "field_claims.html",
        project=get_adviser(config.database_path, project_id),
        run=run,
        action=action,
        result=check_claims(run, action),
    )


@router.post("/api/projects/{project_id}/reliability-runs", response_model=ReliabilityRun)
async def compare(project_id: UUID, action: ReliabilityInput, request: Request):
    require_same_origin(request)
    return await reliability.run_comparison(
        settings(request), request.app.state.inference, project_id, action
    )


@router.post("/projects/{project_id}/reliability")
async def compare_form(project_id: UUID, request: Request):
    data = await form_values(request, {"configuration"})
    try:
        action = ReliabilityInput.model_validate_json(data.get("configuration", ""))
    except ValidationError:
        raise DomainError(
            "RELIABILITY_INPUT: Check the question, inputs and reviewed field-rule JSON."
        ) from None
    run = await reliability.run_comparison(
        settings(request), request.app.state.inference, project_id, action
    )
    return RedirectResponse(f"/projects/{project_id}/reliability?run_id={run.id}", status_code=303)


@router.get(
    "/api/projects/{project_id}/reliability-runs/{run_id}/reviews",
    response_model=list[QualityReview],
)
def reviews(project_id: UUID, run_id: UUID, request: Request):
    return reliability.reviews(settings(request), project_id, run_id)


@router.post(
    "/api/projects/{project_id}/reliability-runs/{run_id}/reviews/{arm}",
    response_model=QualityReview,
)
def review(project_id: UUID, run_id: UUID, arm: Arm, action: QualityReviewInput, request: Request):
    require_same_origin(request)
    return reliability.review(settings(request), project_id, run_id, arm, action)


@router.post("/projects/{project_id}/reliability/{run_id}/reviews/{arm}")
async def review_form(project_id: UUID, run_id: UUID, arm: Arm, request: Request):
    data = await form_values(
        request,
        {
            "expected_revision",
            "factual_quality",
            "clarification_relevance",
            "unsupported_assertions",
            "citation_relevance",
            "decision_usefulness",
            "notes",
        },
    )
    reliability.review(
        settings(request), project_id, run_id, arm, validate_form(QualityReviewInput, data)
    )
    return RedirectResponse(f"/projects/{project_id}/reliability?run_id={run_id}", status_code=303)
