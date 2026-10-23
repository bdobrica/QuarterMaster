import logging
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from quartermaster.api.routes import router, validation_error
from quartermaster.config import Settings, initialize_storage
from quartermaster.db import SchemaError, migrate

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            app.state.settings = settings if settings is not None else Settings()
            initialize_storage(app.state.settings)
            migrate(app.state.settings.database_path)
        except SchemaError as exc:
            raise RuntimeError(str(exc)) from None
        except (OSError, sqlite3.Error, ValidationError):
            raise RuntimeError(
                "STORAGE_INIT: Check QM_DATA_DIR, configuration and disk permissions."
            ) from None
        yield

    app = FastAPI(title="QuarterMaster", version="0.1.0.dev0", lifespan=lifespan)
    app.include_router(router)
    app.mount("/static", StaticFiles(directory=Path(__file__).parent / "ui" / "static"), "static")
    app.add_exception_handler(RequestValidationError, validation_error)

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
