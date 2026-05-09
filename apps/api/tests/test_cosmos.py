"""Smoke tests for `services.cosmos` (T037).

No real Cosmos calls — every container method is mocked. Asserts:
 * Each repo invokes the right container with the right `partition_key`.
 * `ConversationsRepo` enforces `user_oid` partition isolation (SC-011).
 * `azure.cosmos` errors are mapped to `AppError` subclasses.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from azure.cosmos import exceptions as cosmos_exc

from src.middleware.error_handler import (
    ConflictError,
    NotFoundError,
    PermissionDenied,
)
from src.models.turn import Turn, TurnRole
from src.services import cosmos as cosmos_module
from src.services.cosmos import (
    ConversationRecord,
    ConversationsRepo,
    DocumentsRepo,
    IngestionRunRecord,
    IngestionRunsRepo,
    _map_cosmos_error,
)

USER_A = "oid:11111111-1111-1111-1111-111111111111"
USER_B = "oid:22222222-2222-2222-2222-222222222222"


def _async_iter(items: list[dict[str, Any]]) -> Any:
    """Build an object that supports `async for` over `items`."""

    class _It:
        def __init__(self) -> None:
            self._i = iter(items)

        def __aiter__(self) -> _It:
            return self

        async def __anext__(self) -> dict[str, Any]:
            try:
                return next(self._i)
            except StopIteration as exc:
                raise StopAsyncIteration from exc

    return _It()


def _make_container() -> MagicMock:
    c = MagicMock()
    c.read_item = AsyncMock()
    c.upsert_item = AsyncMock()
    c.create_item = AsyncMock()
    c.delete_item = AsyncMock()
    # query_items is a sync method that returns an async iterable.
    c.query_items = MagicMock()
    return c


def _convo_doc(user_oid: str = USER_A) -> dict[str, Any]:
    return {
        "id": "c_01J9X8YZABCDEFGHJKMNPQRSTV",
        "userId": user_oid,
        "title": "Hello",
        "createdAt": "2026-05-08T14:22:00Z",
        "updatedAt": "2026-05-08T14:35:11Z",
        "turns": [],
        "uploadedDocumentIds": [],
        "status": "active",
    }


def _doc_doc(scope: str = "shared", uploader: str | None = None) -> dict[str, Any]:
    return {
        "id": "d_01J9X8YZABCDEFGHJKMNPQRSTV",
        "scope": scope,
        "parentConversationId": None,
        "uploadedByUserId": uploader,
        "fileName": "x.pdf",
        "mimeType": "application/pdf",
        "sizeBytes": 100,
        "blobUri": "https://stx.blob.core.windows.net/shared-corpus/x.pdf",
        "ingestion": {"status": "indexed", "passageCount": 4},
    }


def _run_doc() -> dict[str, Any]:
    return {
        "id": "r_01J9X8YZABCDEFGHJKMNPQRSTV",
        "scope": "shared",
        "trigger": "eventgrid",
        "startedAt": "2026-05-08T14:21:55Z",
        "completedAt": None,
        "status": "running",
        "perDocument": [],
        "totals": {},
    }


# ---------------------------------------------------------------------------
# ConversationsRepo
# ---------------------------------------------------------------------------


async def test_conversations_get_uses_user_oid_as_partition_key() -> None:
    c = _make_container()
    c.read_item.return_value = _convo_doc(USER_A)
    repo = ConversationsRepo(c)

    record = await repo.get("c_01J9X8YZABCDEFGHJKMNPQRSTV", USER_A)

    c.read_item.assert_awaited_once_with(
        item="c_01J9X8YZABCDEFGHJKMNPQRSTV",
        partition_key=USER_A,
    )
    assert record.userId == USER_A


async def test_conversations_get_rejects_cross_user_record() -> None:
    """SC-011: even if a foreign doc somehow comes back, never return it."""
    c = _make_container()
    c.read_item.return_value = _convo_doc(USER_B)  # Cosmos returned other user's doc
    repo = ConversationsRepo(c)

    with pytest.raises(NotFoundError):
        await repo.get("c_01J9X8YZABCDEFGHJKMNPQRSTV", USER_A)


async def test_conversations_get_maps_404() -> None:
    c = _make_container()
    c.read_item.side_effect = cosmos_exc.CosmosResourceNotFoundError(
        message="not found", response=None
    )
    repo = ConversationsRepo(c)

    with pytest.raises(NotFoundError):
        await repo.get("c_missing", USER_A)


async def test_conversations_upsert_serializes_record() -> None:
    c = _make_container()
    c.upsert_item.side_effect = lambda body: body  # echo
    repo = ConversationsRepo(c)
    rec = ConversationRecord(
        id="c_01J9X8YZABCDEFGHJKMNPQRSTV",
        userId=USER_A,
        title="t",
        createdAt=datetime(2026, 5, 8, tzinfo=UTC),
        updatedAt=datetime(2026, 5, 8, tzinfo=UTC),
    )

    saved = await repo.upsert(rec)

    c.upsert_item.assert_awaited_once()
    body = c.upsert_item.call_args.kwargs["body"]
    assert body["userId"] == USER_A
    assert saved.id == rec.id


async def test_conversations_delete_uses_partition_key() -> None:
    c = _make_container()
    repo = ConversationsRepo(c)

    await repo.delete("c_01J9X8YZABCDEFGHJKMNPQRSTV", USER_A)

    c.delete_item.assert_awaited_once_with(
        item="c_01J9X8YZABCDEFGHJKMNPQRSTV",
        partition_key=USER_A,
    )


async def test_conversations_add_turn_appends_and_upserts() -> None:
    c = _make_container()
    c.read_item.return_value = _convo_doc(USER_A)
    c.upsert_item.side_effect = lambda body: body
    repo = ConversationsRepo(c)

    turn = Turn(
        turnId="t_01J9X8YZABCDEFGHJKMNPQRSTV",
        role=TurnRole.USER,
        content="hi",
        createdAt=datetime(2026, 5, 8, 15, 0, tzinfo=UTC),
    )

    updated = await repo.add_turn("c_01J9X8YZABCDEFGHJKMNPQRSTV", USER_A, turn)

    assert len(updated.turns) == 1
    assert updated.turns[0].turnId == turn.turnId
    # The read used the user_oid PK, and the upsert went to the same partition.
    c.read_item.assert_awaited_with(
        item="c_01J9X8YZABCDEFGHJKMNPQRSTV", partition_key=USER_A
    )
    c.upsert_item.assert_awaited_once()


# ---------------------------------------------------------------------------
# DocumentsRepo
# ---------------------------------------------------------------------------


async def test_documents_get_uses_scope_partition() -> None:
    c = _make_container()
    c.read_item.return_value = _doc_doc("shared")
    repo = DocumentsRepo(c)

    record = await repo.get("d_01J9X8YZABCDEFGHJKMNPQRSTV", "shared")

    c.read_item.assert_awaited_once_with(
        item="d_01J9X8YZABCDEFGHJKMNPQRSTV",
        partition_key="shared",
    )
    assert record.scope == "shared"


async def test_documents_list_by_scope_filters_owner_oid() -> None:
    c = _make_container()
    scope = f"user:{USER_A}"
    c.query_items.return_value = _async_iter(
        [
            _doc_doc(scope, uploader=USER_A),
            _doc_doc(scope, uploader=USER_B),  # must be filtered out
        ]
    )
    repo = DocumentsRepo(c)

    results = await repo.list_by_scope(scope, owner_oid=USER_A)

    c.query_items.assert_called_once()
    assert c.query_items.call_args.kwargs["partition_key"] == scope
    assert len(results) == 1
    assert results[0].uploadedByUserId == USER_A


async def test_documents_list_rejects_mismatched_user_scope() -> None:
    c = _make_container()
    repo = DocumentsRepo(c)

    with pytest.raises(PermissionDenied):
        await repo.list_by_scope(f"user:{USER_B}", owner_oid=USER_A)


async def test_documents_update_status_transitions_to_indexed() -> None:
    c = _make_container()
    doc = _doc_doc("shared")
    doc["ingestion"] = {
        "status": "indexing",
        "errorCode": "old",
        "errorReason": "old",
    }
    c.read_item.return_value = doc
    c.upsert_item.side_effect = lambda body: body
    repo = DocumentsRepo(c)

    saved = await repo.update_status(doc["id"], "shared", "indexed")

    assert saved.ingestion.status == "indexed"
    assert saved.ingestion.errorCode is None
    assert saved.ingestion.errorReason is None


# ---------------------------------------------------------------------------
# IngestionRunsRepo
# ---------------------------------------------------------------------------


async def test_ingestion_runs_create_calls_create_item() -> None:
    c = _make_container()
    raw = _run_doc()
    c.create_item.side_effect = lambda body: body
    repo = IngestionRunsRepo(c)
    rec = IngestionRunRecord.model_validate(raw)

    saved = await repo.create(rec)

    c.create_item.assert_awaited_once()
    assert saved.id == rec.id
    assert saved.scope == "shared"


async def test_ingestion_runs_list_recent_uses_scope_partition() -> None:
    c = _make_container()
    c.query_items.return_value = _async_iter([_run_doc(), _run_doc()])
    repo = IngestionRunsRepo(c)

    results = await repo.list_recent("shared", limit=10)

    c.query_items.assert_called_once()
    assert c.query_items.call_args.kwargs["partition_key"] == "shared"
    assert len(results) == 2


async def test_ingestion_runs_get_maps_404() -> None:
    c = _make_container()
    c.read_item.side_effect = cosmos_exc.CosmosResourceNotFoundError(
        message="not found", response=None
    )
    repo = IngestionRunsRepo(c)

    with pytest.raises(NotFoundError):
        await repo.get("r_missing", "shared")


# ---------------------------------------------------------------------------
# Error mapping & client lifecycle
# ---------------------------------------------------------------------------


def test_map_cosmos_error_403() -> None:
    err = cosmos_exc.CosmosHttpResponseError(message="forbidden", response=None)
    err.status_code = 403
    mapped = _map_cosmos_error(err)
    assert isinstance(mapped, PermissionDenied)


def test_map_cosmos_error_409() -> None:
    err = cosmos_exc.CosmosResourceExistsError(message="dup", response=None)
    mapped = _map_cosmos_error(err)
    assert isinstance(mapped, ConflictError)


async def test_close_cosmos_client_is_idempotent() -> None:
    # Reset module state so the test is hermetic.
    cosmos_module._client_holder.clear()
    await cosmos_module.close_cosmos_client()
    await cosmos_module.close_cosmos_client()
