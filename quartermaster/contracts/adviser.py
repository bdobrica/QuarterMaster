"""Versioned local adviser configuration. Revisions are append-only."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from quartermaster.contracts.project import Mission, Name


class ModelSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    base_model_id: Literal["Qwen/Qwen3.5-0.8B"] = "Qwen/Qwen3.5-0.8B"
    base_revision: Literal["2fc06364715b967f1860aea9cf38778875588b17"] = (
        "2fc06364715b967f1860aea9cf38778875588b17"
    )
    adapter_artifact: None = None


class AdviserSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["quartermaster.adviser/v1"] = "quartermaster.adviser/v1"
    id: UUID
    revision: int = Field(ge=1)
    created_at: AwareDatetime
    name: Name
    mission: Mission
    business_goal: Mission | None = None
    inputs: Literal["quartermaster.case/v1"] = "quartermaster.case/v1"
    outputs: Literal["quartermaster.advice/v1"] = "quartermaster.advice/v1"
    model: ModelSpec = Field(default_factory=ModelSpec)
    knowledge_revision: UUID | None = None
    lessons_revision: None = None


class ProjectEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: Name
    mission: Mission
    business_goal: Mission | None = None
    expected_revision: int = Field(ge=1)
