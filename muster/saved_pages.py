"""Saved HTML enters the existing capture/extraction pipeline without a browser or fetch."""

import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from muster.schema import PageText, now
from muster.storage import connect

MAX_PAGE = 8 * 1024 * 1024


def save_page(root, name, filename, content, source_url="", collection_id=None):
    if not filename or Path(filename).suffix.lower() not in {".html", ".htm"}:
        raise ValueError("Choose a saved HTML page (.html or .htm).")
    if not content or len(content) > MAX_PAGE:
        raise ValueError("Choose a nonempty saved page no larger than 8 MiB.")
    parser = PageText()
    parser.feed(content.decode("utf-8", errors="replace"))
    if not "".join(parser.parts).strip():
        raise ValueError("This page has no readable text. Save a page with the details visible.")
    if not name.strip() or len(name.strip()) > 120:
        raise ValueError("Give your collection a name of 1–120 characters.")
    if source_url:
        parts = urlsplit(source_url)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username
            or parts.password
            or len(source_url) > 2000
        ):
            raise ValueError("Use the original http or https page address without login details.")
    sha = hashlib.sha256(content).hexdigest()
    # Missing origin is explicit, never represented as an observed web address.
    url = source_url or f"saved-page:{sha}"
    with connect(root) as db:
        db.execute("BEGIN IMMEDIATE")
        if collection_id is None:
            collection_id = db.execute(
                "INSERT INTO collections(name) VALUES(?)", (name.strip(),)
            ).lastrowid
        elif not db.execute("SELECT 1 FROM collections WHERE id=?", (collection_id,)).fetchone():
            raise ValueError("Choose an existing collection.")
        if (
            db.execute(
                "SELECT 1 FROM jobs WHERE collection_id=? AND status='collecting'", (collection_id,)
            ).fetchone()
            or db.execute(
                "SELECT 1 FROM extraction_batches WHERE collection_id=? AND status='running'",
                (collection_id,),
            ).fetchone()
        ):
            raise ValueError(
                "Wait for collection and extraction to finish before adding a saved page."
            )
        row = db.execute(
            "SELECT id FROM jobs WHERE collection_id=? AND url=?", (collection_id, url)
        ).fetchone()
        if row:
            jid = row[0]
            # Identical uploads do not duplicate captures or change review state.
            for capture in db.execute("SELECT id,metadata FROM captures WHERE job_id=?", (jid,)):
                if json.loads(capture["metadata"]).get("upload_sha256") == sha:
                    return collection_id
            raise ValueError(
                "This address already has a different saved page. Use a separate collection to preserve its extraction and review history."
            )
        jid = db.execute(
            "INSERT INTO jobs(collection_id,url,status) VALUES(?,?,'captured')",
            (collection_id, url),
        ).lastrowid
        cid = uuid4().hex
        folder = root / "sources" / str(jid) / cid
        folder.mkdir(parents=True, exist_ok=False)
        (folder / "page.html").write_bytes(content)
        metadata = dict(
            id=cid,
            job_id=jid,
            captured_at=now(),
            final_url=url,
            title=Path(filename).name[:200],
            status="captured",
            error=None,
            http_status=None,
            html="page.html",
            screenshot=None,
            images=[],
            upload_sha256=sha,
            warnings=[
                "Uploaded saved page. No network fetch, screenshot or visual verification was performed."
            ],
            collector="Saved HTML upload",
        )
        (folder / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False), encoding="utf-8"
        )
        db.execute(
            "INSERT INTO captures(id,job_id,captured_at,final_url,status,metadata) VALUES(?,?,?,?,'captured',?)",
            (cid, jid, metadata["captured_at"], url, json.dumps(metadata, ensure_ascii=False)),
        )
    return collection_id
