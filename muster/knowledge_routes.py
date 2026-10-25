"""Local Markdown editing; every provider send and AI acceptance is explicit."""

import json

from fastapi import HTTPException, Request
from fastapi.responses import PlainTextResponse, RedirectResponse

from muster import knowledge as kb
from muster.review import get_review
from muster.schema import get_draft
from muster.storage import connect


def register_knowledge_routes(app, root, render):
    def attempt(call):
        try:
            return call()
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc

    def home(request, cid, message=None, status_code=200, lesson="", aid="", job_id=None):
        item = attempt(lambda: kb.collection(root, cid))
        if job_id is None:
            raw = request.query_params.get("job_id")
            if raw:
                try:
                    job_id = int(raw)
                except ValueError:
                    raise HTTPException(400, "Invalid example number") from None
        review = attempt(lambda: get_review(root, cid, job_id)) if job_id is not None else None
        return render(
            request,
            "knowledge.html",
            collection=item,
            articles=kb.articles(root, cid),
            suggestions=kb.suggestions(root, cid),
            guidance=get_draft(root, cid)["guidance"],
            review=review,
            job_id=job_id,
            lesson=lesson,
            selected_article=aid,
            message=message,
            status_code=status_code,
        )

    def editor(request, cid, aid=None, raw=None, message=None, status_code=200):
        item = attempt(lambda: kb.collection(root, cid))
        saved = attempt(lambda: kb.article(root, cid, aid)) if aid else None
        with connect(root) as db:
            history = (
                [
                    dict(r)
                    for r in db.execute(
                        "SELECT * FROM knowledge_revisions WHERE article_id=? ORDER BY revision DESC",
                        (aid,),
                    )
                ]
                if aid
                else []
            )
        for entry in history:
            entry["provenance"] = json.loads(entry["provenance"])
        return render(
            request,
            "knowledge_article.html",
            collection=item,
            article=saved,
            title=raw.get("title", "") if raw is not None else saved["title"] if saved else "",
            body=raw.get("body", "") if raw is not None else saved["body"] if saved else "",
            revision=raw.get("revision", "0")
            if raw is not None
            else saved["revision"]
            if saved
            else 0,
            history=history,
            message=message,
            status_code=status_code,
        )

    def proposal(request, cid, rid, message=None, status_code=200, raw=None):
        item = attempt(lambda: kb.collection(root, cid))
        suggestion = attempt(lambda: kb.get_request(root, cid, rid))
        title = (
            raw.get("title", "")
            if raw is not None
            else (suggestion["result"] or {}).get("title", "")
        )
        body = (
            raw.get("body", "") if raw is not None else (suggestion["result"] or {}).get("body", "")
        )
        current = True
        try:
            with connect(root) as db:
                kb._current(db, suggestion)
        except kb.KnowledgeConflict as exc:
            current = False
            message = message or str(exc)
        return render(
            request,
            "knowledge_request.html",
            collection=item,
            suggestion=suggestion,
            title=title,
            body=body,
            diff=kb.diff(suggestion, title, body),
            current=current,
            message=message,
            status_code=status_code,
        )

    @app.get("/collections/{cid}/knowledge")
    def list_articles(request: Request, cid: int):
        return home(request, cid)

    @app.get("/collections/{cid}/knowledge/new")
    def new_article(request: Request, cid: int):
        return editor(request, cid)

    @app.get("/collections/{cid}/knowledge/articles/{aid}")
    def edit_article(request: Request, cid: int, aid: str):
        return editor(request, cid, aid)

    @app.get("/collections/{cid}/knowledge/articles/{aid}/download")
    def download(cid: int, aid: str):
        saved = attempt(lambda: kb.article(root, cid, aid))
        return PlainTextResponse(
            saved["body"], headers={"Content-Disposition": f'attachment; filename="{aid}.md"'}
        )

    @app.post("/collections/{cid}/knowledge/save")
    async def save(request: Request, cid: int):
        form = await request.form()
        aid = form.get("article_id") or None
        try:
            revision = int(form.get("revision", ""))
            aid = attempt(
                lambda: kb.save_article(
                    root, cid, aid, revision, form.get("title", ""), form.get("body", "")
                )
            )
        except ValueError as exc:
            return editor(
                request,
                cid,
                aid,
                form,
                str(exc) or "Check the article and revision.",
                409 if isinstance(exc, kb.KnowledgeConflict) else 400,
            )
        return RedirectResponse(f"/collections/{cid}/knowledge/articles/{aid}", 303)

    @app.post("/collections/{cid}/knowledge/prepare")
    async def prepare(request: Request, cid: int):
        form = await request.form()
        job_id = None
        try:
            job_id = int(form["job_id"]) if form.get("job_id") else None
            rid = attempt(
                lambda: kb.prepare(
                    root,
                    cid,
                    app.state.schema_provider,
                    form.get("article_id") or None,
                    job_id,
                    form.get("lesson", ""),
                )
            )
        except ValueError as exc:
            return home(
                request,
                cid,
                str(exc) or "Check the selected example.",
                400,
                form.get("lesson", ""),
                form.get("article_id", ""),
                job_id,
            )
        return RedirectResponse(f"/collections/{cid}/knowledge/suggestions/{rid}", 303)

    @app.get("/collections/{cid}/knowledge/suggestions/{rid}")
    def request_view(request: Request, cid: int, rid: str):
        return proposal(request, cid, rid)

    @app.post("/collections/{cid}/knowledge/suggestions/{rid}/{action}")
    async def change(request: Request, cid: int, rid: str, action: str):
        attempt(lambda: kb.get_request(root, cid, rid))
        form = await request.form()
        if action == "send" and form.get("consent") != "yes":
            return proposal(
                request,
                cid,
                rid,
                "Agree to send the displayed content before requesting a suggestion.",
                403,
            )
        try:
            if action == "send":
                await kb.send(root, cid, rid, app.state.schema_provider)
            elif action == "preview-edit":
                kb.validate_text(form.get("title", ""), form.get("body", ""))
                return proposal(
                    request, cid, rid, "Updated diff below. Check it before accepting.", raw=form
                )
            elif action in ("accept", "dismiss"):
                kb.resolve(root, cid, rid, action, form.get("title", ""), form.get("body", ""))
            else:
                raise HTTPException(404, "Action not found")
        except ValueError as exc:
            return proposal(
                request,
                cid,
                rid,
                str(exc),
                409 if isinstance(exc, kb.KnowledgeConflict) else 400,
                raw=form if action != "send" else None,
            )
        return RedirectResponse(f"/collections/{cid}/knowledge/suggestions/{rid}", 303)
