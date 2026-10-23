"""Project listing contract; the adviser contract holds versioned configuration."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, StringConstraints

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Mission = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: Name
    mission: Mission
    business_goal: Mission | None = None


class Project(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["quartermaster.project/v1"] = "quartermaster.project/v1"
    id: UUID
    name: Name
    mission: Mission
    created_at: AwareDatetime

    @classmethod
    def from_row(cls, row) -> "Project":
        return cls(
            id=UUID(row["id"]),
            name=row["name"],
            mission=row["mission"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
