"""Cosmos DB client + repository layer (T037).

Single source of truth for all `apps/api` writes/reads to the three Cosmos SQL
containers declared in `infra/modules/cosmos/main.bicep` and specified in
`specs/001-private-rag-accelerator/data-model.md` §1:

| Container         | Partition key | Default TTL | Purpose                                  |
|-------------------|---------------|-------------|------------------------------------------|
| `conversations`   | `/userId`     | 30 d        | Chat history (FR-030 sliding retention)  |
| `documents`       | `/scope`      | none*       | Document metadata (per-doc `ttl` field)  |
| `ingestion-runs`  | `/scope`      | 90 d        | Operational telemetry                    |

\\* `documents` has container-level TTL **enabled with no default** (`-1`); the
ingest worker writes a per-document `ttl` for `user:*` scope, never for
`shared`.

Every operation pins `partition_key=` explicitly. The `ConversationsRepo`
methods additionally enforce that the caller's `user_oid` matches the
partition value before returning the document — this is defense in depth on
top of Cosmos data-plane RBAC and is exercised by the SC-011 isolation tests.

Authentication is via `azure.identity.aio.DefaultAzureCredential` only —
account keys are disabled at the resource level (see `disableLocalAuthentication`
in the bicep).
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Final, Literal, cast

from azure.cosmos import exceptions as cosmos_exc
from azure.cosmos.aio import ContainerProxy, CosmosClient, DatabaseProxy
from azure.identity.aio import DefaultAzureCredential
from pydantic import BaseModel, ConfigDict, Field

from ..config import Settings, get_settings
from ..middleware.error_handler import (
    AppError,
    ConflictError,
    NotFoundError,
    PermissionDenied,
)
from ..middleware.logging import get_logger
from ..models.turn import Turn

_log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Storage record models
# ---------------------------------------------------------------------------
# These are the on-disk shapes that get serialized to Cosmos JSON. They are
# intentionally distinct from the API DTOs in `apps/api/src/models/` because:
#   * Storage records carry full scope strings ("user:<oid>", "shared") while
#     API DTOs use the abstracted enum ("user" / "shared").
#   * Storage records include partition-key fields (`userId`, `scope`) that
#     are not part of the public API surface.
# Field names use the camelCase from data-model.md verbatim — Cosmos is
# untyped JSON, so we match the spec rather than translating to snake_case.


class ConversationRecord(BaseModel):
    """`conversations` container document (data-model.md §2)."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str = Field(..., min_length=1)
    userId: str = Field(..., min_length=1)
    title: str
    createdAt: datetime
    updatedAt: datetime
    turns: list[Turn] = Field(default_factory=list)
    uploadedDocumentIds: list[str] = Field(default_factory=list)
    status: Literal["active", "deletePending"] = "active"


class DocumentIngestionStatus(BaseModel):
    """Embedded ingestion sub-document for `DocumentRecord`."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    status: Literal[
        "queued", "cracking", "indexing", "indexed", "failed", "skipped"
    ]
    runId: str | None = None
    startedAt: datetime | None = None
    completedAt: datetime | None = None
    passageCount: int | None = Field(default=None, ge=0)
    errorReason: str | None = None
    errorCode: str | None = None


class DocumentRecord(BaseModel):
    """`documents` container document (data-model.md §3)."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str = Field(..., min_length=1)
    scope: str = Field(..., min_length=1)  # "shared" | "user:<oid>"
    parentConversationId: str | None = None
    uploadedByUserId: str | None = None
    fileName: str
    mimeType: str
    sizeBytes: int = Field(..., ge=0)
    sha256: str | None = None
    blobUri: str
    ingestion: DocumentIngestionStatus
    language: str | None = None
    checksum: str | None = None
    ttl: int | None = None


