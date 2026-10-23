"""Public interview, disclosure and review contracts. No examples are approved here."""

from typing import Literal

from pydantic import AwareDatetime, Field, field_validator

from quartermaster.contracts.adviser import AdviserSpec, DecisionDefinition
from quartermaster.contracts.project import Mission, Name
from quartermaster.contracts.sources import Contract, UUIDValue

Topic = Literal[
    "mission",
    "business_goal",
    "available_choices",
    "target_behavior",
    "case_grain",
    "decision_inputs",
    "success_and_harm",
]


class InterviewAnswers(Contract):
    mission: Mission | None = None
    business_goal: Mission | None = None
    available_choices: Mission | None = None
    target_behavior: Mission | None = None
    case_grain: Mission | None = None
    decision_inputs: Mission | None = None
    success_and_harm: Mission | None = None


class Interpretation(Contract):
    """The provider may propose these fields, never model pins or training labels."""

    name: Name
    mission: Mission
    business_goal: Mission | None
    decision_definition: DecisionDefinition


class VersionedAction(Contract):
    expected_revision: int = Field(ge=0)


class Answer(VersionedAction):
    topic: Topic
    answer: Mission


class Prepare(VersionedAction):
    excerpt_source_ids: list[UUIDValue] = Field(default_factory=list, max_length=3)

    @field_validator("excerpt_source_ids")
    @classmethod
    def unique_excerpts(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("Choose each source once")
        return value


class Consent(VersionedAction):
    turn_id: UUIDValue
    disclosure_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    consent: Literal[True]

    @field_validator("consent", mode="before")
    @classmethod
    def explicit_consent(cls, value):
        if value is not True:
            raise ValueError("Explicit consent required")
        return value


class ProviderTest(Contract):
    consent: Literal[True]

    _explicit_consent = field_validator("consent", mode="before")(Consent.explicit_consent.__func__)


class Review(VersionedAction):
    action: Literal["apply", "reject"]
    edited: Interpretation | None = None


class PreparedTurn(Contract):
    id: UUIDValue
    endpoint: str
    model: str
    adviser_revision: int
    system: str
    context: str
    response_schema: dict
    disclosure_sha256: str
    input_bytes: int


class Interview(Contract):
    schema_version: Literal["quartermaster.interview/v1"] = "quartermaster.interview/v1"
    project_id: UUIDValue
    revision: int = Field(ge=0)
    created_at: AwareDatetime
    status: Literal["answering", "prepared", "sending", "review", "rejected", "failed", "applied"]
    # M3 has no reviewed TrainingExample store. Source labels/targets never change this.
    readiness: Literal["needs_examples"] = "needs_examples"
    answers: InterviewAnswers
    prepared: PreparedTurn | None = None
    consented_at: AwareDatetime | None = None
    proposal: AdviserSpec | None = None
    proposal_origin: Literal["AI_DRAFT", "OWNER_DRAFT"] | None = None
    base_adviser_revision: int | None = None
    error: str | None = None
