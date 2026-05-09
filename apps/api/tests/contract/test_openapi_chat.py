"""OpenAPI contract test for ``/chat`` (T072).

Validates request body + SSE event payload shapes against
``specs/001-private-rag-accelerator/contracts/api-openapi.yaml``.

Approach mirrors :mod:`test_openapi_conversations` — single source of
truth for schemas is the YAML; we drive the FastAPI app with a fake
ConversationsRepo, fake LLM service that yields a scripted token
sequence, and a fake search client that returns a fixed passage set.
"""

from __future__ import annotations

import copy
import json
import re
from collections.abc import AsyncIterator, Callable, Generator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from src.config import Settings, get_settings
from src.main import create_app
from src.middleware.error_handler import NotFoundError
from src.models.chat import ChatStreamDelta, ChatStreamEvent
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

_REPO_ROOT = Path(__file__).resolve().parents[4]
_OPENAPI_PATH = (
    _REPO_ROOT / "specs" / "001-private-rag-accelerator" / "contracts" / "api-openapi.yaml"
)

_CLIENT_ID = "22222222-2222-2222-2222-222222222222"
_OWNER_OID = "user-oid-1"  # matches fixtures.DEFAULT_OID
_OTHER_OID = "user-oid-other"
_OWNED_ID = "c_01HZZZZZZZZZZZZZZZZZZZZZZZ"
_OTHER_ID = "c_01HZZZZZZZZZZZZZZZZZZZZZY0"

# Caller oid for retrieval scope filter — must be a UUID (search
# wrapper rejects non-UUIDs in `user:<oid>`).
_OWNER_OID_UUID = "33333333-3333-3333-3333-333333333333"


# ---------------------------------------------------------------------------
# OpenAPI -> JSON Schema bridge (copy of the helper from the conversations
# contract test — kept inline so this module stays self-contained).
# ---------------------------------------------------------------------------


def _load_openapi() -> dict[str, Any]:
    with _OPENAPI_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _normalize_schema(node: Any) -> Any:
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for k, v in node.items():
            if k == "$ref" and isinstance(v, str):
                out[k] = v.replace("#/components/schemas/", "#/$defs/")
                continue
            out[k] = _normalize_schema(v)
        if out.pop("nullable", False):
            t = out.get("type")
            if isinstance(t, str):
                out["type"] = [t, "null"]
            elif isinstance(t, list) and "null" not in t:
                out["type"] = [*t, "null"]
        return out
    if isinstance(node, list):
        return [_normalize_schema(item) for item in node]
    return node


_OPENAPI = _load_openapi()
_DEFS: dict[str, Any] = _normalize_schema(_OPENAPI["components"]["schemas"])


def _validator_for(schema: dict[str, Any]) -> Draft202012Validator:
    bundled = copy.deepcopy(schema)
    bundled["$defs"] = _DEFS
    return Draft202012Validator(bundled)


# ---------------------------------------------------------------------------
# Fakes
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
    """Async-iterable substitute for :class:`LLMService`.

    ``chunks`` is the scripted delta sequence; if ``raise_after`` is set,
    raises after that many chunks have been yielded (used to verify the
    SSE error frame).
    """

    chunks: list[str]
    raise_after: int | None = None
    raise_during_call: bool = False

    async def chat_stream(self, _messages: Any) -> AsyncIterator[ChatStreamEvent]:
        if self.raise_during_call:
            raise RuntimeError("simulated LLM failure before any tokens")
        for yielded, chunk in enumerate(self.chunks):
            if self.raise_after is not None and yielded >= self.raise_after:
                raise RuntimeError("simulated mid-stream LLM failure")
            yield ChatStreamDelta(data={"text": chunk})


class _FakeSearch:
    """Stub for :class:`ScopedSearchClient`. Records the oid it was called with."""

    def __init__(self, hits: list[SearchHit]) -> None:
        self._hits = hits
        self.last_oid: str | None = None
        self.call_count: int = 0

    async def search_combined(
        self,
        _query: str,
        *,
        oid: str,
        top: int = 5,  # noqa: ARG002 — unused in stub
        **_kwargs: Any,
    ) -> SearchResults:
        self.last_oid = oid
        self.call_count += 1
        return SearchResults(documents=list(self._hits))


_FIXTURE_HITS: list[SearchHit] = [
    SearchHit(
        id="p1",
        documentId="doc-A",
        scope="shared",
        title="Shared Handbook",
        content="The capital of France is Paris.",
        score=0.91,
        page=1,
        chunkOrder=0,
    ),
    SearchHit(
        id="p2",
        documentId="doc-B",
        scope=f"user:{_OWNER_OID_UUID}",
        title="My Notes",
        content="Population of Paris is approximately 2.1 million.",
        score=0.74,
        page=3,
        chunkOrder=2,
    ),
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
) -> Iterator[
    tuple[
        TestClient,
        _FakeConversationsRepo,
        _FakeSearch,
        list[_ScriptedLLM],
    ]
]:
    """Wire the FastAPI app with all chat dependencies replaced by fakes.

    The fourth tuple member is a single-element list holding the active
    LLM stub — tests overwrite ``[0]`` to script different scenarios.
    """
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
        yield client, fake_repo, fake_search, llm_box
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


