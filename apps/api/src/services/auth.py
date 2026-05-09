"""Entra ID JWT authentication (T035).

Validates an `Authorization: Bearer <jwt>` header against the tenant's JWKS,
enforces the optional group-restriction gate (research.md D8), and yields a
:class:`CurrentUser` via the :func:`current_user` FastAPI dependency.

Library choice
--------------
We use :mod:`jose` (``python-jose[cryptography]``) for JWT validation. JWT
verification is CPU-bound + sync; both ``python-jose`` and ``pyjwt`` are sync
for the verify step. Async only matters for the JWKS fetch — we use
``httpx.AsyncClient`` for that. python-jose is the lighter dep that's already
pinned in ``pyproject.toml`` and accepts a JWKS dict directly without needing
a JWK client wrapper.

JWKS caching
------------
A process-local TTL cache keyed by ``kid`` (refreshed on miss/expiry). On
cache miss for a presented ``kid`` we force a refetch (handles key rotation
without waiting for TTL).

Group claim semantics
---------------------
* ``role = "admin"`` iff ``ADMIN_GROUP_OBJECT_ID`` ∈ ``groups``.
* If ``ALLOWED_USER_GROUP_OBJECT_IDS`` is non-empty, the caller MUST be in
  at least one of those groups, otherwise we reject with 403.

NOTE on overage: when a user is in too many groups Entra emits ``_claim_names``
/ ``_claim_sources`` instead of inlining ``groups``. Resolving the overage
requires a Graph callback — that's an *app registration* concern (configure
the app to emit only security groups assigned to the application). We mirror
the same posture as ``apps/web/src/lib/auth.ts`` and treat overage tokens as
having an empty ``groups`` claim at runtime.

Token bytes are never logged.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Final

import httpx
from fastapi import Depends, Header
from jose import jwt
from jose.exceptions import ExpiredSignatureError, JWKError, JWTError

from ..config import Settings, get_settings
from ..middleware.error_handler import AuthenticationError, PermissionDenied
from ..middleware.logging import get_logger
from ..models import CurrentUser

_log = get_logger(__name__)

# JWKS TTL (seconds). Microsoft rotates signing keys every ~24h; one hour
# gives us prompt rotation pickup without hammering the discovery endpoint.
_JWKS_TTL_SECONDS: Final[int] = 3600
# Hard cap on key set size (defense-in-depth against a misbehaving endpoint).
_JWKS_MAX_KEYS: Final[int] = 32
# Per-fetch timeout for the JWKS HTTP call.
_JWKS_HTTP_TIMEOUT: Final[float] = 5.0


# ---------------------------------------------------------------------------
# JWKS cache
# ---------------------------------------------------------------------------


@dataclass
class _JwksCacheEntry:
    keys_by_kid: dict[str, dict[str, Any]]
    fetched_at: float


class JwksClient:
    """Async JWKS fetcher with per-tenant TTL caching, keyed by ``kid``.

    Safe for concurrent use; a single asyncio lock serialises refetches so
    we never stampede the discovery endpoint on cold start or rotation.
    """

    def __init__(self, tenant_id: str, *, ttl_seconds: int = _JWKS_TTL_SECONDS) -> None:
        if not tenant_id or not tenant_id.strip():
            raise ValueError("tenant_id must not be empty")
        self._tenant_id = tenant_id
        self._ttl = ttl_seconds
        self._jwks_url = (
            f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
        )
        self._cache: _JwksCacheEntry | None = None
        self._lock = asyncio.Lock()

    @property
    def jwks_url(self) -> str:
        return self._jwks_url

    async def get_signing_key(self, kid: str) -> dict[str, Any]:
        """Return the JWK dict for ``kid``, refreshing the cache on miss/expiry."""
        if not kid:
            raise AuthenticationError("Token header is missing 'kid'")
        cache = self._cache
        now = time.monotonic()
        if cache is not None and (now - cache.fetched_at) < self._ttl:
            key = cache.keys_by_kid.get(kid)
            if key is not None:
                return key
            # kid not present — possible rotation; force refetch below.
        return await self._refresh_and_get(kid)

    async def _refresh_and_get(self, kid: str) -> dict[str, Any]:
        async with self._lock:
            # Re-check after acquiring the lock — another coroutine may have refreshed.
            cache = self._cache
            now = time.monotonic()
            fresh_enough = cache is not None and (now - cache.fetched_at) < self._ttl
            if fresh_enough and cache is not None and kid in cache.keys_by_kid:
                return cache.keys_by_kid[kid]
            try:
                async with httpx.AsyncClient(timeout=_JWKS_HTTP_TIMEOUT) as client:
                    resp = await client.get(self._jwks_url)
                resp.raise_for_status()
                payload: Any = resp.json()
            except (httpx.HTTPError, ValueError) as exc:
                _log.warning("jwks_fetch_failed", error_type=type(exc).__name__)
                raise AuthenticationError("Unable to fetch JWKS") from exc

            keys = payload.get("keys") if isinstance(payload, dict) else None
            if not isinstance(keys, list) or not keys:
                raise AuthenticationError("JWKS document has no keys")
            keys_by_kid: dict[str, dict[str, Any]] = {}
            for k in keys[:_JWKS_MAX_KEYS]:
                if isinstance(k, dict):
                    k_kid = k.get("kid")
                    if isinstance(k_kid, str):
                        keys_by_kid[k_kid] = k
            self._cache = _JwksCacheEntry(keys_by_kid=keys_by_kid, fetched_at=now)
            key = keys_by_kid.get(kid)
            if key is None:
                raise AuthenticationError("Unknown signing key 'kid'")
            return key


# ---------------------------------------------------------------------------
# Token validation
# ---------------------------------------------------------------------------


def _expected_issuers(tenant_id: str) -> tuple[str, ...]:
    """v1.0 (`sts.windows.net`) and v2.0 (`login.microsoftonline.com/.../v2.0`).

    Either issuer is accepted because Entra emits v1.0 tokens for resources
    configured with ``accessTokenAcceptedVersion=1`` and v2.0 otherwise.
    """
    return (
        f"https://login.microsoftonline.com/{tenant_id}/v2.0",
        f"https://sts.windows.net/{tenant_id}/",
    )


def _expected_audience(settings: Settings) -> str:
    if settings.ENTRA_API_AUDIENCE and settings.ENTRA_API_AUDIENCE.strip():
        return settings.ENTRA_API_AUDIENCE
    return f"api://{settings.AZURE_CLIENT_ID}"


def _extract_bearer(authorization: str | None) -> str:
    if not authorization:
        raise AuthenticationError("Missing Authorization header")
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise AuthenticationError("Authorization header must be 'Bearer <token>'")
    return parts[1].strip()


def _compute_role(groups: list[str], admin_group_id: str | None) -> str:
    if admin_group_id and admin_group_id in groups:
        return "admin"
    return "user"


def _enforce_group_gate(groups: list[str], allowed: list[str]) -> None:
    """Reject if the allow-list is set and groups doesn't intersect it (D8)."""
    if not allowed:
        return
    if not groups or not any(g in allowed for g in groups):
        raise PermissionDenied(
            "Caller is not a member of any allowed Entra group",
            details={"reason": "group_restriction"},
        )


