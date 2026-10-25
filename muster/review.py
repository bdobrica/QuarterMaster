"""Human reviews stay separate from model output, with optimistic save conflicts."""

import json
import re
from collections import Counter
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from muster.schema import get_draft, now, validate_record
from muster.storage import connect

STATUSES = {
    "needs_review": "Needs review",
    "reviewed": "Reviewed",
    "excluded": "Excluded",
    "queued": "Waiting to collect",
    "collecting": "Collecting",
    "captured": "Needs extraction",
    "failed": "Failed",
    "blocked": "Needs attention",
    "extracting": "Extracting",
}


class ReviewConflict(ValueError):
    pass


class ReviewInputError(ValueError):
    def __init__(self, message, field=None):
        super().__init__(message)
        self.field = field


def restore_observations(payload, values):
    """Restore compatible human work for successful or manually recovered rebuilds."""
    notes, reason, status, corrections = "", "", "needs_review", {}
    prior = payload.get("prior_observations")
    if prior and prior.get("review"):
        from jsonschema import Draft202012Validator, FormatChecker

        previous = prior["review"]
        notes, reason = previous["notes"], previous["exclusion_reason"]
        status = "excluded" if previous["status"] == "excluded" else "needs_review"
        properties = payload["schema"]["properties"]
        for key, correction in json.loads(previous["corrections"]).items():
            if key in properties and Draft202012Validator(
                properties[key], format_checker=FormatChecker()
            ).is_valid(correction["value"]):
                values[key] = correction["value"]
                corrections[key] = correction | {"restored_from_job": prior["original_job_id"]}
    return values, notes, status, reason, corrections


def ensure_reviews(root, collection_id):
    """Seed a review once. Subsequent extractions never overwrite it."""
    with connect(root) as db:
        if not db.execute("SELECT 1 FROM collections WHERE id=?", (collection_id,)).fetchone():
            raise LookupError("Collection not found")
        rows = db.execute(
            """SELECT e.* FROM extractions e JOIN jobs j ON j.id=e.job_id
            LEFT JOIN reviews existing ON existing.job_id=e.job_id
            WHERE j.removed=0 AND j.collection_id=? AND existing.job_id IS NULL AND e.status='complete'
            AND e.id=(SELECT latest.id FROM extractions latest WHERE latest.job_id=e.job_id AND latest.status='complete'
                ORDER BY latest.finished_at DESC,latest.id DESC LIMIT 1)""",
            (collection_id,),
        ).fetchall()
        for row in rows:
            values = json.loads(row["result"])["values"]
            values, notes, status, reason, corrections = restore_observations(
                json.loads(row["payload"]), values
            )
            db.execute(
                "INSERT OR IGNORE INTO reviews(job_id,extraction_id,values_json,notes,status,exclusion_reason,corrections) VALUES(?,?,?,?,?,?,?)",
                (
                    row["job_id"],
                    row["id"],
                    json.dumps(values, ensure_ascii=False),
                    notes,
                    status,
                    reason,
                    json.dumps(corrections, ensure_ascii=False),
                ),
            )


def options(params, fields):
    result = {
        name: params.get(name, default)
        for name, default in (("q", ""), ("status", ""), ("sort", "id"), ("direction", "asc"))
    }
    if len(result["q"]) > 200:
        raise ValueError("Keep searches within 200 characters.")
    if result["status"] and result["status"] not in STATUSES:
        raise ValueError("Choose a listed review status.")
    if result["sort"] not in {
        "source",
        "status",
        "updated",
        "id",
        *("field:" + field["key"] for field in fields),
    }:
        raise ValueError("Choose a listed sort column.")
    if result["direction"] not in ("asc", "desc"):
        raise ValueError("Choose ascending or descending order.")
    return result


def list_url(collection_id, context):
    return f"/collections/{collection_id}/review?" + urlencode(context)


