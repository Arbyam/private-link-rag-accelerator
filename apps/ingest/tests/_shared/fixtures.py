"""Shared pytest fixtures for the Private RAG Accelerator test suites (T046).

This module is loaded as a pytest plugin (see each ``conftest.py``'s
``pytest_plugins``). It provides:

* Synthetic Entra ID JWT signing primitives backed by an in-process JWKS:
  ``synthetic_jwks_keypair``, ``make_entra_token``, ``patched_jwks_client``.
* The ``integration_invnet`` marker handler — auto-skips marked tests
  unless ``RUN_INVNET_TESTS=1`` is set in the environment.
* A ``cosmos_emulator`` fixture that returns either an ``AsyncMock`` shaped
  like ``azure.cosmos.aio.CosmosClient`` (unit tests) or a real client
  pointed at a local Cosmos emulator when ``COSMOS_EMULATOR_ENDPOINT`` is
  set (in-VNet integration tests).
* Lightweight async mocks for the other Azure SDK clients used by the api/
  ingest services: Blob, Search, AOAI.

Per ``specs/001-private-rag-accelerator/plan.md`` (Testing): deployed-env
tests run on the in-VNet runner against the **real** deployed Cosmos —
never the emulator. The emulator path here only exists for engineers who
want to exercise the marker locally.
"""

from __future__ import annotations

import base64
import os
import time
from collections.abc import Callable, Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt as jose_jwt

# ---------------------------------------------------------------------------
# Defaults — kept out of fixtures so callers can import these for assertions
# ---------------------------------------------------------------------------

DEFAULT_TENANT_ID = "11111111-1111-1111-1111-111111111111"
DEFAULT_CLIENT_ID = "22222222-2222-2222-2222-222222222222"
DEFAULT_AUDIENCE = f"api://{DEFAULT_CLIENT_ID}"
DEFAULT_ISSUER_V2 = f"https://login.microsoftonline.com/{DEFAULT_TENANT_ID}/v2.0"
DEFAULT_OID = "user-oid-1"
DEFAULT_KID = "test-kid-1"


# ---------------------------------------------------------------------------
# JWKS / JWT
# ---------------------------------------------------------------------------


def _b64url_uint(n: int) -> str:
    length = (n.bit_length() + 7) // 8
    return base64.urlsafe_b64encode(n.to_bytes(length, "big")).rstrip(b"=").decode("ascii")


@pytest.fixture(scope="session")
def synthetic_jwks_keypair() -> tuple[bytes, dict[str, Any]]:
    """Session-scoped RSA-2048 keypair + JWKS document.

    Returns ``(private_key_pem, jwks_dict)`` where ``jwks_dict`` matches the
    Entra discovery payload shape: ``{"keys": [{kid, kty, use, alg, n, e}]}``.
    The kid is :data:`DEFAULT_KID`.
    """
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub = key.public_key().public_numbers()
    jwks: dict[str, Any] = {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "kid": DEFAULT_KID,
                "n": _b64url_uint(pub.n),
                "e": _b64url_uint(pub.e),
            }
        ]
    }
    return pem, jwks


@pytest.fixture
def make_entra_token(
    synthetic_jwks_keypair: tuple[bytes, dict[str, Any]],
) -> Callable[..., str]:
    """Factory: mint a synthetic Entra-shaped RS256 JWT.

    Usage::

        token = make_entra_token({"groups": ["abc"], "oid": "u1"})
        token = make_entra_token(kid="rotated-kid")  # forces a JWKS miss

    Default claims: ``iss`` = v2.0 issuer for :data:`DEFAULT_TENANT_ID`,
    ``aud`` = :data:`DEFAULT_AUDIENCE`, ``exp`` = now+3600, ``nbf`` = now-60,
    ``iat`` = now, ``oid`` = :data:`DEFAULT_OID`, ``tid`` = tenant,
    ``name`` = ``"Test User"``, ``groups`` = ``[]``.
    """
    pem, jwks = synthetic_jwks_keypair
    default_kid: str = jwks["keys"][0]["kid"]

    def _make(
        claims_overrides: dict[str, Any] | None = None,
        *,
        kid: str = default_kid,
    ) -> str:
        now = int(time.time())
        claims: dict[str, Any] = {
            "iss": DEFAULT_ISSUER_V2,
            "aud": DEFAULT_AUDIENCE,
            "iat": now,
            "nbf": now - 60,
            "exp": now + 3600,
            "oid": DEFAULT_OID,
            "tid": DEFAULT_TENANT_ID,
            "name": "Test User",
            "groups": [],
        }
        if claims_overrides:
            claims.update(claims_overrides)
        return jose_jwt.encode(claims, pem, algorithm="RS256", headers={"kid": kid})

    return _make


