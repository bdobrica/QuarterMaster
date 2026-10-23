"""Immutable local originals and project-scoped source metadata."""

import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from quartermaster.config import Settings
from quartermaster.contracts.sources import Label, ParseOptions, Source
from quartermaster.db import connect
from quartermaster.errors import DomainError
from quartermaster.ingestion import Parsed, markdown_sections, parse, preview, safe_name
from quartermaster.projects import read_spec


def blob_path(root: Path, sha256: str) -> Path:
    # Hash comes from a validated Source or hashlib, never a filename/URL parameter.
    return root / "sources" / sha256[:2] / sha256


def read_source(connection, project_id, source_id) -> Source:
    row = connection.execute(
        "SELECT document FROM sources WHERE project_id=? AND id=?",
        (str(project_id), str(source_id)),
    ).fetchone()
    if row is None:
        raise DomainError("SOURCE_MISSING: Choose a source uploaded to this project.", 404)
    return Source.model_validate_json(row["document"])


def source_bytes(settings: Settings, source: Source) -> bytes:
    path = blob_path(settings.artifact_root, source.sha256)
    try:
        if path.is_symlink() or path.stat().st_size != source.size_bytes:
            raise OSError
        data = path.read_bytes()
    except OSError:
        raise DomainError(
            "SOURCE_UNAVAILABLE: Restore the original file from your backup.", 503
        ) from None
    if hashlib.sha256(data).hexdigest() != source.sha256:
        raise DomainError("SOURCE_HASH: Restore the unchanged original file from your backup.", 503)
    return data


def parsed_source(settings: Settings, source: Source) -> Parsed:
    return parse(source_bytes(settings, source), source.kind, source.options)


def list_sources(settings: Settings, project_id) -> list[Source]:
    with connect(settings.database_path) as connection:
        read_spec(connection, project_id)
        rows = connection.execute(
            "SELECT document FROM sources WHERE project_id=? ORDER BY rowid", (str(project_id),)
        ).fetchall()
    return [Source.model_validate_json(row["document"]) for row in rows]


def get_source(settings: Settings, project_id, source_id) -> Source:
    with connect(settings.database_path) as connection:
        read_spec(connection, project_id)
        return read_source(connection, project_id, source_id)


def upload_source(
    settings: Settings, project_id, filename: str, data: bytes, label: Label, options: ParseOptions
) -> Source:
    with connect(settings.database_path) as connection:
        read_spec(connection, project_id)
    name, kind = safe_name(filename)
    parsed = parse(data, kind, options)
    source = Source(
        id=uuid4(),
        project_id=project_id,
        created_at=datetime.now(UTC),
        display_name=name,
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
        kind=kind,
        label=label,
        options=options,
        sheets=[preview(t) for t in parsed.tables],
        markdown_headings=[h for _, h in markdown_sections(parsed.markdown) if h]
        if parsed.markdown is not None
        else [],
    )
    path = blob_path(settings.artifact_root, source.sha256)
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            with path.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            path.chmod(0o400)
        except FileExistsError:
            # Content-addressed deduplication must never overwrite existing bytes.
            source_bytes(settings, source)
        with connect(settings.database_path) as connection:
            connection.execute(
                "INSERT INTO sources VALUES (?, ?, ?)",
                (str(source.id), str(project_id), source.model_dump_json()),
            )
    except OSError:
        raise DomainError(
            "SOURCE_STORAGE: Check free disk space and data-directory permissions.", 503
        ) from None
    return source
