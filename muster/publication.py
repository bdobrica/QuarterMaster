"""Self-contained, checked publication snapshots. No provider or browser access."""

import hashlib
import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from uuid import uuid4

from jsonschema import Draft202012Validator, FormatChecker

from muster.review import ensure_reviews
from muster.schema import now
from muster.storage import connect


class PublicationConflict(ValueError):
    pass


def encoded(value):
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def snapshot(db, cid):
    collection = db.execute("SELECT * FROM collections WHERE id=?", (cid,)).fetchone()
    if collection is None:
        raise LookupError("Collection not found")

    def rows(query, params=(cid,)):
        return [dict(row) for row in db.execute(query, params)]

    return {
        "collection": dict(collection),
        "schema": rows("SELECT * FROM collection_schemas WHERE collection_id=?"),
        "publications": rows("SELECT * FROM publications WHERE collection_id=? ORDER BY version"),
        "jobs": rows("SELECT * FROM jobs WHERE collection_id=? AND removed=0 ORDER BY id"),
        "reviews": rows(
            "SELECT r.* FROM reviews r JOIN jobs j ON j.id=r.job_id WHERE j.collection_id=? ORDER BY r.job_id"
        ),
        "exclusions": rows(
            "SELECT x.* FROM publication_exclusions x JOIN jobs j ON j.id=x.job_id WHERE j.collection_id=? ORDER BY x.job_id"
        ),
        "articles": rows("SELECT * FROM knowledge_articles WHERE collection_id=? ORDER BY id"),
        "revisions": rows(
            "SELECT r.* FROM knowledge_revisions r JOIN knowledge_articles a ON a.id=r.article_id WHERE a.collection_id=? ORDER BY r.article_id,r.revision"
        ),
        "suggestions": rows("SELECT * FROM knowledge_requests WHERE collection_id=? ORDER BY id"),
        "extractions": rows(
            "SELECT e.*,b.provider,b.consent_at FROM extractions e JOIN jobs j ON j.id=e.job_id JOIN extraction_batches b ON b.id=e.batch_id WHERE j.collection_id=? ORDER BY e.id"
        ),
        "schema_requests": rows("SELECT * FROM schema_requests WHERE collection_id=? ORDER BY id"),
        "captures": rows(
            "SELECT c.* FROM captures c JOIN jobs j ON j.id=c.job_id WHERE j.collection_id=? ORDER BY c.id"
        ),
    }


def assess(data):
    reviews = {r["job_id"]: r for r in data["reviews"]}
    exclusions = {r["job_id"]: r for r in data["exclusions"]}
    jobs = []
    for job in data["jobs"]:
        review = reviews.get(job["id"])
        reason = exclusions.get(job["id"], {}).get("reason") or (
            review["exclusion_reason"] if review and review["status"] == "excluded" else ""
        )
        state = (
            "excluded"
            if reason
            else "reviewed"
            if review and review["status"] == "reviewed"
            else "unreviewed"
            if review
            else "unavailable"
        )
        jobs.append(job | {"decision": state, "reason": reason, "review": review})
    pending = [s for s in data["suggestions"] if s["status"] not in ("accepted", "dismissed")]
    problems = []
    if not data["schema"] or not data["schema"][0]["accepted_at"]:
        problems.append("Accept your fields before publishing.")
    warnings = []
    unreviewed = sum(j["decision"] == "unreviewed" for j in jobs)
    unavailable = sum(j["decision"] == "unavailable" for j in jobs)
    if unreviewed:
        warnings.append(f"{unreviewed} examples will be included as unreviewed.")
    if unavailable:
        warnings.append(
            f"{unavailable} links have no extracted example and will be left out of this version."
        )
    if pending:
        warnings.append(
            f"{len(pending)} pending knowledge suggestions will be left out; saved articles will be included."
        )
    if not any(j["decision"] in ("reviewed", "unreviewed") for j in jobs):
        problems.append("Extract at least one example before publishing.")
    # Publishing during active work could conceal an arriving result.
    if any(j["status"] == "collecting" for j in jobs) or any(
        e["status"] in ("queued", "running") for e in data["extractions"]
    ):
        problems.append("Wait for collection and extraction to finish, or stop them first.")
    return {
        "jobs": jobs,
        "pending": pending,
        "warnings": warnings,
        "problems": problems,
        "fingerprint": digest(encoded(data)),
        "included": sum(j["decision"] in ("reviewed", "unreviewed") for j in jobs),
        "unreviewed": unreviewed,
        "unavailable": unavailable,
        "excluded": sum(j["decision"] == "excluded" for j in jobs),
    }


