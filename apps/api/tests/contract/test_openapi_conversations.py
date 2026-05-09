"""OpenAPI contract test for ``/conversations`` (T073).

Validates request/response shapes for every conversations endpoint against
``specs/001-private-rag-accelerator/contracts/api-openapi.yaml`` (the single
source of truth — we **do not** copy schemas into the test).

Approach:
* Load the YAML once at module scope.
* Strip OpenAPI-3.0 ``nullable: true`` artifacts and rewrite
  ``#/components/schemas/X`` refs to local ``#/$defs/X`` so we can hand the
  result to a stock JSON-Schema Draft 2020-12 validator without pulling in
  ``openapi-core``.
* Drive the FastAPI app via ``TestClient`` with an in-memory
  ``ConversationsRepo`` fake (mirrors the admin test fixture pattern) and
  synthetic Entra tokens minted by the shared fixtures.

Coverage:
* GET  /conversations            — empty list + non-empty page
* POST /conversations            — default title + custom title (201)
* GET  /conversations/{id}       — happy path + 404 for non-owner
* DELETE /conversations/{id}     — 202 + 404 for non-owner + soft-delete state
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Generator, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from src.config import Settings, get_settings
from src.main import create_app
from src.routers.conversations import _conversations_repo
from src.services import auth as auth_service
from src.services.cosmos import (
    ConversationRecord,
    ConversationsRepo,
)
from tests._shared.fixtures import (
    DEFAULT_AUDIENCE,
    DEFAULT_TENANT_ID,
)

_REPO_ROOT = Path(__file__).resolve().parents[4]
_OPENAPI_PATH = (
    _REPO_ROOT
    / "specs"
    / "001-private-rag-accelerator"
    / "contracts"
    / "api-openapi.yaml"
)

_CLIENT_ID = "22222222-2222-2222-2222-222222222222"
_OWNER_OID = "user-oid-1"  # matches fixtures.DEFAULT_OID
_OTHER_OID = "user-oid-other"


# ---------------------------------------------------------------------------
# OpenAPI -> JSON Schema bridge
# ---------------------------------------------------------------------------


def _load_openapi() -> dict[str, Any]:
    with _OPENAPI_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _normalize_schema(node: Any) -> Any:
    """Recursively rewrite OpenAPI 3.0/3.1 quirks into pure JSON Schema.

    * ``nullable: true`` → ``type: [<orig>, "null"]`` (or removed if no type).
    * ``#/components/schemas/X`` refs → ``#/$defs/X``.
    """
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
_PATHS: dict[str, Any] = _normalize_schema(_OPENAPI["paths"])


def _validator_for(schema: dict[str, Any]) -> Draft202012Validator:
    """Return a Draft 2020-12 validator wired to the OpenAPI ``$defs``."""
    bundled = copy.deepcopy(schema)
    bundled["$defs"] = _DEFS
    return Draft202012Validator(bundled)


def _response_schema(path: str, method: str, status_code: str) -> dict[str, Any]:
    op = _PATHS[path][method.lower()]
    media = op["responses"][status_code]["content"]["application/json"]
    return media["schema"]


# ---------------------------------------------------------------------------
# In-memory ConversationsRepo fake
# ---------------------------------------------------------------------------


class _FakeConversationsRepo:
    """Drop-in shape-compatible stand-in for ``ConversationsRepo``.

    Stores records by ``(userId, id)``. ``list_for_user`` returns active
    rows newest-first; ``get`` enforces partition + soft-delete invisibility
    via the router's ``load_conversation_for_caller`` helper (the helper
    skips ``deletePending``, so we do NOT filter here).
    """

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], ConversationRecord] = {}

    def seed(self, record: ConversationRecord) -> None:
        self._store[(record.userId, record.id)] = record

    async def get(self, conversation_id: str, user_oid: str) -> ConversationRecord:
        rec = self._store.get((user_oid, conversation_id))
        if rec is None:
            from src.middleware.error_handler import NotFoundError

            raise NotFoundError("Conversation not found")
        return rec

    async def list_for_user(
        self,
        user_oid: str,
        limit: int = 50,
        continuation: str | None = None,  # noqa: ARG002 — fake doesn't paginate
    ) -> tuple[list[ConversationRecord], str | None]:
        rows = [
            r
            for (uid, _), r in self._store.items()
            if uid == user_oid and r.status != "deletePending"
        ]
        rows.sort(key=lambda r: r.updatedAt, reverse=True)
        return rows[:limit], None

    async def upsert(self, conversation: ConversationRecord) -> ConversationRecord:
        self._store[(conversation.userId, conversation.id)] = conversation
        return conversation

    async def delete(self, conversation_id: str, user_oid: str) -> None:
        self._store.pop((user_oid, conversation_id), None)


def _as_repo(fake: _FakeConversationsRepo) -> ConversationsRepo:
    """Cast for ``dependency_overrides`` — duck-typing is enough at runtime."""
    return fake  # type: ignore[return-value]


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
def app_with_repo(
    patched_jwks_client: Any,  # noqa: ARG001 — fixture activates monkeypatch
) -> Iterator[tuple[TestClient, _FakeConversationsRepo]]:
    get_settings.cache_clear()
    fake = _FakeConversationsRepo()

    app = create_app()
    settings = _make_settings()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[_conversations_repo] = lambda: _as_repo(fake)

    client = TestClient(app)
    try:
        yield client, fake
    finally:
        client.close()
        get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _reset_jwks_client_cache() -> Generator[None, None, None]:
    auth_service._jwks_clients.clear()
    yield
    auth_service._jwks_clients.clear()


def _owner_headers(make_entra_token: Callable[..., str]) -> dict[str, str]:
    token = make_entra_token({"oid": _OWNER_OID})
    return {"Authorization": f"Bearer {token}"}


def _other_headers(make_entra_token: Callable[..., str]) -> dict[str, str]:
    token = make_entra_token({"oid": _OTHER_OID})
    return {"Authorization": f"Bearer {token}"}


def _seed(
    fake: _FakeConversationsRepo,
    *,
    conv_id: str,
    user_oid: str,
    title: str = "hello",
    when: datetime | None = None,
    status: str = "active",
) -> ConversationRecord:
    when = when or datetime.now(UTC)
    rec = ConversationRecord(
        id=conv_id,
        userId=user_oid,
        title=title,
        createdAt=when,
        updatedAt=when,
        turns=[],
        uploadedDocumentIds=[],
        status=status,  # type: ignore[arg-type]
    )
    fake.seed(rec)
    return rec


# Valid OpenAPI-pattern conversation ids (Crockford-base32, 26 chars).
_OWNED_ID = "c_01HZZZZZZZZZZZZZZZZZZZZZZZ"
_OTHER_ID = "c_01HZZZZZZZZZZZZZZZZZZZZZY0"


# ---------------------------------------------------------------------------
# GET /conversations
# ---------------------------------------------------------------------------


def test_list_empty_matches_contract(
    app_with_repo: tuple[TestClient, _FakeConversationsRepo],
    make_entra_token: Callable[..., str],
) -> None:
    client, _ = app_with_repo
    r = client.get("/conversations", headers=_owner_headers(make_entra_token))
    assert r.status_code == 200, r.text
    body = r.json()
    _validator_for(_response_schema("/conversations", "get", "200")).validate(body)
    assert body["items"] == []


def test_list_returns_summaries_for_caller_only(
    app_with_repo: tuple[TestClient, _FakeConversationsRepo],
    make_entra_token: Callable[..., str],
) -> None:
    client, fake = app_with_repo
    _seed(fake, conv_id=_OWNED_ID, user_oid=_OWNER_OID, title="mine")
    _seed(fake, conv_id=_OTHER_ID, user_oid=_OTHER_OID, title="theirs")

    r = client.get("/conversations", headers=_owner_headers(make_entra_token))
    assert r.status_code == 200, r.text
    body = r.json()
    _validator_for(_response_schema("/conversations", "get", "200")).validate(body)
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] == _OWNED_ID
    assert body["items"][0]["title"] == "mine"


# ---------------------------------------------------------------------------
# POST /conversations
# ---------------------------------------------------------------------------


def test_create_default_title(
    app_with_repo: tuple[TestClient, _FakeConversationsRepo],
    make_entra_token: Callable[..., str],
) -> None:
    client, fake = app_with_repo
    r = client.post("/conversations", headers=_owner_headers(make_entra_token))
    assert r.status_code == 201, r.text
    body = r.json()
    _validator_for(_response_schema("/conversations", "post", "201")).validate(body)
    assert body["title"] == "New conversation"
    assert body["turns"] == []
    # Persisted under caller's partition.
    assert (_OWNER_OID, body["id"]) in fake._store


def test_create_custom_title(
    app_with_repo: tuple[TestClient, _FakeConversationsRepo],
    make_entra_token: Callable[..., str],
) -> None:
    client, _ = app_with_repo
    r = client.post(
        "/conversations",
        headers=_owner_headers(make_entra_token),
        json={"title": "Quarterly review"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    _validator_for(_response_schema("/conversations", "post", "201")).validate(body)
    assert body["title"] == "Quarterly review"


# ---------------------------------------------------------------------------
# GET /conversations/{id}
# ---------------------------------------------------------------------------


def test_get_owned_conversation(
    app_with_repo: tuple[TestClient, _FakeConversationsRepo],
    make_entra_token: Callable[..., str],
) -> None:
    client, fake = app_with_repo
    _seed(fake, conv_id=_OWNED_ID, user_oid=_OWNER_OID, title="visible")

    r = client.get(
        f"/conversations/{_OWNED_ID}",
        headers=_owner_headers(make_entra_token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    _validator_for(_response_schema("/conversations/{id}", "get", "200")).validate(body)
    assert body["id"] == _OWNED_ID
    assert body["title"] == "visible"


def test_get_non_owner_returns_404_no_leak(
    app_with_repo: tuple[TestClient, _FakeConversationsRepo],
    make_entra_token: Callable[..., str],
) -> None:
    client, fake = app_with_repo
    _seed(fake, conv_id=_OTHER_ID, user_oid=_OTHER_OID, title="secret")

    r = client.get(
        f"/conversations/{_OTHER_ID}",
        headers=_owner_headers(make_entra_token),
    )
    assert r.status_code == 404, r.text
    body = r.json()
    # Error envelope doesn't leak the title or owner.
    assert "secret" not in r.text
    assert body["code"] == "not_found"


def test_get_unknown_id_returns_404(
    app_with_repo: tuple[TestClient, _FakeConversationsRepo],
    make_entra_token: Callable[..., str],
) -> None:
    client, _ = app_with_repo
    r = client.get(
        f"/conversations/{_OWNED_ID}",
        headers=_owner_headers(make_entra_token),
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /conversations/{id}
# ---------------------------------------------------------------------------


def test_delete_owned_soft_deletes_and_returns_202(
    app_with_repo: tuple[TestClient, _FakeConversationsRepo],
    make_entra_token: Callable[..., str],
) -> None:
    client, fake = app_with_repo
    _seed(fake, conv_id=_OWNED_ID, user_oid=_OWNER_OID)

    r = client.delete(
        f"/conversations/{_OWNED_ID}",
        headers=_owner_headers(make_entra_token),
    )
    assert r.status_code == 202, r.text
    assert r.content == b""

    stored = fake._store[(_OWNER_OID, _OWNED_ID)]
    assert stored.status == "deletePending"


def test_delete_non_owner_returns_404(
    app_with_repo: tuple[TestClient, _FakeConversationsRepo],
    make_entra_token: Callable[..., str],
) -> None:
    client, fake = app_with_repo
    _seed(fake, conv_id=_OTHER_ID, user_oid=_OTHER_OID)

    r = client.delete(
        f"/conversations/{_OTHER_ID}",
        headers=_owner_headers(make_entra_token),
    )
    assert r.status_code == 404
    # Other user's record was NOT mutated.
    assert fake._store[(_OTHER_OID, _OTHER_ID)].status == "active"


def test_delete_already_deleted_returns_404(
    app_with_repo: tuple[TestClient, _FakeConversationsRepo],
    make_entra_token: Callable[..., str],
) -> None:
    client, fake = app_with_repo
    _seed(fake, conv_id=_OWNED_ID, user_oid=_OWNER_OID, status="deletePending")

    r = client.delete(
        f"/conversations/{_OWNED_ID}",
        headers=_owner_headers(make_entra_token),
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Auth gate
# ---------------------------------------------------------------------------


def test_unauthenticated_gets_401(
    app_with_repo: tuple[TestClient, _FakeConversationsRepo],
) -> None:
    client, _ = app_with_repo
    r = client.get("/conversations")
    assert r.status_code == 401