class _StubJwksClient:
    """Drop-in replacement for ``apps.api.src.services.auth.JwksClient``."""

    def __init__(self, jwks: dict[str, Any]) -> None:
        self._by_kid = {k["kid"]: k for k in jwks["keys"] if "kid" in k}

    async def get_signing_key(self, kid: str) -> dict[str, Any]:
        key = self._by_kid.get(kid)
        if key is None:
            try:
                from src.middleware.error_handler import (  # type: ignore[import-not-found]
                    AuthenticationError,
                )

                raise AuthenticationError("Unknown signing key 'kid'")
            except ImportError:  # pragma: no cover — ingest path
                raise RuntimeError(f"Unknown kid {kid}") from None
        return key


@pytest.fixture
def patched_jwks_client(
    monkeypatch: pytest.MonkeyPatch,
    synthetic_jwks_keypair: tuple[bytes, dict[str, Any]],
) -> _StubJwksClient:
    """Monkeypatch the auth service's JWKS lookup to use the synthetic keypair.

    Best-effort: patches ``apps.api.src.services.auth._get_jwks_client`` if
    importable (api suite) and the equivalent ingest hook if/when it exists.
    Returns the stub for direct assertions if a test wants them.
    """
    _, jwks = synthetic_jwks_keypair
    stub = _StubJwksClient(jwks)

    async def _fake_get_jwks_client(_tenant_id: str) -> _StubJwksClient:
        return stub

    try:
        from src.services import auth as api_auth  # type: ignore[import-not-found]

        monkeypatch.setattr(api_auth, "_get_jwks_client", _fake_get_jwks_client)
        if hasattr(api_auth, "_jwks_clients"):
            api_auth._jwks_clients.clear()  # type: ignore[attr-defined]
    except ImportError:
        pass

    return stub


# ---------------------------------------------------------------------------
# In-VNet integration marker
# ---------------------------------------------------------------------------


_RUN_INVNET_ENV = "RUN_INVNET_TESTS"


