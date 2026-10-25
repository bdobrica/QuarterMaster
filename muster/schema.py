"""Reviewed field lists and the single validation contract for later extraction."""

import hashlib
import json
import re
import unicodedata
from datetime import UTC, datetime
from html.parser import HTMLParser
from uuid import uuid4

from jsonschema import Draft202012Validator, FormatChecker

from muster.storage import connect

FIELD_TYPES = {
    "text": "Text",
    "number": "Number",
    "integer": "Whole number",
    "boolean": "Yes / no",
    "date": "Date",
    "text_list": "List of text values",
}


class SchemaConflict(ValueError):
    pass


def now():
    return datetime.now(UTC).isoformat()


def validate_fields(fields, allow_empty=False):
    if not isinstance(fields, list) or len(fields) > 30 or (not fields and not allow_empty):
        raise ValueError("Choose between 1 and 30 fields.")
    keys, labels = set(), set()
    for field in fields:
        if not isinstance(field, dict) or set(field) != {"key", "label", "type", "description"}:
            raise ValueError(
                "Each field needs a name, type and description, with a valid internal identifier."
            )
        if any(not isinstance(value, str) for value in field.values()):
            raise ValueError("Field names, types and descriptions must be text.")
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,47}", field["key"]):
            raise ValueError(
                "A field has an invalid internal identifier. Rename or remove that field."
            )
        if (
            not field["label"].strip()
            or len(field["label"]) > 80
            or len(field["description"]) > 600
        ):
            raise ValueError(
                "Use field names of 1–80 characters and descriptions of at most 600 characters."
            )
        if field["type"] not in FIELD_TYPES:
            raise ValueError("Choose a supported type for every field.")
        label = " ".join(field["label"].casefold().split())
        if field["key"] in keys or label in labels:
            raise ValueError("Each field needs a different name.")
        keys.add(field["key"])
        labels.add(label)
    return fields


def form_fields(form, validate=True):
    columns = [form.getlist(name) for name in ("key", "label", "type", "description")]
    if len({len(column) for column in columns}) != 1:
        raise ValueError("The field list was incomplete. Reload it and try again.")
    if len(columns[0]) > 31:
        raise ValueError("Choose at most 30 fields.")
    fields, used = [], set(columns[0]) - {""}
    for key, label, kind, description in zip(*columns, strict=True):
        if not all(isinstance(value, str) for value in (key, label, kind, description)):
            raise ValueError("Field values must be text.")
        label, description = label.strip(), description.strip()
        if not key and not label and not description:
            continue
        if not key:
            base = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode().lower()
            base = re.sub(r"[^a-z0-9]+", "_", base).strip("_")[:40] or "field"
            if not base[0].isalpha():
                base = "field_" + base
            key, index = base, 2
            while key in used:
                key = f"{base}_{index}"
                index += 1
            used.add(key)
        fields.append({"key": key, "label": label, "type": kind, "description": description})
    return validate_fields(fields, allow_empty=True) if validate else fields


def get_draft(root, collection_id):
    with connect(root) as db:
        if not db.execute("SELECT 1 FROM collections WHERE id=?", (collection_id,)).fetchone():
            raise LookupError("Collection not found")
        db.execute(
            "INSERT OR IGNORE INTO collection_schemas(collection_id) VALUES(?)", (collection_id,)
        )
        row = dict(
            db.execute(
                "SELECT * FROM collection_schemas WHERE collection_id=?", (collection_id,)
            ).fetchone()
        )
    row["fields"] = json.loads(row["fields"])
    return row


def save_draft(root, collection_id, revision, fields, guidance, proposal_id=None):
    validate_fields(fields, allow_empty=True)
    if not isinstance(guidance, str) or len(guidance) > 4000:
        raise ValueError("Keep your guidance within 4,000 characters.")
    with connect(root) as db:
        result = db.execute(
            "UPDATE collection_schemas SET fields=?, guidance=?, proposal_id=COALESCE(?,proposal_id), revision=revision+1 WHERE collection_id=? AND revision=? AND accepted_at IS NULL",
            (
                json.dumps(fields, ensure_ascii=False),
                guidance,
                proposal_id,
                collection_id,
                revision,
            ),
        )
        if not result.rowcount:
            raise SchemaConflict(
                "These fields were accepted or changed in another tab. Reload before making changes."
            )
    return get_draft(root, collection_id)


