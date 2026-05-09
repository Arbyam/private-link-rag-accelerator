"""ChatRequest schema (api-openapi.yaml#/components/schemas/ChatRequest)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    conversationId: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1, max_length=8000)
    useUploads: bool = True
