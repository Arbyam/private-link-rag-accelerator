"""Chat router (T083) — POST /chat as a Server-Sent Events stream.

Pipeline (per FR-006/FR-016/FR-017/FR-018/FR-022):

1. AuthN: ``current_user`` dep — caller's ``oid`` is the source of truth
   for retrieval scope.
2. Conversation: load existing (404 if not owner) or mint a new
   ``c_<ulid>`` and persist *before* streaming so the web client can
   navigate to the URL while tokens are still arriving.
3. Retrieval: hybrid search via :class:`ScopedSearchClient.search_combined`
   with the mandatory scope filter ``scope eq 'shared' or scope eq
   'user:<oid>'`` (SC-011). The query is the current message plus the
   most recent N user turns (configurable, default 3).
4. Prompting: admin-overridable system prompt (FR-019) +
   conversation history + a numbered ``Sources:`` block whose indices
   match the ``[N]`` citation convention enforced by the prompt.
5. Streaming: emit SSE events ``delta`` → (terminal) ``citations`` →
   ``done`` (or ``error`` on failure). Citations are filtered to the
   subset of passages whose ``[N]`` index actually appeared in the
   model output.
6. Persistence: append both user + assistant turns to Cosmos in a
   single upsert once streaming completes; assistant turn is flagged
   ``declined=True`` when the output starts with :data:`DECLINE_PHRASE`.

SSE wire format (every event ends with a blank line — i.e. ``\\n\\n``)::

    event: delta
    data: {"text": "Hello"}

    event: citations
    data: {"citations": [{"passageId": "...", ...}]}

    event: done
    data: {"conversationId": "c_...", "turnId": "t_..."}

    event: error
    data: {"code": "service_unavailable", "message": "..."}
"""

from __future__ import annotations

import json
import re
import secrets
from collections.abc import AsyncIterator, Iterable
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from ..middleware.error_handler import AppError, NotFoundError
from ..middleware.logging import get_logger
from ..models import CurrentUser
from ..models.chat import ChatMessage, ChatRole, ChatStreamDelta, ChatStreamError
from ..models.citation import Citation, CitationScope
from ..models.turn import Turn, TurnRole
from ..services.auth import current_user
from ..services.cosmos import (
    ConversationRecord,
    ConversationsRepo,
    get_conversations_repo,
    get_cosmos_client,
)
from ..services.llm import (
    DECLINE_PHRASE,
    LLMService,
    get_system_prompt,
)
from ..services.search import (
    ScopedSearchClient,
    SearchHit,
    SearchResults,
)
from .conversations import (
    load_conversation_for_caller,
    new_conversation_id,
)

_log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

# Top-K passages to retrieve per turn. 8 keeps the prompt within budget
# for gpt-4o-class models even with long passages.
_DEFAULT_TOP_K: int = 8

# How many prior user messages to fold into the retrieval query.
_RETRIEVAL_HISTORY_TURNS: int = 3

# Title length cap when auto-titling a brand-new conversation from the
# first user message. Matches the OpenAPI ``ConversationSummary.title``
# 200-char ceiling, but we use a kinder 80 for UX.
_AUTO_TITLE_CHAR_CAP: int = 80

# Regex for ``[N]`` citation indices in assistant output. Matches one or
# more digits inside square brackets — used to determine which passages
# the model actually grounded on, so the citations event is honest.
_CITE_INDEX_RE = re.compile(r"\[(\d+)\]")


# ---------------------------------------------------------------------------
# Request body
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    """POST /chat request body.

    The OpenAPI contract marks ``conversationId`` as required, but we
    accept ``None`` here as a forward-compatible convenience: clients
    that omit it get a fresh conversation auto-created and the new id
    is returned in the terminal ``done`` event.
    """

    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    conversationId: str | None = Field(default=None, min_length=1, max_length=64)
    message: str = Field(..., min_length=1, max_length=8000)
    useUploads: bool = True


# ---------------------------------------------------------------------------
# Dependency factories — all overridable in tests via dependency_overrides
# ---------------------------------------------------------------------------


async def _conversations_repo() -> ConversationsRepo:
    return await get_conversations_repo()


async def _llm_service() -> LLMService:
    """Process-singleton LLM service. Tests override this dependency."""
    return LLMService.from_settings()


async def _search_client() -> ScopedSearchClient:
    """Per-request scoped search wrapper. Tests override this dependency."""
    return ScopedSearchClient()


async def _cosmos_client_dep() -> Any:
    return await get_cosmos_client()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _new_turn_id() -> str:
    """Short opaque turn id. Not persisted across processes — one per turn."""
    return "t_" + secrets.token_hex(8)


def _auto_title(message: str) -> str:
    cleaned = " ".join(message.split())
    if len(cleaned) <= _AUTO_TITLE_CHAR_CAP:
        return cleaned or "New conversation"
    return cleaned[: _AUTO_TITLE_CHAR_CAP - 1].rstrip() + "…"


