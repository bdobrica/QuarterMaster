"""Frozen, owner-authored holdouts and append-only context comparisons."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, StringConstraints

from quartermaster.contracts.advice import Advice, Case, Text
from quartermaster.contracts.adviser import AdviserSpec
from quartermaster.contracts.sources import Contract, ShortText, UUIDValue
from quartermaster.contracts.teaching import (
    AppliedLesson,
    Category,
    EvidenceSnapshot,
    GroundedAdvice,
    RawCorrection,
)

Behavior = Literal["recommend", "clarify", "abstain"]
Digest = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]


class SuiteCreate(Contract):
    name: ShortText


class SuiteAction(Contract):
    expected_revision: int = Field(ge=1)


class Rubric(Contract):
    expected_behavior: Literal["any", "recommend", "clarify", "abstain"]
    expectation: Text


class SaveEvaluationCase(SuiteAction):
    test_id: UUIDValue
    rubric: Rubric


class EvaluationCase(Contract):
    id: UUIDValue
    test_id: UUIDValue
    case: Case
    case_sha256: Digest
    rubric: Rubric
    held_out: Literal[True] = True


class EvaluationInput(Contract):
    """Exact decision-time request; rubric and observed outcomes are deliberately absent."""

    variant: Literal["base_only", "base_context"]
    adviser: AdviserSpec
    system: str
    context: str
    prompt_version: Literal["context/v1", "context/v2"] = "context/v1"
    engine_revision: Literal["1a24df163920a4744a95373d178d790b72a9bb2f"] = (
        "1a24df163920a4744a95373d178d790b72a9bb2f"
    )
    model_alias: str
    parameters: dict
    response_schema: dict
    evidence: list[EvidenceSnapshot]
    lessons: list[AppliedLesson]
    omitted_lessons: int
    omitted_excerpts: int
    input_sha256: Digest


class FrozenPair(Contract):
    case_id: UUIDValue
    a: EvaluationInput
    b: EvaluationInput


class EvaluationSuite(Contract):
    schema_version: Literal["quartermaster.evaluation-suite/v1"] = (
        "quartermaster.evaluation-suite/v1"
    )
    id: UUIDValue
    project_id: UUIDValue
    name: ShortText
    revision: int = Field(ge=1)
    created_at: AwareDatetime
    status: Literal["draft", "frozen"]
    frozen_at: AwareDatetime | None = None
    cases: list[EvaluationCase] = Field(max_length=10)
    inputs: list[FrozenPair] = Field(default_factory=list, max_length=10)
    source_hashes: dict[str, Digest] = Field(default_factory=dict)
    frozen_sha256: Digest | None = None


class DeterministicChecks(Contract):
    schema_valid: bool
    citations_valid: bool | None
    supporting_facts_valid: bool | None
    behavior: Behavior | None
    expected_behavior_passed: bool | None
    unsupported_recommendation: bool


class EvaluationOutput(Contract):
    case_id: UUIDValue
    variant: Literal["base_only", "base_context"]
    created_at: AwareDatetime
    input_sha256: Digest
    draft: GroundedAdvice | None
    advice: Advice | None
    error: str | None
    checks: DeterministicChecks


class EvaluationRun(Contract):
    schema_version: Literal["quartermaster.evaluation-run/v1"] = "quartermaster.evaluation-run/v1"
    id: UUIDValue
    project_id: UUIDValue
    suite_id: UUIDValue
    suite_revision: int
    suite_sha256: Digest
    revision: int = Field(ge=1)
    created_at: AwareDatetime
    status: Literal["running", "completed", "interrupted"]
    comparison_kind: Literal["context_comparison"] = "context_comparison"
    weight_improvement_assessed: Literal[False] = False
    outputs: list[EvaluationOutput] = Field(max_length=20)
    error: str | None = None


Preference = Literal["a_better", "b_better", "same", "both_bad"]


class RatingInput(Contract):
    expected_revision: int = Field(ge=0)
    preference: Preference
    category: Category
    rationale: RawCorrection


class ComparisonRating(Contract):
    schema_version: Literal["quartermaster.comparison-rating/v1"] = (
        "quartermaster.comparison-rating/v1"
    )
    run_id: UUIDValue
    case_id: UUIDValue
    revision: int = Field(ge=1)
    created_at: AwareDatetime
    preference: Preference
    category: Category
    rationale: RawCorrection