def pytest_configure(config: pytest.Config) -> None:
    """Register the ``integration_invnet`` marker on every project that loads us."""
    config.addinivalue_line(
        "markers",
        "integration_invnet: requires in-VNet runner with real Azure deps "
        "(Cosmos, Search, OpenAI, Storage). Skipped unless RUN_INVNET_TESTS=1.",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Auto-skip ``integration_invnet`` tests outside the in-VNet runner."""
    if os.environ.get(_RUN_INVNET_ENV) == "1":
        return
    skip = pytest.mark.skip(
        reason=f"integration_invnet test — set {_RUN_INVNET_ENV}=1 to run on in-VNet runner",
    )
    for item in items:
        if "integration_invnet" in item.keywords:
            item.add_marker(skip)


# ---------------------------------------------------------------------------
# Cosmos: emulator-or-mock fixture
# ---------------------------------------------------------------------------

# Public well-known emulator master key — NOT a secret. Documented at:
# https://learn.microsoft.com/azure/cosmos-db/local-emulator
_COSMOS_EMULATOR_KEY = (
    "C2y6yDjf5/R+ob0N8A7Cgv30VRDJIWEHLM+4QDU5DE2nQ9nDuVTqobD4b8mGGyPMbIZnqyMsEcaGQy67XIw/Jw=="
)


def _make_async_cosmos_container_mock() -> MagicMock:
    """Build a mock shaped like ``azure.cosmos.aio.ContainerProxy``."""
    container = MagicMock(name="ContainerProxy")
    container.read_item = AsyncMock()
    container.upsert_item = AsyncMock()
    container.create_item = AsyncMock()
    container.delete_item = AsyncMock()
    container.query_items = MagicMock()
    return container


def _make_async_cosmos_client_mock() -> MagicMock:
    """Mock chain: ``client.get_database_client(...).get_container_client(...)``."""
    client = MagicMock(name="CosmosClient")
    container = _make_async_cosmos_container_mock()
    db = MagicMock(name="DatabaseProxy")
    db.get_container_client = MagicMock(return_value=container)
    client.get_database_client = MagicMock(return_value=db)
    client.__test_container__ = container
    client.__test_database__ = db
    client.close = AsyncMock()
    return client


@pytest.fixture
def cosmos_emulator() -> Iterator[Any]:
    """Cosmos client for unit OR in-VNet integration tests.

    Behaviour:

    * If ``COSMOS_EMULATOR_ENDPOINT`` is set (typically only on the in-VNet
      runner with the emulator running), yields a real
      ``azure.cosmos.aio.CosmosClient`` connected with the well-known public
      emulator master key. The client is closed on teardown.
    * Otherwise yields an :class:`unittest.mock.MagicMock` shaped like
      ``CosmosClient`` with ``get_database_client(...).get_container_client(...)``
      pre-wired. Convenience attributes ``__test_database__`` and
      ``__test_container__`` expose the inner mocks for assertions.

    Per plan.md Testing, deployed-env tests run against the **real**
    deployed Cosmos via the in-VNet runner (NOT this emulator path); the
    emulator branch exists for local engineer convenience only.
    """
    endpoint = os.environ.get("COSMOS_EMULATOR_ENDPOINT")
    if endpoint:  # pragma: no cover — only exercised on machines with the emulator
        from azure.cosmos.aio import CosmosClient

        client = CosmosClient(endpoint, credential=_COSMOS_EMULATOR_KEY)
        try:
            yield client
        finally:
            import asyncio
            import contextlib

            with contextlib.suppress(RuntimeError):
                asyncio.get_event_loop().run_until_complete(client.close())
        return

    yield _make_async_cosmos_client_mock()


# ---------------------------------------------------------------------------
# Other Azure SDK mocks (low-friction DRY-ups)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_blob_service_client() -> MagicMock:
    """Async mock for ``azure.storage.blob.aio.BlobServiceClient``.

    Pre-wires ``get_container_client(...).get_blob_client(...)`` and
    ``upload_blob`` / ``download_blob`` async leaves.
    """
    blob = MagicMock(name="BlobClient")
    blob.upload_blob = AsyncMock()
    blob.download_blob = AsyncMock()
    blob.delete_blob = AsyncMock()
    blob.get_blob_properties = AsyncMock()

    container = MagicMock(name="ContainerClient")
    container.get_blob_client = MagicMock(return_value=blob)
    container.upload_blob = AsyncMock()

    svc = MagicMock(name="BlobServiceClient")
    svc.get_container_client = MagicMock(return_value=container)
    svc.close = AsyncMock()

    svc.__test_container__ = container
    svc.__test_blob__ = blob
    return svc


@pytest.fixture
def mock_search_client() -> MagicMock:
    """Async mock for ``azure.search.documents.aio.SearchClient``."""
    sc = MagicMock(name="SearchClient")
    sc.search = AsyncMock()
    sc.upload_documents = AsyncMock()
    sc.merge_or_upload_documents = AsyncMock()
    sc.delete_documents = AsyncMock()
    sc.close = AsyncMock()
    return sc


@pytest.fixture
def mock_aoai_client() -> MagicMock:
    """Async mock for ``openai.AsyncAzureOpenAI``.

    Pre-wires ``chat.completions.create``, ``embeddings.create``.
    """
    chat = MagicMock(name="chat")
    chat.completions = MagicMock()
    chat.completions.create = AsyncMock()

    embeddings = MagicMock(name="embeddings")
    embeddings.create = AsyncMock()

    client = MagicMock(name="AsyncAzureOpenAI")
    client.chat = chat
    client.embeddings = embeddings
    client.close = AsyncMock()
    return client
