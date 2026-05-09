"""ChatRequest schema (api-openapi.yaml#/components/schemas/ChatRequest).

Also exports the LLM-service IO models used by `services/llm.py` (T040):
- ChatMessage      — input messages for chat completions
- ChatResponse     — non-streaming chat completion result
- ChatStreamEvent  — SSE event payloads compatible with the web client
  (`apps/web/src/lib/api.ts#ChatStreamEvent`).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    conversationId: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1, max_length=8000)
    useUploads: bool = True


class ChatRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ChatMessage(BaseModel):
    """A single message in a chat completion request."""

    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=False)

    role: ChatRole
    content: str = Field(..., min_length=0)


class ChatUsage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    prompt_tokens: int = Field(..., ge=0)
    completion_tokens: int = Field(..., ge=0)
    total_tokens: int = Field(..., ge=0)


class ChatResponse(BaseModel):
    """Non-streaming chat completion result."""

    model_config = ConfigDict(populate_by_name=True)

    content: str
    finish_reason: str | None = None
    usage: ChatUsage | None = None
    model: str | None = None


# SSE event payloads. `type` mirrors the web client's discriminator.
# See `apps/web/src/lib/api.ts` ChatStreamEvent for the wire shape.
class _StreamEventBase(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class ChatStreamDelta(_StreamEventBase):
    type: Literal["delta"] = "delta"
    data: dict[str, str]  # {"text": "..."}


class ChatStreamCitations(_StreamEventBase):
    type: Literal["citations"] = "citations"
    data: dict[str, Any]  # {"citations": [...]}


class ChatStreamDone(_StreamEventBase):
    type: Literal["done"] = "done"
    data: dict[str, Any] = Field(default_factory=dict)


class ChatStreamError(_StreamEventBase):
    type: Literal["error"] = "error"
    data: dict[str, Any]  # {"code"?, "message"}


ChatStreamEvent = ChatStreamDelta | ChatStreamCitations | ChatStreamDone | ChatStreamError
