"""Public file boundary for reviewed SFT, bounded jobs and immutable candidates."""

from typing import Literal

from pydantic import AwareDatetime, Field, field_validator

from quartermaster.contracts.advice import Case
from quartermaster.contracts.adviser import AdviserSpec, ModelSpec
from quartermaster.contracts.evaluation import Digest, EvaluationInput, EvaluationOutput
from quartermaster.contracts.interview import Consent, VersionedAction
from quartermaster.contracts.sources import Contract, UUIDValue
from quartermaster.contracts.teaching import GroundedAdvice, Lesson, LessonDisclosure


class ExampleTarget(VersionedAction):
    target: GroundedAdvice


class ExampleReview(VersionedAction):
    action: Literal["approve", "reject"]
    target: GroundedAdvice | None = None


class ExampleProposal(Contract):
    case: Case
    target: GroundedAdvice


class TrainingExample(Contract):
    schema_version: Literal["quartermaster.training-example/v1"] = (
        "quartermaster.training-example/v1"
    )
    id: UUIDValue
    project_id: UUIDValue
    revision: int = Field(ge=1)
    created_at: AwareDatetime
    origin: Literal["OWNER_DRAFT", "AI_DRAFT"]
    status: Literal["draft", "prepared", "sending", "reviewed", "approved", "rejected", "failed"]
    lesson: Lesson
    case: Case
    input: EvaluationInput
    target: GroundedAdvice | None = None
    disclosure: LessonDisclosure | None = None
    consented_at: AwareDatetime | None = None
    error: str | None = None


class ExampleSend(Consent):
    pass


class Recipe(Contract):
    schema_version: Literal["quartermaster.lora-recipe/v1"] = "quartermaster.lora-recipe/v1"
    preset: Literal["quick", "standard"]
    steps: Literal[12, 48]
    max_length: Literal[2048] = 2048
    rank: Literal[4] = 4
    alpha: Literal[8] = 8
    learning_rate: Literal[0.00001] = 0.00001
    seed: Literal[17] = 17
    precision: Literal["float32"] = "float32"
    completion_only_loss: Literal[True] = True
    seconds: Literal[1200, 3600]


class TrainingSelection(Contract):
    example_ids: list[UUIDValue] = Field(min_length=1, max_length=100)
    suite_id: UUIDValue
    suite_revision: int = Field(ge=1)
    preset: Literal["quick", "standard"]
    acknowledge_small_data: Literal[True]

    @field_validator("acknowledge_small_data", mode="before")
    @classmethod
    def explicit(cls, value):
        if value is not True:
            raise ValueError("Explicit acknowledgement required")
        return value


class TrainingRow(Contract):
    id: UUIDValue
    example_revision: int = Field(ge=1)
    messages: list[dict[str, str]]


class TrainingJob(Contract):
    schema_version: Literal["quartermaster.training-job/v1"] = "quartermaster.training-job/v1"
    id: UUIDValue
    project_id: UUIDValue
    created_at: AwareDatetime
    adviser: AdviserSpec
    examples: list[TrainingExample] = Field(min_length=1, max_length=100)
    dataset_sha256: Digest
    suite_id: UUIDValue
    suite_revision: int
    suite_sha256: Digest
    holdout_ids: list[UUIDValue]
    holdout_hashes: list[Digest]
    source_hashes: dict[str, Digest]
    model: ModelSpec = Field(default_factory=ModelSpec)
    recipe: Recipe


class TrainingRun(Contract):
    schema_version: Literal["quartermaster.training-run/v1"] = "quartermaster.training-run/v1"
    id: UUIDValue
    project_id: UUIDValue
    revision: int = Field(ge=1)
    created_at: AwareDatetime
    updated_at: AwareDatetime
    status: Literal[
        "queued",
        "preflight",
        "training",
        "verifying",
        "converting",
        "evaluating",
        "completed",
        "failed",
        "canceled",
        "interrupted",
        "cleanup_required",
    ]
    job_sha256: Digest
    dataset_sha256: Digest
    cancel_requested: bool = False
    trainer_image_id: Digest | None = None
    runtime_image_id: Digest | None = None
    candidate_id: UUIDValue | None = None
    error: str | None = None
    # Fixed diagnostic events only. Never raw trainer stdout or customer text.
    log: list[str] = Field(default_factory=list, max_length=100)


class ArtifactFile(Contract):
    sha256: Digest
    size_bytes: int = Field(gt=0, le=3_000_000_000)


class TrainingManifest(Contract):
    schema_version: Literal["quartermaster.training-artifacts/v1"] = (
        "quartermaster.training-artifacts/v1"
    )
    job_id: UUIDValue
    job_sha256: Digest
    dataset_sha256: Digest
    model: ModelSpec
    recipe: Recipe
    completed_steps: int = Field(ge=1, le=48)
    training_loss: float = Field(allow_inf_nan=False)
    files: dict[str, ArtifactFile]


class CandidatePair(Contract):
    case_id: UUIDValue
    baseline: EvaluationOutput
    candidate: EvaluationOutput


class AdviserVersion(Contract):
    schema_version: Literal["quartermaster.adviser-version/v1"] = "quartermaster.adviser-version/v1"
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
    suite_id: UUIDValue
    suite_revision: int
    suite_sha256: Digest
    smoke_passed: bool
    comparisons: list[CandidatePair] = Field(min_length=1, max_length=10)


class Promote(VersionedAction):
    acknowledge_regressions: Literal[True]

    _explicit = field_validator("acknowledge_regressions", mode="before")(
        TrainingSelection.explicit.__func__
    )