class IngestionRunRecord(BaseModel):
    """`ingestion-runs` container document (data-model.md §4)."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str = Field(..., min_length=1)
    scope: str = Field(..., min_length=1)
    trigger: Literal["eventgrid", "manual", "user-upload"]
    startedAt: datetime
    completedAt: datetime | None = None
    status: Literal["running", "completed", "failed", "partial"]
    perDocument: list[dict[str, Any]] = Field(default_factory=list)
    totals: dict[str, int] = Field(default_factory=dict)
    ttl: int | None = None


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------


def _map_cosmos_error(exc: cosmos_exc.CosmosHttpResponseError) -> AppError:
    status = getattr(exc, "status_code", None)
    if isinstance(exc, cosmos_exc.CosmosResourceNotFoundError) or status == 404:
        return NotFoundError("Resource not found")
    if isinstance(exc, cosmos_exc.CosmosResourceExistsError) or status == 409:
        return ConflictError("Resource already exists")
    if status == 403:
        return PermissionDenied("Cosmos data-plane denied access")
    return AppError(f"Cosmos error: {exc.message or exc!s}")


# ---------------------------------------------------------------------------
# Singleton client lifecycle
# ---------------------------------------------------------------------------
# `azure.cosmos.aio.CosmosClient` holds a connection pool and an HTTP session.
# Keep one instance per process; close on shutdown.

_client_lock = asyncio.Lock()
_client_holder: dict[str, CosmosClient | DefaultAzureCredential] = {}

_KEY_CLIENT: Final = "client"
_KEY_CRED: Final = "credential"


async def get_cosmos_client(settings: Settings | None = None) -> CosmosClient:
    """Return the process-wide async `CosmosClient` (lazy-init, AAD-only).

    Uses `DefaultAzureCredential` so the API container's user-assigned managed
    identity is picked up automatically in Azure (and `az login` works locally).
    """
    if _KEY_CLIENT in _client_holder:
        return cast(CosmosClient, _client_holder[_KEY_CLIENT])

    async with _client_lock:
        if _KEY_CLIENT in _client_holder:
            return cast(CosmosClient, _client_holder[_KEY_CLIENT])

        s = settings or get_settings()
        cred = DefaultAzureCredential()
        client = CosmosClient(s.COSMOS_ACCOUNT_ENDPOINT, credential=cred)
        _client_holder[_KEY_CRED] = cred
        _client_holder[_KEY_CLIENT] = client
        _log.info("cosmos_client_initialized", endpoint=s.COSMOS_ACCOUNT_ENDPOINT)
        return client


async def close_cosmos_client() -> None:
    """Close the singleton client and credential. Idempotent."""
    client = _client_holder.pop(_KEY_CLIENT, None)
    cred = _client_holder.pop(_KEY_CRED, None)
    if isinstance(client, CosmosClient):
        await client.close()
    if isinstance(cred, DefaultAzureCredential):
        await cred.close()


async def get_database(settings: Settings | None = None) -> DatabaseProxy:
    """Return the configured SQL database proxy (does not perform I/O)."""
    s = settings or get_settings()
    client = await get_cosmos_client(s)
    return client.get_database_client(s.COSMOS_DATABASE)


# ---------------------------------------------------------------------------
# Repositories
# ---------------------------------------------------------------------------


class _BaseRepo:
    """Shared plumbing — every repo binds to one container."""

    def __init__(self, container: ContainerProxy) -> None:
        self._container = container


class ConversationsRepo(_BaseRepo):
    """`conversations` container — PK `/userId` (data-model.md §2).

    Every method requires the caller's `user_oid` and uses it as the partition
    key. A user **cannot** read or mutate another user's conversation through
    this repo even if they guess an `id` (SC-011).
    """

    async def get(self, conversation_id: str, user_oid: str) -> ConversationRecord:
        try:
            item = await self._container.read_item(
                item=conversation_id,
                partition_key=user_oid,
            )
        except cosmos_exc.CosmosHttpResponseError as exc:
            raise _map_cosmos_error(exc) from exc

        if item.get("userId") != user_oid:
            # Defense in depth — should be impossible given the partition-key
            # read above, but we never want to leak another user's record.
            raise NotFoundError("Conversation not found")
        return ConversationRecord.model_validate(item)

    async def list_for_user(
        self,
        user_oid: str,
        limit: int = 50,
        continuation: str | None = None,
    ) -> tuple[list[ConversationRecord], str | None]:
        """List a user's conversations newest-first, single-partition query."""
        query = (
            "SELECT c.id, c.userId, c.title, c.createdAt, c.updatedAt, "
            "c.turns, c.uploadedDocumentIds, c.status "
            "FROM c WHERE c.status != 'deletePending' "
            "ORDER BY c.updatedAt DESC"
        )
        try:
            iterator = self._container.query_items(
                query=query,
                partition_key=user_oid,
                max_item_count=limit,
            )
            pager = iterator.by_page(continuation_token=continuation)
            try:
                page = await pager.__anext__()
            except StopAsyncIteration:
                return [], None
            items: list[ConversationRecord] = []
            async for raw in page:
                items.append(ConversationRecord.model_validate(raw))
            next_token = getattr(pager, "continuation_token", None)
        except cosmos_exc.CosmosHttpResponseError as exc:
            raise _map_cosmos_error(exc) from exc
        return items, next_token

    async def upsert(self, conversation: ConversationRecord) -> ConversationRecord:
        if not conversation.userId:
            raise AppError("Conversation.userId is required (partition key)")
        body = conversation.model_dump(mode="json", exclude_none=True)
        try:
            saved = await self._container.upsert_item(body=body)
        except cosmos_exc.CosmosHttpResponseError as exc:
            raise _map_cosmos_error(exc) from exc
        return ConversationRecord.model_validate(saved)

    async def delete(self, conversation_id: str, user_oid: str) -> None:
        try:
            await self._container.delete_item(
                item=conversation_id,
                partition_key=user_oid,
            )
        except cosmos_exc.CosmosHttpResponseError as exc:
            raise _map_cosmos_error(exc) from exc

    async def add_turn(
        self,
        conversation_id: str,
        user_oid: str,
        turn: Turn,
    ) -> ConversationRecord:
        """Append a `Turn`. Re-reads, mutates, upserts (no patch API used).

        Touches `updatedAt` so Cosmos `_ts` resets — this is what makes the
        30-day retention *sliding* (FR-030).
        """
        record = await self.get(conversation_id, user_oid)
        record.turns.append(turn)
        record.updatedAt = turn.createdAt
        return await self.upsert(record)


