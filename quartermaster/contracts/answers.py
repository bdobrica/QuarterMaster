"""Answer format configured once per adviser."""

from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from quartermaster.contracts.sources import Contract

Short = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class NumberAnswer(Contract):
    kind: Literal["number"]
    unit: Short


class CategoryAnswer(Contract):
    kind: Literal["category"]
    choices: list[Short] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def unique(self):
        if len(set(self.choices)) != len(self.choices):
            raise ValueError("Choose each answer once")
        return self


AnswerFormat = Annotated[NumberAnswer | CategoryAnswer, Field(discriminator="kind")]
