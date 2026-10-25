"""Thin, same-origin example review, queue and candidate selection routes."""

from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse, RedirectResponse

from quartermaster import evaluations, teaching, training
from quartermaster.api.foundation import form_error, page, settings, validate_form
from quartermaster.api.interview import form_values
from quartermaster.api.routes import require_same_origin
from quartermaster.contracts.evaluation import RatingInput
from quartermaster.contracts.interview import VersionedAction
from quartermaster.contracts.prediction import PredictionCandidate, PredictionJob
from quartermaster.contracts.training import (
    AdviserVersion,
    ExampleReview,
    ExampleSend,
    ExampleTarget,
    Promote,
    TrainingExample,
    TrainingJob,
    TrainingRun,
    TrainingSelection,
)
from quartermaster.projects import get_adviser

router = APIRouter()
API = "/api/projects/{project_id}"
WEB = "/projects/{project_id}"


def redirect(project_id):
    return RedirectResponse(f"/projects/{project_id}/train", status_code=303)


@router.get(WEB + "/train")
def training_page(project_id: UUID, request: Request):
    config = settings(request)
    candidates = [
        v
        for v in training.versions(config, project_id)
        if v.schema_version == "quartermaster.adviser-version/v1"
    ]
    reviews = {
        str(v.id): {str(r.case_id): r for r in training.ratings(config, project_id, v.id)}
        for v in candidates
    }
    return page(
        request,
        "train.html",
        project=get_adviser(config.database_path, project_id),
        examples=training.examples(config, project_id),
        runs=training.runs(config, project_id),
        candidates=candidates,
        reviews=reviews,
        suites=[
            s
            for s in evaluations.list_suites(config, project_id)
            if s.status == "frozen" or (s.cases and s.reviewed_at)
        ],
        lessons=[
            lesson
            for lesson in teaching.latest_lessons(config, project_id)
            if lesson.status == "applied"
        ],
        resources=training.resource_warning(config),
        categories=teaching.CATEGORIES,
        preferences=evaluations.PREFERENCES,
        candidate_suites={
            str(v.id): evaluations.get_suite(config, project_id, v.suite_id, v.suite_revision)
            for v in candidates
        },
    )


@router.get(API + "/training-examples", response_model=list[TrainingExample])
def examples(project_id: UUID, request: Request):
    return training.examples(settings(request), project_id)


@router.get(API + "/training-examples/{example_id}", response_model=TrainingExample)
def example(project_id: UUID, example_id: UUID, request: Request, revision: int | None = None):
    return training.get_example(settings(request), project_id, example_id, revision)


@router.post(API + "/lessons/{lesson_id}/training-example", response_model=TrainingExample)
def from_lesson(project_id: UUID, lesson_id: UUID, action: VersionedAction, request: Request):
    require_same_origin(request)
    return training.from_lesson(settings(request), project_id, lesson_id, action)


@router.post(WEB + "/lessons/{lesson_id}/training-example")
async def from_lesson_form(project_id: UUID, lesson_id: UUID, request: Request):
    data = await form_values(request, {"expected_revision"})
    training.from_lesson(
        settings(request), project_id, lesson_id, validate_form(VersionedAction, data)
    )
    return redirect(project_id)


@router.post(API + "/training-examples/{example_id}/target", response_model=TrainingExample)
def target(project_id: UUID, example_id: UUID, action: ExampleTarget, request: Request):
    require_same_origin(request)
    return training.set_target(settings(request), project_id, example_id, action)


@router.post(WEB + "/training-examples/{example_id}/target")
async def target_form(project_id: UUID, example_id: UUID, request: Request):
    data = await form_values(
        request,
        {
            "expected_revision",
            "behavior",
            "recommendation",
            "explanation",
            "question",
            "limitations",
            "quotes",
            "missing",
            "refs",
        },
    )

    def lines(key):
        return [line.strip() for line in data.get(key, "").splitlines() if line.strip()]

    action = validate_form(
        ExampleTarget,
        {
            "expected_revision": data["expected_revision"],
            "target": {
                "behavior": data.get("behavior"),
                "supporting_quotes": lines("quotes"),
                "missing_information": lines("missing"),
                "advice": {
                    "recommendation": data.get("recommendation"),
                    "explanation": data.get("explanation"),
                    "clarification_question": data.get("question", "").strip() or None,
                    "limitations": lines("limitations"),
                    "evidence_refs": lines("refs"),
                },
            },
        },
    )
    training.set_target(settings(request), project_id, example_id, action)
    return redirect(project_id)


