"""Deliberate, sequential SQLite migrations. No automatic downgrade or reset."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 1


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
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        check_schema(connection)
    with connect(path) as connection:
        connection.execute("PRAGMA journal_mode = WAL")
