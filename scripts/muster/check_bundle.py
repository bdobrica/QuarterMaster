"""Read a Muster bundle with Python's standard library; no running app required.

Usage: python scripts/check_bundle.py /path/to/unpacked/collection-1-v1
Integrity/reference checks only; this does not judge facts or validate field types.
"""

import hashlib
import json
import sys
from pathlib import Path, PurePosixPath


def check(folder):
    root = Path(folder).resolve()

    def file(name):
        part = PurePosixPath(name)
        path = root.joinpath(*part.parts)
        if (
            part.is_absolute()
            or ".." in part.parts
            or "\\" in name
            or not path.resolve().is_relative_to(root)
        ):
            raise ValueError("Invalid file reference")
        return path

    manifest = json.loads(file("manifest.json").read_text(encoding="utf-8"))
    if (manifest["format"], manifest["format_version"]) != ("muster.bundle", 1):
        raise ValueError("Unsupported bundle format")
    checksums = manifest["checksums"]
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    if actual != {"manifest.json", *checksums}:
        raise ValueError("File inventory differs from the manifest")
    for name, expected in checksums.items():
        if hashlib.sha256(file(name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"Checksum mismatch: {name}")

    def reference(name):
        if name not in checksums:
            raise ValueError(f"Missing checksummed reference: {name}")

    for name in manifest["references"]:
        reference(name)
    reference(manifest["schema"])
    reference(manifest["examples"])
    reference(manifest["decisions"])
    schema = json.loads(file(manifest["schema"]).read_text(encoding="utf-8"))
    if schema["$id"] != "urn:muster:schema:" + manifest["schema_id"]:
        raise ValueError("Schema identifier differs")
    records = [
        json.loads(line)
        for line in file(manifest["examples"]).read_text(encoding="utf-8").splitlines()
    ]
    if len(records) != manifest["counts"]["examples"] or len({r["id"] for r in records}) != len(
        records
    ):
        raise ValueError("Example count or identifiers differ")
    statuses = [record.get("review_status", "reviewed") for record in records]
    if any(status not in ("reviewed", "unreviewed") for status in statuses):
        raise ValueError("Invalid example review status.")
    if statuses.count("unreviewed") != manifest["counts"].get("unreviewed", 0):
        raise ValueError("Unreviewed example count differs.")
    sources = {s["id"]: s for s in manifest["sources"]}
    for source in sources.values():
        for name in source["files"]:
            reference(name)
    for record in records:
        reference(record["provenance"])
        reference(record["source"]["path"] + "/page.html")
        if (
            record["source"]["capture_id"] not in sources
            or record["schema_id"] != manifest["schema_id"]
        ):
            raise ValueError("Example source or schema differs")
        for refs in record["evidence"].values():
            for ref in refs:
                if ref["source"] == "image":
                    reference(record["source"]["path"] + "/" + ref["file"])
    if len(manifest["knowledge"]) != manifest["counts"]["articles"]:
        raise ValueError("Knowledge count differs")
    for article in manifest["knowledge"]:
        reference(article["path"])
        reference(article["provenance"])
    decisions = json.loads(file(manifest["decisions"]).read_text(encoding="utf-8"))
    if len(decisions["excluded"]) != manifest["counts"]["excluded"]:
        raise ValueError("Exclusion count differs")
    return manifest


if __name__ == "__main__":
    try:
        manifest = check(sys.argv[1])
    except (IndexError, ValueError, OSError, KeyError) as exc:
        raise SystemExit(f"Cannot verify bundle: {exc}") from exc
    counts = manifest["counts"]
    print(
        f"Verified v{manifest['version']}: {counts['examples']} examples, {counts['articles']} knowledge articles, {counts['excluded']} excluded links."
    )
