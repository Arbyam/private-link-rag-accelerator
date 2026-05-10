"""Structured logging tests for the chat router (T091).

Verifies the per-request event set the US6 admin dashboard depends on
(``conversationId``, ``turnId``, retrieval count, decline flag, p50/p95
latencies) is emitted in the right order on happy/decline/error paths,
and that no PII (raw oid, raw user message, raw LLM completion text,
citation snippets) ever lands in a log record.

We use :func:`structlog.testing.capture_logs` because the project's
logger factory is :class:`structlog.PrintLoggerFactory` — pytest's
built-in ``caplog`` fixture only sees stdlib ``logging`` records and
would silently miss every event under test.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Callable, Generator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
import structlog
from fastapi.testclient import TestClient

from src.config import Settings, get_settings
from src.main import create_app
from src.middleware.error_handler import NotFoundError
from src.models.chat import ChatStreamDelta, ChatStreamEvent
from src.routers import chat as chat_module
from src.routers.chat import (
    _conversations_repo as chat_conversations_repo,
)
from src.routers.chat import (
    _cosmos_client_dep,
    _llm_service,
    _search_client,
)
from src.services import auth as auth_service
from src.services.cosmos import ConversationRecord, ConversationsRepo
from src.services.llm import DECLINE_PHRASE
from src.services.search import SearchHit, SearchResults
from tests._shared.fixtures import DEFAULT_AUDIENCE, DEFAULT_TENANT_ID

_CLIENT_ID = "22222222-2222-2222-2222-222222222222"
_OWNER_OID_UUID = "33333333-3333-3333-3333-333333333333"
_OWNED_ID = "c_01HZZZZZZZZZZZZZZZZZZZZZZZ"
_RAW_USER_MESSAGE = "Tell me about Paris and its secret pizza recipe."
_LLM_TEXT_PARTS = ["Paris is the capital [1]. ", "Pizza is from Naples [2]."]
_LLM_FULL_TEXT = "".join(_LLM_TEXT_PARTS)
_PASSAGE_SNIPPET_A = "The capital of France is Paris."
_PASSAGE_SNIPPET_B = "Population of Paris is approximately 2.1 million."


# ---------------------------------------------------------------------------
# Fakes (trimmed copies of the contract-test fakes — kept local so this
# unit test stays decoupled from the openapi suite).
# ---------------------------------------------------------------------------


class _FakeConversationsRepo:
    def __init__(self) -> None:
        self._store: dict[tuple[str, str], ConversationRecord] = {}

    def seed(self, record: ConversationRecord) -> None:
        self._store[(record.userId, record.id)] = record

    async def get(self, conversation_id: str, user_oid: str) -> ConversationRecord:
        rec = self._store.get((user_oid, conversation_id))
        if rec is None:
            raise NotFoundError("Conversation not found")
        return rec

    async def upsert(self, conversation: ConversationRecord) -> ConversationRecord:
        self._store[(conversation.userId, conversation.id)] = conversation
        return conversation


def _as_repo(fake: _FakeConversationsRepo) -> ConversationsRepo:
    return fake  # type: ignore[return-value]


@dataclass
class _ScriptedLLM:
    chunks: list[str]
    raise_during_call: bool = False

    async def chat_stream(self, _messages: Any) -> AsyncIterator[ChatStreamEvent]:
        if self.raise_during_call:
            raise RuntimeError("simulated LLM failure with secret-token-xyz")
        for chunk in self.chunks:
            yield ChatStreamDelta(data={"text": chunk})


class _FakeSearch:
    def __init__(self, hits: list[SearchHit]) -> None:
        self._hits = hits

    async def search_combined(
        self,
        _query: str,
        *,
        oid: str,  # noqa: ARG002
        top: int = 5,  # noqa: ARG002
        **_kwargs: Any,
    ) -> SearchResults:
        return SearchResults(documents=list(self._hits))


_FIXTURE_HITS: list[SearchHit] = [
    SearchHit(
        id="p1",
        documentId="doc-A",
        scope="shared",
        title="Shared Handbook",
        content=_PASSAGE_SNIPPET_A,
        score=0.9123,
        page=1,
        chunkOrder=0,
    ),
    SearchHit(
        id="p2",
        documentId="doc-B",
        scope=f"user:{_OWNER_OID_UUID}",
        title="My Notes",
        content=_PASSAGE_SNIPPET_B,
        score=0.7456,
        page=3,
        chunkOrder=2,
    ),
]


def _make_settings() -> Settings:
    return Settings(
        AZURE_TENANT_ID=DEFAULT_TENANT_ID,
        AZURE_CLIENT_ID=_CLIENT_ID,
        ENTRA_API_AUDIENCE=DEFAULT_AUDIENCE,
        COSMOS_ACCOUNT_ENDPOINT="https://cosmos.example/",
        SEARCH_ENDPOINT="https://search.example/",
        AOAI_ENDPOINT="https://aoai.example/",
        AOAI_CHAT_DEPLOYMENT="gpt",
        AOAI_EMBEDDING_DEPLOYMENT="emb",
        STORAGE_ACCOUNT_NAME="stor",
        DOCINTEL_ENDPOINT="https://di.example/",
    )  # type: ignore[call-arg]


@pytest.fixture
def app_with_chat(
    patched_jwks_client: Any,  # noqa: ARG001 — fixture activates monkeypatch
) -> Iterator[tuple[TestClient, _FakeConversationsRepo, list[_ScriptedLLM]]]:
    get_settings.cache_clear()
    fake_repo = _FakeConversationsRepo()
    fake_search = _FakeSearch(_FIXTURE_HITS)
    llm_box: list[_ScriptedLLM] = [_ScriptedLLM(chunks=[])]

    app = create_app()
    settings = _make_settings()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[chat_conversations_repo] = lambda: _as_repo(fake_repo)
    app.dependency_overrides[_llm_service] = lambda: llm_box[0]  # type: ignore[return-value]
    app.dependency_overrides[_search_client] = lambda: fake_search  # type: ignore[return-value]
    app.dependency_overrides[_cosmos_client_dep] = lambda: object()

    client = TestClient(app)
    try:
        yield client, fake_repo, llm_box
    finally:
        client.close()
        get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _reset_jwks_client_cache() -> Generator[None, None, None]:
    auth_service._jwks_clients.clear()
    yield
    auth_service._jwks_clients.clear()


@pytest.fixture(autouse=True)
def _reset_system_prompt_cache() -> Generator[None, None, None]:
    from src.services.llm import reset_system_prompt_cache

    reset_system_prompt_cache()
    yield
    reset_system_prompt_cache()


def _owner_headers(make_entra_token: Callable[..., str]) -> dict[str, str]:
    token = make_entra_token({"oid": _OWNER_OID_UUID})
    return {"Authorization": f"Bearer {token}"}


def _seed(fake: _FakeConversationsRepo, conv_id: str = _OWNED_ID) -> ConversationRecord:
    now = datetime.now(UTC)
    rec = ConversationRecord(
        id=conv_id,
        userId=_OWNER_OID_UUID,
        title="hello",
        createdAt=now,
        updatedAt=now,
        turns=[],
        uploadedDocumentIds=[],
        status="active",
    )
    fake.seed(rec)
    return rec


# ---------------------------------------------------------------------------
# Privacy assertion — runs over every captured event for every test.
# ---------------------------------------------------------------------------

# Field names that must NEVER appear in any log record.
_FORBIDDEN_KEYS: frozenset[str] = frozenset({"user_oid", "userOid", "oid", "message", "content"})

# Substring blacklist — anything we KNOW would be PII if it leaked. Kept
# narrow so we don't fight against legitimate identifiers (e.g.
# conversation ids).
_FORBIDDEN_VALUES: tuple[str, ...] = (
    _OWNER_OID_UUID,
    _RAW_USER_MESSAGE,
    "secret pizza",
    _LLM_FULL_TEXT,
    _PASSAGE_SNIPPET_A,
    _PASSAGE_SNIPPET_B,
)


def _assert_privacy_safe(records: list[dict[str, Any]]) -> None:
    """No raw oid, no raw user message, no raw LLM text, no snippets."""
    for rec in records:
        for forbidden in _FORBIDDEN_KEYS:
            assert forbidden not in rec, f"forbidden key {forbidden!r} present in {rec!r}"
        as_text = json.dumps(rec, default=str)
        for needle in _FORBIDDEN_VALUES:
            assert needle not in as_text, f"forbidden value {needle!r} leaked in {rec!r}"


def _chat_records(captured: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter to chat.* events only — middleware emits its own records."""
    return [r for r in captured if str(r.get("event", "")).startswith("chat.")]


