"""Opt-in development comparisons; never training targets or active adviser settings."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, StringConstraints, field_validator, model_validator

from quartermaster.contracts.advice import Advice, Case, CompactAdvice, DecisionOnly, Text
from quartermaster.contracts.adviser import AdviserSpec
from quartermaster.contracts.sources import Contract, ShortText, UUIDValue
from quartermaster.contracts.teaching import AppliedLesson, EvidenceSnapshot, GroundedAdvice

FieldName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$")]
Value = Annotated[str, StringConstraints(max_length=100)]
Quote = Annotated[str, StringConstraints(min_length=1, max_length=500)]
Arm = Literal[
    "current_v1",
    "compact_v2",
    "interpreted_v2",
    "no_lessons",
    "all_lessons",
    "relevant_lesson",
    "irrelevant_lesson",
    "existing_instructions",
    "answer_first",
    "decision_gated",
    "full_context",
    "relevant_raw",
    "relevant_interpreted",
    "compact_contract",
    "decision_only",
]
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


class LessonAblation(Contract):
    """Operator-selected experimental roles, never new lesson approval or quality labels."""

    relevant_id: UUIDValue
    relevant_rationale: ShortText
    irrelevant_id: UUIDValue
    irrelevant_rationale: ShortText

    @model_validator(mode="after")
    def distinct(self):
        if self.relevant_id == self.irrelevant_id:
            raise ValueError("Select different lessons for the two experimental roles")
        return self


class ContextSelection(Contract):
    fields: list[FieldName] = Field(min_length=1, max_length=20)
    rationale: ShortText
    reviewed: Literal[True]

    @field_validator("reviewed", mode="before")
    @classmethod
    def confirmed(cls, value):
        if value is not True:
            raise ValueError("Explicitly review the field selection")
        return value

    @model_validator(mode="after")
    def distinct(self):
        if len(set(self.fields)) != len(self.fields):
            raise ValueError("Select distinct fields")
        return self


class DefinitionSpan(Contract):
    field: FieldName
    citation_id: UUIDValue
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: Quote


class ReliabilityInput(Contract):
    situation: Text
    decision_inputs: dict[FieldName, Value | None] = Field(max_length=30)
    field_rules: FieldRules
    inputs_available_at_decision: Literal[True]
    lesson_ablation: LessonAblation | None = None
    decision_selection: Literal[True] | None = None
    context_selection: ContextSelection | None = None
    decision_contract: ContextSelection | None = None

    @field_validator("decision_selection", mode="before")
    @classmethod
    def selection_opt_in(cls, value):
        if value is not None and value is not True:
            raise ValueError("Use true to select the decision-selection experiment")
        return value

    @model_validator(mode="after")
    def one_experiment(self):
        if (
            sum(
                bool(v)
                for v in (
                    self.lesson_ablation,
                    self.decision_selection,
                    self.context_selection,
                    self.decision_contract,
                )
            )
            > 1
        ):
            raise ValueError("Choose only one development experiment")
        selection = self.context_selection or self.decision_contract
        if selection and not set(selection.fields) <= {r.field for r in self.field_rules.rules}:
            raise ValueError("Each selected field needs an attributed field rule, even if absent")
        return self

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
    draft: GroundedAdvice | CompactAdvice | DecisionOnly | None
    advice: Advice | CompactAdvice | None
    error: str | None
    schema_valid: bool
    citations_valid: bool | None
    elapsed_seconds: float = Field(ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    output_characters: int | None = Field(default=None, ge=0)

    @property
    def citation_count(self):
        if self.draft is None or isinstance(self.draft, DecisionOnly):
            return None
        advice = self.draft if isinstance(self.draft, CompactAdvice) else self.draft.advice
        return len(advice.evidence_refs)

    @property
    def citation_status(self):
        if self.arm == "decision_only":
            return "not_applicable"
        if self.citation_count is None:
            return "not_assessed"
        if self.citation_count == 0:
            return "none_provided"
        return "accessible" if self.citations_valid else "inaccessible"

    @property
    def sentence_endings_valid(self):
        # A diagnostic only. Punctuation cannot establish a complete explanation.
        if not isinstance(self.draft, CompactAdvice):
            return None
        return all(
            text.rstrip().endswith((".", "!", "?"))
            for text in (self.draft.recommendation, self.draft.reason, self.draft.question)
            if text is not None
        )


class ReliabilityRun(Contract):
    schema_version: Literal[
        "quartermaster.reliability-run/v1",
        "quartermaster.reliability-run/v2",
        "quartermaster.reliability-run/v3",
        "quartermaster.reliability-run/v4",
        "quartermaster.reliability-run/v5",
    ] = "quartermaster.reliability-run/v1"
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
    requests: list[ReliabilityRequest] = Field(min_length=2, max_length=4)
    outputs: list[ReliabilityOutput] = Field(max_length=4)
    error: str | None = None
    full_context: str | None = None
    definition_spans: list[DefinitionSpan] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def experiment_arms(self):
        ablation = self.action.lesson_ablation is not None
        expected = (
            ["no_lessons", "all_lessons", "relevant_lesson", "irrelevant_lesson"]
            if ablation
            else ["current_v1", "compact_v2", "interpreted_v2"]
        )
        version = (
            "quartermaster.reliability-run/v2" if ablation else "quartermaster.reliability-run/v1"
        )
        if self.action.decision_selection:
            expected = ["existing_instructions", "answer_first", "decision_gated"]
            version = "quartermaster.reliability-run/v3"
        selection = self.action.context_selection or self.action.decision_contract
        if selection:
            if self.action.decision_contract:
                expected = ["compact_contract", "decision_only"]
                version = "quartermaster.reliability-run/v5"
                if len(self.requests) != 2 or any(
                    r.context != self.requests[0].context
                    or r.system != self.requests[0].system
                    or r.parameters != self.requests[0].parameters
                    for r in self.requests
                ):
                    raise ValueError("Decision contracts require identical messages and parameters")
            else:
                expected = ["full_context", "relevant_raw", "relevant_interpreted"]
                version = "quartermaster.reliability-run/v4"
            if not self.full_context or (
                self.action.context_selection and self.full_context != self.requests[0].context
            ):
                raise ValueError("Preserve the exact full control context")
            if [s.field for s in self.definition_spans] != selection.fields:
                raise ValueError("Preserve a definition span for every selected field")
            for span in self.definition_spans:
                rule = next(r for r in self.action.field_rules.rules if r.field == span.field)
                if span.citation_id != rule.citation_id or span.text != rule.source_quote:
                    raise ValueError("Definition span must match its selected rule")
                if not any(
                    e.citation_id == span.citation_id
                    and span.start < span.end <= len(e.text)
                    and e.text[span.start : span.end] == span.text
                    for e in self.evidence
                ):
                    raise ValueError("Definition span must match captured original excerpt bytes")
        elif self.full_context is not None or self.definition_spans:
            raise ValueError("Selected views belong only to context-selection experiments")
        if self.schema_version != version or [r.arm for r in self.requests] != expected:
            raise ValueError("Run version and ordered requests must match the selected experiment")
        if [o.arm for o in self.outputs] != expected[: len(self.outputs)]:
            raise ValueError("Outputs must follow captured request order without duplicates")
        for output in self.outputs:
            if output.arm == "decision_only":
                if (
                    (output.draft is not None and not isinstance(output.draft, DecisionOnly))
                    or output.advice is not None
                    or output.citations_valid is not None
                ):
                    raise ValueError("A decision-only label is not grounded advice")
            elif isinstance(output.draft, DecisionOnly):
                raise ValueError("Decision-only labels belong only to their experimental arm")
        return self


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


class FieldClaim(Contract):
    """Explicit assertion to compare with captured facts; never inferred from prose."""

    field: FieldName
    state: Literal["absent", "missing", "unknown", "sentinel", "value", "invalid"]
    value: int | Value | None
    unit: ShortText | None
    citation_id: UUIDValue

    @model_validator(mode="after")
    def typed_assertion(self):
        if self.state != "value" and (self.value is not None or self.unit is not None):
            raise ValueError("Non-value states cannot assert a value or measurement unit")
        if self.state == "value" and self.value is None:
            raise ValueError("A value claim must supply its exact typed value")
        return self


class FieldClaims(Contract):
    schema_version: Literal["quartermaster.field-claims/v1"] = "quartermaster.field-claims/v1"
    claims: list[FieldClaim] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def distinct_fields(self):
        if len({c.field for c in self.claims}) != len(self.claims):
            raise ValueError("Supply one assertion per field")
        return self


class FieldClaimResult(Contract):
    field: FieldName
    matches: bool
    mismatches: list[Literal["unconfigured_field", "state", "value", "unit", "citation_id"]]


class FieldClaimCheck(Contract):
    schema_version: Literal["quartermaster.field-claim-check/v1"] = (
        "quartermaster.field-claim-check/v1"
    )
    run_id: UUIDValue
    rules_sha256: Digest
    all_claims_match: bool
    advice_prose_checked: Literal[False] = False
    results: list[FieldClaimResult] = Field(min_length=1, max_length=20)
