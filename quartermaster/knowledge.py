"""Immutable knowledge selections and a rebuildable, project-scoped FTS5 projection."""

import bisect
import hashlib
import re
from datetime import UTC, datetime
from uuid import uuid4

from quartermaster.config import Settings
from quartermaster.contracts.sources import Chunk, KnowledgeRevision, KnowledgeSelection
from quartermaster.db import connect
from quartermaster.errors import DomainError
from quartermaster.ingestion import chunk_markdown, decode, newline_positions
from quartermaster.projects import append_spec, read_spec
from quartermaster.sources import read_source, source_bytes

MAX_KNOWLEDGE_BYTES = 16 * 1024 * 1024
MAX_KNOWLEDGE_CHUNKS = 10_000


def read_revision(connection, project_id, revision_id=None) -> KnowledgeRevision | None:
    if revision_id is None:
        row = connection.execute(
            "SELECT document FROM knowledge_revisions WHERE project_id=? "
            "ORDER BY rowid DESC LIMIT 1",
            (str(project_id),),
        ).fetchone()
    else:
        row = connection.execute(
            "SELECT document FROM knowledge_revisions WHERE project_id=? AND id=?",
            (str(project_id), str(revision_id)),
        ).fetchone()
        if row is None:
            raise DomainError(
                "KNOWLEDGE_MISSING: Choose a knowledge revision from this project.", 404
            )
    return KnowledgeRevision.model_validate_json(row["document"]) if row else None


def current_knowledge(settings: Settings, project_id):
    with connect(settings.database_path) as connection:
        read_spec(connection, project_id)
        return read_revision(connection, project_id)


def knowledge_history(settings: Settings, project_id):
    with connect(settings.database_path) as connection:
        read_spec(connection, project_id)
        rows = connection.execute(
            "SELECT document FROM knowledge_revisions WHERE project_id=? ORDER BY rowid DESC",
            (str(project_id),),
        ).fetchall()
    return [KnowledgeRevision.model_validate_json(row["document"]) for row in rows]


