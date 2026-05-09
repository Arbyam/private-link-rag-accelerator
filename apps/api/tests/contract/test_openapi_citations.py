"""OpenAPI contract test for ``GET /citations/{documentId}`` (T074).

Validates the citations router (T084) against the response shapes declared
in ``specs/001-private-rag-accelerator/contracts/api-openapi.yaml``:

* 200: streams a binary body whose ``Content-Type`` matches one of the
  ``content`` keys declared for the 200 response (``application/pdf``,
  ``application/octet-stream``, ``image/png``, ``image/jpeg``).
* 404: returned for both *not found* and *out of scope* — the latter MUST
  also include cross-user requests (SC-011: never leak existence).

The test mocks Cosmos (`DocumentsRepo.get`) and the Blob downloader so it
runs as a pure unit test without any Azure dependency.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Generator, Iterator
from pathlib import Path as FsPath
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from src.config import Settings, get_settings
from src.main import create_app
from src.middleware.error_handler import NotFoundError
from src.routers import citations as citations_router
from src.services import auth as auth_service
from src.services.cosmos import (
    DocumentIngestionStatus,
    DocumentRecord,
    DocumentsRepo,
    get_documents_repo,
)
from tests._shared.fixtures import (
    DEFAULT_AUDIENCE,
    DEFAULT_OID,
    DEFAULT_TENANT_ID,
)

_CLIENT_ID = "22222222-2222-2222-2222-222222222222"
_STORAGE_ACCOUNT = "stexample"
_OWNED_BLOB_HOST = f"{_STORAGE_ACCOUNT}.blob.core.windows.net"


# ---------------------------------------------------------------------------
# OpenAPI contract loader
# ---------------------------------------------------------------------------


_OPENAPI_PATH = (
    FsPath(__file__).resolve().parents[4]
    / "specs"
    / "001-private-rag-accelerator"
    / "contracts"
    / "api-openapi.yaml"
)


@pytest.fixture(scope="module")
def openapi_spec() -> dict[str, Any]:
    with _OPENAPI_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@pytest.fixture(scope="module")
def citations_get_op(openapi_spec: dict[str, Any]) -> dict[str, Any]:
    op = (
        openapi_spec.get("paths", {})
        .get("/citations/{documentId}", {})
        .get("get")
    )
    assert op is not None, "OpenAPI is missing GET /citations/{documentId}"
    return op


# ---------------------------------------------------------------------------
# Cosmos repo fake — pluggable per test
# ---------------------------------------------------------------------------


def _make_doc(
    *,
    doc_id: str = "doc-1",
    scope: str = "shared",
    file_name: str = "policy.pdf",
    mime_type: str = "application/pdf",
    blob_uri: str | None = None,
) -> DocumentRecord:
    if blob_uri is None:
        container = "shared-corpus" if scope == "shared" else "user-uploads"
        blob_uri = f"https://{_OWNED_BLOB_HOST}/{container}/{doc_id}/{file_name}"
    return DocumentRecord(
        id=doc_id,
        scope=scope,
        fileName=file_name,
        mimeType=mime_type,
        sizeBytes=1234,
        blobUri=blob_uri,
        ingestion=DocumentIngestionStatus(status="indexed"),
    )


def _docs_repo_returning(per_scope: dict[str, DocumentRecord]) -> DocumentsRepo:
    """Repo whose ``get(id, scope)`` returns the doc for that partition or 404."""
    repo = DocumentsRepo.__new__(DocumentsRepo)
    repo._container = None  # type: ignore[attr-defined]

    async def _get(document_id: str, scope: str) -> DocumentRecord:
        doc = per_scope.get(scope)
        if doc is None or doc.id != document_id:
            raise NotFoundError("Resource not found")
        return doc

    repo.get = _get  # type: ignore[method-assign]
    return repo


# ---------------------------------------------------------------------------
# Blob client fake — captures calls so we can assert container+name
# ---------------------------------------------------------------------------


class _FakeDownloader:
    def __init__(self, payload: bytes, chunk_size: int = 64) -> None:
        self._payload = payload
        self._chunk = chunk_size

    async def chunks(self) -> AsyncIterator[bytes]:
        for i in range(0, len(self._payload), self._chunk):
            yield self._payload[i : i + self._chunk]


class _FakeBlobClient:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    async def download_blob(self) -> _FakeDownloader:
        return _FakeDownloader(self._payload)


class _FakeBlobServiceClient:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.last_call: dict[str, str] | None = None

    def get_blob_client(self, container: str, blob: str) -> _FakeBlobClient:
        self.last_call = {"container": container, "blob": blob}
        return _FakeBlobClient(self.payload)


# ---------------------------------------------------------------------------
# App / settings fixtures
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
        STORAGE_ACCOUNT_NAME=_STORAGE_ACCOUNT,
        DOCINTEL_ENDPOINT="https://di.example/",
    )  # type: ignore[call-arg]


@pytest.fixture
def app_factory(
    patched_jwks_client: Any,  # noqa: ARG001 — fixture activates monkeypatch
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Callable[..., tuple[TestClient, _FakeBlobServiceClient]]]:
    get_settings.cache_clear()
    created: list[TestClient] = []

    def _build(
        *,
        per_scope: dict[str, DocumentRecord] | None = None,
        blob_payload: bytes = b"",
    ) -> tuple[TestClient, _FakeBlobServiceClient]:
        repo = _docs_repo_returning(per_scope or {})
        fake_blob = _FakeBlobServiceClient(blob_payload)

        async def _get_blob_client_stub() -> _FakeBlobServiceClient:
            return fake_blob

        # Patch both the source symbol and the name imported into the router
        # module — the router does ``from ..services.storage import
        # get_blob_service_client`` so the bound name lives on the router.
        monkeypatch.setattr(
            citations_router, "get_blob_service_client", _get_blob_client_stub
        )

        app = create_app()
        settings = _make_settings()
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_documents_repo] = lambda: repo

        client = TestClient(app)
        created.append(client)
        return client, fake_blob

    yield _build

    for c in created:
        c.close()
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _reset_jwks_client_cache() -> Generator[None, None, None]:
    auth_service._jwks_clients.clear()
    yield
    auth_service._jwks_clients.clear()


def _headers_for(make_entra_token: Callable[..., str], oid: str = DEFAULT_OID) -> dict[str, str]:
    token = make_entra_token({"oid": oid, "groups": []})
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Contract: valid 200 content types & 404 are declared
# ---------------------------------------------------------------------------


def test_openapi_declares_expected_responses(citations_get_op: dict[str, Any]) -> None:
    responses = citations_get_op.get("responses", {})
    assert "200" in responses
    assert "404" in responses
    content = responses["200"].get("content", {})
    # The router uses these media types when streaming; contract MUST include them.
    assert "application/pdf" in content
    assert "application/octet-stream" in content
    assert "image/png" in content
    assert "image/jpeg" in content


def test_openapi_declares_documentid_and_optional_page(
    openapi_spec: dict[str, Any],
) -> None:
    path_item = openapi_spec["paths"]["/citations/{documentId}"]
    params = {p["name"]: p for p in path_item.get("parameters", [])}
    assert params["documentId"]["required"] is True
    assert params["documentId"]["in"] == "path"
    assert params["page"]["required"] is False
    assert params["page"]["in"] == "query"


# ---------------------------------------------------------------------------
# 200 happy paths
# ---------------------------------------------------------------------------


def test_get_shared_document_streams_binary_with_correct_mime(
    app_factory: Any,
    make_entra_token: Callable[..., str],
    citations_get_op: dict[str, Any],
) -> None:
    payload = b"%PDF-1.7\n" + (b"x" * 500)
    doc = _make_doc(
        doc_id="doc-shared-1",
        scope="shared",
        file_name="handbook.pdf",
        mime_type="application/pdf",
    )
    client, fake_blob = app_factory(
        per_scope={"shared": doc},
        blob_payload=payload,
    )

    r = client.get(
        "/citations/doc-shared-1",
        headers=_headers_for(make_entra_token),
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.content == payload
    assert 'filename="handbook.pdf"' in r.headers["content-disposition"]

    # The streamed media-type MUST be one of the contract's declared options.
    declared = set(citations_get_op["responses"]["200"]["content"].keys())
    assert any(r.headers["content-type"].startswith(t) for t in declared)

    # And the router asked Storage for the right (container, blob) pair.
    assert fake_blob.last_call == {
        "container": "shared-corpus",
        "blob": "doc-shared-1/handbook.pdf",
    }


def test_get_user_owned_document_succeeds(
    app_factory: Any, make_entra_token: Callable[..., str]
) -> None:
    payload = b"\x89PNG\r\n\x1a\n" + b"y" * 100
    user_scope = f"user:{DEFAULT_OID}"
    doc = _make_doc(
        doc_id="doc-user-1",
        scope=user_scope,
        file_name="screenshot.png",
        mime_type="image/png",
    )
    client, fake_blob = app_factory(
        per_scope={user_scope: doc},
        blob_payload=payload,
    )

    r = client.get(
        "/citations/doc-user-1",
        headers=_headers_for(make_entra_token, oid=DEFAULT_OID),
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("image/png")
    assert r.content == payload
    assert fake_blob.last_call == {
        "container": "user-uploads",
        "blob": "doc-user-1/screenshot.png",
    }


def test_page_query_param_accepted_and_streams_full_doc(
    app_factory: Any, make_entra_token: Callable[..., str]
) -> None:
    payload = b"%PDF-1.7\n" + b"z" * 200
    doc = _make_doc(scope="shared", mime_type="application/pdf")
    client, _ = app_factory(per_scope={"shared": doc}, blob_payload=payload)

    r = client.get(
        "/citations/doc-1?page=3",
        headers=_headers_for(make_entra_token),
    )
    assert r.status_code == 200
    # We always return the full document binary; the page param is for the
    # client-side viewer — assert no truncation happened.
    assert r.content == payload


# ---------------------------------------------------------------------------
# 404 paths — SC-011 cross-user MUST NOT leak
# ---------------------------------------------------------------------------


def test_cross_user_document_returns_404_not_403(
    app_factory: Any, make_entra_token: Callable[..., str]
) -> None:
    other_oid = "other-user-oid"
    other_scope = f"user:{other_oid}"
    # Doc only exists in another user's partition. The router only ever
    # queries `shared` and `user:<callerOid>`, so this read returns 404 by
    # construction — but we still assert the response shape to lock in
    # SC-011 even if a future refactor accidentally widens the lookup.
    doc = _make_doc(doc_id="doc-other", scope=other_scope)
    client, fake_blob = app_factory(
        per_scope={other_scope: doc},
        blob_payload=b"SECRET",
    )

    r = client.get(
        "/citations/doc-other",
        headers=_headers_for(make_entra_token, oid=DEFAULT_OID),
    )
    assert r.status_code == 404, r.text
    # MUST NOT have read the blob.
    assert fake_blob.last_call is None
    # MUST NOT leak the other user's bytes anywhere in the body.
    assert b"SECRET" not in r.content


def test_unknown_document_returns_404(
    app_factory: Any, make_entra_token: Callable[..., str]
) -> None:
    client, fake_blob = app_factory(per_scope={}, blob_payload=b"")
    r = client.get(
        "/citations/does-not-exist",
        headers=_headers_for(make_entra_token),
    )
    assert r.status_code == 404
    assert fake_blob.last_call is None


def test_unauthenticated_returns_401(app_factory: Any) -> None:
    client, _ = app_factory(per_scope={}, blob_payload=b"")
    r = client.get("/citations/doc-1")
    assert r.status_code == 401