def overview(root, cid):
    ensure_reviews(root, cid)
    with connect(root) as db:
        data = snapshot(db, cid)
        versions = [
            dict(r)
            for r in db.execute(
                "SELECT * FROM publications WHERE collection_id=? ORDER BY version DESC", (cid,)
            )
        ]
    return assess(data) | {
        "collection": data["collection"],
        "articles": data["articles"],
        "versions": versions,
    }


def exclude(root, cid, jid, reason):
    if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 1000:
        raise ValueError("Give a reason of 1–1,000 characters for leaving this link out.")
    with connect(root) as db:
        if not db.execute(
            "SELECT 1 FROM jobs WHERE id=? AND collection_id=?", (jid, cid)
        ).fetchone():
            raise LookupError("Link not found")
        db.execute(
            "INSERT INTO publication_exclusions VALUES(?,?,?) ON CONFLICT(job_id) DO UPDATE SET reason=excluded.reason,updated_at=excluded.updated_at",
            (jid, reason.strip(), now()),
        )


def include(root, cid, jid):
    with connect(root) as db:
        if not db.execute(
            "SELECT 1 FROM jobs WHERE id=? AND collection_id=?", (jid, cid)
        ).fetchone():
            raise LookupError("Link not found")
        db.execute("DELETE FROM publication_exclusions WHERE job_id=?", (jid,))
        # A review exclusion also needs an explicit inclusion before it can be reviewed again.
        db.execute(
            "UPDATE reviews SET status='needs_review',exclusion_reason='',reviewed_at=NULL,revision=revision+1,updated_at=? WHERE job_id=? AND status='excluded'",
            (now(), jid),
        )


def safe_path(base, relative):
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ValueError("Invalid bundle reference.")
    part = PurePosixPath(relative)
    if part.is_absolute() or any(p in ("..", ".") for p in part.parts) or str(part) != relative:
        raise ValueError("Invalid bundle reference.")
    result = base.joinpath(*part.parts)
    # Reject symlinks, including directories, rather than exporting unrelated files.
    if any(p.is_symlink() for p in (result, *result.parents) if p != base.parent):
        raise ValueError(
            "A retained file uses a symbolic link. Restore the original file before publishing."
        )
    if not result.resolve().is_relative_to(base.resolve()):
        raise ValueError("Invalid bundle reference.")
    return result