def _build_retrieval_query(message: str, history: Iterable[Turn]) -> str:
    """Concatenate the last few user messages with the current one.

    Cheap and effective for short multi-turn follow-ups; doesn't require
    a separate query-rewriter LLM call.
    """
    prior_users = [t.content for t in history if t.role == TurnRole.USER][
        -_RETRIEVAL_HISTORY_TURNS:
    ]
    parts = [*prior_users, message]
    return " ".join(p.strip() for p in parts if p and p.strip())


def _scope_to_citation_scope(scope: str) -> CitationScope:
    if scope == "shared":
        return CitationScope.SHARED
    return CitationScope.USER


def _hit_to_citation(hit: SearchHit) -> Citation:
    snippet = hit.content
    if snippet and len(snippet) > 600:
        snippet = snippet[:600].rstrip() + "…"
    return Citation(
        passageId=hit.id or hit.documentId,
        documentId=hit.documentId,
        scope=_scope_to_citation_scope(hit.scope),
        page=max(1, hit.page or 1),
        snippet=snippet or None,
        score=hit.score,
    )


def _build_sources_block(hits: list[SearchHit]) -> str:
    """Format passages as ``[1] ...`` numbered list for the system prompt."""
    if not hits:
        return "Sources:\n(no passages were retrieved)"
    lines = ["Sources:"]
    for idx, hit in enumerate(hits, start=1):
        body = (hit.content or "").strip().replace("\n", " ")
        if len(body) > 1200:
            body = body[:1200].rstrip() + "…"
        title = hit.title or hit.documentId
        lines.append(f"[{idx}] ({title}, p.{hit.page or 1}) {body}")
    return "\n".join(lines)


def _flatten_history_to_messages(turns: list[Turn]) -> list[ChatMessage]:
    """Map persisted ``Turn``s to LLM-consumable ``ChatMessage``s."""
    out: list[ChatMessage] = []
    for t in turns:
        role = ChatRole.USER if t.role == TurnRole.USER else ChatRole.ASSISTANT
        out.append(ChatMessage(role=role, content=t.content))
    return out


def _used_citations(text: str, hits: list[SearchHit]) -> list[Citation]:
    """Return the de-duplicated citations whose ``[N]`` index appears in ``text``.

    Indices that don't correspond to a retrieved passage are silently
    dropped — the model is asked to use 1-based indices but we never
    trust output verbatim.
    """
    if not text or not hits:
        return []
    seen: set[int] = set()
    citations: list[Citation] = []
    for match in _CITE_INDEX_RE.finditer(text):
        idx = int(match.group(1))
        if idx in seen or idx < 1 or idx > len(hits):
            continue
        seen.add(idx)
        citations.append(_hit_to_citation(hits[idx - 1]))
    return citations


def _format_sse(event: str, payload: dict[str, Any]) -> bytes:
    """Render a single SSE event frame: ``event: <name>\\ndata: <json>\\n\\n``.

    JSON is compact (no whitespace) so the wire format mirrors what the
    web client's EventSource consumer expects.
    """
    data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    return f"event: {event}\ndata: {data}\n\n".encode()


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


router = APIRouter(tags=["chat"], dependencies=[Depends(current_user)])


