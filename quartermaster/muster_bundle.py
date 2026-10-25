"""Read the public muster.bundle/1 directory contract. Never import or run Muster code."""

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path, PurePosixPath

from quartermaster.errors import DomainError

MAX_FILES = 20_000
MAX_BYTES = 2 * 1024**3
MAX_TEXT = 8 * 1024**2


def invalid():
    return DomainError(
        "MUSTER_BUNDLE: Cannot verify this publication. Restore it or publish a new version "
        "in Muster. Only bundle format 1 and its documented field types are supported."
    )


def relative(name):
    if not isinstance(name, str) or not name or len(name) > 500:
        raise invalid()
    path = PurePosixPath(name)
    if (
        path.is_absolute()
        or any(part in {"", ".", ".."} for part in name.split("/"))
        or "\\" in name
        or ":" in name
        or any(ord(c) < 32 for c in name)
    ):
        raise invalid()
    return path


def controlled(path):
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise invalid()
    return path


def read_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise invalid()
            result[key] = value
        return result

    return json.loads(
        raw,
        object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(invalid()),
    )


def sha_file(path):
    controlled(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024**2), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_schema(schema, schema_id):
    # Muster's public format-1 subset. Fail closed instead of partially interpreting
    # a future JSON Schema feature (notably references or remote resolution).
    allowed = {
        "$schema",
        "$id",
        "type",
        "properties",
        "required",
        "additionalProperties",
        "x-muster-guidance",
    }
    properties = schema["properties"]
    if (
        set(schema) - allowed
        or schema["$id"] != "urn:muster:schema:" + schema_id
        or schema["$schema"] != "https://json-schema.org/draft/2020-12/schema"
        or schema["type"] != "object"
        or schema["additionalProperties"] is not False
        or not 1 <= len(properties) <= 30
        or set(schema["required"]) != set(properties)
        or len(schema["required"]) != len(properties)
    ):
        raise invalid()
    for key, field in properties.items():
        if not isinstance(key, str) or not 1 <= len(key) <= 200:
            raise invalid()
        if set(field) - {"type", "title", "description", "format", "items"}:
            raise invalid()
        kinds = field["type"]
        if not isinstance(kinds, list) or len(kinds) != 2 or kinds.count("null") != 1:
            raise invalid()
        kind = next(k for k in kinds if k != "null")
        if kind not in {"string", "number", "integer", "boolean", "array"}:
            raise invalid()
        if "format" in field and (kind != "string" or field["format"] != "date"):
            raise invalid()
        if kind == "array":
            if field.get("items") != {"type": "string"}:
                raise invalid()
        elif "items" in field:
            raise invalid()
    return properties


def validate_values(properties, values):
    if not isinstance(values, dict) or set(values) != set(properties):
        raise invalid()
    for key, field in properties.items():
        value = values[key]
        if value is None:
            continue
        kind = next(k for k in field["type"] if k != "null")
        numeric = type(value) in {int, float} and math.isfinite(value)
        valid = {
            "string": isinstance(value, str),
            "number": numeric,
            "integer": numeric and int(value) == value,
            "boolean": type(value) is bool,
            "array": isinstance(value, list) and all(isinstance(v, str) for v in value),
        }[kind]
        if not valid:
            raise invalid()
        if field.get("format") == "date" and date.fromisoformat(value).isoformat() != value:
            raise invalid()


@dataclass(frozen=True)
class Bundle:
    root: Path
    digest: str
    manifest: dict
    schema: dict
    examples: list[dict]

    def text(self, name):
        path = controlled(self.root / str(relative(name)))
        if path.stat().st_size > MAX_TEXT:
            raise invalid()
        raw = path.read_bytes()
        expected = self.manifest.get("checksums", {}).get(name)
        if expected is not None and hashlib.sha256(raw).hexdigest() != expected:
            raise invalid()
        return raw.decode("utf-8")


def load_bundle(folder):
    try:
        return _load_bundle(Path(folder).absolute())
    except DomainError:
        raise
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        OverflowError,
        RecursionError,
    ):
        raise invalid() from None


