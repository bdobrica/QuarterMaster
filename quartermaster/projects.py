from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from quartermaster.contracts.project import Project, ProjectCreate
from quartermaster.db import connect


def create_project(database: Path, draft: ProjectCreate) -> Project:
    project = Project(id=uuid4(), created_at=datetime.now(UTC), **draft.model_dump())
    with connect(database) as connection:
        connection.execute(
            "INSERT INTO projects (id, name, mission, created_at) VALUES (?, ?, ?, ?)",
            (str(project.id), project.name, project.mission, project.created_at.isoformat()),
        )
    return project


def list_projects(database: Path) -> list[Project]:
    with connect(database) as connection:
        rows = connection.execute("SELECT * FROM projects ORDER BY created_at DESC, id").fetchall()
    return [Project.from_row(row) for row in rows]