def _other_headers(make_entra_token: Callable[..., str]) -> dict[str, str]:
    token = make_entra_token({"oid": "44444444-4444-4444-4444-444444444444"})
    return {"Authorization": f"Bearer {token}"}


def _seed(
    fake: _FakeConversationsRepo,
    *,
    conv_id: str,
    user_oid: str,
    title: str = "hello",
) -> ConversationRecord:
    now = datetime.now(UTC)
    rec = ConversationRecord(
        id=conv_id,
        userId=user_oid,
        title=title,
        createdAt=now,
        updatedAt=now,
        turns=[],
        uploadedDocumentIds=[],
        status="active",
    )
    fake.seed(rec)
    return rec


# ---------------------------------------------------------------------------
# SSE parser
# ---------------------------------------------------------------------------


_EVENT_FRAME_RE = re.compile(r"event:\s*(?P<event>[^\n]+)\ndata:\s*(?P<data>[^\n]*)\n\n")


def _parse_sse(body: str) -> list[tuple[str, dict[str, Any]]]:
    """Parse an SSE response body into a list of (event_name, payload) pairs."""
    events: list[tuple[str, dict[str, Any]]] = []
    for match in _EVENT_FRAME_RE.finditer(body):
        events.append((match.group("event"), json.loads(match.group("data"))))
    return events


# ---------------------------------------------------------------------------
# Schema validators
# ---------------------------------------------------------------------------


_REQUEST_SCHEMA: dict[str, Any] = _DEFS["ChatRequest"]
_CITATION_SCHEMA: dict[str, Any] = _DEFS["Citation"]


def _validate_chat_request(payload: dict[str, Any]) -> None:
    _validator_for(_REQUEST_SCHEMA).validate(payload)


def _validate_citations_payload(citations: list[dict[str, Any]]) -> None:
    validator = _validator_for(_CITATION_SCHEMA)
    for c in citations:
        validator.validate(c)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_chat_request_schema_round_trip() -> None:
    """Sanity-check that our locally-built request body validates."""
    body = {"conversationId": _OWNED_ID, "message": "hello", "useUploads": True}
    _validate_chat_request(body)


def test_happy_path_streams_delta_then_citations_then_done(
    app_with_chat: tuple[TestClient, _FakeConversationsRepo, _FakeSearch, list[_ScriptedLLM]],
    make_entra_token: Callable[..., str],
) -> None:
    client, repo, search, llm_box = app_with_chat
    _seed(repo, conv_id=_OWNED_ID, user_oid=_OWNER_OID_UUID)
    # Model cites passages [1] and [2] — both should land in the citations event.
    llm_box[0] = _ScriptedLLM(chunks=["Paris is the capital [1]. ", "About 2.1M live there [2]."])

    body = {"conversationId": _OWNED_ID, "message": "Tell me about Paris."}
    _validate_chat_request(body)
    r = client.post("/chat", headers=_owner_headers(make_entra_token), json=body)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.headers.get("cache-control") == "no-cache"
    assert r.headers.get("x-accel-buffering") == "no"

    events = _parse_sse(r.text)
    names = [n for n, _ in events]
    # Order: deltas... → citations → done
    assert names[-2:] == ["citations", "done"], names
    assert names[0] == "delta"
    assert all(n == "delta" for n in names[:-2])

    # Deltas reconstruct the streamed text.
    delta_text = "".join(p["text"] for n, p in events if n == "delta")
    assert "Paris" in delta_text and "[1]" in delta_text and "[2]" in delta_text

    # Citations event matches the openapi Citation schema.
    citations_payload = events[-2][1]["citations"]
    assert isinstance(citations_payload, list)
    assert len(citations_payload) == 2
    _validate_citations_payload(citations_payload)
    # Indices map to fixture passages 1 and 2.
    document_ids = {c["documentId"] for c in citations_payload}
    assert document_ids == {"doc-A", "doc-B"}

    # Done event carries the conversation id.
    done_payload = events[-1][1]
    assert done_payload["conversationId"] == _OWNED_ID
    assert done_payload["declined"] is False
    assert "turnId" in done_payload

    # Search was called with the caller's oid (scope filter applied).
    assert search.last_oid == _OWNER_OID_UUID
    assert search.call_count == 1

    # User + assistant turn both persisted.
    stored = repo._store[(_OWNER_OID_UUID, _OWNED_ID)]
    assert len(stored.turns) == 2
    assert stored.turns[0].role.value == "user"
    assert stored.turns[1].role.value == "assistant"
    assert stored.turns[1].citations is not None
    assert len(stored.turns[1].citations) == 2


