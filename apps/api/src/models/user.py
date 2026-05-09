"""GET /me response schema (inline in api-openapi.yaml)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class UserRole(StrEnum):
    USER = "user"
    ADMIN = "admin"


class Me(BaseModel):
    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    oid: str = Field(..., min_length=1)
    displayName: str = Field(..., min_length=1)
    role: UserRole
    groups: list[str] | None = None
