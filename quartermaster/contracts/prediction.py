"""Generic owner supervision and prediction; historical advice contracts stay unchanged."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from quartermaster.contracts.advice import Case, Text
from quartermaster.contracts.adviser import AdviserSpec, ModelSpec
from quartermaster.contracts.muster import Digest, MusterImport, OwnerDecision, Short, Target
from quartermaster.contracts.sources import Contract, Source, UUIDValue
from quartermaster.contracts.teaching import EvidenceSnapshot
from quartermaster.contracts.training import Recipe


class NumberAnswer(Contract):
    kind: Literal["number"]
    unit: Short


class CategoryAnswer(Contract):
    kind: Literal["category"]
    choices: list[Short] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def unique(self):
        if len(set(self.choices)) != len(self.choices):
            raise ValueError("Choose each answer once")
        return self


AnswerFormat = Annotated[NumberAnswer | CategoryAnswer, Field(discriminator="kind")]


class Prediction(Contract):
    schema_version: Literal["quartermaster.prediction/v1"] = "quartermaster.prediction/v1"
    behavior: Literal["answer", "clarify", "abstain"]
    target: Target | None
    explanation: str = Field(min_length=1, max_length=600)
    evidence_refs: list[UUIDValue] = Field(max_length=3)
    question: str | None = Field(max_length=240)
    limitations: list[Short] = Field(max_length=3)
    # Optional model estimates, never calibrated probabilities.
    estimated_probabilities: dict[Short, float] | None = None

    @model_validator(mode="after")
    def consistent(self):
        if (self.behavior == "answer") != (self.target is not None):
            raise ValueError("Only an answer carries a target")
        if (self.behavior == "clarify") != (self.question is not None):
            raise ValueError("Only clarification carries a question")
        if self.question is not None and not self.question.strip():
            raise ValueError("Write a clarification question")
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("Repeated citation")
        if self.estimated_probabilities is not None:
            values = self.estimated_probabilities.values()
            if (
                not self.target
                or self.target.kind != "category"
                or not values
                or any(not 0 <= v <= 1 for v in values)
                or abs(sum(values) - 1) > 0.000001
            ):
                raise ValueError("Category estimates must be finite probabilities summing to one")
        return self


class TeachingSource(Contract):
    manifest_sha256: Digest
    example_id: str
    capture: dict
    provenance: str


class TaughtExample(Contract):
    input: Case
    owner_decision: OwnerDecision
    source: TeachingSource


class TeachingKnowledge(Contract):
    source: Source
    text: str


class TeachingDataset(Contract):
    schema_version: Literal["quartermaster.teaching-dataset/v1"] = (
        "quartermaster.teaching-dataset/v1"
    )
    project_id: UUIDValue
    knowledge_revision: UUIDValue | None
    examples: list[TaughtExample] = Field(min_length=1, max_length=100)
    knowledge: list[TeachingKnowledge] = Field(max_length=100)
    imports: list[MusterImport] = Field(min_length=1, max_length=100)


class PredictionInput(Contract):
    case: Case
    answer_format: AnswerFormat
    system: str
    context: str
    prompt_version: Literal["context/v4"] = "context/v4"
    parameters: dict
    response_schema: dict
    evidence: list[EvidenceSnapshot]
    input_sha256: Digest


class SupervisedPrediction(Contract):
    id: UUIDValue
    revision: int = Field(ge=1)
    input: PredictionInput
    target: Prediction

    @property
    def case(self):
        return self.input.case


class PredictionJob(Contract):
    schema_version: Literal["quartermaster.training-job/v2"] = "quartermaster.training-job/v2"
    id: UUIDValue
    project_id: UUIDValue
    created_at: AwareDatetime
    adviser: AdviserSpec
    baseline: ModelSpec
    answer_format: AnswerFormat
    teaching: TeachingDataset
    teaching_sha256: Digest
    examples: list[SupervisedPrediction] = Field(min_length=1, max_length=100)
    dataset_sha256: Digest
    source_hashes: dict[str, Digest]
    model: ModelSpec = Field(default_factory=ModelSpec)
    recipe: Recipe


class PredictionResult(Contract):
    prediction: Prediction | None
    error: str | None
    input_sha256: Digest


class PredictionPair(Contract):
    case_id: UUIDValue
    baseline: PredictionResult
    candidate: PredictionResult


class PredictionCandidate(Contract):
    schema_version: Literal["quartermaster.adviser-version/v2"] = "quartermaster.adviser-version/v2"
    id: UUIDValue
    project_id: UUIDValue
    training_run_id: UUIDValue
    created_at: AwareDatetime
    status: Literal["candidate"] = "candidate"
    job_sha256: Digest
    training_manifest_sha256: Digest
    model_sha256: Digest
    model_size_bytes: int
    license_sha256: Digest
    trainer_image_id: Digest
    runtime_image_id: Digest
    baseline: ModelSpec
    answer_format: AnswerFormat
    teaching_sha256: Digest
    smoke_passed: bool
    comparison_kind: Literal["taught_preference_consistency"] = "taught_preference_consistency"
    comparisons: list[PredictionPair] = Field(min_length=1, max_length=5)


class ImproveSelection(Contract):
    expected_revision: int = Field(ge=1)
    answer_format: AnswerFormat
    acknowledge_resources: Literal[True]

    @model_validator(mode="before")
    @classmethod
    def explicit(cls, value):
        if isinstance(value, dict) and value.get("acknowledge_resources") is not True:
            raise ValueError("Acknowledge local training resources")
        return value


class PredictRequest(Contract):
    situation: Text
    answer_format: AnswerFormat


class PredictionRun(Contract):
    schema_version: Literal["quartermaster.prediction-run/v1"] = "quartermaster.prediction-run/v1"
    id: UUIDValue
    project_id: UUIDValue
    created_at: AwareDatetime
    adviser: AdviserSpec
    input: PredictionInput
    result: PredictionResult


class RuntimePrediction(Contract):
    prediction: Prediction
    evidence: list[EvidenceSnapshot]
    export_id: UUIDValue
    candidate_id: UUIDValue | None
    context_sha256: Digest