def test_decline_path_emits_empty_citations_and_flags_done(
    app_with_chat: tuple[TestClient, _FakeConversationsRepo, _FakeSearch, list[_ScriptedLLM]],
    make_entra_token: Callable[..., str],
) -> None:
    client, repo, _search, llm_box = app_with_chat
    _seed(repo, conv_id=_OWNED_ID, user_oid=_OWNER_OID_UUID)
    # LLM returns DECLINE_PHRASE verbatim — even though [1] would be a
    # valid index, citations must be empty per FR-017.
    llm_box[0] = _ScriptedLLM(chunks=[DECLINE_PHRASE])

    body = {"conversationId": _OWNED_ID, "message": "What's the meaning of life?"}
    r = client.post("/chat", headers=_owner_headers(make_entra_token), json=body)
    assert r.status_code == 200, r.text
    events = _parse_sse(r.text)
    citations_event = next(e for e in events if e[0] == "citations")
    done_event = next(e for e in events if e[0] == "done")

    assert citations_event[1]["citations"] == []
    assert done_event[1]["declined"] is True

    # Assistant turn persisted with no citations.
    stored = repo._store[(_OWNER_OID_UUID, _OWNED_ID)]
    assistant_turn = stored.turns[-1]
    assert assistant_turn.citations is None
    assert DECLINE_PHRASE in assistant_turn.content


def test_new_conversation_when_no_id_provided(
    app_with_chat: tuple[TestClient, _FakeConversationsRepo, _FakeSearch, list[_ScriptedLLM]],
    make_entra_token: Callable[..., str],
) -> None:
    client, repo, _search, llm_box = app_with_chat
    llm_box[0] = _ScriptedLLM(chunks=["A short answer [1]."])

    body = {"message": "Greet me", "useUploads": True}
    r = client.post("/chat", headers=_owner_headers(make_entra_token), json=body)
    assert r.status_code == 200, r.text

    events = _parse_sse(r.text)
    done_payload = next(e for e in events if e[0] == "done")[1]
    new_id = done_payload["conversationId"]
    assert re.match(r"^c_[0-9A-HJKMNP-TV-Z]{26}$", new_id), new_id
    assert done_payload["isNewConversation"] is True

    # Persisted before streaming completed.
    assert (_OWNER_OID_UUID, new_id) in repo._store
    stored = repo._store[(_OWNER_OID_UUID, new_id)]
    # Title auto-derived from message.
    assert "Greet" in stored.title


def test_cross_user_conversation_returns_404_no_leak(
    app_with_chat: tuple[TestClient, _FakeConversationsRepo, _FakeSearch, list[_ScriptedLLM]],
    make_entra_token: Callable[..., str],
) -> None:
    client, repo, _search, _llm = app_with_chat
    # Belongs to *other* user.
    _seed(repo, conv_id=_OTHER_ID, user_oid=_OWNER_OID_UUID, title="secret")

    body = {"conversationId": _OTHER_ID, "message": "leak it"}
    r = client.post("/chat", headers=_other_headers(make_entra_token), json=body)
    assert r.status_code == 404, r.text
    # Title MUST NOT appear in the error body.
    assert "secret" not in r.text


def test_unauthenticated_returns_401(
    app_with_chat: tuple[TestClient, _FakeConversationsRepo, _FakeSearch, list[_ScriptedLLM]],
) -> None:
    client, _repo, _search, _llm = app_with_chat
    body = {"conversationId": _OWNED_ID, "message": "hi"}
    r = client.post("/chat", json=body)
    assert r.status_code == 401, r.text


def test_llm_failure_emits_error_event_and_closes_stream(
    app_with_chat: tuple[TestClient, _FakeConversationsRepo, _FakeSearch, list[_ScriptedLLM]],
    make_entra_token: Callable[..., str],
) -> None:
    client, repo, _search, llm_box = app_with_chat
    _seed(repo, conv_id=_OWNED_ID, user_oid=_OWNER_OID_UUID)
    llm_box[0] = _ScriptedLLM(chunks=["partial ", "more"], raise_after=1)

    body = {"conversationId": _OWNED_ID, "message": "go"}
    r = client.post("/chat", headers=_owner_headers(make_entra_token), json=body)
    assert r.status_code == 200, r.text  # SSE always opens 200; error rides inside.

    events = _parse_sse(r.text)
    names = [n for n, _ in events]
    assert "error" in names
    assert names[-1] == "error"  # error frame is terminal
    assert "done" not in names
    error_payload = events[-1][1]
    assert "code" in error_payload and "message" in error_payload