def build(root, destination, data, version, created_at):
    """Copy an allowlist of originals; never walk the profile or storage tree."""
    references = set()

    def write(path, body):
        target = safe_path(destination, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        return path

    def json_file(path, value):
        return write(path, encoded(value))

    def copy(relative, output=None, expected=None):
        source = safe_path(root, relative)
        if not source.is_file():
            raise ValueError(
                f"A retained file is missing: {relative}. Restore it before publishing."
            )
        body = source.read_bytes()
        if expected and digest(body) != expected:
            raise ValueError(
                f"A retained source changed: {relative}. Restore the original before publishing."
            )
        return write(output or relative, body)

    schema = data["schema"][0]
    accepted = json.loads(schema["accepted_json"])
    json_file("schema.json", accepted)
    references.add("schema.json")
    captures = {c["id"]: c for c in data["captures"]}
    retained = {}

    def capture(cid, expected=None):
        if cid not in captures:
            raise ValueError(
                "A provenance capture is missing. Restore local storage before publishing."
            )
        row = captures[cid]
        prefix = f"sources/{row['job_id']}/{cid}"
        if cid not in retained:
            metadata = json.loads(row["metadata"])
            names = ["page.html", "screenshot.png"] + [
                image["file"] for image in metadata.get("images", [])
            ]
            if any(
                not isinstance(n, str) or not re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9]+", n)
                for n in names
            ):
                raise ValueError("A capture has an invalid media filename.")
            files = []
            for name in dict.fromkeys(names):
                files.append(copy(f"{prefix}/{name}"))
            # DB capture metadata is authoritative; do not copy arbitrary sidecar files.
            files.append(json_file(f"{prefix}/metadata.json", metadata))
            retained[cid] = {
                "id": cid,
                "job_id": row["job_id"],
                "source_url": row["final_url"],
                "captured_at": row["captured_at"],
                "status": row["status"],
                "files": files,
            }
            references.update(files)
        if expected:
            body = safe_path(destination, f"{prefix}/page.html").read_bytes()
            if digest(body) != expected:
                raise ValueError(
                    "A retained page differs from its extraction or knowledge preview. Restore the original before publishing."
                )
        return prefix

    records = []
    extractions = {e["id"]: e for e in data["extractions"]}
    decisions = assess(data)
    for job in decisions["jobs"]:
        if job["decision"] not in ("reviewed", "unreviewed"):
            continue
        r = job["review"]
        e = extractions[r["extraction_id"]]
        if e["status"] != "complete" or e["schema_id"] != schema["schema_id"]:
            raise ValueError("An included example has no valid extraction for these fields.")
        values = json.loads(r["values_json"])
        Draft202012Validator(accepted, format_checker=FormatChecker()).validate(values)
        payload = json.loads(e["payload"])
        prefix = capture(e["capture_id"], payload["page"]["sha256"])
        # Recheck every image actually sent, including screenshot fallback.
        for image in payload.get("images", []):
            file = image["file"]
            if f"{prefix}/{file}" not in references:
                raise ValueError("An extraction image is missing from retained media.")
            expected = image.get("sha256")
            if (
                expected
                and digest(safe_path(destination, f"{prefix}/{file}").read_bytes()) != expected
            ):
                raise ValueError(
                    "An extraction image changed. Restore the original before publishing."
                )
        provenance = {
            "extraction_id": e["id"],
            "provider": json.loads(e["provider"]),
            "consent_at": e["consent_at"],
            "extracted_at": e["finished_at"],
            "input": payload,
            "original_result": json.loads(e["result"]),
            "review": {k: r[k] for k in ("status", "revision", "reviewed_at", "updated_at")},
            "corrections": json.loads(r["corrections"]),
        }
        ref = json_file(f"provenance/examples/{job['id']}.json", provenance)
        references.add(ref)
        records.append(
            {
                "id": str(job["id"]),
                "review_status": job["decision"],
                "schema_id": schema["schema_id"],
                "values": values,
                "notes": r["notes"],
                "source": {
                    "url": job["url"],
                    "capture_id": e["capture_id"],
                    "path": prefix,
                    "captured_at": captures[e["capture_id"]]["captured_at"],
                },
                "evidence": json.loads(e["result"])["evidence"],
                "uncertainty": json.loads(e["result"])["uncertainty"],
                "provenance": ref,
            }
        )
    write(
        "examples.jsonl",
        b"".join(
            (json.dumps(r, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n").encode(
                "utf-8"
            )
            for r in records
        ),
    )
    references.add("examples.jsonl")
    articles = []
    requests = {s["id"]: s for s in data["suggestions"]}
    for article in data["articles"]:
        history = []
        for revision in data["revisions"]:
            if revision["article_id"] != article["id"]:
                continue
            # Check the saved Markdown as well as the DB snapshot.
            source = safe_path(root, revision["path"])
            if not source.is_file() or source.read_bytes().replace(b"\r\n", b"\n") != revision[
                "body"
            ].encode("utf-8").replace(b"\r\n", b"\n"):
                raise ValueError(
                    "A saved knowledge revision is missing or changed. Restore the original before publishing."
                )
            prov = json.loads(revision["provenance"])
            entry = {k: revision[k] for k in ("id", "revision", "title", "body", "created_at")} | {
                "provenance": prov
            }
            if prov.get("request_id"):
                request = dict(requests[prov["request_id"]])
                for key in ("payload", "provider", "result"):
                    request[key] = json.loads(request[key]) if request[key] else None
                for source in request["payload"]["sources"]:
                    if source["kind"] == "retained page":
                        capture(
                            source["capture_id"],
                            source.get("source_sha256") or source.get("sha256"),
                        )
                entry["suggestion"] = request
            history.append(entry)
        if (
            not history
            or history[-1]["revision"] != article["revision"]
            or history[-1]["body"] != article["body"]
        ):
            raise ValueError("The current knowledge article has no matching saved revision.")
        path = write(f"knowledge/{article['id']}.md", article["body"].encode("utf-8"))
        prov = json_file(f"provenance/knowledge/{article['id']}.json", history)
        references.update((path, prov))
        articles.append(
            {
                "id": article["id"],
                "title": article["title"],
                "revision": article["revision"],
                "path": path,
                "provenance": prov,
            }
        )
    exclusions = [
        {"id": str(j["id"]), "url": j["url"], "reason": j["reason"]}
        for j in decisions["jobs"]
        if j["decision"] == "excluded"
    ]
    # Resolutions preserve accountability without copying unused failed/preview payloads.
    resolutions = [
        {k: s[k] for k in ("id", "status", "resolved_at", "accepted_article_id")}
        for s in data["suggestions"]
    ]
    schema_proposal = next(
        (dict(s) for s in data["schema_requests"] if s["id"] == schema["proposal_id"]), None
    )
    if schema_proposal:
        for key in ("payload", "provider", "result"):
            schema_proposal[key] = (
                json.loads(schema_proposal[key]) if schema_proposal[key] else None
            )
        for page in schema_proposal["payload"].get("samples", []):
            capture(page["capture_id"], page.get("source_sha256"))
    json_file(
        "provenance/decisions.json",
        {
            "excluded": exclusions,
            "omitted": [
                {"id": str(j["id"]), "url": j["url"], "reason": "No extracted example available"}
                for j in decisions["jobs"]
                if j["decision"] == "unavailable"
            ],
            "knowledge_suggestions": resolutions,
            "schema": {
                "id": schema["schema_id"],
                "accepted_at": schema["accepted_at"],
                "guidance": schema["guidance"],
                "fields": json.loads(schema["fields"]),
                "proposal": schema_proposal,
            },
        },
    )
    references.add("provenance/decisions.json")
    checksums = {
        str(p.relative_to(destination).as_posix()): digest(p.read_bytes())
        for p in sorted(destination.rglob("*"))
        if p.is_file()
    }
    manifest = {
        "format": "muster.bundle",
        "format_version": 1,
        "version": version,
        "created_at": created_at,
        "collection": data["collection"],
        "schema_id": schema["schema_id"],
        "counts": {
            "examples": len(records),
            "excluded": len(exclusions),
            "articles": len(articles),
            "unreviewed": decisions["unreviewed"],
            "omitted": decisions["unavailable"],
            "pending_knowledge": len(decisions["pending"]),
        },
        "examples": "examples.jsonl",
        "schema": "schema.json",
        "knowledge": articles,
        "sources": list(retained.values()),
        "decisions": "provenance/decisions.json",
        "references": sorted(references),
        "checksums": checksums,
    }
    json_file("manifest.json", manifest)
    validate_bundle(destination)
    return manifest


def validate_bundle(folder):
    """Consumer-facing integrity check: exact inventory, hashes, schema and references."""
    folder = Path(folder)
    manifest = json.loads(safe_path(folder, "manifest.json").read_text(encoding="utf-8"))
    if manifest["format"] != "muster.bundle" or manifest["format_version"] != 1:
        raise ValueError("Unsupported bundle format.")
    files = {str(p.relative_to(folder).as_posix()) for p in folder.rglob("*") if p.is_file()}
    if files != {"manifest.json", *manifest["checksums"]}:
        raise ValueError("Bundle files do not match the manifest.")
    for name, checksum in manifest["checksums"].items():
        if digest(safe_path(folder, name).read_bytes()) != checksum:
            raise ValueError(f"Bundle checksum does not match: {name}")
    for ref in manifest["references"]:
        if ref not in manifest["checksums"]:
            raise ValueError("Bundle reference has no checksummed file.")
    schema = json.loads(safe_path(folder, manifest["schema"]).read_text(encoding="utf-8"))
    if schema["$id"] != "urn:muster:schema:" + manifest["schema_id"]:
        raise ValueError("Bundle schema identifier does not match.")
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    records = [
        json.loads(line)
        for line in safe_path(folder, manifest["examples"]).read_text(encoding="utf-8").splitlines()
    ]
    if len(records) != manifest["counts"]["examples"] or len({r["id"] for r in records}) != len(
        records
    ):
        raise ValueError("Bundle example count or identifiers do not match.")
    statuses = [record.get("review_status", "reviewed") for record in records]
    if any(status not in ("reviewed", "unreviewed") for status in statuses):
        raise ValueError("Invalid example review status.")
    if statuses.count("unreviewed") != manifest["counts"].get("unreviewed", 0):
        raise ValueError("Unreviewed example count differs.")
    source_ids = {s["id"] for s in manifest["sources"]}
    for record in records:
        validator.validate(record["values"])
        if (
            record["schema_id"] != manifest["schema_id"]
            or record["source"]["capture_id"] not in source_ids
        ):
            raise ValueError("An example source or schema reference is invalid.")
        if (
            record["provenance"] not in manifest["checksums"]
            or record["source"]["path"] + "/page.html" not in manifest["checksums"]
        ):
            raise ValueError("An example file reference is invalid.")
        for refs in record["evidence"].values():
            for ref in refs:
                if (
                    ref["source"] == "image"
                    and record["source"]["path"] + "/" + ref["file"] not in manifest["checksums"]
                ):
                    raise ValueError("An evidence image reference is invalid.")
    if len(manifest["knowledge"]) != manifest["counts"]["articles"]:
        raise ValueError("Bundle knowledge count does not match.")
    for article in manifest["knowledge"]:
        if any(article[key] not in manifest["checksums"] for key in ("path", "provenance")):
            raise ValueError("A knowledge file reference is invalid.")
    for source in manifest["sources"]:
        if any(name not in manifest["checksums"] for name in source["files"]):
            raise ValueError("A source file reference is invalid.")
    return manifest


def publish(root, cid, fingerprint):
    ensure_reviews(root, cid)
    staging = None
    final = None
    archive = None
    renamed = False
    try:
        with connect(root) as db:
            db.execute("BEGIN IMMEDIATE")
            data = snapshot(db, cid)
            readiness = assess(data)
            if readiness["fingerprint"] != fingerprint:
                raise PublicationConflict(
                    "The draft changed. Check the current examples and knowledge before publishing again."
                )
            if readiness["problems"]:
                raise PublicationConflict(" ".join(readiness["problems"]))
            version = db.execute(
                "SELECT COALESCE(MAX(version),0)+1 FROM publications WHERE collection_id=?", (cid,)
            ).fetchone()[0]
            parent = root / "publications" / str(cid)
            parent.mkdir(parents=True, exist_ok=True)
            final = parent / f"v{version}"
            archive = parent / f"v{version}.zip"
            if final.exists() or archive.exists():
                raise PublicationConflict(
                    "This version already has files in storage. Restore the publication database backup before trying again; existing versions will not be overwritten."
                )
            staging = Path(tempfile.mkdtemp(prefix=".preparing-", dir=parent))
            created_at = now()
            manifest = build(root, staging, data, version, created_at)
            # The archive contains exactly this bundle, with stable ordering and timestamps.
            with zipfile.ZipFile(staging.with_suffix(".zip"), "x", zipfile.ZIP_DEFLATED) as z:
                for file in sorted(staging.rglob("*")):
                    if file.is_file():
                        info = zipfile.ZipInfo(
                            f"collection-{cid}-v{version}/" + file.relative_to(staging).as_posix(),
                            date_time=(1980, 1, 1, 0, 0, 0),
                        )
                        info.compress_type = zipfile.ZIP_DEFLATED
                        z.writestr(info, file.read_bytes())
            staging.rename(final)
            renamed = True
            staging.with_suffix(".zip").rename(archive)
            pid = uuid4().hex
            db.execute(
                "INSERT INTO publications VALUES(?,?,?,?,?,?,?)",
                (
                    pid,
                    cid,
                    version,
                    final.relative_to(root).as_posix(),
                    digest((final / "manifest.json").read_bytes()),
                    created_at,
                    manifest["counts"]["examples"],
                ),
            )
        return pid
    except Exception:
        if renamed:
            shutil.rmtree(final)
            if archive.exists():
                archive.unlink()
        raise
    finally:
        if staging:
            if staging.exists():
                shutil.rmtree(staging)
            if staging.with_suffix(".zip").exists():
                staging.with_suffix(".zip").unlink()


def get_publication(root, cid, pid):
    with connect(root) as db:
        row = db.execute(
            "SELECT * FROM publications WHERE id=? AND collection_id=?", (pid, cid)
        ).fetchone()
    if not row:
        raise LookupError("Published version not found")
    result = dict(row)
    # Older Windows releases stored native separators in this internal DB path.
    # Normalize only this metadata; bundle references remain strictly POSIX.
    relative = result["path"].replace("\\", "/")
    expected = f"publications/{result['collection_id']}/v{result['version']}"
    if relative != expected:
        raise ValueError("The saved publication folder does not match this version.")
    result["path"] = relative
    folder = safe_path(root, relative)
    if digest((folder / "manifest.json").read_bytes()) != result["manifest_sha256"]:
        raise ValueError("The published manifest changed in local storage. Restore your backup.")
    result["manifest"] = validate_bundle(folder)
    return result
