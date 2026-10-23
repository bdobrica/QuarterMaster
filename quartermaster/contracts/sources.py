"""Public ingestion, reviewed mapping and evidence contracts; no provider dependency."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from quartermaster.contracts.advice import Case

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
ExactName = Annotated[str, StringConstraints(min_length=1, max_length=200)]
Label = Literal["observations", "examples", "knowledge"]


def json_uuid(value):
    # FastAPI supplies decoded Python JSON values. Accept the UUID string wire
    # representation explicitly while keeping all other contract types strict.
    if isinstance(value, str):
        if len(value) != 36:
            raise ValueError("Use a canonical UUID")
        return UUID(value)
    return value


UUIDValue = Annotated[UUID, BeforeValidator(json_uuid)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ParseOptions(Contract):
    encoding: Literal["utf-8-sig", "cp1252"] = "utf-8-sig"
    delimiter: Literal[",", ";", "\t", "|"] = ","


class FieldSummary(Contract):
    name: str
    missing: int
    likely_type: Literal["empty", "text", "number", "boolean", "date", "mixed"]
    date_candidate: bool
    formulas: int = 0
    candidate_role: Literal["input", "target", "outcome"]


class SheetPreview(Contract):
    name: str
    fields: list[FieldSummary]
    row_count: int
    samples: list[dict]


class Source(Contract):
    schema_version: Literal["quartermaster.source/v1"] = "quartermaster.source/v1"
    id: UUIDValue
    project_id: UUIDValue
    created_at: AwareDatetime
    display_name: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(gt=0)
    kind: Literal["csv", "xlsx", "md"]
    label: Label
    options: ParseOptions
    sheets: list[SheetPreview]
    markdown_headings: list[str] = Field(default_factory=list)


class TableRef(Contract):
    source_id: UUIDValue
    sheet: ExactName


class FieldRef(TableRef):
    field: ExactName


class Join(Contract):
    table: TableRef
    left: FieldRef
    right_key: ExactName


class CaseMapping(Contract):
    schema_version: Literal["quartermaster.case-mapping/v1"] = "quartermaster.case-mapping/v1"
    primary: TableRef
    grain: ShortText
    decision_time: ShortText
    inputs: list[FieldRef] = Field(min_length=1, max_length=30)
    outcomes: list[FieldRef] = Field(default_factory=list, max_length=10)
    targets: list[FieldRef] = Field(default_factory=list, max_length=10)
    joins: list[Join] = Field(default_factory=list, max_length=3)
    confirmed: Literal[True]
    inputs_available_at_decision: Literal[True]

    @field_validator("confirmed", "inputs_available_at_decision", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("An explicit boolean confirmation is required")
        return value

    @model_validator(mode="after")
    def disjoint_roles(self):
        groups = [
            [(r.source_id, r.sheet, r.field) for r in refs]
            for refs in (self.inputs, self.outcomes, self.targets)
        ]
        flattened = [r for group in groups for r in group]
        if len(set(flattened)) != len(flattened):
            raise ValueError("Fields must have distinct roles and appear only once")
        post_decision = set(groups[1] + groups[2])
        for join in self.joins:
            keys = {
                (join.left.source_id, join.left.sheet, join.left.field),
                (join.table.source_id, join.table.sheet, join.right_key),
            }
            if keys & post_decision:
                raise ValueError("Join keys cannot be mapped as outcomes or target advice")
        return self


class SourceRow(Contract):
    source_id: UUIDValue
    source_sha256: str
    sheet: str
    row: int = Field(ge=2)
    # CSV records can span physical lines; XLSX uses row for both.
    line_start: int
    line_end: int


class DerivedCase(Contract):
    schema_version: Literal["quartermaster.derived-case/v1"] = "quartermaster.derived-case/v1"
    case: Case
    mapping_id: UUIDValue
    source_rows: list[SourceRow]
    # Unreviewed source text; never ground-truth advice or part of decision_input().
    target_candidate: dict[str, str | None]


class MappingPreview(Contract):
    mapping: CaseMapping
    warnings: list[str]
    case_count: int
    samples: list[DerivedCase]


class KnowledgeSelection(Contract):
    source_ids: list[UUIDValue] = Field(max_length=100)
    expected_revision: UUIDValue | None

    @model_validator(mode="after")
    def unique_sources(self):
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("Duplicate source IDs")
        return self


class KnowledgeRevision(Contract):
    schema_version: Literal["quartermaster.knowledge/v1"] = "quartermaster.knowledge/v1"
    id: UUIDValue
    project_id: UUIDValue
    created_at: AwareDatetime
    source_ids: list[UUIDValue]
    source_hashes: dict[str, str]
    chunker_version: Literal["markdown-lines/v1"] = "markdown-lines/v1"


class Chunk(Contract):
    citation_id: UUIDValue
    source_id: UUIDValue
    source_sha256: str
    heading: str
    start: int
    end: int
    line_start: int
    line_end: int
    text: str
    sha256: str


class Evidence(Contract):
    revision_id: UUIDValue
    source: Source
    chunk: Chunk
