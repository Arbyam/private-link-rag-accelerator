"""``ingestion-runs`` Cosmos repository for the ingest worker (T066).

Mirrors the ``IngestionRunsRepo`` pattern from
``apps/api/src/services/cosmos.py`` (PR #30) so the worker can write run
lifecycle records without importing the API package.

Per data-model.md §4 a run document carries:

  * ``id``         — ``r_<26-char ulid-ish>``
  * ``scope``      — partition key, ``"shared"`` for event-driven runs
  * ``trigger``    — ``"eventgrid" | "manual" | "user-upload"``
  * ``startedAt``  — set on dispatch
  * ``status``     — ``"running" | "completed" | "failed" | "partial"``
  * ``completedAt``— set on terminal status

The container has a 90-day TTL configured at the container level, so we do not
write a per-document ``ttl``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from azure.cosmos.aio import CosmosClient
from azure.identity.aio import DefaultAzureCredential

from .config import IngestSettings

Trigger = Literal["eventgrid", "manual", "user-upload"]
RunStatus = Literal["running", "completed", "failed", "partial"]


class IngestionRunsClient:
    """Thin async client over the ``ingestion-runs`` Cosmos container.

    Owns its own Cosmos client + credential when given just settings, or accepts
    an externally-managed credential to share with other workers in the same
    process. Use :meth:`close` to release resources.
    """

    def __init__(
        self,
        settings: IngestSettings,
        *,
        credential: DefaultAzureCredential | None = None,
    ) -> None:
        self._settings = settings
        self._owns_credential = credential is None
        self._credential = credential or DefaultAzureCredential()
        self._client = CosmosClient(
            settings.COSMOS_ACCOUNT_ENDPOINT,
            credential=self._credential,
        )
        db = self._client.get_database_client(settings.COSMOS_DATABASE)
        self._container = db.get_container_client(settings.COSMOS_CONTAINER_INGESTION_RUNS)

    async def start(
        self,
        *,
        run_id: str,
        scope: str,
        trigger: Trigger,
    ) -> dict[str, Any]:
        record: dict[str, Any] = {
            "id": run_id,
            "scope": scope,
            "trigger": trigger,
            "startedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "status": "running",
            "perDocument": [],
            "totals": {},
        }
        return await self._container.create_item(body=record)

    async def complete(
        self,
        run_id: str,
        scope: str,
        *,
        status: RunStatus,
        totals: dict[str, int] | None = None,
        per_document: list[dict[str, Any]] | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        existing = await self._container.read_item(item=run_id, partition_key=scope)
        existing["status"] = status
        existing["completedAt"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        if totals is not None:
            existing["totals"] = dict(totals)
        if per_document is not None:
            existing["perDocument"] = list(per_document)
        if error is not None:
            existing["errorReason"] = error
        return await self._container.upsert_item(body=existing)

    async def close(self) -> None:
        await self._client.close()
        if self._owns_credential:
            await self._credential.close()


class SharedDocumentsClient:
    """Tiny ``documents`` Cosmos repo for the ``shared`` scope partition.

    Mirrors the relevant slice of ``apps/api/src/services/cosmos.py``
    ``DocumentsRepo`` so the ingest worker doesn't fork the API package.
    The shared-corpus handler only needs ``delete`` today.
    """

    def __init__(
        self,
        settings: IngestSettings,
        *,
        credential: DefaultAzureCredential | None = None,
    ) -> None:
        self._owns_credential = credential is None
        self._credential = credential or DefaultAzureCredential()
        self._client = CosmosClient(
            settings.COSMOS_ACCOUNT_ENDPOINT,
            credential=self._credential,
        )
        db = self._client.get_database_client(settings.COSMOS_DATABASE)
        self._container = db.get_container_client(settings.COSMOS_CONTAINER_DOCUMENTS)

    async def delete(self, document_id: str) -> None:
        await self._container.delete_item(item=document_id, partition_key="shared")

    async def close(self) -> None:
        await self._client.close()
        if self._owns_credential:
            await self._credential.close()


__all__ = [
    "IngestionRunsClient",
    "RunStatus",
    "SharedDocumentsClient",
    "Trigger",
]