class PageText(HTMLParser):
    SKIP = {"script", "style", "noscript", "template", "svg", "head", "nav", "header", "footer"}
    VOID = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.parts, self.size = [], [], 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        skip = tag in self.SKIP or "hidden" in attrs or attrs.get("aria-hidden") == "true"
        if tag not in self.VOID:
            self.stack.append((tag, skip or bool(self.stack and self.stack[-1][1])))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        if (self.stack and self.stack[-1][1]) or self.size >= 12000:
            return
        part = " ".join(data.split())[: 12000 - self.size]
        if part:
            self.parts.append(part)
            self.size += len(part) + 1


def sample_pages(root, collection_id):
    with connect(root) as db:
        captures = db.execute(
            """SELECT c.*,j.url,j.input_rows FROM captures c JOIN jobs j ON c.job_id=j.id
            WHERE j.removed=0 AND j.collection_id=? AND j.status='captured' AND c.status='captured'
            AND c.id=(SELECT latest.id FROM captures latest WHERE latest.job_id=j.id
                AND latest.status='captured' ORDER BY latest.captured_at DESC,latest.id DESC LIMIT 1)
            ORDER BY j.id LIMIT 5""",
            (collection_id,),
        ).fetchall()
    samples = []
    for capture in captures:
        path = root / "sources" / str(capture["job_id"]) / capture["id"] / "page.html"
        try:
            if path.stat().st_size > 8 * 1024 * 1024:
                raise ValueError(
                    "A sample page is larger than 8 MB. Define fields manually or use a smaller source sample."
                )
            content = path.read_bytes()
        except OSError:
            raise ValueError(
                "A retained sample page is missing or unreadable. Restore the source or define fields manually."
            ) from None
        parser = PageText()
        parser.feed(content.decode("utf-8", errors="replace"))
        text = "\n".join(parser.parts)[:12000]
        if not text:
            raise ValueError(
                "A sample has no readable text. Define fields manually or collect another page."
            )
        metadata = json.loads(capture["metadata"])
        input_rows = json.loads(capture["input_rows"])
        if len(capture["input_rows"].encode("utf-8")) > 64000:
            raise ValueError(
                "A page has more than 64 KB of spreadsheet context. Keep the originals and consolidate the spreadsheet before requesting AI assistance."
            )
        samples.append(
            {
                "input_rows": input_rows,
                "capture_id": capture["id"],
                "source_url": capture["url"][:2000],
                "title": str(metadata.get("title", ""))[:300],
                "text": text,
                "source_sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    if not samples:
        raise ValueError(
            "Collect at least one page before requesting suggested fields. Around five pages makes a better sample."
        )
    return samples


def prepare_request(root, collection_id, revision, provider):
    provider.settings.validate()
    draft = get_draft(root, collection_id)
    if draft["accepted_at"] or draft["revision"] != revision:
        raise SchemaConflict(
            "These fields were accepted or changed. Reload before requesting a suggestion."
        )
    payload = {"guidance": draft["guidance"], "samples": sample_pages(root, collection_id)}
    request_id = uuid4().hex
    with connect(root) as db:
        db.execute(
            "INSERT INTO schema_requests(id,collection_id,revision,provider,payload,status) VALUES(?,?,?,?,?,'preview')",
            (
                request_id,
                collection_id,
                revision,
                json.dumps(provider.settings.identity),
                json.dumps(payload, ensure_ascii=False),
            ),
        )
    return request_id


def get_request(root, collection_id, request_id):
    with connect(root) as db:
        row = db.execute(
            "SELECT * FROM schema_requests WHERE id=? AND collection_id=?",
            (request_id, collection_id),
        ).fetchone()
    if not row:
        raise LookupError("Suggestion preview not found")
    result = dict(row)
    for name in ("provider", "payload", "result"):
        result[name] = json.loads(result[name]) if result[name] is not None else None
    return result


async def send_request(root, collection_id, request_id, provider):
    request = get_request(root, collection_id, request_id)
    if request["provider"] != provider.settings.identity:
        raise SchemaConflict(
            "The provider settings changed. Preview the sample again before consenting."
        )
    with connect(root) as db:
        db.execute("BEGIN IMMEDIATE")
        draft = db.execute(
            "SELECT * FROM collection_schemas WHERE collection_id=?", (collection_id,)
        ).fetchone()
        if draft["accepted_at"] or draft["revision"] != request["revision"]:
            raise SchemaConflict(
                "The field list or guidance changed. Preview the sample again before consenting."
            )
        if not db.execute(
            "UPDATE schema_requests SET status='sending', consent_at=?,error=NULL WHERE id=? AND status IN ('preview','failed')",
            (now(), request_id),
        ).rowcount:
            raise SchemaConflict("This suggestion was already requested. Reload to see its result.")
    try:
        result = await provider.suggest(request["payload"])
        if not isinstance(result, dict) or set(result) != {"fields"}:
            raise ValueError("The provider did not return a valid field list.")
        validate_fields(result["fields"])
    except Exception as exc:
        # Do not retain raw provider responses, exception details, headers or credentials.
        from muster.provider import SuggestionError

        message = (
            str(exc)
            if isinstance(exc, (SuggestionError, ValueError))
            else "The suggestion failed. Check the provider and try again; your saved fields are unchanged."
        )
        with connect(root) as db:
            db.execute(
                "UPDATE schema_requests SET status='failed',error=? WHERE id=?",
                (message, request_id),
            )
        return
    with connect(root) as db:
        db.execute("BEGIN IMMEDIATE")
        current = db.execute(
            "SELECT * FROM collection_schemas WHERE collection_id=?", (collection_id,)
        ).fetchone()
        stale = current["accepted_at"] or current["revision"] != request["revision"]
        db.execute(
            "UPDATE schema_requests SET status=?,result=?,error=? WHERE id=?",
            (
                "discarded" if stale else "suggested",
                json.dumps(result, ensure_ascii=False),
                "Your fields changed while the suggestion was being prepared. The result was not applied."
                if stale
                else None,
                request_id,
            ),
        )


def apply_suggestion(root, collection_id, request_id):
    request = get_request(root, collection_id, request_id)
    if request["status"] != "suggested":
        raise SchemaConflict("This suggestion is not ready to use.")
    draft = get_draft(root, collection_id)
    return save_draft(
        root,
        collection_id,
        request["revision"],
        request["result"]["fields"],
        draft["guidance"],
        proposal_id=request_id,
    )


def accept_schema(root, collection_id, revision):
    draft = get_draft(root, collection_id)
    validate_fields(draft["fields"])
    schema_id = uuid4().hex
    types = {
        "text": "string",
        "number": "number",
        "integer": "integer",
        "boolean": "boolean",
        "date": "string",
        "text_list": "array",
    }
    properties = {}
    for field in draft["fields"]:
        definition = {
            "type": [types[field["type"]], "null"],
            "title": field["label"],
            "description": field["description"],
        }
        if field["type"] == "date":
            definition["format"] = "date"
        if field["type"] == "text_list":
            definition["items"] = {"type": "string"}
        properties[field["key"]] = definition
    contract = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"urn:muster:schema:{schema_id}",
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
        "x-muster-guidance": draft["guidance"],
    }
    Draft202012Validator.check_schema(contract)
    with connect(root) as db:
        if not db.execute(
            "UPDATE collection_schemas SET schema_id=?, accepted_json=?,accepted_at=?,revision=revision+1 WHERE collection_id=? AND revision=? AND accepted_at IS NULL",
            (schema_id, json.dumps(contract, ensure_ascii=False), now(), collection_id, revision),
        ).rowcount:
            raise SchemaConflict(
                "These fields were already accepted or changed. Reload before making changes."
            )
    return schema_id


def validate_record(root, collection_id, values):
    """All extraction callers must use this accepted, collection-bound contract."""
    draft = get_draft(root, collection_id)
    if not draft["accepted_at"]:
        raise ValueError("Accept the collection's fields before extracting examples.")
    try:
        json.dumps(values, allow_nan=False)
    except (ValueError, TypeError):
        raise ValueError("Extracted values must be ordinary values with finite numbers.") from None
    validator = Draft202012Validator(
        json.loads(draft["accepted_json"]), format_checker=FormatChecker()
    )
    errors = list(validator.iter_errors(values))
    if errors:
        error = errors[0]
        field = ".".join(str(part) for part in error.absolute_path) or "example"
        raise ValueError(
            f"Check {field}: the extracted value does not match the accepted fields. Use unknown for missing information."
        )
    return draft["schema_id"]
