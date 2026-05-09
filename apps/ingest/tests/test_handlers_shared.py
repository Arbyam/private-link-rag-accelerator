"""Tests for the shared-corpus event handler (T068)."""

from __future__ import annotations

import hashlib
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.handlers.shared import (
    EVENT_BLOB_CHANGED,
    EVENT_BLOB_CREATED,
    EVENT_BLOB_DELETED,
    Repos,
    UnsupportedContainerError,
    derive_document_id,
    handle_blob_event,
)
from src.pipeline import RunOutcome

SHARED_BLOB_URL = "https://stexample.blob.core.windows.net/shared-corpus/folder/doc.pdf"


def _event(event_type: str, url: str = SHARED_BLOB_URL) -> dict[str, Any]:
    return {
        "specversion": "1.0",
        "type": event_type,
        "source": (
            "/subscriptions/x/resourceGroups/y/providers/"
            "Microsoft.Storage/storageAccounts/stexample"
        ),
        "id": "evt-1",
        "time": "2026-05-09T00:00:00Z",
        "subject": "/blobServices/default/containers/shared-corpus/blobs/folder/doc.pdf",
        "data": {
            "api": "PutBlob",
            "url": url,
            "contentType": "application/pdf",
        },
    }


def _make_repos() -> tuple[Repos, AsyncMock]:
    docs = AsyncMock()
    docs.delete = AsyncMock(return_value=None)
    runs = AsyncMock()
    return Repos(docs_repo=docs, runs_repo=runs), docs.delete


def _make_pipeline(
    *,
    created: RunOutcome | Exception | None = None,
    changed: RunOutcome | Exception | None = None,
    deleted: RunOutcome | Exception | None = None,
) -> AsyncMock:
    pipeline = AsyncMock()
    pipeline.process_blob_created = AsyncMock(
        side_effect=created if isinstance(created, Exception) else None,
        return_value=created if isinstance(created, RunOutcome) else None,
    )
    pipeline.process_blob_changed = AsyncMock(
        side_effect=changed if isinstance(changed, Exception) else None,
        return_value=changed if isinstance(changed, RunOutcome) else None,
    )
    pipeline.process_blob_deleted = AsyncMock(
        side_effect=deleted if isinstance(deleted, Exception) else None,
        return_value=deleted if isinstance(deleted, RunOutcome) else None,
    )
    return pipeline


# ---------------------------------------------------------------------------
# Document id derivation
# ---------------------------------------------------------------------------


def test_derive_document_id_is_deterministic_and_16_hex_chars() -> None:
    a = derive_document_id(SHARED_BLOB_URL)
    b = derive_document_id(SHARED_BLOB_URL)
    assert a == b
    assert len(a) == 16
    assert all(c in "0123456789abcdef" for c in a)


def test_derive_document_id_strips_query_string() -> None:
    with_q = derive_document_id(SHARED_BLOB_URL + "?sas=token")
    without_q = derive_document_id(SHARED_BLOB_URL)
    assert with_q == without_q


def test_derive_document_id_matches_sha256_prefix_of_canonical_url() -> None:
    expected = hashlib.sha256(SHARED_BLOB_URL.encode("utf-8")).hexdigest()[:16]
    assert derive_document_id(SHARED_BLOB_URL) == expected


def test_derive_document_id_differs_for_different_paths() -> None:
    other = "https://stexample.blob.core.windows.net/shared-corpus/other.pdf"
    assert derive_document_id(SHARED_BLOB_URL) != derive_document_id(other)


# ---------------------------------------------------------------------------
# Container routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unsupported_container_raises() -> None:
    pipeline = _make_pipeline()
    repos, _ = _make_repos()
    bad = _event(
        EVENT_BLOB_CREATED,
        url="https://stexample.blob.core.windows.net/user-uploads/u/doc.pdf",
    )
    with pytest.raises(UnsupportedContainerError):
        await handle_blob_event(bad, pipeline, repos)
    pipeline.process_blob_created.assert_not_awaited()