@contextmanager
def _capture_chat_logs() -> Iterator[list[dict[str, Any]]]:
    """Wrap :func:`structlog.testing.capture_logs` and rebind ``chat._log``.

    structlog is configured with ``cache_logger_on_first_use=True``; once
    the chat module's ``_log`` proxy has been used, its processor chain
    is frozen — including any ``LogCapture`` processor from a previous
    test. Allocating a fresh logger inside each capture block ensures
    the new ``LogCapture`` is the one that receives events.
    """
    original = chat_module._log
    with structlog.testing.capture_logs() as captured:
        chat_module._log = structlog.get_logger("chat_test")
        try:
            yield captured
        finally:
            chat_module._log = original


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_happy_path_emits_start_retrieval_complete_in_order(
    app_with_chat: tuple[TestClient, _FakeConversationsRepo, list[_ScriptedLLM]],
    make_entra_token: Callable[..., str],
) -> None:
    client, repo, llm_box = app_with_chat
    _seed(repo)
    llm_box[0] = _ScriptedLLM(chunks=list(_LLM_TEXT_PARTS))

    body = {"conversationId": _OWNED_ID, "message": _RAW_USER_MESSAGE}
    with _capture_chat_logs() as captured:
        r = client.post("/chat", headers=_owner_headers(make_entra_token), json=body)
        assert r.status_code == 200, r.text
        # Drain the streaming body so the generator runs to completion
        # and emits its terminal log record before we inspect captured.
        _ = r.text

    chat = _chat_records(captured)
    events = [r["event"] for r in chat]
    assert events == [
        "chat.request.start",
        "chat.retrieval.complete",
        "chat.response.complete",
    ], events

    expected_hash = hashlib.sha256(_OWNER_OID_UUID.encode()).hexdigest()[:8]
    start = chat[0]
    assert start["conversationId"] == _OWNED_ID
    assert start["userOidHash"] == expected_hash
    assert start["messageLen"] == len(_RAW_USER_MESSAGE)
    assert start["isNewConversation"] is False

    retrieval = chat[1]
    assert retrieval["conversationId"] == _OWNED_ID
    assert retrieval["retrievalCount"] == 2
    assert isinstance(retrieval["topScore"], float)
    assert retrieval["topScore"] == pytest.approx(0.9123, abs=1e-4)
    assert isinstance(retrieval["searchLatencyMs"], int)
    assert retrieval["searchLatencyMs"] >= 0

    done = chat[2]
    assert done["conversationId"] == _OWNED_ID
    assert done["turnId"].startswith("t_")
    assert done["declined"] is False
    assert done["citationsEmitted"] == 2
    assert done["tokensStreamed"] == len(_LLM_FULL_TEXT)
    assert isinstance(done["llmLatencyMs"], int) and done["llmLatencyMs"] >= 0
    assert isinstance(done["totalLatencyMs"], int) and done["totalLatencyMs"] >= 0

    _assert_privacy_safe(chat)