def _coerce_groups(claim: object) -> list[str]:
    if isinstance(claim, list):
        return [g for g in claim if isinstance(g, str)]
    return []


# Module-level JwksClient cache, keyed by tenant_id, so we share the JWKS
# cache across requests in the same worker.
_jwks_clients: dict[str, JwksClient] = {}
_jwks_clients_lock = asyncio.Lock()


async def _get_jwks_client(tenant_id: str) -> JwksClient:
    client = _jwks_clients.get(tenant_id)
    if client is not None:
        return client
    async with _jwks_clients_lock:
        client = _jwks_clients.get(tenant_id)
        if client is None:
            client = JwksClient(tenant_id)
            _jwks_clients[tenant_id] = client
        return client


async def validate_token(token: str, settings: Settings) -> CurrentUser:
    """Validate ``token`` against the tenant JWKS and return a CurrentUser.

    Raises :class:`AuthenticationError` (401) on any signature/claim failure
    and :class:`PermissionDenied` (403) when the group-restriction gate fails.
    """
    try:
        unverified_header = jwt.get_unverified_header(token)
    except JWTError as exc:
        raise AuthenticationError("Malformed token header") from exc

    kid = unverified_header.get("kid") if isinstance(unverified_header, dict) else None
    if not isinstance(kid, str):
        raise AuthenticationError("Token header is missing 'kid'")

    jwks_client = await _get_jwks_client(settings.AZURE_TENANT_ID)
    try:
        jwk_dict = await jwks_client.get_signing_key(kid)
    except AuthenticationError:
        raise
    except Exception as exc:  # noqa: BLE001 — surface as 401 regardless of internal error
        _log.warning("jwks_lookup_failed", error_type=type(exc).__name__)
        raise AuthenticationError("Unable to resolve signing key") from exc

    audience = _expected_audience(settings)
    issuers = _expected_issuers(settings.AZURE_TENANT_ID)

    last_err: Exception | None = None
    claims: dict[str, Any] | None = None
    for issuer in issuers:
        try:
            claims = jwt.decode(
                token,
                jwk_dict,
                algorithms=["RS256"],
                audience=audience,
                issuer=issuer,
                options={"require": ["exp", "iat", "iss", "aud"]},
            )
            break
        except ExpiredSignatureError as exc:
            raise AuthenticationError("Token expired") from exc
        except (JWTError, JWKError) as exc:
            last_err = exc
            continue
    if claims is None:
        _log.info("jwt_validation_failed", error_type=type(last_err).__name__ if last_err else None)
        raise AuthenticationError("Invalid token") from last_err

    oid_claim = claims.get("oid") or claims.get("sub")
    if not isinstance(oid_claim, str) or not oid_claim:
        raise AuthenticationError("Token is missing 'oid'/'sub'")

    name_claim: str | None = None
    for key in ("name", "preferred_username", "upn", "unique_name"):
        v = claims.get(key)
        if isinstance(v, str) and v.strip():
            name_claim = v
            break
    if name_claim is None:
        name_claim = oid_claim

    groups = _coerce_groups(claims.get("groups"))
    _enforce_group_gate(groups, settings.ALLOWED_USER_GROUP_OBJECT_IDS)

    role = _compute_role(groups, settings.ADMIN_GROUP_OBJECT_ID)

    return CurrentUser(
        oid=oid_claim,
        display_name=name_claim,
        role=role,  # type: ignore[arg-type]
        groups=groups,
    )


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


async def current_user(
    authorization: str | None = Header(default=None, alias="Authorization"),
    settings: Settings = Depends(get_settings),  # noqa: B008 — FastAPI DI idiom
) -> CurrentUser:
    """FastAPI dependency: extract Bearer token, validate, return CurrentUser."""
    token = _extract_bearer(authorization)
    return await validate_token(token, settings)


__all__ = [
    "CurrentUser",
    "JwksClient",
    "current_user",
    "validate_token",
]
