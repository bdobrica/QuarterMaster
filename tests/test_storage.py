import sqlite3

import pytest
from fastapi.testclient import TestClient

from quartermaster.app import create_app
from quartermaster.config import initialize_storage
from quartermaster.db import SCHEMA_VERSION, SchemaError, connect, migrate


def test_migration_is_idempotent_and_uses_wal(settings):
    initialize_storage(settings)
    migrate(settings.database_path)
    migrate(settings.database_path)
    assert settings.artifact_root.is_dir()
    with connect(settings.database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1


@pytest.mark.parametrize("version", [3, 999])
def test_newer_schema_fails_without_downgrading(settings, version):
    initialize_storage(settings)
    with connect(settings.database_path) as connection:
        connection.execute(f"PRAGMA user_version = {version}")
    with pytest.raises(SchemaError, match="DB_VERSION"):
        migrate(settings.database_path)
    with connect(settings.database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == version


def test_unversioned_existing_database_is_not_overwritten(settings):
    initialize_storage(settings)
    with connect(settings.database_path) as connection:
        connection.execute("CREATE TABLE owner_data (value TEXT)")
        connection.execute("INSERT INTO owner_data VALUES ('keep')")
    with pytest.raises(SchemaError, match="DB_UNVERSIONED"):
        migrate(settings.database_path)
    with connect(settings.database_path) as connection:
        assert connection.execute("SELECT value FROM owner_data").fetchone()[0] == "keep"
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0


def test_mismatched_schema_is_rejected(settings):
    initialize_storage(settings)
    with connect(settings.database_path) as connection:
        connection.execute("CREATE TABLE projects (id TEXT)")
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    with pytest.raises(SchemaError, match="DB_SCHEMA"):
        migrate(settings.database_path)


def test_transactions_roll_back(settings):
    initialize_storage(settings)
    migrate(settings.database_path)
    with pytest.raises(sqlite3.OperationalError), connect(settings.database_path) as connection:
        connection.execute("INSERT INTO projects VALUES ('id', 'name', 'mission', 'time')")
        connection.execute("INSERT INTO nonexistent VALUES ('fail')")
    with connect(settings.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 0


def test_invalid_storage_path_has_safe_startup_error(settings):
    settings.data_dir.write_text("not a directory")
    with pytest.raises(RuntimeError, match="STORAGE_INIT"), TestClient(create_app(settings)):
        pass


def test_corrupt_database_has_safe_startup_error(settings):
    initialize_storage(settings)
    settings.database_path.write_bytes(b"synthetic corrupt database")
    with pytest.raises(RuntimeError, match="STORAGE_INIT"), TestClient(create_app(settings)):
        pass
    assert settings.database_path.read_bytes() == b"synthetic corrupt database"


def test_newer_database_fails_application_startup(settings):
    initialize_storage(settings)
    with connect(settings.database_path) as connection:
        connection.execute("PRAGMA user_version = 999")
    with pytest.raises(RuntimeError, match="DB_VERSION"), TestClient(create_app(settings)):
        pass


def test_health_fails_if_schema_changes(client, settings, caplog):
    with connect(settings.database_path) as connection:
        connection.execute("PRAGMA user_version = 999")
    response = client.get("/healthz")
    assert response.status_code == 503
    assert "STORAGE_UNAVAILABLE" in response.text
    assert "STORAGE_UNAVAILABLE" in caplog.text


def test_health_fails_if_artifact_root_disappears(client, settings):
    settings.artifact_root.rmdir()
    assert client.get("/healthz").status_code == 503


def test_v1_migration_preserves_projects_and_initial_mission(settings):
    from uuid import uuid4

    from quartermaster.projects import adviser_history, get_adviser

    initialize_storage(settings)
    project_id = str(uuid4())
    with connect(settings.database_path) as connection:
        connection.execute(
            "CREATE TABLE projects (id TEXT PRIMARY KEY, name TEXT NOT NULL, "
            "mission TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        connection.execute("PRAGMA user_version = 1")
        connection.execute(
            "INSERT INTO projects VALUES (?, ?, ?, ?)",
            (project_id, "Existing adviser", "Keep this mission", "2026-01-01T12:00:00+00:00"),
        )
    migrate(settings.database_path)
    spec = get_adviser(settings.database_path, project_id)
    assert str(spec.id) == project_id
    assert spec.mission == "Keep this mission"
    assert spec.created_at.isoformat() == "2026-01-01T12:00:00+00:00"
    assert spec.revision == 1
    migrate(settings.database_path)
    assert adviser_history(settings.database_path, project_id) == [spec]


def test_failed_v1_migration_rolls_back_all_new_tables(settings):
    initialize_storage(settings)
    with connect(settings.database_path) as connection:
        connection.execute(
            "CREATE TABLE projects (id TEXT PRIMARY KEY, name TEXT NOT NULL, "
            "mission TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        connection.execute("PRAGMA user_version = 1")
        connection.execute(
            "INSERT INTO projects VALUES ('not-a-uuid', 'keep', 'mission', 'bad-time')"
        )
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        migrate(settings.database_path)
    with connect(settings.database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert connection.execute("SELECT name FROM projects").fetchone()[0] == "keep"
        tables = {
            r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert tables == {"projects"}