@router.post(API + "/training-examples/{example_id}/review", response_model=TrainingExample)
def review(project_id: UUID, example_id: UUID, action: ExampleReview, request: Request):
    require_same_origin(request)
    return training.review_example(settings(request), project_id, example_id, action)


@router.post(WEB + "/training-examples/{example_id}/review")
async def review_form(project_id: UUID, example_id: UUID, request: Request):
    data = await form_values(request, {"expected_revision", "action"})
    training.review_example(
        settings(request), project_id, example_id, validate_form(ExampleReview, data)
    )
    return redirect(project_id)


@router.post(API + "/training-examples/{example_id}/prepare", response_model=TrainingExample)
def prepare(project_id: UUID, example_id: UUID, action: VersionedAction, request: Request):
    require_same_origin(request)
    return training.prepare_example(settings(request), project_id, example_id, action)


@router.post(WEB + "/training-examples/{example_id}/prepare")
async def prepare_form(project_id: UUID, example_id: UUID, request: Request):
    data = await form_values(request, {"expected_revision"})
    training.prepare_example(
        settings(request), project_id, example_id, validate_form(VersionedAction, data)
    )
    return redirect(project_id)


@router.post(API + "/training-examples/{example_id}/send", response_model=TrainingExample)
async def send(project_id: UUID, example_id: UUID, action: ExampleSend, request: Request):
    require_same_origin(request)
    return await training.send_example(
        settings(request), request.app.state.builder, project_id, example_id, action
    )


@router.post(WEB + "/training-examples/{example_id}/send")
async def send_form(project_id: UUID, example_id: UUID, request: Request):
    data = await form_values(
        request, {"expected_revision", "turn_id", "consent", "disclosure_sha256"}
    )
    data["consent"] = data.get("consent") == "yes"
    await training.send_example(
        settings(request),
        request.app.state.builder,
        project_id,
        example_id,
        validate_form(ExampleSend, data),
    )
    return redirect(project_id)


@router.post(API + "/training-runs", response_model=TrainingRun)
def freeze(project_id: UUID, action: TrainingSelection, request: Request):
    require_same_origin(request)
    return training.freeze_dataset(settings(request), project_id, action)


@router.post(WEB + "/training-runs")
async def freeze_form(project_id: UUID, request: Request):
    require_same_origin(request, form=True)
    async with request.form(max_files=0, max_fields=105, max_part_size=16384) as form:
        if set(form) - {"example_ids", "suite", "preset", "acknowledge_small_data"}:
            raise form_error()
        if any(len(form.getlist(k)) != 1 for k in set(form) - {"example_ids"}):
            raise form_error()
        try:
            suite_id, revision = form.get("suite", "").split(":")
            data = {
                "example_ids": form.getlist("example_ids"),
                "suite_id": suite_id,
                "suite_revision": int(revision),
                "preset": form.get("preset") or "quick",
                "acknowledge_small_data": form.get("acknowledge_small_data") == "yes",
            }
        except (ValueError, TypeError):
            raise form_error() from None
    action = validate_form(TrainingSelection, data)
    suite = evaluations.get_suite(settings(request), project_id, action.suite_id)
    if suite.revision != action.suite_revision:
        raise form_error()
    if suite.status == "draft":
        if not suite.reviewed_at:
            raise form_error()
        from quartermaster.contracts.evaluation import SuiteAction

        suite = evaluations.freeze_suite(
            settings(request),
            project_id,
            suite.id,
            SuiteAction(expected_revision=suite.revision),
        )
        action = action.model_copy(update={"suite_revision": suite.revision})
    training.freeze_dataset(settings(request), project_id, action)
    return redirect(project_id)


