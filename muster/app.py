import json
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.trustedhost import TrustedHostMiddleware

from muster.collector import Collector
from muster.extraction import Extractor
from muster.extraction_routes import register_extraction_routes
from muster.imports import MAX_BYTES, parse_import
from muster.knowledge_routes import register_knowledge_routes
from muster.provider import SchemaProvider
from muster.publication_routes import register_publication_routes
from muster.review_routes import register_review_routes
from muster.schema_routes import register_schema_routes
from muster.storage import connect, initialize


def create_app(data_dir=None, schema_provider=None):
    root = Path(data_dir or os.environ.get("MUSTER_DATA_DIR", ".muster")).resolve()

    @asynccontextmanager
    async def lifespan(app):
        initialize(root)
        app.state.collector = Collector(root)
        app.state.extractor = Extractor(root, app.state.schema_provider)
        try:
            yield
        finally:
            await app.state.extractor.close()
            await app.state.collector.close()

    app = FastAPI(title="Muster", lifespan=lifespan)
    app.state.data_dir = root
    app.state.schema_provider = schema_provider or SchemaProvider()
    app.mount(
        "/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static"
    )
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"]
    )
    templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
    csrf_token = secrets.token_urlsafe(32)

    @app.middleware("http")
    async def local_writes(request: Request, call_next):
        if request.method == "POST":
            # Forms carry a per-process secret; malicious websites cannot submit local writes.
            from starlette.responses import PlainTextResponse

            if request.headers.get("sec-fetch-site") == "cross-site":
                return PlainTextResponse("Open Muster locally to make changes.", status_code=403)
            await request.body()
            form = await request.form(max_part_size=MAX_BYTES)
            token = form.get("csrf", "")
            if not isinstance(token, str) or not secrets.compare_digest(token, csrf_token):
                return PlainTextResponse(
                    "This form has expired. Reload the page and try again.", status_code=403
                )
        response = await call_next(request)
        # Redirects are application-generated local paths. Keep them under the
        # same mount as the forms and assets when embedded in QuarterMaster.
        location = response.headers.get("location", "")
        prefix = request.scope.get("root_path", "")
        if prefix and location.startswith("/") and not location.startswith("//"):
            response.headers["location"] = prefix + location
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def render(request, page, status_code=200, **context):
        return templates.TemplateResponse(
            request=request,
            name=page,
            status_code=status_code,
            context={
                "csrf": csrf_token,
                "mount_path": request.scope.get("root_path", ""),
                **context,
            },
        )

    @app.get("/")
    def home(request: Request):
        with connect(root) as db:
            collections = db.execute("""SELECT c.*, count(j.id) AS total FROM collections c
                LEFT JOIN jobs j ON j.collection_id=c.id AND j.removed=0 GROUP BY c.id ORDER BY c.id DESC""").fetchall()
        return render(request, "home.html", collections=collections)

    @app.post("/imports/preview")
    async def preview(
        request: Request,
        name: str = Form("My collection"),
        links: str = Form(""),
        spreadsheet: Annotated[UploadFile | None, File()] = None,
        collection_id: int | None = Form(None),
    ):
        try:
            if not name.strip() or len(name.strip()) > 120:
                raise ValueError("Give your collection a name of 1–120 characters.")
            content = await spreadsheet.read(MAX_BYTES + 1) if spreadsheet else b""
            result = parse_import(spreadsheet.filename if spreadsheet else "", content, links)
        except ValueError as exc:
            return render(request, "error.html", message=str(exc))
        if collection_id is not None:
            with connect(root) as db:
                target = db.execute(
                    "SELECT name FROM collections WHERE id=?", (collection_id,)
                ).fetchone()
                if not target:
                    raise HTTPException(404, "Collection not found")
                existing = {
                    row["url"]
                    for row in db.execute(
                        "SELECT url FROM jobs WHERE collection_id=?", (collection_id,)
                    )
                }
            name = target["name"]
            result["duplicates"] += sum(url in existing for url in result["urls"])
            result["urls"] = [url for url in result["urls"] if url not in existing]
            result["records"] = [
                record for record in result["records"] if record["url"] not in existing
            ]
        token = secrets.token_urlsafe(24)
        with connect(root) as db:
            db.execute(
                "INSERT INTO import_previews(token,name,payload,collection_id) VALUES(?,?,?,?)",
                (token, name.strip(), json.dumps(result), collection_id),
            )
        return render(
            request,
            "preview.html",
            preview=result,
            token=token,
            name=name.strip(),
            collection_id=collection_id,
        )

    @app.post("/imports/{token}/confirm")
    def confirm(token: str):
        with connect(root) as db:
            # Serialize confirmations so a double-click cannot import the same preview twice.
            db.execute("BEGIN IMMEDIATE")
            preview = db.execute("SELECT * FROM import_previews WHERE token=?", (token,)).fetchone()
            if not preview:
                raise HTTPException(404, "This preview was already imported or does not exist.")
            payload = json.loads(preview["payload"])
            urls = payload["urls"]
            if not urls:
                raise HTTPException(400, "There are no valid links to import.")
            collection_id = (
                preview["collection_id"]
                or db.execute(
                    "INSERT INTO collections(name) VALUES(?)", (preview["name"],)
                ).lastrowid
            )
            records = payload.get("records", [{"url": url, "input_rows": []} for url in urls])
            db.executemany(
                "INSERT INTO jobs(collection_id,url,input_rows) VALUES(?,?,?) ON CONFLICT(collection_id,url) DO UPDATE SET removed=0",
                [
                    (
                        collection_id,
                        record["url"],
                        json.dumps(record["input_rows"], ensure_ascii=False),
                    )
                    for record in records
                ],
            )
            db.execute("DELETE FROM import_previews WHERE token=?", (token,))
        return RedirectResponse(f"/collections/{collection_id}", status_code=303)

    @app.get("/collections/{collection_id}")
    def collection(request: Request, collection_id: int):
        with connect(root) as db:
            item = db.execute("SELECT * FROM collections WHERE id=?", (collection_id,)).fetchone()
            if not item:
                raise HTTPException(404, "Collection not found")
            jobs = db.execute(
                "SELECT * FROM jobs WHERE collection_id=? AND removed=0 ORDER BY id",
                (collection_id,),
            ).fetchall()
            removed_jobs = db.execute(
                "SELECT * FROM jobs WHERE collection_id=? AND removed=1 ORDER BY id",
                (collection_id,),
            ).fetchall()
            captures = db.execute(
                "SELECT captures.* FROM captures JOIN jobs ON jobs.id=captures.job_id WHERE jobs.collection_id=? ORDER BY captured_at DESC",
                (collection_id,),
            ).fetchall()
            batches = db.execute(
                "SELECT * FROM extraction_batches WHERE collection_id=? ORDER BY created_at DESC,id DESC LIMIT 5",
                (collection_id,),
            ).fetchall()
            examples = db.execute(
                """SELECT e.* FROM extractions e JOIN jobs j ON j.id=e.job_id WHERE j.collection_id=? AND j.removed=0 AND e.status='complete'
                AND e.id=(SELECT latest.id FROM extractions latest WHERE latest.job_id=e.job_id AND latest.status='complete' ORDER BY latest.finished_at DESC,latest.id DESC LIMIT 1)
                ORDER BY e.job_id""",
                (collection_id,),
            ).fetchall()
            schema = db.execute(
                "SELECT accepted_at,fields FROM collection_schemas WHERE collection_id=?",
                (collection_id,),
            ).fetchone()
        collector = app.state.collector
        return render(
            request,
            "collection.html",
            collection=item,
            jobs=jobs,
            captures=captures,
            examples=examples,
            batches=batches,
            schema=schema,
            removed_jobs=removed_jobs,
            active=collector.active and collector.collection_id == collection_id,
            waiting=collector.waiting,
            current_job=collector.job_id,
        )

    @app.post("/collections/{collection_id}/jobs/{job_id}/{action}")
    def change_link(collection_id: int, job_id: int, action: str):
        if action == "retry":
            return retry(collection_id, job_id)
        if action not in ("remove", "restore"):
            raise HTTPException(404, "Action not found")
        with connect(root) as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute(
                "SELECT 1 FROM jobs WHERE id=? AND collection_id=?", (job_id, collection_id)
            ).fetchone():
                raise HTTPException(404, "Link not found")
            if (
                app.state.collector.active and app.state.collector.collection_id == collection_id
            ) or db.execute(
                "SELECT 1 FROM extraction_batches WHERE collection_id=? AND status='running'",
                (collection_id,),
            ).fetchone():
                raise HTTPException(409, "Stop collection and extraction before changing links.")
            db.execute("UPDATE jobs SET removed=? WHERE id=?", (int(action == "remove"), job_id))
        return RedirectResponse(f"/collections/{collection_id}", 303)

    @app.post("/collections/{collection_id}/jobs/{job_id}/retry")
    def retry(collection_id: int, job_id: int):
        if app.state.collector.active and app.state.collector.job_id == job_id:
            raise HTTPException(
                409, "Use Continue or Skip for the page currently open in the browser."
            )
        with connect(root) as db:
            result = db.execute(
                "UPDATE jobs SET status='queued', error=NULL WHERE id=? AND collection_id=? AND removed=0 AND status IN ('failed','blocked')",
                (job_id, collection_id),
            )
            if not result.rowcount:
                raise HTTPException(409, "Only failed or blocked pages can be retried.")
        return RedirectResponse(f"/collections/{collection_id}", status_code=303)

    @app.post("/collections/{collection_id}/collect")
    async def collect(collection_id: int):
        try:
            app.state.collector.start(collection_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return RedirectResponse(f"/collections/{collection_id}", status_code=303)

    @app.post("/collections/{collection_id}/control/{action}")
    async def control(collection_id: int, action: str):
        try:
            app.state.collector.control(collection_id, action)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return RedirectResponse(f"/collections/{collection_id}", status_code=303)

    def get_capture(capture_id):
        with connect(root) as db:
            capture = db.execute("SELECT * FROM captures WHERE id=?", (capture_id,)).fetchone()
        if not capture:
            raise HTTPException(404, "Capture not found")
        return capture, json.loads(capture["metadata"])

    @app.get("/captures/{capture_id}")
    def capture_view(request: Request, capture_id: str):
        capture, metadata = get_capture(capture_id)
        with connect(root) as db:
            job = db.execute("SELECT * FROM jobs WHERE id=?", (capture["job_id"],)).fetchone()
        return render(
            request,
            "capture.html",
            capture=capture,
            metadata=metadata,
            job=job,
            input_rows=json.loads(job["input_rows"]),
        )

    @app.get("/captures/{capture_id}/files/{filename}")
    def capture_file(capture_id: str, filename: str):
        capture, metadata = get_capture(capture_id)
        allowed = {
            "page.html": "text/html",
            "metadata.json": "application/json",
            "screenshot.png": "image/png",
        }
        allowed.update({image["file"]: image["mime"] for image in metadata["images"]})
        if filename not in allowed:
            raise HTTPException(404, "File not found")
        path = root / "sources" / str(capture["job_id"]) / capture_id / filename
        if not path.is_file():
            raise HTTPException(404, "The retained file is missing from local storage.")
        # Download source HTML; never execute untrusted collected scripts in the app's origin.
        return FileResponse(
            path,
            media_type=allowed[filename],
            filename=filename,
            content_disposition_type="attachment"
            if filename.endswith((".html", ".json"))
            else "inline",
            headers={"Content-Security-Policy": "sandbox; default-src 'none'"},
        )

    from muster.rebuild import register_rebuild_routes

    register_rebuild_routes(app, root, render)
    from muster.connectors import register_connector_routes

    register_connector_routes(app, root, render)
    register_schema_routes(app, root, render)
    register_extraction_routes(app, root, render)
    register_review_routes(app, root, render)
    register_knowledge_routes(app, root, render)
    register_publication_routes(app, root, render)
    return app


app = create_app()