def revise_knowledge(
    settings: Settings, project_id, selection: KnowledgeSelection
) -> KnowledgeRevision:
    with connect(settings.database_path) as connection:
        read_spec(connection, project_id)
        sources = [read_source(connection, project_id, sid) for sid in selection.source_ids]
    if any(source.label != "knowledge" or source.kind != "md" for source in sources):
        raise DomainError(
            "KNOWLEDGE_KIND: Select Markdown sources labeled knowledge for text retrieval."
        )
    if sum(source.size_bytes for source in sources) > MAX_KNOWLEDGE_BYTES:
        raise DomainError("KNOWLEDGE_SIZE: Select at most 16 MiB of Markdown at a time.")
    chunks = []
    for source in sources:
        text = decode(source_bytes(settings, source), "utf-8-sig")
        chunks.extend(chunk_markdown(source.id, source.sha256, text))
        if len(chunks) > MAX_KNOWLEDGE_CHUNKS:
            raise DomainError(
                "KNOWLEDGE_CHUNKS: Select smaller documents (at most 10,000 excerpts)."
            )
    revision = KnowledgeRevision(
        id=uuid4(),
        project_id=project_id,
        created_at=datetime.now(UTC),
        source_ids=selection.source_ids,
        source_hashes={str(s.id): s.sha256 for s in sources},
    )
    with connect(settings.database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        previous = read_revision(connection, project_id)
        if selection.expected_revision != (previous.id if previous else None):
            raise DomainError(
                "KNOWLEDGE_CHANGED: Reload before changing the selected sources.", 409
            )
        # These are derived records only. Reindexing can replace them; source bytes and
        # prior selections remain unchanged. Stable IDs keep historical citations valid.
        for source in sources:
            ids = [
                row["id"]
                for row in connection.execute(
                    "SELECT id FROM chunks WHERE source_id=?", (str(source.id),)
                )
            ]
            connection.executemany(
                "DELETE FROM chunks_fts WHERE citation_id=?", [(cid,) for cid in ids]
            )
            connection.execute("DELETE FROM chunks WHERE source_id=?", (str(source.id),))
        for chunk in chunks:
            connection.execute(
                "INSERT INTO chunks VALUES (?, ?, ?, ?)",
                (
                    str(chunk.citation_id),
                    str(chunk.source_id),
                    str(project_id),
                    chunk.model_dump_json(),
                ),
            )
            connection.execute(
                "INSERT INTO chunks_fts VALUES (?, ?)", (str(chunk.citation_id), chunk.text)
            )
        connection.execute(
            "INSERT INTO knowledge_revisions VALUES (?, ?, ?)",
            (str(revision.id), str(project_id), revision.model_dump_json()),
        )
        connection.executemany(
            "INSERT INTO knowledge_members VALUES (?, ?)",
            [(str(revision.id), str(source.id)) for source in sources],
        )
        append_spec(connection, read_spec(connection, project_id), knowledge_revision=revision.id)
    return revision


def verify_excerpt(settings: Settings, source, chunk: Chunk):
    text = decode(source_bytes(settings, source), "utf-8-sig")
    newlines = newline_positions(text)
    if (
        chunk.source_sha256 != source.sha256
        or chunk.start < 0
        or chunk.end <= chunk.start
        or text[chunk.start : chunk.end] != chunk.text
        or hashlib.sha256(chunk.text.encode()).hexdigest() != chunk.sha256
        or bisect.bisect_left(newlines, chunk.start) + 1 != chunk.line_start
        or bisect.bisect_left(newlines, chunk.end - 1) + 1 != chunk.line_end
    ):
        raise DomainError("CITATION_INVALID: Reindex this source from its unchanged original.", 503)


def citation(settings: Settings, project_id, citation_id, revision_id=None):
    with connect(settings.database_path) as connection:
        read_spec(connection, project_id)
        revision = read_revision(connection, project_id, revision_id)
        if revision is None:
            raise DomainError("CITATION_MISSING: Select knowledge sources first.", 404)
        row = connection.execute(
            "SELECT chunks.document FROM chunks JOIN knowledge_members ON "
            "knowledge_members.source_id=chunks.source_id "
            "WHERE chunks.id=? AND chunks.project_id=? "
            "AND knowledge_members.revision_id=?",
            (str(citation_id), str(project_id), str(revision.id)),
        ).fetchone()
        if row is None:
            raise DomainError(
                "CITATION_MISSING: This excerpt is not in the selected knowledge revision.", 404
            )
        chunk = Chunk.model_validate_json(row["document"])
        source = read_source(connection, project_id, chunk.source_id)
    verify_excerpt(settings, source, chunk)
    return {"revision_id": revision.id, "source": source, "chunk": chunk}


def search(settings: Settings, project_id, query: str, revision_id=None):
    if len(query) > 200:
        raise DomainError("SEARCH_LENGTH: Use a search of at most 200 characters.")
    terms = re.findall(r"\w+", query, re.UNICODE)[:16]
    with connect(settings.database_path) as connection:
        read_spec(connection, project_id)
        revision = read_revision(connection, project_id, revision_id)
        if not terms or revision is None:
            return []
        # Treat all user input as literal terms, never as the FTS query language.
        match = " OR ".join('"' + term + '"' for term in terms)
        rows = connection.execute(
            "SELECT chunks.id FROM chunks_fts JOIN chunks ON chunks.id=chunks_fts.citation_id "
            "JOIN knowledge_members ON knowledge_members.source_id=chunks.source_id "
            "WHERE chunks_fts MATCH ? AND chunks.project_id=? AND knowledge_members.revision_id=? "
            "ORDER BY bm25(chunks_fts), chunks.id LIMIT 10",
            (match, str(project_id), str(revision.id)),
        ).fetchall()
    return [citation(settings, project_id, row["id"], revision.id) for row in rows]