@router.get(API + "/training-runs", response_model=list[TrainingRun])
def runs(project_id: UUID, request: Request):
    return training.runs(settings(request), project_id)


@router.get(API + "/training-runs/{run_id}", response_model=TrainingRun)
def run(project_id: UUID, run_id: UUID, request: Request, revision: int | None = None):
    return training.get_run(settings(request), project_id, run_id, revision)


@router.get(API + "/training-runs/{run_id}/job", response_model=TrainingJob | PredictionJob)
def job(project_id: UUID, run_id: UUID, request: Request):
    config = settings(request)
    return training.read_job(config, training.get_run(config, project_id, run_id))


@router.get(API + "/training-runs/{run_id}/dataset", response_class=PlainTextResponse)
def dataset(project_id: UUID, run_id: UUID, request: Request):
    config = settings(request)
    record = training.read_job(config, training.get_run(config, project_id, run_id))
    if record.schema_version == "quartermaster.training-job/v2":
        from quartermaster.prediction_context import serialize

        return PlainTextResponse(serialize(record.examples), media_type="application/x-ndjson")
    return PlainTextResponse(training.serialize(record.examples), media_type="application/x-ndjson")


@router.get(API + "/training-resources")
def resources(project_id: UUID, request: Request):
    get_adviser(settings(request).database_path, project_id)
    return training.resource_warning(settings(request))


@router.post(API + "/training-runs/{run_id}/cancel", response_model=TrainingRun)
def cancel(project_id: UUID, run_id: UUID, action: VersionedAction, request: Request):
    require_same_origin(request)
    return training.cancel(settings(request), project_id, run_id, action)


@router.post(WEB + "/training-runs/{run_id}/cancel")
async def cancel_form(project_id: UUID, run_id: UUID, request: Request):
    data = await form_values(request, {"expected_revision"})
    training.cancel(settings(request), project_id, run_id, validate_form(VersionedAction, data))
    return redirect(project_id)


@router.get(API + "/adviser-versions", response_model=list[AdviserVersion | PredictionCandidate])
def versions(project_id: UUID, request: Request):
    return training.versions(settings(request), project_id)


@router.get(
    API + "/adviser-versions/{version_id}", response_model=AdviserVersion | PredictionCandidate
)
def version(project_id: UUID, version_id: UUID, request: Request):
    return training.get_version(settings(request), project_id, version_id)


@router.post(API + "/adviser-versions/{version_id}/ratings/{case_id}")
def rate(project_id: UUID, version_id: UUID, case_id: UUID, action: RatingInput, request: Request):
    require_same_origin(request)
    return training.rate(settings(request), project_id, version_id, case_id, action)


@router.post(WEB + "/adviser-versions/{version_id}/ratings/{case_id}")
async def rate_form(project_id: UUID, version_id: UUID, case_id: UUID, request: Request):
    data = await form_values(request, {"expected_revision", "preference", "category", "rationale"})
    training.rate(
        settings(request), project_id, version_id, case_id, validate_form(RatingInput, data)
    )
    return redirect(project_id)


@router.post(API + "/adviser-versions/{version_id}/promote")
def promote(project_id: UUID, version_id: UUID, action: Promote, request: Request):
    require_same_origin(request)
    return training.promote(settings(request), project_id, version_id, action)


@router.post(WEB + "/adviser-versions/{version_id}/promote")
async def promote_form(project_id: UUID, version_id: UUID, request: Request):
    data = await form_values(request, {"expected_revision", "acknowledge_regressions"})
    data["acknowledge_regressions"] = data.get("acknowledge_regressions") == "yes"
    training.promote(settings(request), project_id, version_id, validate_form(Promote, data))
    return redirect(project_id)


@router.post(API + "/retain-base")
def retain_base(project_id: UUID, action: VersionedAction, request: Request):
    require_same_origin(request)
    return training.retain_base(settings(request), project_id, action)


@router.post(WEB + "/retain-base")
async def retain_base_form(project_id: UUID, request: Request):
    data = await form_values(request, {"expected_revision"})
    training.retain_base(settings(request), project_id, validate_form(VersionedAction, data))
    return redirect(project_id)