def detail_url(collection_id, job_id, context):
    return f"/collections/{collection_id}/review/{job_id}?" + urlencode(context)


def display(value):
    if value is None:
        return "Unknown"
    if value is True:
        return "Yes"
    if value is False:
        return "No"
    if isinstance(value, list):
        return ", ".join(value)
    return str(value)


def review_list(root, collection_id, params):
    ensure_reviews(root, collection_id)
    draft = get_draft(root, collection_id)
    fields = draft["fields"]
    context = options(params, fields)
    with connect(root) as db:
        collection = dict(
            db.execute("SELECT * FROM collections WHERE id=?", (collection_id,)).fetchone()
        )
        jobs = db.execute(
            """SELECT j.*,r.extraction_id,r.values_json,r.notes,r.status AS review_status,r.updated_at,r.exclusion_reason,r.revision AS review_revision
            FROM jobs j LEFT JOIN reviews r ON r.job_id=j.id WHERE j.removed=0 AND j.collection_id=? ORDER BY j.id""",
            (collection_id,),
        ).fetchall()
        attempts = db.execute(
            """SELECT e.*,c.metadata FROM extractions e JOIN jobs j ON j.id=e.job_id
            JOIN captures c ON c.id=e.capture_id WHERE j.removed=0 AND j.collection_id=? ORDER BY e.created_at DESC,e.id DESC""",
            (collection_id,),
        ).fetchall()
    with connect(root) as db:
        captures = db.execute(
            "SELECT c.job_id,c.final_url FROM captures c JOIN jobs j ON j.id=c.job_id WHERE j.collection_id=? AND j.removed=0 AND c.status='captured' ORDER BY c.captured_at DESC,c.id DESC",
            (collection_id,),
        ).fetchall()
    destinations = {}
    for capture in captures:
        parts = urlsplit(capture["final_url"])
        query = [
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if not k.casefold().startswith("utm_") and k.casefold() not in ("fbclid", "gclid")
        ]
        destinations.setdefault(
            capture["job_id"],
            urlunsplit((parts.scheme, parts.netloc.casefold(), parts.path, urlencode(query), "")),
        )
    latest, bases = {}, {}
    for attempt in attempts:
        latest.setdefault(attempt["job_id"], attempt)
        bases[attempt["id"]] = attempt
    rows = []
    for job in jobs:
        row = dict(job)
        attempt = latest.get(row["id"])
        base = bases.get(row["extraction_id"])
        row["values"] = json.loads(row["values_json"]) if row["values_json"] else {}
        row["state"] = row["review_status"] or (
            "failed"
            if attempt and attempt["status"] == "failed"
            else "extracting"
            if attempt and attempt["status"] in ("queued", "running")
            else row["status"]
        )
        row["label"] = STATUSES[row["state"]]
        row["title"] = (str(json.loads(base["metadata"]).get("title", "")) if base else "") or row[
            "url"
        ]
        row["domain"] = urlsplit(row["url"]).netloc
        row["detail"] = (
            row["error"]
            or (attempt["error"] if attempt and attempt["status"] == "failed" else "")
            or ""
        )
        row["newer"] = bool(
            base and attempt and attempt["id"] != base["id"] and attempt["status"] == "complete"
        )
        row["open_url"] = detail_url(collection_id, row["id"], context) if base else None
        haystack = " ".join(
            [
                row["url"],
                row["title"],
                row["notes"] or "",
                row["input_rows"],
                *(display(value) for value in row["values"].values()),
            ]
        ).casefold()
        row["duplicate_ids"] = [
            jid
            for jid, destination in destinations.items()
            if jid != row["id"] and destination == destinations.get(row["id"])
        ]
        row["matches"] = (not context["q"] or context["q"].casefold() in haystack) and (
            not context["status"] or row["state"] == context["status"]
        )
        rows.append(row)
    counts = Counter(row["state"] for row in rows)
    filtered = [row for row in rows if row["matches"]]
    sort = context["sort"]

    def key(row):
        if sort.startswith("field:"):
            value = row["values"].get(sort[6:])
            return (
                value.casefold()
                if isinstance(value, str)
                else tuple(value)
                if isinstance(value, list)
                else value
            )
        return (
            row["title"].casefold()
            if sort == "source"
            else row["label"]
            if sort == "status"
            else row["updated_at"]
            if sort == "updated"
            else row["id"]
        )

    present = [row for row in rows if key(row) is not None]
    missing = [row for row in rows if key(row) is None]
    ordered = sorted(present, key=key, reverse=context["direction"] == "desc") + missing
    filtered = [row for row in ordered if row["matches"]]
    return {
        "collection": collection,
        "fields": fields,
        "context": context,
        "rows": filtered,
        "counts": counts,
        "navigation": [row["id"] for row in ordered if row["open_url"]],
        "total": len(rows),
        "statuses": STATUSES,
        "list_url": list_url(collection_id, context),
    }


