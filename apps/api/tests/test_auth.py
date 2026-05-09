"""Smoke tests for Entra JWT auth + CurrentUser dependency (T035).

Refactored under T046 to consume the shared fixtures
(`synthetic_jwks_keypair`, `make_entra_token`, `patched_jwks_client`)
defined in ``tests/_shared/fixtures.py``.
"""

from __future__ import annotations

from collections.abc import Callable, Generator, Iterator
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt

from src.config import Settings, get_settings
from src.main import create_app
from src.services import auth as auth_service
from tests._shared.fixtures import (
    DEFAULT_AUDIENCE,
    DEFAULT_ISSUER_V2,
    DEFAULT_TENANT_ID,
)

_CLIENT_ID = "22222222-2222-2222-2222-222222222222"
_ADMIN_GROUP = "admin-group-oid"
_USER_GROUP = "user-group-oid"
_OUTSIDER_GROUP = "outsider-group-oid"


# ---------------------------------------------------------------------------
# App fixture: settings override layered on top of patched_jwks_client
# ---------------------------------------------------------------------------


def _make_settings(
    *,
    allowed_groups: list[str] | None = None,
    admin_group: str | None = _ADMIN_GROUP,
) -> Settings:
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
        ADMIN_GROUP_OBJECT_ID=admin_group,
        ALLOWED_USER_GROUP_OBJECT_IDS=allowed_groups or [],
    )  # type: ignore[call-arg]


@pytest.fixture
def client_factory(patched_jwks_client: Any) -> Iterator[Any]:
    """Yields a callable that builds a TestClient with overridden settings.

    The shared ``patched_jwks_client`` fixture has already monkeypatched
    ``services.auth._get_jwks_client`` against the synthetic JWKS, so any
    token minted via ``make_entra_token`` validates locally.
    """
    get_settings.cache_clear()
    created: list[TestClient] = []

    def _build(
        *,
        allowed_groups: list[str] | None = None,
        admin_group: str | None = _ADMIN_GROUP,
    ) -> TestClient:
        app = create_app()
        settings = _make_settings(allowed_groups=allowed_groups, admin_group=admin_group)
        app.dependency_overrides[get_settings] = lambda: settings
        c = TestClient(app)
        created.append(c)
        return c

    yield _build

    for c in created:
        c.close()
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _reset_jwks_client_cache() -> Generator[None, None, None]:
    auth_service._jwks_clients.clear()
    yield
    auth_service._jwks_clients.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_valid_token_returns_me(
    client_factory: Any, make_entra_token: Callable[..., str]
) -> None:
    client = client_factory()
    token = make_entra_token({"groups": [_USER_GROUP], "name": "Ada Lovelace"})
    r = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["oid"] == "user-oid-1"
    assert body["displayName"] == "Ada Lovelace"
    assert body["role"] == "user"
    assert body["groups"] == [_USER_GROUP]


def test_admin_group_yields_admin_role(
    client_factory: Any, make_entra_token: Callable[..., str]
) -> None:
    client = client_factory()
    token = make_entra_token({"groups": [_ADMIN_GROUP, _USER_GROUP]})
    r = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "admin"


def test_invalid_signature_returns_401(client_factory: Any) -> None:
    """A token signed by an unrelated key must fail signature validation."""
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other_pem = other_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    import time

    now = int(time.time())
    token = jose_jwt.encode(
        {
            "iss": DEFAULT_ISSUER_V2,
            "aud": DEFAULT_AUDIENCE,
            "iat": now,
            "nbf": now - 1,
            "exp": now + 3600,
            "oid": "user-oid-1",
            "name": "Ada",
            "groups": [_USER_GROUP],
        },
        other_pem,
        algorithm="RS256",
        headers={"kid": "test-kid-1"},
    )
    client = client_factory()
    r = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401, r.text
    assert r.json()["code"] == "authentication_required"


def test_group_gate_rejects_outsider_with_403(
    client_factory: Any, make_entra_token: Callable[..., str]
) -> None:
    client = client_factory(allowed_groups=[_USER_GROUP])
    token = make_entra_token({"groups": [_OUTSIDER_GROUP]})
    r = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403, r.text
    assert r.json()["code"] == "permission_denied"


def test_missing_authorization_returns_401(client_factory: Any) -> None:
    client = client_factory()
    r = client.get("/me")
    assert r.status_code == 401
    assert r.json()["code"] == "authentication_required"
