"""Storage Queue client for the API tier (T070).

The API only enqueues to the ``ingestion-events`` Storage Queue (the target of
the Event Grid → Storage subscription wired in
``infra/modules/storage/main.bicep``). The ingest worker is the sole reader.

Auth: ``DefaultAzureCredential`` only — the account has shared-key auth
disabled. The API's user-assigned managed identity is granted
``Storage Queue Data Message Sender`` at the storage-account scope by the
infra module.

Single-process singleton lifecycle mirrors :mod:`apps.api.src.services.cosmos`.
"""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Any, Final, cast

from azure.identity.aio import DefaultAzureCredential
from azure.storage.queue.aio import QueueClient

from ..config import Settings, get_settings
from ..middleware.logging import get_logger

_log = get_logger(__name__)

_lock = asyncio.Lock()
_holder: dict[str, QueueClient | DefaultAzureCredential] = {}

_KEY_CLIENT: Final = "client"
_KEY_CRED: Final = "credential"


def _queue_endpoint(account_name: str) -> str:
    return f"https://{account_name}.queue.core.windows.net"


async def get_ingestion_queue_client(settings: Settings | None = None) -> QueueClient:
    """Return the process-wide async ``QueueClient`` for the ingestion queue."""
    if _KEY_CLIENT in _holder:
        return cast(QueueClient, _holder[_KEY_CLIENT])

    async with _lock:
        if _KEY_CLIENT in _holder:
            return cast(QueueClient, _holder[_KEY_CLIENT])

        s = settings or get_settings()
        cred = DefaultAzureCredential()
        client = QueueClient(
            account_url=_queue_endpoint(s.STORAGE_ACCOUNT_NAME),
            queue_name=s.INGESTION_QUEUE_NAME,
            credential=cred,
        )
        _holder[_KEY_CRED] = cred
        _holder[_KEY_CLIENT] = client
        _log.info(
            "ingestion_queue_client_initialized",
            account=s.STORAGE_ACCOUNT_NAME,
            queue=s.INGESTION_QUEUE_NAME,
        )
        return client


async def close_ingestion_queue_client() -> None:
    """Close the singleton client + credential. Idempotent."""
    client = _holder.pop(_KEY_CLIENT, None)
    cred = _holder.pop(_KEY_CRED, None)
    if isinstance(client, QueueClient):
        await client.close()
    if isinstance(cred, DefaultAzureCredential):
        await cred.close()


async def enqueue_cloud_event(
    event: dict[str, Any],
    *,
    settings: Settings | None = None,
) -> None:
    """Enqueue a CloudEvents 1.0 envelope as a base64-encoded JSON message.

    Event Grid's StorageQueue handler base64-encodes payloads by default; we
    mirror that encoding so the ingest consumer can use a single decode path
    regardless of producer (Event Grid or admin-reindex).
    """
    client = await get_ingestion_queue_client(settings)
    body = json.dumps(event, separators=(",", ":")).encode("utf-8")
    encoded = base64.b64encode(body).decode("ascii")
    await client.send_message(encoded)


__all__ = [
    "close_ingestion_queue_client",
    "enqueue_cloud_event",
    "get_ingestion_queue_client",
]
