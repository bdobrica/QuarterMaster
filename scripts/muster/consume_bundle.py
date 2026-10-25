"""Reference consumer adapter using only the standard library and bundle contract.

Copy this file and check_bundle.py beside a publication; Muster is not required.
Print portable JSON for a future QuarterMaster importer, without executing source content.
"""

import argparse
import json
import math
from datetime import date
from pathlib import Path

from check_bundle import check


def validate_values(schema, values):
    """Validate the deliberately small field schema emitted by Muster format 1.

    This is not a general JSON Schema implementation. Unknown schema features fail
    closed; a production consumer can use a JSON Schema 2020-12 library instead.
    """
    allowed = {
        "$schema",
        "$id",
        "type",
        "properties",
        "required",
        "additionalProperties",
        "x-muster-guidance",
    }
    if set(schema) - allowed:
        raise ValueError("Unsupported schema feature; use a full JSON Schema 2020-12 validator.")
    properties = schema.get("properties", {})
    if (
        schema.get("type") != "object"
        or schema.get("additionalProperties") is not False
        or set(schema.get("required", [])) != set(properties)
        or not isinstance(values, dict)
        or set(values) != set(properties)
    ):
        raise ValueError("Values do not match the accepted field keys.")
    supported = {"type", "title", "description", "format", "items"}
    for key, definition in properties.items():
        if set(definition) - supported:
            raise ValueError(
                "Unsupported schema feature; use a full JSON Schema 2020-12 validator."
            )
        types = definition.get("type")
        if not isinstance(types, list) or len(types) != 2 or types.count("null") != 1:
            raise ValueError("Unsupported field schema.")
        kind = next(kind for kind in types if kind != "null")
        if kind not in ("string", "number", "integer", "boolean", "array"):
            raise ValueError("Unsupported field type.")
        if definition.get("format") not in (None, "date"):
            raise ValueError("Unsupported field format.")
        if kind == "array" and definition.get("items") != {"type": "string"}:
            raise ValueError("Unsupported list item schema.")
        value = values[key]
        if value is None:
            continue
        if kind == "string":
            valid = isinstance(value, str)
        elif kind == "number":
            valid = type(value) is int or (type(value) is float and math.isfinite(value))
        elif kind == "integer":
            valid = type(value) is int or (
                type(value) is float and math.isfinite(value) and value.is_integer()
            )
        elif kind == "boolean":
            valid = type(value) is bool
        else:
            valid = isinstance(value, list) and all(isinstance(item, str) for item in value)
        if not valid:
            raise ValueError(f"Invalid value for field {key}.")
        if definition.get("format") == "date":
            if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
                raise ValueError(f"Invalid date for field {key}.")


def consume(folder, include_unreviewed=False):
    root = Path(folder).resolve()
    manifest = check(root)
    schema = json.loads((root / manifest["schema"]).read_text(encoding="utf-8"))
    records = [
        json.loads(line)
        for line in (root / manifest["examples"]).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    examples = []
    sources = {item["id"]: item for item in manifest["sources"]}
    for record in records:
        validate_values(schema, record["values"])
        source = sources[record["source"]["capture_id"]]
        if record["source"]["path"] + "/page.html" not in source["files"]:
            raise ValueError("Record source path does not belong to its capture.")
        status = record.get("review_status", "reviewed")
        if status == "unreviewed" and not include_unreviewed:
            continue
        examples.append(
            {
                "id": record["id"],
                "review_status": status,
                "values": record["values"],
                "notes": record["notes"],
                "source": record["source"],
                "evidence": record["evidence"],
                "uncertainty": record["uncertainty"],
                "provenance": record["provenance"],
            }
        )
    knowledge = [
        {
            "id": item["id"],
            "title": item["title"],
            "revision": item["revision"],
            "body": (root / item["path"]).read_text(encoding="utf-8"),
            "provenance": item["provenance"],
        }
        for item in manifest["knowledge"]
    ]
    return {
        "format": "muster.consumer-preview",
        "format_version": 1,
        "collection": manifest["collection"],
        "publication_version": manifest["version"],
        "schema_id": manifest["schema_id"],
        "schema": schema,
        "examples": examples,
        "knowledge": knowledge,
        "skipped_unreviewed": len(records) - len(examples),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Verify and read a Muster bundle without Muster installed."
    )
    parser.add_argument("folder", type=Path)
    parser.add_argument(
        "--include-unreviewed",
        action="store_true",
        help="Include explicitly labeled unreviewed examples; default imports reviewed examples only.",
    )
    args = parser.parse_args()
    try:
        result = consume(args.folder, args.include_unreviewed)
    except (OSError, ValueError, KeyError, TypeError, OverflowError) as exc:
        parser.exit(1, f"Cannot consume bundle: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))


if __name__ == "__main__":
    main()