def test_decline_path_emits_response_declined(
    app_with_chat: tuple[TestClient, _FakeConversationsRepo, list[_ScriptedLLM]],
    make_entra_token: Callable[..., str],
) -> None:
    client, repo, llm_box = app_with_chat
    _seed(repo)
    llm_box[0] = _ScriptedLLM(chunks=[DECLINE_PHRASE])

    body = {"conversationId": _OWNED_ID, "message": _RAW_USER_MESSAGE}
    with _capture_chat_logs() as captured:
        r = client.post("/chat", headers=_owner_headers(make_entra_token), json=body)
        assert r.status_code == 200, r.text
        _ = r.text

    chat = _chat_records(captured)
    events = [r["event"] for r in chat]
    assert events == [
        "chat.request.start",
        "chat.retrieval.complete",
        "chat.response.declined",
    ], events

    declined = chat[2]
    assert declined["declined"] is True
    assert declined["citationsEmitted"] == 0
    assert declined["retrievalCount"] == 2
    assert declined["turnId"].startswith("t_")
    assert isinstance(declined["totalLatencyMs"], int) and declined["totalLatencyMs"] >= 0
    # Decline path doesn't claim an LLM-only latency or token count.
    assert "tokensStreamed" not in declined
    assert "llmLatencyMs" not in declined

    _assert_privacy_safe(chat)


