"""Error schema (api-openapi.yaml#/components/schemas/Error)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Error(BaseModel):
    """Canonical error envelope returned by every non-2xx response."""

    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    code: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)
    details: dict[str, Any] | None = None
