"""Smoke tests for the admin router (T070).

Covers:
* non-admin caller → 403 on each endpoint
* admin caller → 200 / 202
* ``POST /admin/reindex`` enqueues a CloudEvent + writes a manual IngestionRun
* ``GET /admin/stats`` handles an empty Cosmos cleanly
"""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator, Callable, Generator, Iterator
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from src.config import Settings, get_settings
from src.main import create_app
from src.services import auth as auth_service
from src.services import queue as queue_service
from src.services.cosmos import (
    DocumentsRepo,
    IngestionRunsRepo,
    get_documents_repo,
    get_ingestion_runs_repo,
)
from tests._shared.fixtures import (
    DEFAULT_AUDIENCE,
    DEFAULT_TENANT_ID,
)

_CLIENT_ID = "22222222-2222-2222-2222-222222222222"
_ADMIN_GROUP = "admin-group-oid"
_USER_GROUP = "user-group-oid"


# ---------------------------------------------------------------------------
# Cosmos repo fakes
# ---------------------------------------------------------------------------


class _FakeAsyncIter:
    def __init__(self, items: list[Any]) -> None:
        self._items = list(items)

    def __aiter__(self) -> AsyncIterator[Any]:
        async def _gen() -> AsyncIterator[Any]:
            for it in self._items:
                yield it

        return _gen()


class _FakeContainer:
    """Minimal ContainerProxy stand-in for the COUNT(1) path in admin.py."""

    def __init__(self, count: int) -> None:
        self._count = count

    def query_items(self, *_: Any, **__: Any) -> _FakeAsyncIter:
        return _FakeAsyncIter([self._count])


def _docs_repo(count: int) -> DocumentsRepo:
    repo = DocumentsRepo.__new__(DocumentsRepo)
    repo._container = _FakeContainer(count)  # type: ignore[attr-defined]
    return repo


def _runs_repo(
    recent: list[Any] | None = None,
    created_sink: list[Any] | None = None,
) -> IngestionRunsRepo:
    repo = IngestionRunsRepo.__new__(IngestionRunsRepo)
    repo._container = None  # type: ignore[attr-defined]

    async def _list_recent(scope: str = "shared", limit: int = 20) -> list[Any]:
        return list(recent or [])

    async def _create(run: Any) -> Any:
        if created_sink is not None:
            created_sink.append(run)
        return run

    repo.list_recent = _list_recent  # type: ignore[method-assign]
    repo.create = _create  # type: ignore[method-assign]
    return repo


# ---------------------------------------------------------------------------
# App factory + fixtures
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
        ADMIN_GROUP_OBJECT_ID=_ADMIN_GROUP,
    )  # type: ignore[call-arg]


@pytest.fixture
def app_factory(
    patched_jwks_client: Any,  # noqa: ARG001 — fixture activates monkeypatch
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Callable[..., tuple[TestClient, dict[str, Any]]]]:
    get_settings.cache_clear()
    created: list[TestClient] = []

    def _build(
        *,
        doc_count: int = 0,
        recent_runs: list[Any] | None = None,
    ) -> tuple[TestClient, dict[str, Any]]:
        sink: list[Any] = []
        docs = _docs_repo(doc_count)
        runs = _runs_repo(recent=recent_runs, created_sink=sink)

        enqueue_mock = AsyncMock()
        monkeypatch.setattr(queue_service, "enqueue_cloud_event", enqueue_mock)
        # The router imports the symbol at module load — patch the imported
        # name too so the router uses the mock.
        from src.routers import admin as admin_router

        monkeypatch.setattr(admin_router, "enqueue_cloud_event", enqueue_mock)

        app = create_app()
        settings = _make_settings()
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_documents_repo] = lambda: docs
        app.dependency_overrides[get_ingestion_runs_repo] = lambda: runs

        client = TestClient(app)
        created.append(client)
        return client, {"created_runs": sink, "enqueue": enqueue_mock}

    yield _build

    for c in created:
        c.close()
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _reset_jwks_client_cache() -> Generator[None, None, None]:
    auth_service._jwks_clients.clear()
    yield
    auth_service._jwks_clients.clear()


def _admin_headers(make_entra_token: Callable[..., str]) -> dict[str, str]:
    token = make_entra_token({"groups": [_ADMIN_GROUP]})
    return {"Authorization": f"Bearer {token}"}


