"""Deliberate, sequential SQLite migrations. No automatic downgrade or reset."""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

from quartermaster.contracts.adviser import AdviserSpec

SCHEMA_VERSION = 5


class SchemaError(RuntimeError):
    """A safe, actionable database startup failure."""


@contextmanager
def connect(path: Path):
    connection = sqlite3.connect(path, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def check_schema(connection: sqlite3.Connection) -> None:
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version != SCHEMA_VERSION:
        raise SchemaError("DB_VERSION: Use a compatible QuarterMaster version; back up data first.")
    columns = {row[1] for row in connection.execute("PRAGMA table_info(projects)")}
    if columns != {"id", "name", "mission", "created_at"}:
        raise SchemaError("DB_SCHEMA: Restore a valid backup; the projects schema is incompatible.")
    required = {
        "adviser_revisions": {"project_id", "revision", "document"},
        "sources": {"id", "project_id", "document"},
        "case_mappings": {"id", "project_id", "document", "created_at"},
        "derived_cases": {"id", "mapping_id", "document"},
        "knowledge_revisions": {"id", "project_id", "document"},
        "knowledge_members": {"revision_id", "source_id"},
        "chunks": {"id", "source_id", "project_id", "document"},
        "chunks_fts": {"citation_id", "text"},
        "interview_revisions": {"project_id", "revision", "document"},
        "test_runs": {"id", "project_id", "document"},
        "feedback": {"id", "project_id", "document"},
        "lesson_revisions": {"id", "project_id", "revision", "document"},
        "evaluation_suites": {"id", "project_id", "revision", "document"},
        "evaluation_runs": {"id", "project_id", "revision", "document"},
        "evaluation_ratings": {"run_id", "case_id", "revision", "document"},
        "evaluation_holdouts": {"project_id", "case_id", "case_sha256", "test_id"},
    }
    for table, expected in required.items():
        actual = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        if actual != expected:
            raise SchemaError(
                "DB_SCHEMA: Restore a valid backup; a metadata table is incompatible."
            )


def migrate(path: Path) -> None:
    with connect(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            tables = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            if tables:
                raise SchemaError("DB_UNVERSIONED: Back up and inspect this existing database.")
            connection.execute(
                "CREATE TABLE projects (id TEXT PRIMARY KEY, name TEXT NOT NULL, "
                "mission TEXT NOT NULL, created_at TEXT NOT NULL)"
            )
            version = 1
        if version == 1:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(projects)")}
            if columns != {"id", "name", "mission", "created_at"}:
                raise SchemaError("DB_SCHEMA: Restore a valid projects backup before migrating.")
            statements = [
                "CREATE TABLE adviser_revisions (project_id TEXT REFERENCES projects(id), "
                "revision INTEGER, document TEXT NOT NULL, PRIMARY KEY(project_id, revision))",
                "CREATE TABLE sources (id TEXT PRIMARY KEY, "
                "project_id TEXT NOT NULL REFERENCES projects(id), document TEXT NOT NULL)",
                "CREATE TABLE case_mappings (id TEXT PRIMARY KEY, "
                "project_id TEXT NOT NULL REFERENCES projects(id), document TEXT NOT NULL, "
                "created_at TEXT NOT NULL)",
                "CREATE TABLE derived_cases (id TEXT PRIMARY KEY, "
                "mapping_id TEXT NOT NULL REFERENCES case_mappings(id), document TEXT NOT NULL)",
                "CREATE TABLE knowledge_revisions (id TEXT PRIMARY KEY, "
                "project_id TEXT NOT NULL REFERENCES projects(id), document TEXT NOT NULL)",
                "CREATE TABLE knowledge_members "
                "(revision_id TEXT REFERENCES knowledge_revisions(id),"
                " source_id TEXT REFERENCES sources(id), PRIMARY KEY(revision_id, source_id))",
                "CREATE TABLE chunks (id TEXT PRIMARY KEY, source_id TEXT REFERENCES sources(id), "
                "project_id TEXT REFERENCES projects(id), document TEXT NOT NULL)",
                "CREATE VIRTUAL TABLE chunks_fts USING fts5(citation_id UNINDEXED, text)",
            ]
            for statement in statements:
                connection.execute(statement)
            for row in connection.execute("SELECT * FROM projects").fetchall():
                spec = AdviserSpec.model_validate_json(json.dumps({**dict(row), "revision": 1}))
                connection.execute(
                    "INSERT INTO adviser_revisions VALUES (?, 1, ?)",
                    (str(UUID(row["id"])), spec.model_dump_json()),
                )
            connection.execute("PRAGMA user_version = 2")
            version = 2
        if version == 2:
            connection.execute(
                "CREATE TABLE interview_revisions (project_id TEXT REFERENCES projects(id), "
                "revision INTEGER, document TEXT NOT NULL, PRIMARY KEY(project_id, revision))"
            )
            connection.execute("PRAGMA user_version = 3")
            version = 3
        if version == 3:
            for table in ("test_runs", "feedback"):
                connection.execute(
                    f"CREATE TABLE {table} (id TEXT PRIMARY KEY, "
                    "project_id TEXT NOT NULL REFERENCES projects(id), document TEXT NOT NULL)"
                )
            connection.execute(
                "CREATE TABLE lesson_revisions (id TEXT, project_id TEXT REFERENCES projects(id), "
                "revision INTEGER, document TEXT NOT NULL, PRIMARY KEY(id, revision))"
            )
            connection.execute("PRAGMA user_version = 4")
            version = 4
        if version == 4:
            for table in ("evaluation_suites", "evaluation_runs"):
                connection.execute(
                    f"CREATE TABLE {table} (id TEXT, project_id TEXT REFERENCES projects(id), "
                    "revision INTEGER, document TEXT NOT NULL, PRIMARY KEY(id, revision))"
                )
            connection.execute(
                "CREATE TABLE evaluation_ratings (run_id TEXT, case_id TEXT, revision INTEGER, "
                "document TEXT NOT NULL, PRIMARY KEY(run_id, case_id, revision))"
            )
            connection.execute(
                "CREATE TABLE evaluation_holdouts (project_id TEXT REFERENCES projects(id), "
                "case_id TEXT NOT NULL, case_sha256 TEXT NOT NULL, test_id TEXT NOT NULL, "
                "PRIMARY KEY(project_id, case_sha256))"
            )
            connection.execute("PRAGMA user_version = 5")
        check_schema(connection)
    with connect(path) as connection:
        connection.execute("PRAGMA journal_mode = WAL")
