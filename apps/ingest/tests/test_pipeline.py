"""Tests for ``apps.ingest.src.pipeline`` (T067, T069).

Covers:

* T069 MIME allowlist + size cap → ``skipped`` with controlled
  ``errorReason`` vocabulary.
* T067 happy path: pre-flight passes → indexer triggered → polled to
  success → Document.ingestion.status = ``indexed``.
* All five ``errorReason`` values from the controlled vocabulary:
  ``unsupported-mime``, ``oversize``, ``crack-failed``, ``embed-failed``,
  ``upsert-failed``.
* BlobDeleted: search-then-delete and tombstone status.
* Defensive blob-URL validation.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config import IngestSettings
from src.pipeline import (
    ALLOWED_MIME_TYPES,
    IngestionPipeline,
    PipelineDeps,
    RunOutcome,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@dataclass
class _FakeContentSettings:
    content_type: str | None


@dataclass
class _FakeBlobProps:
    size: int
    content_settings: _FakeContentSettings


def _props(*, size: int = 1024, ct: str | None = "application/pdf") -> _FakeBlobProps:
    return _FakeBlobProps(size=size, content_settings=_FakeContentSettings(content_type=ct))


@dataclass
class _FakeLastResult:
    status: str
    item_count: int = 0
    error_message: str | None = None
    start_time: str | None = "2026-05-09T00:00:00Z"


@dataclass
class _FakeIndexerStatus:
    last_result: _FakeLastResult | None


def _make_settings() -> IngestSettings:
    return IngestSettings(  # type: ignore[call-arg]
        AZURE_TENANT_ID="00000000-0000-0000-0000-000000000000",
        AZURE_CLIENT_ID="00000000-0000-0000-0000-000000000001",
        STORAGE_ACCOUNT_NAME="stexample",
        SEARCH_ENDPOINT="https://example-search.search.windows.net",
        DOCINTEL_ENDPOINT="https://example-di.cognitiveservices.azure.com/",
        AOAI_ENDPOINT="https://example-aoai.openai.azure.com/",
        MAX_INGEST_BLOB_BYTES=1024,  # tiny cap so oversize tests don't need huge values
        INDEXER_POLL_TIMEOUT_SECONDS=2.0,
        INDEXER_POLL_INTERVAL_SECONDS=0.01,
    )


def _make_deps(
    *,
    blob_props: _FakeBlobProps | None = None,
    blob_props_exc: BaseException | None = None,
    indexer_run_exc: BaseException | None = None,
    indexer_status_sequence: list[_FakeIndexerStatus] | None = None,
    search_hits: list[dict[str, Any]] | None = None,
    search_delete_exc: BaseException | None = None,
    docs_repo_update_exc: BaseException | None = None,
) -> tuple[IngestionPipeline, dict[str, Any]]:
    """Build an IngestionPipeline with mocked deps; return (pipe, mocks)."""
    settings = _make_settings()

    # Storage / blob client.
    blob_client = AsyncMock()
    if blob_props_exc is not None:
        blob_client.get_blob_properties.side_effect = blob_props_exc
    else:
        blob_client.get_blob_properties.return_value = blob_props or _props()
    storage = MagicMock()
    storage.get_blob_client = MagicMock(return_value=blob_client)

    # Indexer client.
    indexer_client = AsyncMock()
    if indexer_run_exc is not None:
        indexer_client.run_indexer.side_effect = indexer_run_exc
    else:
        indexer_client.run_indexer.return_value = None
    if indexer_status_sequence is not None:
        indexer_client.get_indexer_status.side_effect = list(indexer_status_sequence)
    else:
        indexer_client.get_indexer_status.return_value = _FakeIndexerStatus(
            last_result=_FakeLastResult(status="success", item_count=5)
        )

    # Search client (used for delete-by-filter on BlobDeleted).
    search_client = AsyncMock()

    async def _aiter(items: list[dict[str, Any]]) -> AsyncIterator[dict[str, Any]]:
        for it in items:
            yield it

    search_client.search = AsyncMock(return_value=_aiter(search_hits or []))
    if search_delete_exc is not None:
        search_client.delete_documents.side_effect = search_delete_exc

    # DocIntel — only relevant for crack-failed test (direct path); the
    # BlobCreated flow doesn't call docintel because the indexer skillset
    # owns cracking.
    docintel = AsyncMock()

    # DocumentsRepo
    docs_repo = AsyncMock()
    if docs_repo_update_exc is not None:
        docs_repo.update_status.side_effect = docs_repo_update_exc

    deps = PipelineDeps(
        docintel=docintel,
        storage=storage,
        docs_repo=docs_repo,
        indexer_client=indexer_client,
        search_client=search_client,
        settings=settings,
    )
    pipe = IngestionPipeline(deps)
    return pipe, {
        "blob_client": blob_client,
        "storage": storage,
        "indexer_client": indexer_client,
        "search_client": search_client,
        "docintel": docintel,
        "docs_repo": docs_repo,
        "settings": settings,
    }


_GOOD_URL = "https://stexample.blob.core.windows.net/shared-corpus/policy.pdf"
_DOC_ID = "d_01J9ABCXYZ"


# ---------------------------------------------------------------------------
# T067 — happy path
# ---------------------------------------------------------------------------


async def test_happy_path_indexed() -> None:
    pipe, mocks = _make_deps()
    outcome = await pipe.process_blob_created(_GOOD_URL, _DOC_ID)
    assert isinstance(outcome, RunOutcome)
    assert outcome.status == "indexed"
    assert outcome.failed is False and outcome.skipped is False
    assert outcome.passage_count == 5

    # Indexer was triggered exactly once with the configured indexer name.
    mocks["indexer_client"].run_indexer.assert_awaited_once_with("kb-indexer")
    mocks["indexer_client"].get_indexer_status.assert_awaited()

    # Cosmos transitions: cracking → indexing → indexed.
    statuses = [c.args[2] for c in mocks["docs_repo"].update_status.await_args_list]
    assert statuses == ["cracking", "indexing", "indexed"]


# ---------------------------------------------------------------------------
# T069 — MIME allowlist
# ---------------------------------------------------------------------------


async def test_unsupported_mime_skipped() -> None:
    pipe, mocks = _make_deps(
        blob_props=_props(ct="application/x-msdownload"),
    )
    outcome = await pipe.process_blob_created(_GOOD_URL, _DOC_ID)
    assert outcome.skipped is True
    assert outcome.status == "skipped"
    assert outcome.reason == "unsupported-mime"

    # Indexer was NOT triggered.
    mocks["indexer_client"].run_indexer.assert_not_called()

    # Cosmos was updated with skipped + controlled errorReason.
    call = mocks["docs_repo"].update_status.await_args
    assert call.args[2] == "skipped"
    err = call.kwargs.get("error") or (call.args[3] if len(call.args) > 3 else None)
    assert err is not None
    code, reason = err
    assert code == "MIME_NOT_ALLOWED"
    assert reason.startswith("unsupported-mime:")


@pytest.mark.parametrize("mime", sorted(ALLOWED_MIME_TYPES))
async def test_all_allowlisted_mimes_pass_preflight(mime: str) -> None:
    pipe, mocks = _make_deps(blob_props=_props(ct=mime))
    outcome = await pipe.process_blob_created(_GOOD_URL, _DOC_ID)
    assert outcome.status == "indexed"
    mocks["indexer_client"].run_indexer.assert_awaited_once()


async def test_missing_content_type_rejected() -> None:
    pipe, _ = _make_deps(blob_props=_props(ct=None))
    outcome = await pipe.process_blob_created(_GOOD_URL, _DOC_ID)
    assert outcome.skipped is True
    assert outcome.reason == "unsupported-mime"


async def test_content_type_with_charset_normalized() -> None:
    pipe, _ = _make_deps(blob_props=_props(ct="text/plain; charset=utf-8"))
    outcome = await pipe.process_blob_created(_GOOD_URL, _DOC_ID)
    assert outcome.status == "indexed"


# ---------------------------------------------------------------------------
# T069 — size cap
# ---------------------------------------------------------------------------


async def test_oversize_skipped() -> None:
    pipe, mocks = _make_deps(blob_props=_props(size=10_000))  # cap is 1024
    outcome = await pipe.process_blob_created(_GOOD_URL, _DOC_ID)
    assert outcome.skipped is True
    assert outcome.reason == "oversize"
    mocks["indexer_client"].run_indexer.assert_not_called()
    call = mocks["docs_repo"].update_status.await_args
    assert call.args[2] == "skipped"
    err = call.kwargs.get("error")
    assert err is not None
    assert err[0] == "BLOB_TOO_LARGE"
    assert err[1].startswith("oversize:")


# ---------------------------------------------------------------------------
# errorReason: embed-failed
# ---------------------------------------------------------------------------


async def test_indexer_run_failure_marks_embed_failed() -> None:
    pipe, mocks = _make_deps(indexer_run_exc=RuntimeError("boom"))
    outcome = await pipe.process_blob_created(_GOOD_URL, _DOC_ID)
    assert outcome.failed is True
    assert outcome.reason == "embed-failed"

    # Status went to cracking (set just before run_indexer) then failed.
    statuses = [c.args[2] for c in mocks["docs_repo"].update_status.await_args_list]
    assert statuses == ["cracking", "failed"]
    err = mocks["docs_repo"].update_status.await_args.kwargs.get("error")
    assert err is not None
    assert err[0] == "INDEXER_FAILED"
    assert err[1].startswith("embed-failed:")


async def test_indexer_terminal_failure_marks_embed_failed() -> None:
    pipe, mocks = _make_deps(
        indexer_status_sequence=[
            _FakeIndexerStatus(
                last_result=_FakeLastResult(
                    status="persistentFailure", error_message="skill x failed"
                )
            )
        ]
    )
    outcome = await pipe.process_blob_created(_GOOD_URL, _DOC_ID)
    assert outcome.failed is True
    assert outcome.reason == "embed-failed"


async def test_indexer_poll_timeout_marks_embed_failed() -> None:
    """A perpetually-running indexer should time out, not hang."""
    pipe, mocks = _make_deps(
        indexer_status_sequence=[
            _FakeIndexerStatus(last_result=_FakeLastResult(status="inProgress"))
        ]
        * 1000,
    )
    outcome = await pipe.process_blob_created(_GOOD_URL, _DOC_ID)
    assert outcome.failed is True
    assert outcome.reason == "embed-failed"


# ---------------------------------------------------------------------------
# errorReason: upsert-failed
# ---------------------------------------------------------------------------


async def test_blob_url_outside_owned_account_marks_upsert_failed() -> None:
    pipe, mocks = _make_deps()
    bad = "https://attacker.blob.core.windows.net/x/y.pdf"
    outcome = await pipe.process_blob_created(bad, _DOC_ID)
    assert outcome.failed is True
    assert outcome.reason == "upsert-failed"
    # Indexer never triggered.
    mocks["indexer_client"].run_indexer.assert_not_called()


async def test_blob_url_with_sas_rejected() -> None:
    pipe, _ = _make_deps()
    bad = "https://stexample.blob.core.windows.net/c/b.pdf?sig=abcd"
    outcome = await pipe.process_blob_created(bad, _DOC_ID)
    assert outcome.failed is True
    assert outcome.reason == "upsert-failed"


async def test_blob_not_found_marks_upsert_failed() -> None:
    from azure.core.exceptions import ResourceNotFoundError

    pipe, _ = _make_deps(blob_props_exc=ResourceNotFoundError("missing"))
    outcome = await pipe.process_blob_created(_GOOD_URL, _DOC_ID)
    assert outcome.failed is True
    assert outcome.reason == "upsert-failed"


# ---------------------------------------------------------------------------
# errorReason: crack-failed (direct-push variant)
# ---------------------------------------------------------------------------


async def test_crack_failed_in_direct_push_variant() -> None:
    """The crack-failed reason is emitted by the future user-upload variant.

    We exercise the helper directly to lock the controlled vocabulary in
    place; the BlobCreated path delegates cracking to the skillset and
    cannot raise crack-failed.
    """
    pipe, mocks = _make_deps()
    mocks["docintel"].analyze_layout.side_effect = RuntimeError("docintel down")
    with pytest.raises(RuntimeError):
        await pipe._crack_and_chunk(_GOOD_URL)

    # Simulate the wrapping path-fragment used by the user-upload variant
    # (T110): caller must classify the error to ``crack-failed``.
    await pipe._record_failure(_DOC_ID, "crack-failed", "docintel down")
    err = mocks["docs_repo"].update_status.await_args.kwargs.get("error")
    assert err == ("DOCINTEL_FAILED", "crack-failed: docintel down")


# ---------------------------------------------------------------------------
# BlobDeleted
# ---------------------------------------------------------------------------


async def test_blob_deleted_removes_passages_and_tombstones() -> None:
    pipe, mocks = _make_deps(
        search_hits=[{"id": "d_01J9ABCXYZ-0000"}, {"id": "d_01J9ABCXYZ-0001"}]
    )
    outcome = await pipe.process_blob_deleted(_DOC_ID)
    assert outcome.status == "deleted"
    assert outcome.passage_count == 2
    mocks["search_client"].delete_documents.assert_awaited_once()
    args, kwargs = mocks["search_client"].delete_documents.await_args
    docs = kwargs.get("documents") or args[0]
    assert {d["id"] for d in docs} == {"d_01J9ABCXYZ-0000", "d_01J9ABCXYZ-0001"}

    last = mocks["docs_repo"].update_status.await_args
    assert last.args[2] == "deleted"


async def test_blob_deleted_with_no_passages_still_tombstones() -> None:
    pipe, mocks = _make_deps(search_hits=[])
    outcome = await pipe.process_blob_deleted(_DOC_ID)
    assert outcome.status == "deleted"
    assert outcome.passage_count == 0
    mocks["search_client"].delete_documents.assert_not_called()


async def test_blob_deleted_search_failure_marks_upsert_failed() -> None:
    pipe, mocks = _make_deps()
    mocks["search_client"].search.side_effect = RuntimeError("search down")
    outcome = await pipe.process_blob_deleted(_DOC_ID)
    assert outcome.failed is True
    assert outcome.reason == "upsert-failed"


async def test_blob_deleted_rejects_unsafe_document_id() -> None:
    pipe, _ = _make_deps()
    outcome = await pipe.process_blob_deleted("d' OR 1 eq 1--")
    assert outcome.failed is True
    assert outcome.reason == "upsert-failed"


# ---------------------------------------------------------------------------
# process_blob_changed mirrors process_blob_created
# ---------------------------------------------------------------------------


async def test_blob_changed_runs_same_pipeline() -> None:
    pipe, mocks = _make_deps()
    outcome = await pipe.process_blob_changed(_GOOD_URL, _DOC_ID)
    assert outcome.status == "indexed"
    mocks["indexer_client"].run_indexer.assert_awaited_once()


# ---------------------------------------------------------------------------
# Chunking helper
# ---------------------------------------------------------------------------


async def test_crack_and_chunk_produces_overlapping_passages() -> None:
    pipe, mocks = _make_deps()

    class _Layout:
        markdown = "x" * 10_000

    mocks["docintel"].analyze_layout.return_value = _Layout()
    passages = await pipe._crack_and_chunk(_GOOD_URL)
    assert len(passages) >= 2
    # Orders are 0-based and contiguous.
    assert [p[0] for p in passages] == list(range(len(passages)))


async def test_crack_and_chunk_empty_markdown_yields_no_passages() -> None:
    pipe, mocks = _make_deps()

    class _Layout:
        markdown = "   "

    mocks["docintel"].analyze_layout.return_value = _Layout()
    passages = await pipe._crack_and_chunk(_GOOD_URL)
    assert passages == []


async def test_direct_upsert_passages_round_trip() -> None:
    pipe, mocks = _make_deps()
    n = await pipe._direct_upsert_passages(
        document_id=_DOC_ID,
        title="Policy.pdf",
        passages=[(0, "alpha"), (1, "beta")],
    )
    assert n == 2
    mocks["search_client"].upload_documents.assert_awaited_once()
    docs = mocks["search_client"].upload_documents.await_args.kwargs["documents"]
    assert [d["id"] for d in docs] == [f"{_DOC_ID}-0000", f"{_DOC_ID}-0001"]
    assert all(d["scope"] == "shared" for d in docs)
    assert all(d["userOid"] is None for d in docs)
    assert all(d["conversationId"] is None for d in docs)
