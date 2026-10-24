"""Versioned test snapshots, unchanged owner feedback and reviewed context lessons."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, StringConstraints

from quartermaster.contracts.advice import Advice, Case, Text
from quartermaster.contracts.adviser import AdviserSpec
from quartermaster.contracts.interview import Consent, VersionedAction
from quartermaster.contracts.sources import Contract, UUIDValue


class TestInput(Contract):
    situation: Text
    choices: list[Text] = Field(default_factory=list, max_length=10)
    compare_existing: bool = False


class GroundedAdvice(Contract):
    """Model draft includes checkable quotes and declared missing decision inputs."""

    missing_information: list[Text] = Field(max_length=10)
    behavior: Literal["recommend", "clarify", "abstain"]
    supporting_quotes: list[Text] = Field(max_length=10)
    advice: Advice


class EvidenceSnapshot(Contract):
    citation_id: UUIDValue
    source_id: UUIDValue
    source_name: str
    source_sha256: str
    excerpt_sha256: str
    text: str
    line_start: int
    line_end: int


class LessonText(Contract):
    applicability: Text
    instruction: Text


class AppliedLesson(Contract):
    id: UUIDValue
    revision: int
    text: LessonText


class TestRun(Contract):
    schema_version: Literal["quartermaster.test/v1"] = "quartermaster.test/v1"
    id: UUIDValue
    project_id: UUIDValue
    created_at: AwareDatetime
    case: Case
    adviser: AdviserSpec
    prompt_version: Literal["context/v1", "context/v2", "context/v3"] = "context/v1"
    engine_revision: Literal["1a24df163920a4744a95373d178d790b72a9bb2f", "openai-compatible/v1"] = (
        "1a24df163920a4744a95373d178d790b72a9bb2f"
    )
    system: str
    context: str
    provider_prompt_version: Literal["hosted/v1"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    provider: str = Field(default="local", exclude_if=lambda value: value == "local")
    latency_ms: int | None = Field(default=None, ge=0, exclude_if=lambda value: value is None)
    model_alias: str
    parameters: dict
    response_schema: dict
    evidence: list[EvidenceSnapshot]
    lessons: list[AppliedLesson]
    draft: GroundedAdvice | None
    advice: Advice | None
    error: str | None
    model_role: Literal["active", "base", "existing_lora"] = "active"
    comparison_of: UUIDValue | None = None
    comparison_model_sha256: str | None = None


Category = Literal["good", "wrong_call", "missing_knowledge", "should_ask", "weak_explanation"]
RawCorrection = Annotated[str, StringConstraints(min_length=1, max_length=4000)]


class FeedbackInput(Contract):
    category: Category
    # Deliberately no strip_whitespace: preserve the owner's bytes as UTF-8 text.
    correction: RawCorrection


class Feedback(Contract):
    schema_version: Literal["quartermaster.feedback/v1"] = "quartermaster.feedback/v1"
    id: UUIDValue
    project_id: UUIDValue
    test_id: UUIDValue
    case_id: UUIDValue
    created_at: AwareDatetime
    category: Category
    correction: RawCorrection


class LessonDisclosure(Contract):
    endpoint: str
    model: str
    system: str
    context: str
    response_schema: dict
    disclosure_sha256: str
    input_bytes: int


class Lesson(Contract):
    schema_version: Literal["quartermaster.lesson/v1"] = "quartermaster.lesson/v1"
    id: UUIDValue
    project_id: UUIDValue
    feedback_id: UUIDValue
    case_id: UUIDValue
    revision: int = Field(ge=1)
    created_at: AwareDatetime
    status: Literal["pending", "sending", "reviewed", "applied", "rejected", "failed"]
    origin: Literal["AI_DRAFT", "OWNER_DRAFT"]
    text: LessonText | None = None
    disclosure: LessonDisclosure | None = None
    consented_at: AwareDatetime | None = None
    error: str | None = None


class LessonSend(Consent):
    """turn_id is the immutable lesson ID; expected_revision prevents replay."""


class LessonReview(VersionedAction):
    action: Literal["apply", "reject"]
    edited: LessonText | None = None


class ManualLesson(VersionedAction):
    text: LessonText
