"""Small public text contracts shared by the feasibility spike and future inference."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

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


class CompactAdvice(BaseModel):
    """Opt-in short response. Shape and citation checks do not prove factual quality."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal["quartermaster.advice/v2"] = "quartermaster.advice/v2"
    decision: Literal["answer", "clarify", "abstain"]
    recommendation: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)
    ]
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=400)]
    evidence_refs: list[Annotated[str, StringConstraints(pattern=r"^[a-f0-9-]{36}$")]] = Field(
        max_length=3
    )
    question: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
        | None
    )

    @model_validator(mode="after")
    def consistent(self):
        if (self.decision == "clarify") != (self.question is not None):
            raise ValueError("Only clarify has one question")
        if self.question and self.question.count("?") > 1:
            raise ValueError("Ask at most one clarification question")
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("Duplicate evidence references")
        for ref in self.evidence_refs:
            if str(UUID(ref)) != ref:
                raise ValueError("Use a canonical citation UUID")
        return self

    def check_evidence(self, accessible_refs: set[str]) -> None:
        if not set(self.evidence_refs) <= accessible_refs:
            raise ValueError("Advice cites inaccessible evidence")
