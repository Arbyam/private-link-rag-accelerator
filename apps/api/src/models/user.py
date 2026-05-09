"""GET /me response schema (inline in api-openapi.yaml).

Also defines the internal `CurrentUser` model that the FastAPI auth dependency
yields. `Me` is the wire-shape (camelCase, optional groups); `CurrentUser` is
the snake_case internal type passed between services.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

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


class CurrentUser(BaseModel):
    """Internal identity object yielded by the `current_user` FastAPI dependency.

    Mirrors the shape used by the web tier (`apps/web/src/lib/auth.ts`):
    role is "admin" iff `ADMIN_GROUP_OBJECT_ID` ∈ groups, else "user".
    """

    model_config = ConfigDict(str_strip_whitespace=True, frozen=True)

    oid: str = Field(..., min_length=1)
    display_name: str = Field(..., min_length=1)
    role: Literal["admin", "user"]
    groups: list[str] = Field(default_factory=list)

    def to_me(self) -> Me:
        return Me(
            oid=self.oid,
            displayName=self.display_name,
            role=UserRole(self.role),
            groups=list(self.groups),
        )
