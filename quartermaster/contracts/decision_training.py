"""Isolated synthetic decision experiment; never a full-advice training job."""

import hashlib
import json
from collections import Counter
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, JsonValue, StringConstraints, model_validator

from quartermaster.contracts.advice import DecisionOnly
from quartermaster.contracts.evaluation import Digest
from quartermaster.contracts.sources import Contract, ShortText, UUIDValue

# Exact system bytes used by the completed explicit-contract baseline.
SYSTEM_SHA256 = "b2eef451cfc1e22b4930beefb7de6365ae52b388548aca6da7740927cc66192e"
ContextText = Annotated[str, StringConstraints(min_length=1, max_length=12000)]


def content_hash(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate context key")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError("Non-finite JSON context value")


class DecisionQuestion(Contract):
    situation: Annotated[str, StringConstraints(min_length=1, max_length=4000)]


class SyntheticDefinition(Contract):
    id: ShortText
    text: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    origin: Literal["AI_DRAFT_SYNTHETIC_DEFINITION"]


class DecisionContext(Contract):
    case: DecisionQuestion
    structured_inputs: dict[str, JsonValue] = Field(max_length=20)
    reference_definitions: list[SyntheticDefinition] = Field(min_length=1, max_length=10)
    approved_lessons: list[ShortText] = Field(max_length=0)


class DecisionReview(Contract):
    status: Literal["pending", "approved", "revise", "rejected"] = "pending"
    reviewer: Literal["owner"] | None = None
    content_sha256: Digest | None = None
    notes: str = Field(default="", max_length=4000)


class DecisionExample(Contract):
    model_config = ConfigDict(revalidate_instances="always")

    id: UUIDValue
    label: ShortText
    domain: ShortText
    origin: Literal["AI_DRAFT", "OWNER_DRAFT"]
    context: ContextText
    target: DecisionOnly
    review: DecisionReview = Field(default_factory=DecisionReview)

    @model_validator(mode="after")
    def integrity(self):
        # Validate a narrow context without changing its captured serialization.
        DecisionContext.model_validate(
            json.loads(self.context, object_pairs_hook=unique_keys, parse_constant=reject_constant)
        )
        if self.review.status == "approved" and (
            self.review.reviewer != "owner" or self.review.content_sha256 != self.content_sha256()
        ):
            raise ValueError("Approval must bind the owner's review to the final example")
        return self

    def content_sha256(self):
        return content_hash(self.model_dump(mode="json", exclude={"review"}))

    def identity(self):
        # Ignore synthetic definition IDs, formatting and case UUIDs when checking reuse.
        context = DecisionContext.model_validate_json(self.context)
        return content_hash(
            {
                "question": " ".join(context.case.situation.casefold().split()),
                "values": context.structured_inputs,
            }
        )


class DecisionReviewPack(Contract):
    model_config = ConfigDict(revalidate_instances="always")

    schema_version: Literal["quartermaster.decision-review-pack/v1"] = (
        "quartermaster.decision-review-pack/v1"
    )
    purpose: Literal["teaching", "evaluation"]
    system: str = Field(min_length=1, max_length=6000)
    examples: list[DecisionExample] = Field(min_length=1, max_length=90)

    @model_validator(mode="after")
    def integrity(self):
        if hashlib.sha256(self.system.encode()).hexdigest() != SYSTEM_SHA256:
            raise ValueError("Use the exact baseline system contract")
        if len({e.id for e in self.examples}) != len(self.examples) or len(
            {e.identity() for e in self.examples}
        ) != len(self.examples):
            raise ValueError("Duplicate example ID or question/values")
        return self


class DecisionRecipe(Contract):
    schema_version: Literal["quartermaster.decision-recipe/v1"] = "quartermaster.decision-recipe/v1"
    steps: Literal[120] = 120
    max_length: Literal[2048] = 2048
    rank: Literal[4] = 4
    alpha: Literal[8] = 8
    learning_rate: Literal[0.00001] = 0.00001
    seed: Literal[17] = 17
    precision: Literal["float32"] = "float32"
    seconds: Literal[3600] = 3600


class DecisionJob(Contract):
    schema_version: Literal["quartermaster.decision-training-job/v1"] = (
        "quartermaster.decision-training-job/v1"
    )
    id: UUIDValue
    model_id: Literal["Qwen/Qwen3.5-0.8B"] = "Qwen/Qwen3.5-0.8B"
    model_revision: Literal["2fc06364715b967f1860aea9cf38778875588b17"] = (
        "2fc06364715b967f1860aea9cf38778875588b17"
    )
    supervision: DecisionReviewPack
    # Only a commitment is mounted in the trainer; no evaluation questions or labels.
    evaluation_sha256: Digest
    dataset_sha256: Digest
    recipe: DecisionRecipe = Field(default_factory=DecisionRecipe)

    @model_validator(mode="after")
    def reviewed(self):
        examples = self.supervision.examples
        counts = Counter(e.target.decision for e in examples)
        if (
            self.supervision.purpose != "teaching"
            or not 45 <= len(examples) <= 90
            or any(e.review.status != "approved" for e in examples)
            or set(counts) != {"answer", "clarify", "abstain"}
            or len(set(counts.values())) != 1
            or len({e.domain for e in examples}) < 3
        ):
            raise ValueError("Use balanced, explicitly reviewed synthetic supervision")
        return self


class DecisionManifest(Contract):
    schema_version: Literal["quartermaster.decision-training-artifacts/v1"] = (
        "quartermaster.decision-training-artifacts/v1"
    )
    job_id: UUIDValue
    job_sha256: Digest
    dataset_sha256: Digest
    recipe: DecisionRecipe
    completed_steps: Literal[120]
    training_loss: float = Field(allow_inf_nan=False)
    peak_vram_bytes: int = Field(ge=0)
    files: dict[ShortText, Digest] = Field(min_length=2, max_length=3)
