"""Opt-in development comparisons; never training targets or active adviser settings."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, StringConstraints, field_validator, model_validator

from quartermaster.contracts.advice import Advice, Case, CompactAdvice, Text
from quartermaster.contracts.adviser import AdviserSpec
from quartermaster.contracts.sources import Contract, ShortText, UUIDValue
from quartermaster.contracts.teaching import AppliedLesson, EvidenceSnapshot, GroundedAdvice

FieldName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$")]
Value = Annotated[str, StringConstraints(max_length=100)]
Quote = Annotated[str, StringConstraints(min_length=1, max_length=500)]
Arm = Literal["current_v1", "compact_v2", "interpreted_v2"]
Digest = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]


class FieldRule(Contract):
    field: FieldName
    kind: Literal["integer", "category"]
    definition: ShortText
    unit: ShortText | None
    sentinels: dict[Value, ShortText] = Field(default_factory=dict, max_length=10)
    unknown_values: list[Value] = Field(default_factory=list, max_length=10)
    categories: dict[Value, ShortText] = Field(default_factory=dict, max_length=20)
    citation_id: UUIDValue
    source_quote: Quote

    @model_validator(mode="after")
    def unambiguous(self):
        tokens = [*self.sentinels, *self.unknown_values, *self.categories]
        if len(tokens) != len(set(tokens)) or "" in tokens:
            raise ValueError("Use distinct nonempty exact tokens for each interpretation")
        if self.kind == "integer" and (not self.unit or self.categories):
            raise ValueError("Integer rules require units and cannot define categories")
        if self.kind == "category" and (self.unit is not None or not self.categories):
            raise ValueError("Category rules require categories and no unit")
        return self


class FieldRules(Contract):
    schema_version: Literal["quartermaster.field-rules/v1"] = "quartermaster.field-rules/v1"
    reviewed: Literal[True]
    rules: list[FieldRule] = Field(max_length=20)

    @field_validator("reviewed", mode="before")
    @classmethod
    def confirmed(cls, value):
        if value is not True:
            raise ValueError("Review and explicitly confirm these definitions")
        return value

    @model_validator(mode="after")
    def unique(self):
        if len({r.field for r in self.rules}) != len(self.rules):
            raise ValueError("Only one rule per field")
        if len({r.citation_id for r in self.rules}) > 4:
            raise ValueError("Use at most four definition excerpts per comparison")
        return self


class FieldInterpretation(Contract):
    field: FieldName
    raw_value: Value | None
    state: Literal["absent", "missing", "unknown", "sentinel", "value", "invalid"]
    value: int | str | None
    unit: ShortText | None
    meaning: ShortText
    citation_id: UUIDValue
    source_quote: Quote


class ReliabilityInput(Contract):
    situation: Text
    decision_inputs: dict[FieldName, Value | None] = Field(max_length=30)
    field_rules: FieldRules
    inputs_available_at_decision: Literal[True]

    @field_validator("inputs_available_at_decision", mode="before")
    @classmethod
    def confirmed(cls, value):
        if value is not True:
            raise ValueError("Confirm that inputs exclude outcomes and post-decision data")
        return value


class ReliabilityRequest(Contract):
    arm: Arm
    system: str
    context: str
    parameters: dict
    response_schema: dict
    input_sha256: Digest


class ReliabilityOutput(Contract):
    arm: Arm
    draft: GroundedAdvice | CompactAdvice | None
    advice: Advice | CompactAdvice | None
    error: str | None
    schema_valid: bool
    citations_valid: bool | None
    elapsed_seconds: float = Field(ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    output_characters: int | None = Field(default=None, ge=0)


class ReliabilityRun(Contract):
    schema_version: Literal["quartermaster.reliability-run/v1"] = "quartermaster.reliability-run/v1"
    id: UUIDValue
    project_id: UUIDValue
    revision: int = Field(ge=1)
    created_at: AwareDatetime
    status: Literal["running", "completed", "interrupted"]
    action: ReliabilityInput
    case: Case
    adviser: AdviserSpec
    model_alias: str
    engine_revision: Literal["1a24df163920a4744a95373d178d790b72a9bb2f"] = (
        "1a24df163920a4744a95373d178d790b72a9bb2f"
    )
    evidence: list[EvidenceSnapshot]
    lessons: list[AppliedLesson]
    omitted_lessons: int
    omitted_excerpts: int
    interpretations: list[FieldInterpretation]
    rules_sha256: Digest
    requests: list[ReliabilityRequest] = Field(min_length=3, max_length=3)
    outputs: list[ReliabilityOutput] = Field(max_length=3)
    error: str | None = None


Assessment = Literal["pass", "fail", "not_assessed"]


class QualityReviewInput(Contract):
    expected_revision: int = Field(ge=0)
    factual_quality: Assessment
    clarification_relevance: Assessment
    unsupported_assertions: Assessment
    citation_relevance: Assessment
    decision_usefulness: Literal["useful", "not_useful", "not_assessed"]
    notes: Text


class QualityReview(QualityReviewInput):
    schema_version: Literal["quartermaster.reliability-review/v1"] = (
        "quartermaster.reliability-review/v1"
    )
    run_id: UUIDValue
    arm: Arm
    revision: int = Field(ge=1)
    created_at: AwareDatetime
