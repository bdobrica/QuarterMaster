import json

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse

from muster.extraction import batch_details, prepare_batch, recover_manually, select_images
from muster.storage import connect


def register_extraction_routes(app, root, render):
    def get_batch(batch_id):
        try:
            return batch_details(root, batch_id)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc

    def batch_page(request, batch_id, message=None, status_code=200):
        batch = get_batch(batch_id)
        return render(
            request, "extraction_batch.html", batch=batch, message=message, status_code=status_code
        )

    @app.post("/collections/{collection_id}/extract/prepare")
    async def prepare(request: Request, collection_id: int):
        form = await request.form()
        try:
            job_id = int(form["job_id"]) if form.get("job_id") else None
            batch_id = prepare_batch(root, collection_id, app.state.schema_provider, job_id)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            return render(
                request,
                "extraction_error.html",
                collection_id=collection_id,
                message=str(exc),
                status_code=400,
            )
        return RedirectResponse(f"/extraction-batches/{batch_id}", status_code=303)

    @app.get("/extraction-batches/{batch_id}")
    def preview(request: Request, batch_id: str):
        return batch_page(request, batch_id)

    @app.post("/extractions/{attempt_id}/images")
    async def images(request: Request, attempt_id: str):
        form = await request.form()
        try:
            batch_id = select_images(root, attempt_id, form.getlist("image"))
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return RedirectResponse(f"/extraction-batches/{batch_id}", 303)

    @app.post("/extraction-batches/{batch_id}/send")
    async def send(request: Request, batch_id: str):
        get_batch(batch_id)
        form = await request.form()
        if form.get("consent") != "yes":
            return batch_page(
                request,
                batch_id,
                "Agree to send the displayed sources and spreadsheet details before extracting.",
                403,
            )
        try:
            app.state.extractor.start(batch_id)
        except ValueError as exc:
            return batch_page(request, batch_id, str(exc), 409)
        return RedirectResponse(f"/extraction-batches/{batch_id}", status_code=303)

    @app.post("/extraction-batches/{batch_id}/stop")
    async def stop(request: Request, batch_id: str):
        worker = app.state.extractor
        if not worker.active or worker.batch_id != batch_id:
            return batch_page(request, batch_id, "This extraction is not running.", 409)
        await worker.close()
        return RedirectResponse(f"/extraction-batches/{batch_id}", status_code=303)

    @app.post("/extractions/{attempt_id}/edit-manually")
    def manual(attempt_id: str):
        try:
            cid, jid = recover_manually(root, attempt_id)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return RedirectResponse(f"/collections/{cid}/review/{jid}", 303)

    @app.get("/extractions/{attempt_id}")
    def example(request: Request, attempt_id: str):
        with connect(root) as db:
            attempt = db.execute(
                "SELECT e.*,b.collection_id,b.provider,b.consent_at FROM extractions e JOIN extraction_batches b ON b.id=e.batch_id WHERE e.id=?",
                (attempt_id,),
            ).fetchone()
        if not attempt:
            raise HTTPException(404, "Example not found")
        attempt = dict(attempt)
        payload = json.loads(attempt["payload"])
        result = json.loads(attempt["result"]) if attempt["result"] else None
        return render(
            request,
            "example.html",
            attempt=attempt,
            payload=payload,
            result=result,
            input_rows=payload["input_rows"],
            provider=json.loads(attempt["provider"]),
        )