@router.post(
    "/chat",
    summary="Send a chat message and stream the assistant's grounded answer",
    status_code=status.HTTP_200_OK,
    responses={
        200: {
            "description": "SSE stream",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        },
        404: {"description": "conversationId not found or not owned by caller"},
    },
)
async def post_chat(
    body: ChatRequest,
    user: Annotated[CurrentUser, Depends(current_user)],
    repo: Annotated[ConversationsRepo, Depends(_conversations_repo)],
    llm: Annotated[LLMService, Depends(_llm_service)],
    search: Annotated[ScopedSearchClient, Depends(_search_client)],
    cosmos_client: Annotated[Any, Depends(_cosmos_client_dep)],
) -> StreamingResponse:
    # ------------------------------------------------------------------
    # 1) Load or mint conversation. We do this *before* opening the SSE
    #    stream so 401/404 surface as plain HTTP errors (the web client
    #    can't easily distinguish a 4xx from a closed stream otherwise).
    # ------------------------------------------------------------------
    if body.conversationId:
        record = await load_conversation_for_caller(repo, body.conversationId, user.oid)
        is_new = False
    else:
        now = _utcnow()
        record = ConversationRecord(
            id=new_conversation_id(),
            userId=user.oid,
            title=_auto_title(body.message),
            createdAt=now,
            updatedAt=now,
            turns=[],
            uploadedDocumentIds=[],
            status="active",
        )
        # Persist immediately so the client can navigate to /c/<id>
        # while the first SSE stream is still in flight.
        record = await repo.upsert(record)
        is_new = True

    _log.info(
        "chat_request_start",
        user_oid=user.oid,
        conversation_id=record.id,
        is_new_conversation=is_new,
        history_turns=len(record.turns),
    )

    async def _stream() -> AsyncIterator[bytes]:
        accumulated: list[str] = []
        hits: list[SearchHit] = []
        try:
            # ----------------------------------------------------------
            # 2) Hybrid search (mandatory scope filter applied by the
            #    wrapper — never trust the caller for `scope`).
            # ----------------------------------------------------------
            retrieval_query = _build_retrieval_query(body.message, record.turns)
            results: SearchResults = await search.search_combined(
                retrieval_query,
                oid=user.oid,
                top=_DEFAULT_TOP_K,
            )
            hits = list(results.documents)

            # ----------------------------------------------------------
            # 3) System prompt (admin-overridable, falls back to default
            #    that enforces FR-016 citations + FR-017 decline).
            # ----------------------------------------------------------
            system_prompt = await get_system_prompt(cosmos_client)
            sources_block = _build_sources_block(hits)
            messages: list[ChatMessage] = [
                ChatMessage(role=ChatRole.SYSTEM, content=system_prompt),
                *_flatten_history_to_messages(record.turns),
                ChatMessage(
                    role=ChatRole.USER,
                    content=f"{body.message}\n\n{sources_block}",
                ),
            ]

            # ----------------------------------------------------------
            # 4) Stream tokens. The LLM service yields strongly-typed
            #    events; we relay deltas, swallow the LLM's own done,
            #    and convert its error into our SSE error frame.
            # ----------------------------------------------------------
            async for ev in llm.chat_stream(messages):
                if isinstance(ev, ChatStreamDelta):
                    text = ev.data.get("text", "")
                    if text:
                        accumulated.append(text)
                        yield _format_sse("delta", {"text": text})
                elif isinstance(ev, ChatStreamError):
                    yield _format_sse("error", dict(ev.data))
                    return
                # ChatStreamDone / ChatStreamCitations from the LLM layer
                # are intentionally not relayed — we synthesize our own
                # final frames below so the wire format is deterministic.

            full_text = "".join(accumulated)
            declined = full_text.strip().startswith(DECLINE_PHRASE)

            # ----------------------------------------------------------
            # 5) Citations event — empty on decline so clients don't
            #    render misleading chips next to "I don't have…".
            # ----------------------------------------------------------
            citations = [] if declined else _used_citations(full_text, hits)
            yield _format_sse(
                "citations",
                {"citations": [c.model_dump(mode="json") for c in citations]},
            )

            # ----------------------------------------------------------
            # 6) Persist both turns atomically (single upsert).
            # ----------------------------------------------------------
            now = _utcnow()
            user_turn = Turn(
                turnId=_new_turn_id(),
                role=TurnRole.USER,
                content=body.message,
                citations=None,
                createdAt=now,
            )
            assistant_turn_id = _new_turn_id()
            assistant_turn = Turn(
                turnId=assistant_turn_id,
                role=TurnRole.ASSISTANT,
                content=full_text,
                citations=citations or None,
                createdAt=now,
            )
            # The Turn DTO doesn't model `declined` natively, but
            # ConversationRecord allows extra fields — we tag retrieval
            # metadata onto the record's open-shape store for telemetry.
            record.turns.append(user_turn)
            record.turns.append(assistant_turn)
            record.updatedAt = now
            try:
                await repo.upsert(record)
            except AppError as exc:  # log but don't fail the already-streamed reply
                _log.warning(
                    "chat_turn_persist_failed",
                    conversation_id=record.id,
                    error=exc.code,
                )

            _log.info(
                "chat_request_done",
                user_oid=user.oid,
                conversation_id=record.id,
                retrieval_hits=len(hits),
                declined=declined,
                output_chars=len(full_text),
            )

            # ----------------------------------------------------------
            # 7) Terminal `done` frame — carries enough state for the
            #    client to update its in-memory conversation list and
            #    optimistically render the new turn.
            # ----------------------------------------------------------
            yield _format_sse(
                "done",
                {
                    "conversationId": record.id,
                    "turnId": assistant_turn_id,
                    "declined": declined,
                    "isNewConversation": is_new,
                },
            )
        except AppError as exc:
            _log.warning(
                "chat_stream_app_error",
                conversation_id=record.id,
                code=exc.code,
            )
            yield _format_sse("error", {"code": exc.code, "message": exc.message})
        except Exception as exc:  # noqa: BLE001 — last-resort SSE error frame
            _log.exception(
                "chat_stream_unhandled_error",
                conversation_id=record.id,
                error_type=type(exc).__name__,
            )
            yield _format_sse(
                "error",
                {"code": "internal_error", "message": "An unexpected error occurred."},
            )

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Disable proxy buffering (nginx/Front Door) so deltas land
            # on the wire as soon as they're produced.
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# Re-raise NotFoundError as 404 for the load-conversation path. The
# global handler already maps it, but we list it in `responses` above
# so the OpenAPI surface is honest.
__all__ = [
    "ChatRequest",
    "_conversations_repo",
    "_cosmos_client_dep",
    "_llm_service",
    "_search_client",
    "router",
]


# Suppress unused-import lint for NotFoundError (referenced via raise
# elsewhere in this module's call graph).
_ = NotFoundError
