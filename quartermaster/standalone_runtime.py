"""Fixed standalone CPU adviser. Imports no builder database, training worker or provider."""

import argparse
import asyncio
import json
import subprocess
import time
import urllib.error
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

from quartermaster.advice_context import system_for, validate_advice
from quartermaster.contracts.advice import Advice, Case
from quartermaster.contracts.export import RuntimeAdvice, RuntimeInput
from quartermaster.errors import DomainError
from quartermaster.export_package import PackageContext, content_hash, verify_package
from quartermaster.generation import checked_parameters
from quartermaster.inference import LocalInference


def same_origin(request, form=False):
    origin = request.headers.get("origin")
    if (
        (form and origin is None)
        or (origin is not None and origin != str(request.base_url).rstrip("/"))
        or request.headers.get("sec-fetch-site") == "cross-site"
    ):
        raise HTTPException(403, "Open the local adviser and submit again.")


class RequestLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            return await self.app(scope, receive, send)
        parts, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > 32_000:
                return await JSONResponse({"detail": "REQUEST_SIZE: Shorten the situation."}, 413)(
                    scope, receive, send
                )
            parts.append(message.get("body", b""))
            if not message.get("more_body", False):
                break
        delivered = False

        async def buffered():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": b"".join(parts), "more_body": False}
            return await receive()

        return await self.app(scope, buffered, send)


def start_engine(root, manifest):
    command = [
        "llama-server",
        "-m",
        str(root / "model/model.gguf"),
        "--alias",
        f"qm-candidate-{manifest.files['model/model.gguf'].sha256}",
        "--host",
        "127.0.0.1",
        "--port",
        "8082",
        "-c",
        "8192",
        "-t",
        "4",
        "-ngl",
        "0",
        "--parallel",
        "1",
        "--jinja",
        "--chat-template-kwargs",
        json.dumps(checked_parameters(manifest.inference_parameters)["chat_template_kwargs"]),
        "--reasoning-budget",
        str(manifest.inference_parameters.get("reasoning_budget_tokens", 0)),
        "--reasoning-format",
        "deepseek",
        "--no-webui",
        "--log-disable",
        "-n",
        str(checked_parameters(manifest.inference_parameters)["max_tokens"]),
        "--no-context-shift",
    ]
    try:
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        raise DomainError("EXPORT_ENGINE: Use the pinned standard runtime image.", 503) from None
    try:
        deadline = time.monotonic() + 180
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        while time.monotonic() < deadline and process.poll() is None:
            try:
                with opener.open("http://127.0.0.1:8082/health", timeout=2) as response:
                    if response.status == 200:
                        return process
            except (OSError, urllib.error.URLError):
                pass
            time.sleep(0.5)
        raise DomainError(
            "EXPORT_ENGINE: CPU model startup failed; "
            "check RAM, CPU support and the original archive.",
            503,
        )
    except BaseException:
        stop_engine(process)
        raise