# ---------------------------------------------------------------------------
# Dispatch matrix — happy paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blob_created_invokes_pipeline_process_blob_created() -> None:
    document_id = derive_document_id(SHARED_BLOB_URL)
    expected = RunOutcome(
        status="succeeded", document_id=document_id, event_type=EVENT_BLOB_CREATED
    )
    pipeline = _make_pipeline(created=expected)
    repos, delete_mock = _make_repos()

    outcome = await handle_blob_event(_event(EVENT_BLOB_CREATED), pipeline, repos)

    assert outcome is expected
    pipeline.process_blob_created.assert_awaited_once_with(SHARED_BLOB_URL, document_id)
    pipeline.process_blob_changed.assert_not_awaited()
    pipeline.process_blob_deleted.assert_not_awaited()
    delete_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_blob_changed_invokes_pipeline_process_blob_changed() -> None:
    document_id = derive_document_id(SHARED_BLOB_URL)
    expected = RunOutcome(
        status="succeeded", document_id=document_id, event_type=EVENT_BLOB_CHANGED
    )
    pipeline = _make_pipeline(changed=expected)
    repos, delete_mock = _make_repos()

    outcome = await handle_blob_event(_event(EVENT_BLOB_CHANGED), pipeline, repos)

    assert outcome is expected
    pipeline.process_blob_changed.assert_awaited_once_with(SHARED_BLOB_URL, document_id)
    pipeline.process_blob_created.assert_not_awaited()
    delete_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_blob_deleted_invokes_pipeline_then_repo_delete() -> None:
    document_id = derive_document_id(SHARED_BLOB_URL)
    expected = RunOutcome(
        status="succeeded", document_id=document_id, event_type=EVENT_BLOB_DELETED
    )
    pipeline = _make_pipeline(deleted=expected)
    repos, delete_mock = _make_repos()

    outcome = await handle_blob_event(_event(EVENT_BLOB_DELETED), pipeline, repos)

    assert outcome is expected
    pipeline.process_blob_deleted.assert_awaited_once_with(document_id)
    delete_mock.assert_awaited_once_with(document_id)


@pytest.mark.asyncio
async def test_blob_deleted_skips_repo_delete_when_pipeline_fails() -> None:
    pipeline = _make_pipeline(deleted=RuntimeError("search delete-by-filter failed"))
    repos, delete_mock = _make_repos()

    outcome = await handle_blob_event(_event(EVENT_BLOB_DELETED), pipeline, repos)

    assert outcome.status == "failed"
    assert outcome.event_type == EVENT_BLOB_DELETED
    assert outcome.message == "search delete-by-filter failed"
    pipeline.process_blob_deleted.assert_awaited_once()
    delete_mock.assert_not_awaited()


# ---------------------------------------------------------------------------
# Dispatch matrix — failure paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blob_created_failure_returns_failed_outcome() -> None:
    pipeline = _make_pipeline(created=RuntimeError("docintel down"))
    repos, _ = _make_repos()

    outcome = await handle_blob_event(_event(EVENT_BLOB_CREATED), pipeline, repos)

    assert outcome.status == "failed"
    assert outcome.event_type == EVENT_BLOB_CREATED
    assert outcome.document_id == derive_document_id(SHARED_BLOB_URL)
    assert outcome.message == "docintel down"


@pytest.mark.asyncio
async def test_blob_changed_failure_returns_failed_outcome() -> None:
    pipeline = _make_pipeline(changed=RuntimeError("embedding 429"))
    repos, _ = _make_repos()

    outcome = await handle_blob_event(_event(EVENT_BLOB_CHANGED), pipeline, repos)

    assert outcome.status == "failed"
    assert outcome.event_type == EVENT_BLOB_CHANGED
    assert outcome.message == "embedding 429"


@pytest.mark.asyncio
async def test_blob_deleted_failure_when_repo_delete_raises() -> None:
    document_id = derive_document_id(SHARED_BLOB_URL)
    expected = RunOutcome(
        status="succeeded", document_id=document_id, event_type=EVENT_BLOB_DELETED
    )
    pipeline = _make_pipeline(deleted=expected)
    repos, delete_mock = _make_repos()
    delete_mock.side_effect = RuntimeError("cosmos 503")

    outcome = await handle_blob_event(_event(EVENT_BLOB_DELETED), pipeline, repos)

    assert outcome.status == "failed"
    assert outcome.event_type == EVENT_BLOB_DELETED
    assert outcome.message == "cosmos 503"
    delete_mock.assert_awaited_once_with(document_id)


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_event_type_is_skipped() -> None:
    pipeline = _make_pipeline()
    repos, delete_mock = _make_repos()
    evt = _event("Microsoft.Storage.BlobRenamed")

    outcome = await handle_blob_event(evt, pipeline, repos)

    assert outcome.status == "skipped"
    assert outcome.event_type == "Microsoft.Storage.BlobRenamed"
    assert outcome.message is not None and "unhandled event type" in outcome.message
    pipeline.process_blob_created.assert_not_awaited()
    pipeline.process_blob_changed.assert_not_awaited()
    pipeline.process_blob_deleted.assert_not_awaited()
    delete_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_blob_url_raises_value_error() -> None:
    pipeline = _make_pipeline()
    repos, _ = _make_repos()
    evt = _event(EVENT_BLOB_CREATED)
    evt["data"].pop("url")
    with pytest.raises(ValueError, match="url"):
        await handle_blob_event(evt, pipeline, repos)