def test_error_path_emits_response_error_with_exc_info(
    app_with_chat: tuple[TestClient, _FakeConversationsRepo, list[_ScriptedLLM]],
    make_entra_token: Callable[..., str],
) -> None:
    client, repo, llm_box = app_with_chat
    _seed(repo)
    llm_box[0] = _ScriptedLLM(chunks=[], raise_during_call=True)

    body = {"conversationId": _OWNED_ID, "message": _RAW_USER_MESSAGE}
    with _capture_chat_logs() as captured:
        r = client.post("/chat", headers=_owner_headers(make_entra_token), json=body)
        assert r.status_code == 200, r.text
        _ = r.text

    chat = _chat_records(captured)
    events = [r["event"] for r in chat]
    assert events == [
        "chat.request.start",
        "chat.retrieval.complete",
        "chat.response.error",
    ], events

    err = chat[-1]
    assert err["log_level"] == "error"
    assert err["errorCode"] == "internal_error"
    assert err["errorMessage"] == "RuntimeError"
    assert isinstance(err["totalLatencyMs"], int) and err["totalLatencyMs"] >= 0
    # exc_info: True is forwarded by structlog as either an `exc_info`
    # key or rendered into `exception` depending on processors. Either
    # is acceptable; we just want evidence the traceback path was taken.
    assert err.get("exc_info") is True or "exception" in err

    # The LLM raised with a "secret-token-xyz" substring in its message;
    # the error log must NOT carry the raw exception text.
    as_text = json.dumps(err, default=str)
    assert "secret-token-xyz" not in as_text

    _assert_privacy_safe(chat)


def test_user_oid_never_logged_only_hash_appears(
    app_with_chat: tuple[TestClient, _FakeConversationsRepo, list[_ScriptedLLM]],
    make_entra_token: Callable[..., str],
) -> None:
    """Cross-cutting check: across all chat.* records, no raw oid, ever."""
    client, repo, llm_box = app_with_chat
    _seed(repo)
    llm_box[0] = _ScriptedLLM(chunks=list(_LLM_TEXT_PARTS))

    body = {"conversationId": _OWNED_ID, "message": _RAW_USER_MESSAGE}
    with _capture_chat_logs() as captured:
        r = client.post("/chat", headers=_owner_headers(make_entra_token), json=body)
        assert r.status_code == 200, r.text
        _ = r.text

    chat = _chat_records(captured)
    expected_hash = hashlib.sha256(_OWNER_OID_UUID.encode()).hexdigest()[:8]
    # Hash must appear at least once (in start event).
    assert any(r.get("userOidHash") == expected_hash for r in chat)
    _assert_privacy_safe(chat)