class DocumentsRepo(_BaseRepo):
    """`documents` container — PK `/scope` (data-model.md §3).

    `scope` is `"shared"` for admin-curated corpus or `"user:<oid>"` for
    per-user uploads. Callers must pass the full scope string; this repo does
    not synthesize it.
    """

    async def get(self, document_id: str, scope: str) -> DocumentRecord:
        try:
            item = await self._container.read_item(
                item=document_id,
                partition_key=scope,
            )
        except cosmos_exc.CosmosHttpResponseError as exc:
            raise _map_cosmos_error(exc) from exc
        return DocumentRecord.model_validate(item)

    async def list_by_scope(
        self,
        scope: str,
        owner_oid: str | None = None,
        limit: int = 100,
    ) -> list[DocumentRecord]:
        """List all documents in a scope partition.

        `owner_oid` is an additional defense-in-depth filter applied for
        `user:*` scopes — even if a caller crafts a `user:<other>` scope, we
        verify `uploadedByUserId == owner_oid` before yielding the record.
        """
        if scope.startswith("user:") and owner_oid is not None:
            expected = f"user:{owner_oid}"
            if scope != expected:
                raise PermissionDenied("scope does not match caller user oid")

        query = "SELECT * FROM c"
        try:
            results: list[DocumentRecord] = []
            async for raw in self._container.query_items(
                query=query,
                partition_key=scope,
                max_item_count=limit,
            ):
                if (
                    owner_oid is not None
                    and scope.startswith("user:")
                    and raw.get("uploadedByUserId") != owner_oid
                ):
                    continue
                results.append(DocumentRecord.model_validate(raw))
                if len(results) >= limit:
                    break
        except cosmos_exc.CosmosHttpResponseError as exc:
            raise _map_cosmos_error(exc) from exc
        return results

    async def upsert(self, document: DocumentRecord) -> DocumentRecord:
        body = document.model_dump(mode="json", exclude_none=True)
        try:
            saved = await self._container.upsert_item(body=body)
        except cosmos_exc.CosmosHttpResponseError as exc:
            raise _map_cosmos_error(exc) from exc
        return DocumentRecord.model_validate(saved)

    async def update_status(
        self,
        document_id: str,
        scope: str,
        status: str,
        error: tuple[str, str] | None = None,
    ) -> DocumentRecord:
        """Set `ingestion.status` and optional `(errorCode, errorReason)`."""
        record = await self.get(document_id, scope)
        record.ingestion.status = cast(Any, status)
        if error is not None:
            record.ingestion.errorCode = error[0]
            record.ingestion.errorReason = error[1]
        elif status == "indexed":
            record.ingestion.errorCode = None
            record.ingestion.errorReason = None
        return await self.upsert(record)


