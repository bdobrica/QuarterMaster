"""Public collection lineage and personal supervision, independent of Muster internals."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, StringConstraints, field_validator

from quartermaster.contracts.interview import VersionedAction
from quartermaster.contracts.sources import Contract, UUIDValue

Digest = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
Short = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class NumberTarget(Contract):
    kind: Literal["number"]
    value: float = Field(allow_inf_nan=False)
    unit: Short


class CategoryTarget(Contract):
    kind: Literal["category"]
    value: Short


Target = Annotated[NumberTarget | CategoryTarget, Field(discriminator="kind")]


class DecisionInput(VersionedAction):
    input_fields: list[Short] = Field(min_length=1, max_length=30)
    # Anything not explicitly selected is withheld from decision-time input.
    inputs_available_at_decision: Literal[True]
    target: Target
    reasoning: str = Field(default="", max_length=4000)

    @field_validator("inputs_available_at_decision", mode="before")
    @classmethod
    def explicit_inputs(cls, value):
        if value is not True:
            raise ValueError("Confirm decision-time availability explicitly")
        return value


class OwnerDecision(Contract):
    schema_version: Literal["quartermaster.owner-decision/v1"] = "quartermaster.owner-decision/v1"
    id: UUIDValue
    project_id: UUIDValue
    revision: int = Field(ge=1)
    created_at: AwareDatetime
    import_id: UUIDValue
    manifest_sha256: Digest
    example_id: str
    input_fields: list[str]
    target: Target
    reasoning: str
    origin: Literal["OWNER_REVIEWED"] = "OWNER_REVIEWED"


class MusterImport(Contract):
    schema_version: Literal["quartermaster.muster-import/v1"] = "quartermaster.muster-import/v1"
    id: UUIDValue
    project_id: UUIDValue
    created_at: AwareDatetime
    manifest_sha256: Digest
    collection_name: str
    collection_id: int
    publication_version: int
    schema_id: str
    reviewed: int
    unreviewed: int
    # Article sources retain exact bytes; original revisions/provenance stay in the bundle.
    knowledge_sources: dict[str, UUIDValue]


class ImportCollection(Contract):
    publication: Digest


class UseKnowledge(Contract):
    expected_revision: UUIDValue | None
