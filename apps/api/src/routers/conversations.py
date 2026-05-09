"""Conversations router (T082).

Endpoints (per ``contracts/api-openapi.yaml``):

* ``GET    /conversations``        — paged list of caller's own conversations
* ``POST   /conversations``        — create a new (empty) conversation
* ``GET    /conversations/{id}``   — full conversation by id
* ``DELETE /conversations/{id}``   — soft-delete (status=deletePending)

Authorization
-------------
Every route depends on :func:`current_user` (T035). There is no role gate —
any signed-in user can manage their own conversations. Cross-user access is
prevented by partition-key scoping (`/userId`) plus a defense-in-depth
``userId == caller.oid`` check inside :class:`ConversationsRepo` (SC-011).

ID format
---------
Conversation ids follow the OpenAPI pattern ``^c_[0-9A-HJKMNP-TV-Z]{26}$``,
i.e. a Crockford-base32 ULID prefixed with ``c_`` (data-model.md §2). The
helper :func:`new_conversation_id` builds one without adding a new
dependency — Crockford alphabet, 48-bit ms timestamp + 80-bit random tail.

404 vs 403
----------
For ``GET`` / ``DELETE`` on someone else's conversation we deliberately
return ``404`` (not ``403``) so we don't leak existence of another user's
record (SC-011). The repo's partition-key read makes a true cross-user hit
already impossible; the explicit ``userId`` check is belt + braces.
"""

from __future__ import annotations

import secrets
import time
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field

from ..middleware.error_handler import NotFoundError
from ..middleware.logging import get_logger
from ..models import CurrentUser
from ..models.conversation import Conversation, ConversationSummary
from ..services.auth import current_user
from ..services.cosmos import (
    ConversationRecord,
    ConversationsRepo,
    get_conversations_repo,
)

_log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Local request/response models
# ---------------------------------------------------------------------------


class ConversationListResponse(BaseModel):
    """Response body for ``GET /conversations`` (matches openapi schema)."""

    model_config = ConfigDict(populate_by_name=True)

    items: list[ConversationSummary]
    continuationToken: str | None = None


class CreateConversationRequest(BaseModel):
    """Optional body for ``POST /conversations`` — only ``title`` is accepted."""

    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    title: str | None = Field(default=None, max_length=200)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_DEFAULT_TITLE = "New conversation"


def new_conversation_id() -> str:
    """Return a fresh ``c_<26-char Crockford-ULID>`` id.

    48-bit ms timestamp || 80-bit cryptographic random; encoded to 26
    base32-Crockford characters (matches ULID spec, no external dep).
    """
    ts_ms = int(time.time() * 1000) & ((1 << 48) - 1)
    rand = secrets.randbits(80)
    n = (ts_ms << 80) | rand
    out = []
    for _ in range(26):
        out.append(_CROCKFORD[n & 0x1F])
        n >>= 5
    return "c_" + "".join(reversed(out))


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _to_conversation(record: ConversationRecord) -> Conversation:
    """Map a Cosmos `ConversationRecord` to the public `Conversation` DTO."""
    return Conversation(
        id=record.id,
        title=record.title,
        createdAt=record.createdAt,
        updatedAt=record.updatedAt,
        turns=list(record.turns),
        uploadedDocumentIds=list(record.uploadedDocumentIds),
    )


def _to_summary(record: ConversationRecord) -> ConversationSummary:
    return ConversationSummary(
        id=record.id,
        title=record.title,
        updatedAt=record.updatedAt,
    )


async def load_conversation_for_caller(
    repo: ConversationsRepo,
    conversation_id: str,
    user_oid: str,
) -> ConversationRecord:
    """Read a conversation, returning 404 (no leak) if the caller isn't the owner.

    Exported so other routers (``/chat``, ``/citations``) can reuse the same
    scope-check + 404 semantics.
    """
    try:
        record = await repo.get(conversation_id, user_oid)
    except NotFoundError:
        raise NotFoundError("Conversation not found") from None
    if record.userId != user_oid or record.status == "deletePending":
        # Defense in depth — partition-key read already prevents cross-user
        # hits, and we hide soft-deleted rows behind a 404.
        raise NotFoundError("Conversation not found")
    return record


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


