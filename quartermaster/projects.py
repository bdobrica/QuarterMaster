from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from quartermaster.contracts.adviser import AdviserSpec, ProjectEdit
from quartermaster.contracts.project import Project, ProjectCreate
from quartermaster.db import connect
from quartermaster.errors import DomainError


def create_project(database: Path, draft: ProjectCreate) -> Project:
    project = Project(
        id=uuid4(), created_at=datetime.now(UTC), name=draft.name, mission=draft.mission
    )
    with connect(database) as connection:
        connection.execute(
            "INSERT INTO projects (id, name, mission, created_at) VALUES (?, ?, ?, ?)",
            (str(project.id), project.name, project.mission, project.created_at.isoformat()),
        )
        spec = AdviserSpec(
            id=project.id, revision=1, created_at=project.created_at, **draft.model_dump()
        )
        connection.execute(
            "INSERT INTO adviser_revisions VALUES (?, ?, ?)",
            (str(project.id), 1, spec.model_dump_json()),
        )
    return project


def list_projects(database: Path) -> list[Project]:
    with connect(database) as connection:
        rows = connection.execute("SELECT * FROM projects ORDER BY created_at DESC, id").fetchall()
    return [Project.from_row(row) for row in rows]


def read_spec(connection, project_id) -> AdviserSpec:
    row = connection.execute(
        "SELECT document FROM adviser_revisions WHERE project_id=? ORDER BY revision DESC LIMIT 1",
        (str(project_id),),
    ).fetchone()
    if row is None:
        raise DomainError("PROJECT_MISSING: Open an existing project from the home page.", 404)
    return AdviserSpec.model_validate_json(row["document"])


def append_spec(connection, previous: AdviserSpec, **changes) -> AdviserSpec:
    # Revalidate rather than model_copy(update=...), which bypasses validation.
    data = previous.model_dump()
    data.update(changes, revision=previous.revision + 1, created_at=datetime.now(UTC))
    spec = AdviserSpec.model_validate(data)
    connection.execute(
        "INSERT INTO adviser_revisions VALUES (?, ?, ?)",
        (str(spec.id), spec.revision, spec.model_dump_json()),
    )
    connection.execute(
        "UPDATE projects SET name=?, mission=? WHERE id=?",
        (spec.name, spec.mission, str(spec.id)),
    )
    return spec


def get_adviser(database: Path, project_id) -> AdviserSpec:
    with connect(database) as connection:
        return read_spec(connection, project_id)


def adviser_history(database: Path, project_id) -> list[AdviserSpec]:
    with connect(database) as connection:
        read_spec(connection, project_id)
        rows = connection.execute(
            "SELECT document FROM adviser_revisions WHERE project_id=? ORDER BY revision",
            (str(project_id),),
        ).fetchall()
    return [AdviserSpec.model_validate_json(row["document"]) for row in rows]


def edit_adviser(database: Path, project_id, draft: ProjectEdit) -> AdviserSpec:
    with connect(database) as connection:
        connection.execute("BEGIN IMMEDIATE")
        previous = read_spec(connection, project_id)
        if draft.expected_revision != previous.revision:
            raise DomainError("PROJECT_CHANGED: Reload the project before saving your edits.", 409)
        return append_spec(connection, previous, **draft.model_dump(exclude={"expected_revision"}))


def edit_advice_engine(settings, project_id, action):
    from quartermaster.contracts.adviser import AdviceConsent
    from quartermaster.inference import hosted_identity

    consent = None
    if action.mode == "hosted":
        endpoint, model = hosted_identity(settings)
        if not action.consent or (action.endpoint, action.model) != (endpoint, model):
            raise DomainError(
                "ADVISER_CONSENT: Review the current provider and approve sending this project's "
                "mission, question, retrieved policy excerpts and approved routines."
            )
        consent = AdviceConsent(endpoint=endpoint, model=model, consented_at=datetime.now(UTC))
    with connect(settings.database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        spec = read_spec(connection, project_id)
        if action.expected_revision != spec.revision:
            raise DomainError("PROJECT_CHANGED: Reload before changing the advice engine.", 409)
        return append_spec(connection, spec, advice_mode=action.mode, advice_consent=consent)


def configure_answer(database, project_id, answer_format, expected_revision):
    with connect(database) as connection:
        connection.execute("BEGIN IMMEDIATE")
        previous = read_spec(connection, project_id)
        if expected_revision != previous.revision:
            raise DomainError("PROJECT_CHANGED: Reload before saving your answer settings.", 409)
        if previous.answer_format == answer_format:
            return previous
        if previous.answer_format is not None or previous.model.adapter_artifact:
            raise DomainError(
                "ANSWER_CONFIGURED: This adviser already has an answer format. "
                "Create another adviser for a different kind of decision.",
                409,
            )
        return append_spec(connection, previous, answer_format=answer_format)


def require_answer_format(spec, answer_format):
    if spec.answer_format is not None and spec.answer_format != answer_format:
        raise DomainError("ANSWER_FORMAT: Use this adviser's saved unit or choices.", 409)


def require_target(spec, target):
    fmt = spec.answer_format
    if fmt is not None and (
        target.kind != fmt.kind
        or (target.kind == "number" and target.unit != fmt.unit)
        or (target.kind == "category" and target.value not in fmt.choices)
    ):
        raise DomainError("ANSWER_FORMAT: Use this adviser's saved unit or choices.", 409)