def get_review(root, collection_id, job_id):
    ensure_reviews(root, collection_id)
    with connect(root) as db:
        row = db.execute(
            """SELECT r.*,e.payload,e.result,e.capture_id,e.schema_id,j.url,c.metadata
            FROM reviews r JOIN jobs j ON j.id=r.job_id JOIN extractions e ON e.id=r.extraction_id
            JOIN captures c ON c.id=e.capture_id WHERE r.job_id=? AND j.collection_id=?""",
            (job_id, collection_id),
        ).fetchone()
        latest = db.execute(
            "SELECT id FROM extractions WHERE job_id=? AND status='complete' ORDER BY finished_at DESC,id DESC LIMIT 1",
            (job_id,),
        ).fetchone()
    if row is None:
        raise LookupError(
            "This page has no successful extraction to review. Collect and extract it first."
        )
    result = dict(row)
    for key in ("payload", "result", "metadata", "corrections"):
        result[key] = json.loads(result[key])
    result["values"] = json.loads(result["values_json"])
    result["newer_id"] = (
        latest["id"] if latest and latest["id"] != result["extraction_id"] else None
    )
    return result


def form_values(fields, form):
    values = {}
    for field in fields:
        key, label, kind = field["key"], field["label"], field["type"]
        if form.get("unknown:" + key) == "yes":
            values[key] = None
            continue
        raw = form.get("value:" + key, "")
        if not isinstance(raw, str) or len(raw) > 10000:
            raise ReviewInputError(f"Keep {label} within 10,000 characters.", key)
        try:
            if kind == "number":
                values[key] = float(raw)
            elif kind == "integer":
                if not re.fullmatch(r"[+-]?\d+", raw.strip()):
                    raise ValueError()
                values[key] = int(raw)
            elif kind == "boolean":
                if raw not in ("yes", "no"):
                    raise ValueError()
                values[key] = raw == "yes"
            elif kind == "text_list":
                values[key] = [line for line in raw.splitlines() if line.strip()]
            else:
                if kind == "date" and not raw:
                    raise ValueError()
                values[key] = raw
        except ValueError:
            raise ReviewInputError(f"Enter a valid {label}, or choose Unknown.", key) from None
    return values


