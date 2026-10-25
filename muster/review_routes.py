from urllib.parse import urlencode

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from muster.knowledge import suggestions
from muster.review import (
    ReviewConflict,
    ReviewInputError,
    bulk_status,
    detail_url,
    display,
    form_values,
    get_review,
    review_list,
    save_review,
)


def register_review_routes(app, root, render):
    def listing(collection_id, params):
        try:
            return review_list(root, collection_id, params)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    def neighbors(data, job_id):
        sequence = [row["id"] for row in data["rows"] if row["open_url"]]
        order = data["navigation"]
        if job_id not in order:
            return sequence, None, None, None
        index = order.index(job_id)
        previous = next((item for item in reversed(order[:index]) if item in sequence), None)
        following = next((item for item in order[index + 1 :] if item in sequence), None)
        return sequence, sequence.index(job_id) if job_id in sequence else None, previous, following

    def detail(request, collection_id, job_id, data=None, raw=None, message=None, status_code=200):
        data = data or listing(collection_id, request.query_params)
        try:
            review = get_review(root, collection_id, job_id)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        sequence, position, previous, following = neighbors(data, job_id)
        fields = review["payload"]["fields"]
        controls = {}
        for field in fields:
            key = field["key"]
            value = review["values"][key]
            text = (
                "\n".join(value)
                if isinstance(value, list)
                else "yes"
                if value is True
                else "no"
                if value is False
                else ""
                if value is None
                else str(value)
            )
            controls[key] = {
                "value": raw.get("value:" + key, "") if raw is not None else text,
                "unknown": raw.get("unknown:" + key) == "yes" if raw is not None else value is None,
            }
        images = review["metadata"].get("images", [])
        if not images and review["metadata"].get("screenshot", "screenshot.png"):
            images = [{"file": "screenshot.png", "alt": "Full-page screenshot"}]
        return render(
            request,
            "review_detail.html",
            **data,
            review=review,
            controls=controls,
            images=images,
            input_rows=review["payload"]["input_rows"],
            display=display,
            knowledge_suggestions=suggestions(root, collection_id, job_id),
            previous=previous,
            following=following,
            position=position,
            sequence_count=len(sequence),
            previous_url=detail_url(collection_id, previous, data["context"])
            if previous is not None
            else None,
            next_url=detail_url(collection_id, following, data["context"])
            if following is not None
            else None,
            save_url=detail_url(collection_id, job_id, data["context"]),
            notes=raw.get("notes", "") if raw is not None else review["notes"],
            exclusion_reason=raw.get("exclusion_reason", "")
            if raw is not None
            else review["exclusion_reason"],
            message=message,
            status_code=status_code,
        )

    @app.get("/collections/{collection_id}/review")
    def list_view(request: Request, collection_id: int):
        data = listing(collection_id, request.query_params)
        headers = []
        for key, label in [
            ("id", "#"),
            ("source", "Source"),
            ("status", "Status"),
            *[("field:" + f["key"], f["label"]) for f in data["fields"]],
        ]:
            direction = (
                "desc"
                if data["context"]["sort"] == key and data["context"]["direction"] == "asc"
                else "asc"
            )
            headers.append(
                {
                    "key": key,
                    "label": label,
                    "url": f"/collections/{collection_id}/review?"
                    + urlencode(data["context"] | {"sort": key, "direction": direction}),
                }
            )
        message = (
            "Reached the end of this view. Saved examples remain available in the list."
            if request.query_params.get("done") == "yes"
            else None
        )
        return render(
            request, "review_list.html", **data, headers=headers, display=display, message=message
        )

    @app.post("/collections/{collection_id}/review/bulk")
    async def bulk(request: Request, collection_id: int):
        form = await request.form()
        try:
            selections = [tuple(map(int, value.split(":"))) for value in form.getlist("selection")]
            if any(len(item) != 2 for item in selections):
                raise ValueError()
            bulk_status(
                root, collection_id, selections, form.get("action", ""), form.get("reason", "")
            )
        except (ValueError, TypeError):
            return render(
                request,
                "error.html",
                message="No changes saved. Select 1–100 current examples and an action; give a reason for exclusions. If another tab saved an example, reload and select again.",
                status_code=409,
            )
        return RedirectResponse(f"/collections/{collection_id}/review", 303)

    @app.get("/collections/{collection_id}/review/{job_id}")
    def detail_view(request: Request, collection_id: int, job_id: int):
        return detail(request, collection_id, job_id)

    @app.post("/collections/{collection_id}/review/{job_id}")
    async def save(request: Request, collection_id: int, job_id: int):
        data = listing(collection_id, request.query_params)
        form = await request.form()
        wants_json = "application/json" in request.headers.get("accept", "")
        action = form.get("action", "save")
        sequence, position, previous, following = neighbors(data, job_id)
        target = previous if action == "previous" else following
        try:
            try:
                revision = int(form.get("revision", ""))
            except ValueError:
                raise ReviewInputError("This form expired. Reload before saving.") from None
            values = form_values(data["fields"], form)
            review = save_review(
                root,
                collection_id,
                job_id,
                revision,
                values,
                form.get("notes", ""),
                action,
                form.get("exclusion_reason", ""),
            )
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            code = 409 if isinstance(exc, ReviewConflict) else 400
            if wants_json:
                return JSONResponse(
                    {"message": str(exc), "field": getattr(exc, "field", None)}, status_code=code
                )
            return detail(
                request,
                collection_id,
                job_id,
                data=data,
                raw=form,
                message=str(exc),
                status_code=code,
            )
        redirect = detail_url(collection_id, job_id, data["context"])
        if action in ("previous", "next", "review_next", "exclude"):
            redirect = (
                detail_url(collection_id, target, data["context"])
                if target is not None
                else data["list_url"] + "&done=yes"
            )
        if wants_json:
            redirect = request.scope.get("root_path", "") + redirect
            return JSONResponse(
                {
                    "revision": review["revision"],
                    "status": review["status"],
                    "updated_at": review["updated_at"],
                    "redirect": redirect,
                }
            )
        return RedirectResponse(redirect, status_code=303)
