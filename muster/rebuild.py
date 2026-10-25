"""Fork an editable collection from retained sources without changing accepted schemas."""

import json
import shutil
from uuid import uuid4

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse

from muster.knowledge import _write
from muster.schema import get_draft, now
from muster.storage import connect


def rebuild(root, cid, name):
    if not name.strip() or len(name.strip()) > 120:
        raise ValueError("Give the new draft a name of 1–120 characters.")
    draft = get_draft(root, cid)
    if not draft["accepted_at"]:
        raise ValueError("Accept the original fields before rebuilding.")
    created = []
    try:
        with connect(root) as db:
            db.execute("BEGIN IMMEDIATE")
            if (
                db.execute(
                    "SELECT 1 FROM jobs WHERE collection_id=? AND status='collecting'", (cid,)
                ).fetchone()
                or db.execute(
                    "SELECT 1 FROM extraction_batches WHERE collection_id=? AND status='running'",
                    (cid,),
                ).fetchone()
            ):
                raise ValueError("Stop collection and extraction before rebuilding.")
            new_cid = db.execute(
                "INSERT INTO collections(name) VALUES(?)", (name.strip(),)
            ).lastrowid
            db.execute(
                "INSERT INTO collection_schemas(collection_id,fields,guidance) VALUES(?,?,?)",
                (new_cid, json.dumps(draft["fields"]), draft["guidance"]),
            )
            jobs = db.execute(
                "SELECT * FROM jobs WHERE collection_id=? ORDER BY id", (cid,)
            ).fetchall()
            for job in jobs:
                captures = db.execute(
                    "SELECT * FROM captures WHERE job_id=? ORDER BY captured_at,id", (job["id"],)
                ).fetchall()
                status = (
                    "captured" if any(c["status"] == "captured" for c in captures) else "queued"
                )
                jid = db.execute(
                    "INSERT INTO jobs(collection_id,url,status,input_rows,removed) VALUES(?,?,?,?,?)",
                    (new_cid, job["url"], status, job["input_rows"], job["removed"]),
                ).lastrowid
                review = db.execute("SELECT * FROM reviews WHERE job_id=?", (job["id"],)).fetchone()
                exclusion = db.execute(
                    "SELECT reason FROM publication_exclusions WHERE job_id=?", (job["id"],)
                ).fetchone()
                if exclusion:
                    db.execute(
                        "INSERT INTO publication_exclusions VALUES(?,?,?)",
                        (jid, exclusion["reason"], now()),
                    )
                observations = {
                    "original_collection_id": cid,
                    "original_job_id": job["id"],
                    "review": dict(review) if review else None,
                    "lookup_results": [
                        dict(row)
                        for row in db.execute(
                            "SELECT * FROM connector_calls WHERE collection_id=? AND status='complete'",
                            (cid,),
                        )
                    ],
                }
                db.execute(
                    "INSERT INTO rebuild_observations VALUES(?,?,?)",
                    (jid, new_cid, json.dumps(observations, ensure_ascii=False)),
                )
                for capture in captures:
                    capture_id = uuid4().hex
                    source = root / "sources" / str(job["id"]) / capture["id"]
                    target = root / "sources" / str(jid) / capture_id
                    created.append(target.parent)
                    # Refuse symbolic links instead of following references outside retained storage.
                    if not source.is_dir() or any(p.is_symlink() for p in source.rglob("*")):
                        raise ValueError(
                            "A retained capture is missing or contains symbolic links. Restore it before rebuilding."
                        )
                    shutil.copytree(source, target)
                    metadata = json.loads(capture["metadata"])
                    metadata.update(
                        id=capture_id,
                        job_id=jid,
                        rebuilt_from={
                            "collection_id": cid,
                            "job_id": job["id"],
                            "capture_id": capture["id"],
                        },
                    )
                    (target / "metadata.json").write_bytes(
                        json.dumps(metadata, ensure_ascii=False, indent=2).encode()
                    )
                    db.execute(
                        "INSERT INTO captures VALUES(?,?,?,?,?,?,?)",
                        (
                            capture_id,
                            jid,
                            capture["captured_at"],
                            capture["final_url"],
                            capture["status"],
                            capture["error"],
                            json.dumps(metadata),
                        ),
                    )
            for article in db.execute(
                "SELECT * FROM knowledge_articles WHERE collection_id=?", (cid,)
            ).fetchall():
                aid = uuid4().hex
                db.execute(
                    "INSERT INTO knowledge_articles(id,collection_id,title,body) VALUES(?,?,?,?)",
                    (aid, new_cid, article["title"], article["body"]),
                )
                history = [
                    dict(row)
                    for row in db.execute(
                        "SELECT * FROM knowledge_revisions WHERE article_id=? ORDER BY revision",
                        (article["id"],),
                    )
                ]
                _write(
                    db,
                    root,
                    new_cid,
                    aid,
                    1,
                    article["title"],
                    article["body"],
                    {
                        "author": "rebuild",
                        "original_collection_id": cid,
                        "original_article_id": article["id"],
                        "original_history": history,
                    },
                )
            return new_cid
    except Exception:
        for directory in set(created):
            shutil.rmtree(directory, ignore_errors=True)
        raise


def register_rebuild_routes(app, root, render):
    @app.get("/collections/{cid}/rebuild")
    def preview(request: Request, cid: int):
        try:
            draft = get_draft(root, cid)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        with connect(root) as db:
            collection = db.execute("SELECT * FROM collections WHERE id=?", (cid,)).fetchone()
        return render(request, "rebuild.html", collection=collection, draft=draft)

    @app.post("/collections/{cid}/rebuild")
    async def fork(request: Request, cid: int):
        form = await request.form()
        try:
            if app.state.collector.active and app.state.collector.collection_id == cid:
                raise ValueError("Stop collection before rebuilding.")
            new_cid = rebuild(root, cid, form.get("name", ""))
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(409, str(exc)) from exc
        return RedirectResponse(f"/collections/{new_cid}/fields?manual=1", 303)
