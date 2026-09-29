from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProductInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=3, max_length=120)
    details: str = Field(default="", max_length=3000)
    material: str | None = Field(default=None, min_length=2, max_length=100)


class Draft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=3, max_length=60)
    description: str = Field(min_length=10, max_length=4000)
    material: str | None = Field(default=None, min_length=2, max_length=100)
    requires_review: Literal[True] = True

    @field_validator("title", "description")
    @classmethod
    def plain_text(cls, value):
        if "<" in value or ">" in value:
            raise ValueError("A saída deve ser texto simples, sem HTML.")
        return value


class DraftResponse(BaseModel):
    request_id: str
    mode: Literal["demo", "gemini"]
    model: str
    prompt_version: str
    latency_ms: float
    input_tokens: int | None
    output_tokens: int | None
    estimated_cost_usd: float | None
    draft: Draft