class IngestionRunsRepo(_BaseRepo):
    """`ingestion-runs` container — PK `/scope` (data-model.md §4)."""

    async def get(self, run_id: str, scope: str) -> IngestionRunRecord:
        try:
            item = await self._container.read_item(
                item=run_id,
                partition_key=scope,
            )
        except cosmos_exc.CosmosHttpResponseError as exc:
            raise _map_cosmos_error(exc) from exc
        return IngestionRunRecord.model_validate(item)

    async def list_recent(
        self,
        scope: str = "shared",
        limit: int = 20,
    ) -> list[IngestionRunRecord]:
        """List recent runs newest-first within a scope partition."""
        query = "SELECT * FROM c ORDER BY c.startedAt DESC"
        try:
            results: list[IngestionRunRecord] = []
            async for raw in self._container.query_items(
                query=query,
                partition_key=scope,
                max_item_count=limit,
            ):
                results.append(IngestionRunRecord.model_validate(raw))
                if len(results) >= limit:
                    break
        except cosmos_exc.CosmosHttpResponseError as exc:
            raise _map_cosmos_error(exc) from exc
        return results

    async def create(self, run: IngestionRunRecord) -> IngestionRunRecord:
        body = run.model_dump(mode="json", exclude_none=True)
        try:
            saved = await self._container.create_item(body=body)
        except cosmos_exc.CosmosHttpResponseError as exc:
            raise _map_cosmos_error(exc) from exc
        return IngestionRunRecord.model_validate(saved)

    async def update_status(
        self,
        run_id: str,
        scope: str,
        status: str,
        stats: dict[str, int] | None = None,
    ) -> IngestionRunRecord:
        record = await self.get(run_id, scope)
        record.status = cast(Any, status)
        if stats is not None:
            record.totals = dict(stats)
        if status in {"completed", "failed", "partial"} and record.completedAt is None:
            record.completedAt = datetime.utcnow()
        body = record.model_dump(mode="json", exclude_none=True)
        try:
            saved = await self._container.upsert_item(body=body)
        except cosmos_exc.CosmosHttpResponseError as exc:
            raise _map_cosmos_error(exc) from exc
        return IngestionRunRecord.model_validate(saved)


# ---------------------------------------------------------------------------
# Repo factories — used by FastAPI dependencies (T038+)
# ---------------------------------------------------------------------------


async def get_conversations_repo(settings: Settings | None = None) -> ConversationsRepo:
    s = settings or get_settings()
    db = await get_database(s)
    return ConversationsRepo(db.get_container_client(s.COSMOS_CONTAINER_CONVERSATIONS))


async def get_documents_repo(settings: Settings | None = None) -> DocumentsRepo:
    s = settings or get_settings()
    db = await get_database(s)
    return DocumentsRepo(db.get_container_client(s.COSMOS_CONTAINER_DOCUMENTS))


async def get_ingestion_runs_repo(settings: Settings | None = None) -> IngestionRunsRepo:
    s = settings or get_settings()
    db = await get_database(s)
    return IngestionRunsRepo(db.get_container_client(s.COSMOS_CONTAINER_INGESTION_RUNS))


__all__ = [
    "ConversationRecord",
    "ConversationsRepo",
    "DocumentIngestionStatus",
    "DocumentRecord",
    "DocumentsRepo",
    "IngestionRunRecord",
    "IngestionRunsRepo",
    "close_cosmos_client",
    "get_conversations_repo",
    "get_cosmos_client",
    "get_database",
    "get_documents_repo",
    "get_ingestion_runs_repo",
]
