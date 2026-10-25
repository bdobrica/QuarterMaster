"""Owner judgments are separate from teaching and technical checks."""

from typing import Literal

from pydantic import AwareDatetime, Field

from quartermaster.contracts.sources import Contract, UUIDValue


class AnswerReviewInput(Contract):
    expected_revision: int = Field(ge=0)
    status: Literal["pending", "pass", "fail"]
    correction: str = Field(default="", max_length=4000)


class AnswerReview(AnswerReviewInput):
    schema_version: Literal["quartermaster.answer-review/v1"] = "quartermaster.answer-review/v1"
    project_id: UUIDValue
    answer_id: UUIDValue
    source_kind: Literal["test", "evaluation", "candidate", "diagnostic"]
    source_id: UUIDValue
    source_key: str = Field(max_length=100)
    revision: int = Field(ge=1)
    created_at: AwareDatetime