router = APIRouter(
    prefix="/conversations",
    tags=["conversations"],
    dependencies=[Depends(current_user)],
)


# Thin wrapper around `get_conversations_repo` so its optional `settings`
# kwarg is hidden from FastAPI's request-body inference (the upstream factory
# accepts `settings: Settings | None = None`, which FastAPI would otherwise
# misclassify as a JSON body field on routes that already have a Pydantic
# request body).
async def _conversations_repo() -> ConversationsRepo:
    return await get_conversations_repo()


@router.get(
    "",
    response_model=ConversationListResponse,
    summary="List the caller's conversations (most-recent first)",
)
async def list_conversations(
    user: Annotated[CurrentUser, Depends(current_user)],
    repo: Annotated[ConversationsRepo, Depends(_conversations_repo)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    continuationToken: Annotated[str | None, Query()] = None,
) -> ConversationListResponse:
    _log.info("conversations_list_start", user_oid=user.oid, limit=limit)
    records, next_token = await repo.list_for_user(
        user_oid=user.oid,
        limit=limit,
        continuation=continuationToken,
    )
    items = [_to_summary(r) for r in records]
    _log.info(
        "conversations_list_done",
        user_oid=user.oid,
        count=len(items),
        has_more=bool(next_token),
    )
    return ConversationListResponse(items=items, continuationToken=next_token)


@router.post(
    "",
    response_model=Conversation,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new (empty) conversation",
)
async def create_conversation(
    user: Annotated[CurrentUser, Depends(current_user)],
    repo: Annotated[ConversationsRepo, Depends(_conversations_repo)],
    body: CreateConversationRequest = CreateConversationRequest(),  # noqa: B008
) -> Conversation:
    title = (body.title if body.title else _DEFAULT_TITLE) or _DEFAULT_TITLE
    now = _utcnow()
    record = ConversationRecord(
        id=new_conversation_id(),
        userId=user.oid,
        title=title,
        createdAt=now,
        updatedAt=now,
        turns=[],
        uploadedDocumentIds=[],
        status="active",
    )
    _log.info(
        "conversation_create_start",
        user_oid=user.oid,
        conversation_id=record.id,
    )
    saved = await repo.upsert(record)
    _log.info(
        "conversation_create_done",
        user_oid=user.oid,
        conversation_id=saved.id,
    )
    return _to_conversation(saved)


@router.get(
    "/{conversationId}",
    response_model=Conversation,
    summary="Get full conversation (including turns + citations)",
    responses={404: {"description": "Not found or not owned by caller"}},
)
async def get_conversation(
    user: Annotated[CurrentUser, Depends(current_user)],
    repo: Annotated[ConversationsRepo, Depends(_conversations_repo)],
    conversationId: Annotated[str, Path(min_length=1, max_length=64)],
) -> Conversation:
    _log.info(
        "conversation_get_start",
        user_oid=user.oid,
        conversation_id=conversationId,
    )
    record = await load_conversation_for_caller(repo, conversationId, user.oid)
    _log.info(
        "conversation_get_done",
        user_oid=user.oid,
        conversation_id=record.id,
    )
    return _to_conversation(record)


@router.delete(
    "/{conversationId}",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Soft-delete the conversation (status=deletePending)",
    responses={
        202: {"description": "Accepted; deletion in progress"},
        404: {"description": "Not found or not owned by caller"},
    },
)
async def delete_conversation(
    user: Annotated[CurrentUser, Depends(current_user)],
    repo: Annotated[ConversationsRepo, Depends(_conversations_repo)],
    conversationId: Annotated[str, Path(min_length=1, max_length=64)],
) -> Response:
    _log.info(
        "conversation_delete_start",
        user_oid=user.oid,
        conversation_id=conversationId,
    )
    record = await load_conversation_for_caller(repo, conversationId, user.oid)
    record.status = "deletePending"
    record.updatedAt = _utcnow()
    await repo.upsert(record)
    _log.info(
        "conversation_delete_done",
        user_oid=user.oid,
        conversation_id=record.id,
    )
    return Response(status_code=status.HTTP_202_ACCEPTED)


__all__ = [
    "ConversationListResponse",
    "CreateConversationRequest",
    "load_conversation_for_caller",
    "new_conversation_id",
    "router",
]
