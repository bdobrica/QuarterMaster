"""Server-rendered field review; external requests require their own consent."""

import json

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from muster.schema import (
    FIELD_TYPES,
    SchemaConflict,
    accept_schema,
    apply_suggestion,
    form_fields,
    get_draft,
    get_request,
    prepare_request,
    save_draft,
    send_request,
)
from muster.storage import connect


def register_schema_routes(app, root, render):
    def collection(collection_id):
        with connect(root) as db:
            row = db.execute("SELECT * FROM collections WHERE id=?", (collection_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Collection not found")
        return row

    def fields_page(request, collection_id, draft=None, message=None, status_code=200):
        item = collection(collection_id)
        draft = draft or get_draft(root, collection_id)
        with connect(root) as db:
            latest = db.execute(
                "SELECT id FROM schema_requests WHERE collection_id=? ORDER BY created_at DESC,id DESC LIMIT 1",
                (collection_id,),
            ).fetchone()
        settings = app.state.schema_provider.settings
        return render(
            request,
            "fields.html",
            collection=item,
            draft=draft,
            field_types=FIELD_TYPES,
            provider=settings.identity,
            has_key=bool(settings.api_key),
            latest_request=latest,
            message=message,
            status_code=status_code,
        )

    def request_page(request, collection_id, request_id, message=None, status_code=200):
        item = collection(collection_id)
        try:
            suggestion = get_request(root, collection_id, request_id)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        draft = get_draft(root, collection_id)
        return render(
            request,
            "schema_request.html",
            collection=item,
            suggestion=suggestion,
            field_types=FIELD_TYPES,
            current=not draft["accepted_at"] and draft["revision"] == suggestion["revision"],
            message=message,
            status_code=status_code,
        )

    @app.get("/collections/{collection_id}/fields")
    def fields(request: Request, collection_id: int):
        collection(collection_id)
        message = {
            "saved": "Your field list and guidance were saved.",
            "applied": "The suggestion is now your draft. Edit and check it before accepting.",
        }.get(request.query_params.get("notice"))
        draft = get_draft(root, collection_id)
        if not request.query_params and not draft["accepted_at"] and not draft["fields"]:
            with connect(root) as db:
                latest = db.execute(
                    "SELECT id FROM schema_requests WHERE collection_id=? ORDER BY created_at DESC,id DESC LIMIT 1",
                    (collection_id,),
                ).fetchone()
            if latest:
                return RedirectResponse(
                    f"/collections/{collection_id}/fields/requests/{latest['id']}", 303
                )
            try:
                request_id = prepare_request(
                    root, collection_id, draft["revision"], app.state.schema_provider
                )
            except ValueError:
                pass  # Manual fields remain available without a provider or collected pages.
            else:
                return RedirectResponse(
                    f"/collections/{collection_id}/fields/requests/{request_id}", 303
                )
        return fields_page(request, collection_id, message=message)

    @app.post("/collections/{collection_id}/fields/{action}")
    async def edit_fields(request: Request, collection_id: int, action: str):
        if action not in ("save", "prepare", "accept"):
            raise HTTPException(404, "Action not found")
        collection(collection_id)
        draft = get_draft(root, collection_id)
        if draft["accepted_at"]:
            return fields_page(
                request,
                collection_id,
                message="These fields are already accepted and cannot be changed.",
                status_code=409,
            )
        form = await request.form()
        edited = None
        try:
            revision = int(form.get("revision", ""))
            fields = form_fields(form, validate=False)
            guidance = form.get("guidance", "")
            edited = {**draft, "fields": fields, "guidance": guidance, "revision": revision}
            if action == "accept" and not fields:
                raise ValueError("Add at least one field before accepting.")
            draft = save_draft(root, collection_id, revision, fields, guidance)
            if action == "prepare":
                request_id = prepare_request(
                    root, collection_id, draft["revision"], app.state.schema_provider
                )
                return RedirectResponse(
                    f"/collections/{collection_id}/fields/requests/{request_id}", status_code=303
                )
            if action == "accept":
                accept_schema(root, collection_id, draft["revision"])
            return RedirectResponse(
                f"/collections/{collection_id}/fields?notice=saved", status_code=303
            )
        except SchemaConflict as exc:
            return fields_page(request, collection_id, message=str(exc), status_code=409)
        except ValueError as exc:
            # Once a save succeeded, use its new revision even if preparing a sample failed.
            current = get_draft(root, collection_id)
            if edited and current["revision"] == edited["revision"]:
                current = edited
            return fields_page(
                request,
                collection_id,
                draft=current,
                message=str(exc) or "Check your field list and try again.",
                status_code=400,
            )

    @app.get("/collections/{collection_id}/fields/requests/{request_id}")
    def preview(request: Request, collection_id: int, request_id: str):
        return request_page(request, collection_id, request_id)

    @app.post("/collections/{collection_id}/fields/requests/{request_id}/send")
    async def suggest(request: Request, collection_id: int, request_id: str):
        collection(collection_id)
        # Check existence before parsing consent, but never send without it.
        try:
            get_request(root, collection_id, request_id)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        form = await request.form()
        if form.get("consent") != "yes":
            return request_page(
                request,
                collection_id,
                request_id,
                message="Agree to send the displayed sample before requesting a suggestion.",
                status_code=403,
            )
        try:
            await send_request(root, collection_id, request_id, app.state.schema_provider)
        except SchemaConflict as exc:
            return request_page(
                request, collection_id, request_id, message=str(exc), status_code=409
            )
        return RedirectResponse(
            f"/collections/{collection_id}/fields/requests/{request_id}", status_code=303
        )

    @app.post("/collections/{collection_id}/fields/requests/{request_id}/apply")
    def apply(request: Request, collection_id: int, request_id: str):
        collection(collection_id)
        try:
            apply_suggestion(root, collection_id, request_id)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except SchemaConflict as exc:
            return request_page(
                request, collection_id, request_id, message=str(exc), status_code=409
            )
        return RedirectResponse(
            f"/collections/{collection_id}/fields?notice=applied", status_code=303
        )

    @app.get("/collections/{collection_id}/fields/accepted.json")
    def accepted_file(collection_id: int):
        collection(collection_id)
        draft = get_draft(root, collection_id)
        if not draft["accepted_at"]:
            raise HTTPException(404, "No field list has been accepted yet.")
        return JSONResponse(
            json.loads(draft["accepted_json"]),
            headers={"Content-Disposition": 'attachment; filename="schema.json"'},
        )