def save_review(
    root, collection_id, job_id, revision, values, notes, action="save", exclusion_reason=""
):
    if action not in ("autosave", "save", "previous", "next", "review_next", "exclude", "include"):
        raise ReviewInputError("Choose a listed review action.")
    review = get_review(root, collection_id, job_id)

    def already_saved(current):
        return (
            action in ("autosave", "save", "previous", "next")
            and values == current["values"]
            and notes == current["notes"]
            and isinstance(exclusion_reason, str)
            and exclusion_reason.strip() == current["exclusion_reason"]
        )

    if review["revision"] != revision:
        if already_saved(review):
            return review  # A pagehide save may have finished while the next page was loading.
        raise ReviewConflict(
            "Another tab saved this example. Reload to compare; your unsaved draft stays in this browser."
        )
    if validate_record(root, collection_id, values) != review["schema_id"]:
        raise ReviewInputError("These values do not match the accepted fields.")
    if not isinstance(notes, str) or len(notes) > 10000:
        raise ReviewInputError("Keep review notes within 10,000 characters.", "notes")
    if not isinstance(exclusion_reason, str) or len(exclusion_reason) > 1000:
        raise ReviewInputError(
            "Keep the exclusion reason within 1,000 characters.", "exclusion_reason"
        )
    status = review["status"]
    changed = (
        values != review["values"]
        or notes != review["notes"]
        or exclusion_reason != review["exclusion_reason"]
    )
    if changed and status == "reviewed":
        status = "needs_review"
    if action == "review_next":
        status = "reviewed"
    elif action == "exclude":
        status = "excluded"
    elif action == "include":
        status = "needs_review"
    reason = exclusion_reason.strip()
    if status == "excluded" and not reason:
        raise ReviewInputError("Give a reason before excluding this example.", "exclusion_reason")
    timestamp = now()
    corrections = {}
    for field, value in values.items():
        if value != review["result"]["values"][field]:
            old = review["corrections"].get(field)
            corrections[field] = (
                old
                if old and old["value"] == value
                else {
                    "source": "user",
                    "original": review["result"]["values"][field],
                    "value": value,
                    "updated_at": timestamp,
                }
            )
    if not changed and status == review["status"]:
        return review
    with connect(root) as db:
        result = db.execute(
            """UPDATE reviews SET values_json=?,notes=?,status=?,exclusion_reason=?,corrections=?,
            revision=revision+1,updated_at=?,reviewed_at=? WHERE job_id=? AND revision=?""",
            (
                json.dumps(values, ensure_ascii=False, allow_nan=False),
                notes,
                status,
                reason,
                json.dumps(corrections, ensure_ascii=False),
                timestamp,
                timestamp if status == "reviewed" else None,
                job_id,
                revision,
            ),
        )
        changed = result.rowcount
    current = get_review(root, collection_id, job_id)
    if not changed and not already_saved(current):
        raise ReviewConflict(
            "Another tab saved this example. Reload to compare; your unsaved draft stays in this browser."
        )
    return current


def bulk_status(root, cid, selections, action, reason=""):
    """Atomically change only selected review statuses, with stale-tab protection."""
    if action not in ("reviewed", "needs_review", "excluded") or not 1 <= len(selections) <= 100:
        raise ReviewInputError("Select 1–100 examples and a listed action.")
    if len({jid for jid, revision in selections}) != len(selections):
        raise ReviewInputError("Each selected example must appear once.")
    if len(reason) > 1000 or (action == "excluded" and not reason.strip()):
        raise ReviewInputError(
            "Give a reason of at most 1,000 characters before excluding examples."
        )
    ensure_reviews(root, cid)
    with connect(root) as db:
        db.execute("BEGIN IMMEDIATE")
        for jid, revision in selections:
            row = db.execute(
                "SELECT r.revision FROM reviews r JOIN jobs j ON j.id=r.job_id WHERE j.collection_id=? AND j.removed=0 AND j.id=?",
                (cid, jid),
            ).fetchone()
            if not row or row["revision"] != revision:
                raise ReviewConflict(
                    "One selected example changed or is unavailable. Nothing was changed; reload and select again."
                )
        timestamp = now()
        for jid, _revision in selections:
            db.execute("DELETE FROM publication_exclusions WHERE job_id=?", (jid,))
            db.execute(
                "UPDATE reviews SET status=?,exclusion_reason=?,reviewed_at=?,updated_at=?,revision=revision+1 WHERE job_id=?",
                (
                    action,
                    reason.strip() if action == "excluded" else "",
                    timestamp if action == "reviewed" else None,
                    timestamp,
                    jid,
                ),
            )