def _load_bundle(root):
    controlled(root)
    files = set()
    total = 0
    for path in root.rglob("*"):
        controlled(path)
        if path.is_dir():
            continue
        if not path.is_file():
            raise invalid()
        files.add(str(relative(path.relative_to(root).as_posix())))
        total += path.stat().st_size
        if len(files) > MAX_FILES or total > MAX_BYTES:
            raise invalid()
    bundle = Bundle(root, sha_file(root / "manifest.json"), {}, {}, [])
    manifest = read_json(bundle.text("manifest.json"))
    if manifest["format"] != "muster.bundle" or type(manifest["format_version"]) is not int:
        raise invalid()
    if manifest["format_version"] != 1:
        raise invalid()
    if (
        type(manifest["version"]) is not int
        or manifest["version"] < 1
        or type(manifest["collection"]["id"]) is not int
        or not isinstance(manifest["collection"]["name"], str)
        or not isinstance(manifest["schema_id"], str)
    ):
        raise invalid()
    if datetime.fromisoformat(manifest["created_at"].replace("Z", "+00:00")).utcoffset() is None:
        raise invalid()
    checksums = manifest["checksums"]
    if files != {"manifest.json", *checksums}:
        raise invalid()
    for name, digest in checksums.items():
        if (
            not isinstance(digest, str)
            or not re.fullmatch("[a-f0-9]{64}", digest)
            or sha_file(root / str(relative(name))) != digest
        ):
            raise invalid()

    def ref(name):
        relative(name)
        if name not in checksums:
            raise invalid()

    for name in [
        *manifest["references"],
        manifest["schema"],
        manifest["examples"],
        manifest["decisions"],
    ]:
        ref(name)
    schema = read_json(bundle.text(manifest["schema"]))
    properties = validate_schema(schema, manifest["schema_id"])
    records = [
        read_json(line) for line in bundle.text(manifest["examples"]).splitlines() if line.strip()
    ]
    if len(records) != manifest["counts"]["examples"] or len({r["id"] for r in records}) != len(
        records
    ):
        raise invalid()
    sources = {source["id"]: source for source in manifest["sources"]}
    if len(sources) != len(manifest["sources"]):
        raise invalid()
    for source in sources.values():
        for name in source["files"]:
            ref(name)
    for record in records:
        if (
            not isinstance(record["id"], str)
            or not record["id"]
            or record["schema_id"] != manifest["schema_id"]
            or record.get("review_status", "reviewed") not in {"reviewed", "unreviewed"}
            or not isinstance(record["notes"], str)
        ):
            raise invalid()
        validate_values(properties, record["values"])
        source = sources[record["source"]["capture_id"]]
        page = record["source"]["path"] + "/page.html"
        ref(page)
        if page not in source["files"] or str(source["job_id"]) != record["id"]:
            raise invalid()
        ref(record["provenance"])
        read_json(bundle.text(record["provenance"]))
        for refs in record["evidence"].values():
            for evidence in refs:
                if evidence["source"] == "image":
                    image = record["source"]["path"] + "/" + str(relative(evidence["file"]))
                    ref(image)
                    if image not in source["files"]:
                        raise invalid()
        if not isinstance(record["uncertainty"], dict):
            raise invalid()
    if sum(r.get("review_status", "reviewed") == "unreviewed" for r in records) != manifest[
        "counts"
    ].get("unreviewed", 0):
        raise invalid()
    articles = manifest["knowledge"]
    if len(articles) != manifest["counts"]["articles"] or len({a["id"] for a in articles}) != len(
        articles
    ):
        raise invalid()
    for article in articles:
        for key in ("path", "provenance"):
            ref(article[key])
        body = bundle.text(article["path"])
        history = read_json(bundle.text(article["provenance"]))
        if (
            not isinstance(article["title"], str)
            or not article["title"].strip()
            or not history
            or history[-1]["revision"] != article["revision"]
            or history[-1]["body"].replace("\r\n", "\n") != body.replace("\r\n", "\n")
        ):
            raise invalid()
    decisions = read_json(bundle.text(manifest["decisions"]))
    if len(decisions["excluded"]) != manifest["counts"]["excluded"]:
        raise invalid()
    return Bundle(root, bundle.digest, manifest, schema, records)
