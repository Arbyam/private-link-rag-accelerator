"""Conversation schemas (api-openapi.yaml)."""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .turn import Turn

_CONVO_ID_RE = re.compile(r"^c_[0-9A-HJKMNP-TV-Z]{26}$")


class ConversationSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    id: str = Field(..., pattern=r"^c_[0-9A-HJKMNP-TV-Z]{26}$")
    title: str = Field(..., max_length=200)
    updatedAt: datetime

    @field_validator("id")
    @classmethod
    def _ulid_format(cls, v: str) -> str:
        if not _CONVO_ID_RE.match(v):
            raise ValueError("Conversation id must match c_<26 Crockford-ULID chars>")
        return v


class Conversation(BaseModel):
    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    id: str = Field(..., min_length=1)
    title: str
    createdAt: datetime
    updatedAt: datetime
    turns: list[Turn]
    uploadedDocumentIds: list[str] | None = None
