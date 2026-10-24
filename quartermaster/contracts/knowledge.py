"""Owner-reviewed article changes, separate from lessons and training labels."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, StringConstraints, field_validator

from quartermaster.contracts.interview import Consent, VersionedAction
from quartermaster.contracts.sources import Contract, UUIDValue
from quartermaster.contracts.teaching import LessonDisclosure

ArticleText = Annotated[str, StringConstraints(min_length=1, max_length=12000)]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]


class ArticleContent(Contract):
    title: Title
    text: ArticleText

    @field_validator("text")
    @classmethod
    def readable_article(cls, value):
        if (
            not value.strip()
            or any(ord(c) < 32 and c not in "\t\r\n" for c in value)
            or "\x7f" in value
        ):
            raise ValueError("Supply a nonempty text article without binary controls")
        return value


class KnowledgeDraft(ArticleContent):
    source_id: UUIDValue | None
    expected_revision: UUIDValue | None


class KnowledgeRequest(Contract):
    source_id: UUIDValue | None
    expected_revision: UUIDValue | None
    instruction: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
    ]


class KnowledgeProposal(Contract):
    schema_version: Literal["quartermaster.knowledge-proposal/v1"] = (
        "quartermaster.knowledge-proposal/v1"
    )
    id: UUIDValue
    project_id: UUIDValue
    revision: int = Field(ge=1)
    created_at: AwareDatetime
    source_id: UUIDValue | None
    expected_revision: UUIDValue | None
    before: str
    instruction: str | None = None
    origin: Literal["OWNER_DRAFT", "AI_DRAFT"]
    status: Literal["prepared", "sending", "pending", "applied", "rejected", "failed"]
    content: ArticleContent | None = None
    disclosure: LessonDisclosure | None = None
    consented_at: AwareDatetime | None = None
    error: str | None = None
    applied_revision: UUIDValue | None = None
    applied_source: UUIDValue | None = None


class KnowledgeSend(Consent):
    pass


class KnowledgeReview(VersionedAction):
    action: Literal["apply", "reject"]


class KnowledgeReplay(Contract):
    original_test: UUIDValue
    unseen_situation: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
    ]
