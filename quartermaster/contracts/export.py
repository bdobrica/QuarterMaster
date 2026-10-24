"""Immutable standalone package and bounded runtime request contracts."""

from typing import Literal

from pydantic import AwareDatetime, Field, field_validator

from quartermaster.contracts.advice import Advice, Text
from quartermaster.contracts.adviser import AdviserSpec
from quartermaster.contracts.evaluation import Digest
from quartermaster.contracts.sources import Chunk, Contract, UUIDValue
from quartermaster.contracts.teaching import AppliedLesson, EvidenceSnapshot
from quartermaster.contracts.training import ArtifactFile


class ExportSelection(Contract):
    candidate_id: UUIDValue
    acknowledge_contents: Literal[True]

    @field_validator("acknowledge_contents", mode="before")
    @classmethod
    def explicit(cls, value):
        if value is not True:
            raise ValueError("Explicit acknowledgement required")
        return value


class ExportLesson(AppliedLesson):
    created_at: AwareDatetime


class ExportSource(Contract):
    id: UUIDValue
    display_name: str = Field(max_length=200)
    sha256: Digest


class ExportKnowledge(Contract):
    sources: list[ExportSource] = Field(max_length=100)
    chunks: list[Chunk] = Field(max_length=10_000)


class ExportManifest(Contract):
    schema_version: Literal["quartermaster.export/v1"] = "quartermaster.export/v1"
    id: UUIDValue
    project_id: UUIDValue
    created_at: AwareDatetime
    candidate_id: UUIDValue
    training_run_id: UUIDValue
    candidate_sha256: Digest
    job_sha256: Digest
    training_manifest_sha256: Digest
    suite_id: UUIDValue
    suite_revision: int = Field(ge=1)
    suite_sha256: Digest
    evaluated_adviser_revision: int = Field(ge=1)
    knowledge_revision: UUIDValue | None
    lessons_revision: UUIDValue | None
    source_hashes: dict[str, Digest]
    runtime_image: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    engine_revision: Literal["1a24df163920a4744a95373d178d790b72a9bb2f"] = (
        "1a24df163920a4744a95373d178d790b72a9bb2f"
    )
    model_format: Literal["GGUF-Q8_0"] = "GGUF-Q8_0"
    prompt_version: Literal["context/v1"] = "context/v1"
    files: dict[str, ArtifactFile]


class RuntimeInput(Contract):
    situation: Text
    choices: list[Text] = Field(default_factory=list, max_length=10)
    case_id: UUIDValue | None = None


class RuntimeAdvice(Contract):
    advice: Advice
    evidence: list[EvidenceSnapshot]
    export_id: UUIDValue
    candidate_id: UUIDValue
    context_sha256: Digest


class RuntimeConfiguration(Contract):
    adviser: AdviserSpec
    lessons: list[ExportLesson] = Field(max_length=10_000)


class ExportReference(Contract):
    case: RuntimeInput
    context_sha256: Digest
    evidence_ids: list[UUIDValue]