def stop_engine(process):
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def create_runtime(root: Path, *, inference=None, launch_engine=True):
    templates = Jinja2Templates(directory=Path(__file__).parent / "runtime_templates")

    @asynccontextmanager
    async def lifespan(app):
        engine, context = None, None
        try:
            manifest, config, material, reference = verify_package(root)
            context = PackageContext(config, material, prompt_version=manifest.prompt_version)
            reference_case = Case.model_validate_json(
                json.dumps(
                    {
                        "case_id": str(reference.case.case_id),
                        "situation": reference.case.situation,
                        "choices": reference.case.choices,
                    }
                )
            )
            if content_hash(context.assemble(reference_case)[1]) != reference.context_sha256:
                raise DomainError(
                    "EXPORT_CONTEXT: Restore the original evaluated configuration.", 503
                )
            if launch_engine:
                engine = await asyncio.to_thread(start_engine, root, manifest)
            app.state.manifest, app.state.config, app.state.context = manifest, config, context
            app.state.engine = engine
            # Ignore all ambient builder configuration and credentials, including .env.
            config_settings = SimpleNamespace(local_timeout_seconds=180, local_base_url=None)
            app.state.inference = inference or LocalInference(
                config_settings,
                alias=f"qm-candidate-{manifest.files['model/model.gguf'].sha256}",
                base_url="http://127.0.0.1:8082/v1",
            )
            yield
        finally:
            if context:
                context.close()
            stop_engine(engine)

    app = FastAPI(title="Standalone adviser", lifespan=lifespan)
    app.add_middleware(RequestLimit)

    @app.exception_handler(DomainError)
    async def domain_error(request, exc):
        if request.url.path.startswith("/v1/"):
            return JSONResponse({"detail": exc.message}, status_code=exc.status)
        return templates.TemplateResponse(
            request=request,
            name="adviser.html",
            context={
                "config": app.state.config,
                "message": exc.message,
            },
            status_code=exc.status,
        )

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        return JSONResponse(
            {"detail": "REQUEST_INVALID: Supply situation, optional choices and case_id only."}, 422
        )

    @app.get("/healthz")
    def health():
        if app.state.engine and app.state.engine.poll() is not None:
            raise DomainError(
                "EXPORT_ENGINE: Restart the adviser after checking available RAM.", 503
            )
        return {
            "status": "ok",
            "export_id": str(app.state.manifest.id),
            "candidate_id": str(app.state.manifest.candidate_id)
            if app.state.manifest.candidate_id
            else None,
        }

    @app.get("/")
    def home(request: Request):
        return templates.TemplateResponse(
            request=request, name="adviser.html", context={"config": app.state.config}
        )

    async def advise(action):
        case = Case(
            case_id=action.case_id or uuid4(), situation=action.situation, choices=action.choices
        )
        _, context, evidence, _, omitted = app.state.context.assemble(case)
        try:
            async with asyncio.timeout(180):
                result = await app.state.inference.advise(
                    system=system_for(app.state.manifest.prompt_version),
                    context=context,
                    parameters=app.state.manifest.inference_parameters,
                )
        except TimeoutError:
            raise DomainError("LOCAL_TIMEOUT: Advice timed out; retry explicitly.", 503) from None
        _, advice = validate_advice(
            result, case, evidence, bounded=app.state.manifest.prompt_version == "context/v3"
        )
        if any(omitted):
            advice = Advice.model_validate(
                {
                    **advice.model_dump(),
                    "limitations": [
                        *advice.limitations[:19],
                        f"Context limits omitted {omitted[0]} lessons and {omitted[1]} excerpts.",
                    ],
                }
            )
        return RuntimeAdvice(
            advice=advice,
            evidence=evidence,
            export_id=app.state.manifest.id,
            candidate_id=app.state.manifest.candidate_id,
            context_sha256=content_hash(context),
        )

    @app.post("/v1/advise", response_model=RuntimeAdvice)
    async def advise_api(action: RuntimeInput, request: Request):
        same_origin(request)
        return await advise(action)

    @app.post("/advise")
    async def advise_form(request: Request):
        same_origin(request, form=True)
        try:
            async with request.form(max_fields=2, max_files=0, max_part_size=16_384) as form:
                if set(form) - {"situation", "choices"} or len(form.multi_items()) != len(form):
                    raise ValueError
                action = RuntimeInput(
                    situation=form.get("situation"),
                    choices=[
                        x.strip() for x in str(form.get("choices", "")).splitlines() if x.strip()
                    ],
                )
        except (ValueError, TypeError):
            raise DomainError(
                "REQUEST_INVALID: Check the situation and up to ten choices."
            ) from None
        result = await advise(action)
        return templates.TemplateResponse(
            request=request,
            name="adviser.html",
            context={
                "config": app.state.config,
                "result": result,
                "situation": action.situation,
            },
        )

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, default=Path("/package"))
    args = parser.parse_args()
    import uvicorn

    uvicorn.run(
        create_runtime(args.package),
        host="0.0.0.0",
        port=8080,
        proxy_headers=False,
        access_log=False,
        log_level="error",
    )


if __name__ == "__main__":
    main()
