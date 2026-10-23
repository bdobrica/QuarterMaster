"""Small public text contracts shared by the feasibility spike and future inference."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal["quartermaster.case/v1"] = "quartermaster.case/v1"
    case_id: UUID
    situation: Text
    choices: list[Text] = Field(default_factory=list, max_length=10)
    # Stored separately; never serialized into decision-time prompts.
    observed_outcome: Text | None = None

    def decision_input(self) -> dict:
        return self.model_dump(mode="json", exclude={"observed_outcome"})


class Advice(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal["quartermaster.advice/v1"] = "quartermaster.advice/v1"
    recommendation: Text
    explanation: Text
    evidence_refs: list[Text] = Field(max_length=20)
    clarification_question: Text | None
    limitations: list[Text] = Field(max_length=20)

    def check_evidence(self, accessible_refs: set[str]) -> None:
        if not set(self.evidence_refs) <= accessible_refs:
            raise ValueError("Advice cites inaccessible evidence")
