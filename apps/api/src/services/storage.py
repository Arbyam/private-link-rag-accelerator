"""Blob Storage service (T038).

Exposes a Managed-Identity-bound `BlobServiceClient` factory and the
`assert_blob_in_owned_account` invariant helper required by data-model.md §3.

Hard rules enforced in this module:

* No shared-key auth, ever (`allowSharedKeyAccess: false` on the account).
  Every client is built with `DefaultAzureCredential`, and downloads use
  **User Delegation SAS** issued via the MI — never an account-key SAS.
* Any blob URI we accept for processing MUST live in the platform-owned
  storage account. `assert_blob_in_owned_account` is the defense-in-depth
  gate against confused-deputy attacks where a caller hands us an
  attacker-controlled blob URL.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from azure.identity.aio import DefaultAzureCredential
from azure.storage.blob import (
    BlobSasPermissions,
    generate_blob_sas,
)
from azure.storage.blob.aio import BlobServiceClient

from ..config import Settings, get_settings
from ..middleware.error_handler import AppError

if TYPE_CHECKING:
    from azure.storage.blob.aio import ContainerClient


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class InvariantViolationError(AppError):
    """Raised when a runtime invariant from data-model.md is violated.

    These are programmer/security errors, not user-input errors — surfaced as
    HTTP 500 so they show up loudly in dashboards. Callers should validate
    user input *before* it reaches this layer.
    """

    status_code = 500
    code = "invariant_violation"


# ---------------------------------------------------------------------------
# Container name helpers (mirror env-var contract with infra/postprovision)
# ---------------------------------------------------------------------------


_DEFAULT_CORPUS_CONTAINER = "shared-corpus"
_DEFAULT_USER_UPLOADS_CONTAINER = "user-uploads"
_BLOB_HOST_SUFFIX = ".blob.core.windows.net"


def _container_from_env(name: str, default: str) -> str:
    import os

    value = os.environ.get(name, default).strip()
    return value or default


def get_corpus_container() -> str:
    return _container_from_env("AZURE_STORAGE_CORPUS_CONTAINER", _DEFAULT_CORPUS_CONTAINER)


def get_user_uploads_container() -> str:
    return _container_from_env(
        "AZURE_STORAGE_USER_UPLOADS_CONTAINER", _DEFAULT_USER_UPLOADS_CONTAINER
    )


def _account_url(settings: Settings) -> str:
    return f"https://{settings.STORAGE_ACCOUNT_NAME}{_BLOB_HOST_SUFFIX}"


def _account_host(settings: Settings) -> str:
    return f"{settings.STORAGE_ACCOUNT_NAME}{_BLOB_HOST_SUFFIX}"


# ---------------------------------------------------------------------------
# Singleton client (MI-bound, async)
# ---------------------------------------------------------------------------


_client: BlobServiceClient | None = None
_credential: DefaultAzureCredential | None = None
_lock = asyncio.Lock()


async def get_blob_service_client() -> BlobServiceClient:
    """Return the process-wide async `BlobServiceClient`, creating it lazily.

    Bound to the workload's managed identity via `DefaultAzureCredential`.
    Callers MUST NOT close this client; lifecycle is owned by `close_blob_clients()`
    invoked from the FastAPI shutdown hook.
    """
    global _client, _credential
    if _client is not None:
        return _client
    async with _lock:
        if _client is None:
            settings = get_settings()
            _credential = DefaultAzureCredential()
            _client = BlobServiceClient(
                account_url=_account_url(settings),
                credential=_credential,
            )
    return _client


async def close_blob_clients() -> None:
    """Release the singleton client + credential. Call on app shutdown."""
    global _client, _credential
    if _client is not None:
        await _client.close()
        _client = None
    if _credential is not None:
        await _credential.close()
        _credential = None


async def get_container_client(container_name: str) -> ContainerClient:
    svc = await get_blob_service_client()
    return svc.get_container_client(container_name)


# ---------------------------------------------------------------------------
# Invariant: blob URI must live in the owned storage account
# ---------------------------------------------------------------------------


def assert_blob_in_owned_account(
    blob_uri: str, *, settings: Settings | None = None
) -> None:
    """Defense-in-depth gate per data-model.md §3.

    Reject any blob URI that:
      * is not HTTPS,
      * is not on the configured ``*.blob.core.windows.net`` account,
      * carries a SAS query (``?sig=``) — we use MI, so a caller-supplied
        SAS is suspicious and never required.

    Raises:
        InvariantViolationError: on any rule failure. The exception message is
            safe for logs but is **not** propagated to clients verbatim — the
            global error handler maps it to a generic 500.
    """
    if not blob_uri or not isinstance(blob_uri, str):
        raise InvariantViolationError("blob URI is empty or not a string")

    parsed = urlparse(blob_uri)

    if parsed.scheme != "https":
        raise InvariantViolationError(
            f"blob URI must use https (got scheme={parsed.scheme!r})"
        )

    host = (parsed.hostname or "").lower()
    if not host.endswith(_BLOB_HOST_SUFFIX):
        raise InvariantViolationError(
            f"blob URI host {host!r} is not an Azure Blob endpoint"
        )

    expected = _account_host(settings or get_settings()).lower()
    if host != expected:
        raise InvariantViolationError(
            f"blob URI host {host!r} is not the platform-owned account {expected!r}"
        )

    # SAS tokens use ?sig=...; we are MI-only so any sig= is suspicious.
    query = (parsed.query or "").lower()
    if "sig=" in query:
        raise InvariantViolationError("blob URI carries a SAS signature; rejected")

    if not parsed.path or parsed.path == "/":
        raise InvariantViolationError("blob URI is missing container/blob path")


# ---------------------------------------------------------------------------
# Upload / download helpers
# ---------------------------------------------------------------------------


async def upload_blob(
    container: str,
    name: str,
    data: bytes,
    content_type: str | None = None,
) -> str:
    """Upload `data` to `container/name`. Returns the blob URI.

    Overwrites any existing blob at the same path (callers enforce naming
    uniqueness via `userOid/conversationId/documentId/...`).
    """
    from azure.storage.blob import ContentSettings

    svc = await get_blob_service_client()
    blob_client = svc.get_blob_client(container=container, blob=name)
    content_settings = (
        ContentSettings(content_type=content_type) if content_type else None
    )
    await blob_client.upload_blob(
        data,
        overwrite=True,
        content_settings=content_settings,
    )
    return blob_client.url


async def download_blob(container: str, name: str) -> bytes:
    """Download a blob's full content as bytes. Caller is responsible for size limits."""
    svc = await get_blob_service_client()
    blob_client = svc.get_blob_client(container=container, blob=name)
    stream = await blob_client.download_blob()
    return await stream.readall()


