"""Smoke tests for Entra JWT auth + CurrentUser dependency (T035).

These are pure unit/integration tests against the FastAPI app — no live
Entra dependency. We mint our own RSA key, expose a fake JWKS, and stub
``services.auth._get_jwks_client`` so ``validate_token`` resolves keys
locally without HTTP. T046 will replace these with shared fixtures.
"""

from __future__ import annotations

import base64
import time
from collections.abc import Generator, Iterator
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt

from src.config import Settings, get_settings
from src.main import create_app
from src.services import auth as auth_service

# ---------------------------------------------------------------------------
# RSA key + JWKS fixtures
# ---------------------------------------------------------------------------

_TENANT_ID = "11111111-1111-1111-1111-111111111111"
_CLIENT_ID = "22222222-2222-2222-2222-222222222222"
_AUDIENCE = f"api://{_CLIENT_ID}"
_ISSUER_V2 = f"https://login.microsoftonline.com/{_TENANT_ID}/v2.0"
_ADMIN_GROUP = "admin-group-oid"
_USER_GROUP = "user-group-oid"
_OUTSIDER_GROUP = "outsider-group-oid"


def _b64url_uint(n: int) -> str:
    length = (n.bit_length() + 7) // 8
    return base64.urlsafe_b64encode(n.to_bytes(length, "big")).rstrip(b"=").decode("ascii")


@pytest.fixture(scope="module")
def signing_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def signing_kid() -> str:
    return "test-kid-1"


@pytest.fixture(scope="module")
def jwk_public(signing_key: rsa.RSAPrivateKey, signing_kid: str) -> dict[str, Any]:
    pub = signing_key.public_key().public_numbers()
    return {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": signing_kid,
        "n": _b64url_uint(pub.n),
        "e": _b64url_uint(pub.e),
    }


@pytest.fixture(scope="module")
def signing_pem(signing_key: rsa.RSAPrivateKey) -> bytes:
    return signing_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def _mint(
    *,
    pem: bytes,
    kid: str,
    oid: str = "user-oid-1",
    name: str = "Ada Lovelace",
    groups: list[str] | None = None,
    audience: str = _AUDIENCE,
    issuer: str = _ISSUER_V2,
    exp_offset: int = 3600,
) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": issuer,
        "aud": audience,
        "iat": now,
        "nbf": now - 1,
        "exp": now + exp_offset,
        "oid": oid,
        "name": name,
    }
    if groups is not None:
        claims["groups"] = groups
    return jose_jwt.encode(claims, pem, algorithm="RS256", headers={"kid": kid})


# ---------------------------------------------------------------------------
# App fixture: settings override + JWKS client stub
# ---------------------------------------------------------------------------


def _make_settings(
    *,
    allowed_groups: list[str] | None = None,
    admin_group: str | None = _ADMIN_GROUP,
) -> Settings:
    return Settings(
        AZURE_TENANT_ID=_TENANT_ID,
        AZURE_CLIENT_ID=_CLIENT_ID,
        ENTRA_API_AUDIENCE=_AUDIENCE,
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


class _StubJwksClient:
    def __init__(self, jwk: dict[str, Any]) -> None:
        self._jwk = jwk

    async def get_signing_key(self, kid: str) -> dict[str, Any]:
        if kid != self._jwk["kid"]:
            from src.middleware.error_handler import AuthenticationError

            raise AuthenticationError("Unknown signing key 'kid'")
        return self._jwk


@pytest.fixture
def client_factory(
    monkeypatch: pytest.MonkeyPatch, jwk_public: dict[str, Any]
) -> Iterator[Any]:
    """Yields a callable that builds a TestClient with overridden settings."""

    stub = _StubJwksClient(jwk_public)

    async def _fake_get_jwks_client(_tenant_id: str) -> Any:
        return stub

    monkeypatch.setattr(auth_service, "_get_jwks_client", _fake_get_jwks_client)
    get_settings.cache_clear()

    created: list[TestClient] = []

    def _build(*, allowed_groups: list[str] | None = None,
               admin_group: str | None = _ADMIN_GROUP) -> TestClient:
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
    client_factory: Any, signing_pem: bytes, signing_kid: str
) -> None:
    client = client_factory()
    token = _mint(pem=signing_pem, kid=signing_kid, groups=[_USER_GROUP])
    r = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["oid"] == "user-oid-1"
    assert body["displayName"] == "Ada Lovelace"
    assert body["role"] == "user"
    assert body["groups"] == [_USER_GROUP]


def test_admin_group_yields_admin_role(
    client_factory: Any, signing_pem: bytes, signing_kid: str
) -> None:
    client = client_factory()
    token = _mint(pem=signing_pem, kid=signing_kid, groups=[_ADMIN_GROUP, _USER_GROUP])
    r = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "admin"


def test_invalid_signature_returns_401(
    client_factory: Any, signing_kid: str
) -> None:
    """A token signed by an unrelated key must fail signature validation."""
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other_pem = other_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    client = client_factory()
    token = _mint(pem=other_pem, kid=signing_kid, groups=[_USER_GROUP])
    r = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401, r.text
    assert r.json()["code"] == "authentication_required"


def test_group_gate_rejects_outsider_with_403(
    client_factory: Any, signing_pem: bytes, signing_kid: str
) -> None:
    client = client_factory(allowed_groups=[_USER_GROUP])
    token = _mint(pem=signing_pem, kid=signing_kid, groups=[_OUTSIDER_GROUP])
    r = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403, r.text
    assert r.json()["code"] == "permission_denied"


def test_missing_authorization_returns_401(client_factory: Any) -> None:
    client = client_factory()
    r = client.get("/me")
    assert r.status_code == 401
    assert r.json()["code"] == "authentication_required"
