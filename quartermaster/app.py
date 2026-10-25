import logging
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from quartermaster.api.evaluation import router as evaluation_router
from quartermaster.api.export import router as export_router
from quartermaster.api.foundation import router as foundation_router
from quartermaster.api.interview import router as interview_router
from quartermaster.api.knowledge import router as knowledge_router
from quartermaster.api.limits import BodyLimitMiddleware
from quartermaster.api.muster import router as muster_router
from quartermaster.api.predictions import router as predictions_router
from quartermaster.api.reliability import router as reliability_router
from quartermaster.api.routes import router, validation_error
from quartermaster.api.teaching import router as teaching_router
from quartermaster.api.training import router as training_router
from quartermaster.builder import BuilderLLM, OpenAICompatible
from quartermaster.config import Settings, initialize_storage
from quartermaster.db import SchemaError, migrate
from quartermaster.errors import DomainError
from quartermaster.evaluations import recover_evaluations
from quartermaster.inference import Inference, LocalInference
from quartermaster.interviews import recover_interviews
from quartermaster.reliability import recover as recover_reliability
from quartermaster.teaching import recover_lessons
from quartermaster.training import recover_examples

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    builder: BuilderLLM | None = None,
    inference: Inference | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            app.state.settings = settings if settings is not None else Settings()
            initialize_storage(app.state.settings)
            migrate(app.state.settings.database_path)
            from quartermaster.knowledge_editing import recover as recover_knowledge

            recover_knowledge(app.state.settings)
            recover_interviews(app.state.settings)
            recover_lessons(app.state.settings)
            recover_evaluations(app.state.settings)
            recover_examples(app.state.settings)
            recover_reliability(app.state.settings)
            app.state.inference = (
                inference if inference is not None else LocalInference(app.state.settings)
            )
            app.state.builder = (
                builder if builder is not None else OpenAICompatible(app.state.settings)
            )
        except SchemaError as exc:
            raise RuntimeError(str(exc)) from None
        except (OSError, sqlite3.Error, ValidationError):
            raise RuntimeError(
                "STORAGE_INIT: Check QM_DATA_DIR, configuration and disk permissions."
            ) from None
        from muster.app import create_app as create_muster
        from muster.provider import ProviderSettings, SchemaProvider

        # Read Muster's provider keys from this repo's .env without changing global
        # process state or inheriting the separate adviser/builder credentials.
        config = app.state.settings
        app.state.muster_app = create_muster(
            data_dir=app.state.settings.muster_storage,
            schema_provider=SchemaProvider(
                ProviderSettings(
                    base_url=config.muster_ai_base_url.rstrip("/"),
                    model=config.muster_ai_model,
                    api_key=config.muster_ai_api_key.get_secret_value(),
                    reasoning_effort=config.muster_ai_reasoning_effort,
                )
            ),
        )
        async with app.state.muster_app.router.lifespan_context(app.state.muster_app):
            yield

    app = FastAPI(title="QuarterMaster", version="0.1.0.dev0", lifespan=lifespan)
    app.include_router(router)
    app.include_router(foundation_router)
    app.include_router(knowledge_router)
    app.include_router(muster_router)
    app.include_router(predictions_router)
    app.include_router(interview_router)
    app.include_router(teaching_router)
    app.include_router(evaluation_router)
    app.include_router(training_router)
    app.include_router(export_router)
    app.include_router(reliability_router)

    async def collect_app(scope, receive, send):
        await app.state.muster_app(scope, receive, send)

    app.mount("/collect", collect_app, name="collect")
    app.add_middleware(BodyLimitMiddleware)
    app.mount("/static", StaticFiles(directory=Path(__file__).parent / "ui" / "static"), "static")
    app.add_exception_handler(RequestValidationError, validation_error)

    async def domain_error(request: Request, exc: DomainError):
        if request.url.path.startswith("/api/"):
            return JSONResponse(status_code=exc.status, content={"detail": exc.message})
        from quartermaster.api.routes import templates

        return templates.TemplateResponse(
            request=request,
            name="error.html",
            context={"message": exc.message},
            status_code=exc.status,
        )

    app.add_exception_handler(DomainError, domain_error)

    async def storage_error(request: Request, exc: Exception):
        logger.error("STORAGE_UNAVAILABLE")
        return JSONResponse(
            status_code=503,
            content={
                "detail": "STORAGE_UNAVAILABLE: Check disk permissions and restore a valid backup."
            },
        )

    app.add_exception_handler(sqlite3.Error, storage_error)
    app.add_exception_handler(SchemaError, storage_error)
    return app


app = create_app()