def _user_headers(make_entra_token: Callable[..., str]) -> dict[str, str]:
    token = make_entra_token({"groups": [_USER_GROUP]})
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# 403 for non-admin
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/admin/stats"),
        ("GET", "/admin/runs"),
        ("POST", "/admin/reindex"),
    ],
)
def test_non_admin_gets_403(
    app_factory: Any,
    make_entra_token: Callable[..., str],
    method: str,
    path: str,
) -> None:
    client, _ = app_factory()
    r = client.request(method, path, headers=_user_headers(make_entra_token))
    assert r.status_code == 403, r.text
    assert r.json()["code"] == "permission_denied"


def test_unauthenticated_gets_401(app_factory: Any) -> None:
    client, _ = app_factory()
    r = client.get("/admin/stats")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Admin happy paths
# ---------------------------------------------------------------------------


def test_stats_empty_cosmos(
    app_factory: Any, make_entra_token: Callable[..., str]
) -> None:
    client, _ = app_factory(doc_count=0, recent_runs=[])
    r = client.get("/admin/stats", headers=_admin_headers(make_entra_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sharedDocuments"] == 0
    assert body["lastIngestionRun"] is None
    # Stub fields documented in module docstring.
    assert body["chatRequests24h"] == 0
    assert body["declineRate7d"] == 0.0


def test_stats_with_doc_and_last_run(
    app_factory: Any, make_entra_token: Callable[..., str]
) -> None:
    from src.services.cosmos import IngestionRunRecord

    last = IngestionRunRecord(
        id="r_123",
        scope="shared",
        trigger="eventgrid",
        startedAt="2026-05-01T00:00:00Z",  # type: ignore[arg-type]
        completedAt="2026-05-01T00:05:00Z",  # type: ignore[arg-type]
        status="completed",
    )
    client, _ = app_factory(doc_count=42, recent_runs=[last])
    r = client.get("/admin/stats", headers=_admin_headers(make_entra_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sharedDocuments"] == 42
    assert body["lastIngestionRun"]["id"] == "r_123"
    assert body["lastIngestionRun"]["status"] == "completed"


def test_runs_endpoint_returns_records(
    app_factory: Any, make_entra_token: Callable[..., str]
) -> None:
    from src.services.cosmos import IngestionRunRecord

    runs = [
        IngestionRunRecord(
            id=f"r_{i}",
            scope="shared",
            trigger="eventgrid",
            startedAt="2026-05-01T00:00:00Z",  # type: ignore[arg-type]
            status="completed",
        )
        for i in range(3)
    ]
    client, _ = app_factory(recent_runs=runs)
    r = client.get("/admin/runs?limit=5", headers=_admin_headers(make_entra_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, list)
    assert len(body) == 3
    assert body[0]["id"] == "r_0"


def test_runs_limit_bounds_enforced(
    app_factory: Any, make_entra_token: Callable[..., str]
) -> None:
    client, _ = app_factory()
    r = client.get("/admin/runs?limit=500", headers=_admin_headers(make_entra_token))
    assert r.status_code == 422


def test_reindex_enqueues_cloud_event_and_writes_manual_run(
    app_factory: Any, make_entra_token: Callable[..., str]
) -> None:
    client, ctx = app_factory()
    r = client.post("/admin/reindex", headers=_admin_headers(make_entra_token))
    assert r.status_code == 202, r.text
    body = r.json()
    assert "runId" in body and body["runId"].startswith("r_")

    created = ctx["created_runs"]
    assert len(created) == 1
    record = created[0]
    assert record.trigger == "manual"
    assert record.scope == "shared"
    assert record.status == "running"
    assert record.id == body["runId"]

    enqueue: AsyncMock = ctx["enqueue"]
    assert enqueue.await_count == 1
    event = enqueue.await_args.args[0]
    assert event["specversion"] == "1.0"
    assert event["type"] == "Microsoft.Storage.BlobCreated"
    assert event["id"] == body["runId"]
    assert event["trigger"] == "manual"
    assert event["source"] == "/admin/reindex"


def test_enqueue_helper_base64_encodes_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit test for the queue helper — produces base64(JSON) messages."""
    sent: list[str] = []

    class _StubClient:
        async def send_message(self, msg: str) -> None:
            sent.append(msg)

    async def _fake_get_client(*_: Any, **__: Any) -> Any:
        return _StubClient()

    monkeypatch.setattr(queue_service, "get_ingestion_queue_client", _fake_get_client)

    import asyncio

    asyncio.run(queue_service.enqueue_cloud_event({"hello": "world"}))
    assert len(sent) == 1
    decoded = json.loads(base64.b64decode(sent[0]).decode("utf-8"))
    assert decoded == {"hello": "world"}