# ---------------------------------------------------------------------------
# User Delegation SAS (MI-issued, no account key)
# ---------------------------------------------------------------------------


async def generate_user_delegation_sas_for_download(
    blob_name: str,
    *,
    container: str | None = None,
    ttl_minutes: int = 15,
) -> str:
    """Mint a short-lived read-only User Delegation SAS for `container/blob_name`.

    Uses the MI's user delegation key — never the account key (which is
    disabled by `allowSharedKeyAccess: false`). Default TTL is 15 minutes.
    """
    if ttl_minutes <= 0 or ttl_minutes > 60:
        raise ValueError("ttl_minutes must be in (0, 60]")

    settings = get_settings()
    svc = await get_blob_service_client()

    now = datetime.now(UTC)
    key_start = now - timedelta(minutes=2)  # tolerate clock skew
    expiry = now + timedelta(minutes=ttl_minutes)

    user_delegation_key = await svc.get_user_delegation_key(
        key_start_time=key_start,
        key_expiry_time=expiry,
    )

    container_name = container or get_user_uploads_container()
    sas = generate_blob_sas(
        account_name=settings.STORAGE_ACCOUNT_NAME,
        container_name=container_name,
        blob_name=blob_name,
        user_delegation_key=user_delegation_key,
        permission=BlobSasPermissions(read=True),
        expiry=expiry,
        start=key_start,
    )

    return (
        f"https://{settings.STORAGE_ACCOUNT_NAME}{_BLOB_HOST_SUFFIX}"
        f"/{container_name}/{blob_name}?{sas}"
    )


__all__ = [
    "InvariantViolationError",
    "assert_blob_in_owned_account",
    "close_blob_clients",
    "download_blob",
    "generate_user_delegation_sas_for_download",
    "get_blob_service_client",
    "get_container_client",
    "get_corpus_container",
    "get_user_uploads_container",
    "upload_blob",
]
