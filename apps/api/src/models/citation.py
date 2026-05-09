"""Citation schema (api-openapi.yaml#/components/schemas/Citation)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class CitationScope(StrEnum):
    SHARED = "shared"
    USER = "user"


class Citation(BaseModel):
    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    passageId: str = Field(..., min_length=1)
    documentId: str = Field(..., min_length=1)
    scope: CitationScope
    page: int = Field(..., ge=1)
    snippet: str | None = None
    score: float | None = Field(default=None, ge=0.0, le=1.0)
