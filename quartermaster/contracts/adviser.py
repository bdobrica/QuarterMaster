"""Versioned local adviser configuration. Revisions are append-only."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from quartermaster.contracts.project import Mission, Name
from quartermaster.contracts.sources import UUIDValue


class ModelSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    base_model_id: Literal["Qwen/Qwen3.5-0.8B"] = "Qwen/Qwen3.5-0.8B"
    base_revision: Literal["2fc06364715b967f1860aea9cf38778875588b17"] = (
        "2fc06364715b967f1860aea9cf38778875588b17"
    )
    adapter_artifact: UUIDValue | None = None


class DecisionDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    available_choices: Mission
    target_behavior: Mission
    case_grain: Mission
    decision_inputs: Mission
    success_and_harm: Mission


class AdviceConsent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    endpoint: str
    model: str
    consented_at: AwareDatetime


class AdviceEngineEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    expected_revision: int = Field(ge=1)
    mode: Literal["local_only", "hosted"]
    consent: bool = False
    endpoint: str | None = None
    model: str | None = None


class AdviserSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["quartermaster.adviser/v1"] = "quartermaster.adviser/v1"
    id: UUID
    revision: int = Field(ge=1)
    created_at: AwareDatetime
    name: Name
    mission: Mission
    business_goal: Mission | None = None
    decision_definition: DecisionDefinition | None = None
    inputs: Literal["quartermaster.case/v1"] = "quartermaster.case/v1"
    outputs: Literal["quartermaster.advice/v1", "quartermaster.prediction/v1"] = (
        "quartermaster.advice/v1"
    )
    model: ModelSpec = Field(default_factory=ModelSpec)
    knowledge_revision: UUID | None = None
    lessons_revision: UUID | None = None
    # Omit new defaults so historical frozen input hashes remain byte-for-byte verifiable.
    advice_mode: Literal["local_only", "hosted"] = Field(
        default="local_only", exclude_if=lambda value: value == "local_only"
    )
    advice_consent: AdviceConsent | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class ProjectEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: Name
    mission: Mission
    business_goal: Mission | None = None
    expected_revision: int = Field(ge=1)
