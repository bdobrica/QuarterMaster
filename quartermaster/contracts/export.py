"""Immutable standalone package and bounded runtime request contracts."""

from typing import Literal

from pydantic import AwareDatetime, Field, field_validator, model_serializer, model_validator

from quartermaster.contracts.advice import Advice, Text
from quartermaster.contracts.adviser import AdviserSpec
from quartermaster.contracts.evaluation import Digest
from quartermaster.contracts.prediction import AnswerFormat
from quartermaster.contracts.sources import Chunk, Contract, UUIDValue
from quartermaster.contracts.teaching import AppliedLesson, EvidenceSnapshot
from quartermaster.contracts.training import ArtifactFile
from quartermaster.errors import DomainError
from quartermaster.generation import LEGACY_PARAMETERS, PARAMETERS, checked_parameters


class ExportSelection(Contract):
    candidate_id: UUIDValue
    acknowledge_contents: Literal[True]

    @field_validator("acknowledge_contents", mode="before")
    @classmethod
    def explicit(cls, value):
        if value is not True:
            raise ValueError("Explicit acknowledgement required")
        return value


class BaseExportSelection(Contract):
    test_id: UUIDValue
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
    schema_version: Literal[
        "quartermaster.export/v1",
        "quartermaster.export/v2",
        "quartermaster.export/v3",
        "quartermaster.export/v4",
    ] = "quartermaster.export/v1"
    id: UUIDValue
    project_id: UUIDValue
    created_at: AwareDatetime
    candidate_id: UUIDValue | None
    training_run_id: UUIDValue | None
    candidate_sha256: Digest | None
    job_sha256: Digest | None
    training_manifest_sha256: Digest | None
    suite_id: UUIDValue | None
    suite_revision: int | None = Field(ge=1)
    suite_sha256: Digest | None
    source_test_id: UUIDValue | None = None
    source_test_sha256: Digest | None = None
    evaluated_adviser_revision: int = Field(ge=1)
    knowledge_revision: UUIDValue | None
    lessons_revision: UUIDValue | None
    source_hashes: dict[str, Digest]
    runtime_image: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    engine_revision: Literal["1a24df163920a4744a95373d178d790b72a9bb2f"] = (
        "1a24df163920a4744a95373d178d790b72a9bb2f"
    )
    model_format: Literal["GGUF-Q8_0"] = "GGUF-Q8_0"
    prompt_version: Literal[
        "context/v1", "context/v2", "context/v3", "context/v4", "context/v5", "context/v6"
    ] = "context/v1"
    teaching_sha256: Digest | None = Field(default=None, exclude_if=lambda value: value is None)
    files: dict[str, ArtifactFile]
    inference_parameters: dict = Field(
        default_factory=lambda: checked_parameters(LEGACY_PARAMETERS)
    )

    @model_serializer(mode="wrap")
    def preserve_historical_wire(self, handler):
        data = handler(self)
        if self.schema_version != "quartermaster.export/v3":
            data.pop("source_test_id", None)
            data.pop("source_test_sha256", None)
        return data

    @model_validator(mode="after")
    def generation_profile(self):
        try:
            checked_parameters(self.inference_parameters)
        except DomainError:
            raise ValueError("Unsupported inference parameters") from None
        lineage = (
            self.candidate_id,
            self.training_run_id,
            self.candidate_sha256,
            self.job_sha256,
            self.training_manifest_sha256,
            self.suite_id,
            self.suite_revision,
            self.suite_sha256,
        )
        if self.schema_version == "quartermaster.export/v4":
            if (
                any(v is None for v in lineage[:5])
                or any(v is not None for v in lineage[5:])
                or self.source_test_id is not None
                or self.source_test_sha256 is not None
                or self.teaching_sha256 is None
                or self.prompt_version not in ("context/v4", "context/v5", "context/v6")
                or self.inference_parameters != PARAMETERS
            ):
                raise ValueError("Generic export requires reviewed teaching and candidate lineage")
            return self
        if self.teaching_sha256 is not None or self.prompt_version in (
            "context/v4",
            "context/v5",
            "context/v6",
        ):
            raise ValueError("Generic prediction requires a version 4 export")
        if self.schema_version == "quartermaster.export/v3":
            from quartermaster.generation import ADVICE_PARAMETERS

            if (
                any(v is not None for v in lineage)
                or self.source_test_id is None
                or self.source_test_sha256 is None
                or self.prompt_version != "context/v3"
                or self.inference_parameters != ADVICE_PARAMETERS
            ):
                raise ValueError(
                    "Version 3 base export requires the tested bounded-thinking context"
                )
        elif (
            any(v is None for v in lineage)
            or self.source_test_id
            or self.source_test_sha256
            or self.prompt_version == "context/v3"
        ):
            raise ValueError("Historical candidate exports require their evaluated lineage")
        if self.schema_version == "quartermaster.export/v1":
            if (
                self.inference_parameters != LEGACY_PARAMETERS
                or self.prompt_version != "context/v1"
            ):
                raise ValueError("Version 1 exports use the historical 512-token profile")
        elif "inference_parameters" not in self.model_fields_set:
            raise ValueError("Version 2 exports require explicit inference parameters")
        elif self.schema_version == "quartermaster.export/v2" and self.inference_parameters not in (
            LEGACY_PARAMETERS,
            PARAMETERS,
        ):
            raise ValueError("Version 2 preserves its historical non-thinking profiles")
        return self


class RuntimeInput(Contract):
    situation: Text
    choices: list[Text] = Field(default_factory=list, max_length=10)
    case_id: UUIDValue | None = None


class RuntimeAdvice(Contract):
    advice: Advice
    evidence: list[EvidenceSnapshot]
    export_id: UUIDValue
    candidate_id: UUIDValue | None
    context_sha256: Digest


class RuntimeConfiguration(Contract):
    adviser: AdviserSpec
    lessons: list[ExportLesson] = Field(max_length=10_000)
    answer_format: AnswerFormat | None = Field(default=None, exclude_if=lambda value: value is None)


class ExportReference(Contract):
    case: RuntimeInput
    context_sha256: Digest
    evidence_ids: list[UUIDValue]
