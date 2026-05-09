"""Turn schema (api-openapi.yaml#/components/schemas/Turn)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from .citation import Citation


class TurnRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class Turn(BaseModel):
    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    turnId: str = Field(..., min_length=1)
    role: TurnRole
    content: str
    citations: list[Citation] | None = None
    createdAt: datetime
