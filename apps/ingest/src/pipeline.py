"""Ingestion pipeline (T067, T069).

Implements the crack → chunk → embed → upsert pipeline for blob-triggered
ingestion of the **shared corpus** (Event Grid → Storage Queue → Container
Apps Job) per:

* spec ``specs/001-private-rag-accelerator/tasks.md`` — T067 / T069
* data model ``specs/001-private-rag-accelerator/data-model.md`` §5–§8

The pipeline is invoked from ``apps/ingest/src/main.py`` (T066, separate PR).
Three entrypoints:

* :py:meth:`IngestionPipeline.process_blob_created` — new blob in
  ``shared-corpus``: pre-flight (MIME / size, T069) → trigger AI Search
  indexer → wait → write status to Cosmos.
* :py:meth:`IngestionPipeline.process_blob_changed` — same flow as
  ``BlobCreated`` (the indexer is content-aware via change-tracking; we
  re-run unconditionally for shared corpus because the blob URL is the
  identity of record).
* :py:meth:`IngestionPipeline.process_blob_deleted` — issue a delete-by-
  filter against ``kb-index`` for ``documentId eq '<id>'`` and mark the
  ``Document`` row as deleted (data-model.md §7).

Embedding strategy
------------------
Per the Kane/Phase-4 implementation choice, the **shared corpus** path runs
the AI Search **skillset** (which already includes
``#Microsoft.Skills.Text.AzureOpenAIEmbeddingSkill``) by triggering the
indexer with :py:meth:`SearchIndexerClient.run_indexer`. We do **not**
embed inline; we let the skillset call Azure OpenAI over the shared
private link.

Note: ``data-model.md`` §5 states ``kb-indexer`` is "disabled (we push,
don't pull)"; the Phase-4 implementation reverses that decision because
running the embedding skill outside an indexer requires a Knowledge Store
or direct push of pre-vectorized payloads — both add cost / surface area
for no meaningful gain over an indexer that already wraps the
DocIntelLayout + Split + Embedding skills. The data-model note will be
reconciled in the Phase-5 docs sweep.

For the **user-upload** path (T110, future) the direct-push variant is
already wired as :py:meth:`IngestionPipeline._crack_and_chunk` +
:py:meth:`IngestionPipeline._direct_upsert_passages`. That variant cracks
with :py:class:`DocIntelService`, splits into ~800-token passages, and
upserts per-passage docs to ``kb-index`` directly (the integrated
vectorizer on the index handles embedding at index time). It is **not**
exercised by the BlobCreated/Changed paths in this PR.

Shared-lib note
---------------
This module duplicates the blob-host invariant from
``apps/api/src/services/storage.py::assert_blob_in_owned_account`` (T038)
and consumes the existing :py:class:`DocIntelService` shape rather than
importing it directly — the ``apps/ingest`` and ``apps/api`` packages are
independent hatchling builds. See
``.squad/decisions/inbox/2026-05-09-shared-lib-refactor.md`` for the
escalation to Lead.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final, Literal, Protocol, runtime_checkable
from urllib.parse import urlparse

from azure.core.credentials_async import AsyncTokenCredential
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from azure.identity.aio import DefaultAzureCredential
from azure.search.documents.aio import SearchClient
from azure.search.documents.indexes.aio import SearchIndexerClient
from azure.storage.blob.aio import BlobServiceClient

from .config import IngestSettings, get_settings

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


# Controlled vocabulary for ``Document.ingestion.errorReason`` (data-model §7).
ErrorReason = Literal[
    "unsupported-mime",
    "oversize",
    "crack-failed",
    "embed-failed",
    "upsert-failed",
]

_ERROR_CODES: Final[dict[ErrorReason, str]] = {
    "unsupported-mime": "MIME_NOT_ALLOWED",
    "oversize": "BLOB_TOO_LARGE",
    "crack-failed": "DOCINTEL_FAILED",
    "embed-failed": "INDEXER_FAILED",
    "upsert-failed": "INDEX_UPSERT_FAILED",
}

# MIME allowlist (data-model.md §8): PDF, plain text, DOCX, XLSX, PPTX,
# PNG, JPEG, TIFF.
ALLOWED_MIME_TYPES: Final[frozenset[str]] = frozenset(
    {
        "application/pdf",
        "text/plain",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "image/png",
        "image/jpeg",
        "image/tiff",
    }
)

# Document.ingestion.status alphabet (data-model.md §3 / §7) — written to
# Cosmos. Distinct from :data:`RunStatus` (the worker-facing terminal
# status carried by :class:`RunOutcome`); ``RunOutcome.cosmos_status``
# preserves the rich Cosmos state for callers that care.
DocumentStatus = Literal[
    "queued", "cracking", "indexing", "indexed", "failed", "skipped", "deleted"
]

# Worker-facing terminal status — matches the ``RunOutcome`` placeholder
# shipped by T068 (``apps/ingest/src/handlers/shared.py``). Keep this
# vocabulary stable; the handler boundary depends on it.
RunStatus = Literal["succeeded", "failed", "skipped"]


@dataclass(frozen=True)
class RunOutcome:
    """Result of a single pipeline invocation.

    Compatible with the placeholder shipped by T068 (handlers expect
    ``status``, ``document_id``, ``event_type``, ``message``). Extra
    fields below are pipeline-specific telemetry that handlers may
    ignore.

    ``status`` is the **worker-facing** terminal status (succeeded /
    failed / skipped). ``cosmos_status`` carries the richer
    :data:`DocumentStatus` value the pipeline wrote to Cosmos
    (``indexed`` / ``deleted`` / ``failed`` / ``skipped``) for tests and
    observability.

    The public ``process_*`` methods on :class:`IngestionPipeline` never
    raise — every error path is reflected here and on the ``Document``
    row in Cosmos.
    """

    status: RunStatus
    document_id: str
    event_type: str | None = None
    message: str | None = None
    cosmos_status: DocumentStatus | None = None
    reason: ErrorReason | None = None
    passage_count: int | None = None
    indexer_run_id: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status == "succeeded"

    @property
    def failed(self) -> bool:
        return self.status == "failed"

    @property
    def skipped(self) -> bool:
        return self.status == "skipped"


# ---------------------------------------------------------------------------
# Dependency Protocols
# ---------------------------------------------------------------------------
#
# We use ``Protocol`` rather than concrete imports from ``apps.api`` so that
# the ingest package builds and tests independently. The wiring layer
# (``apps/ingest/src/main.py``, T066) injects the real implementations.


class _LayoutResult(Protocol):
    markdown: str


@runtime_checkable
class DocIntelService(Protocol):
    """Subset of ``apps.api.src.services.docintel.DocIntelService`` we use."""

    async def analyze_layout(self, blob_url: str) -> _LayoutResult: ...


@runtime_checkable
class DocumentsRepo(Protocol):
    """Subset of ``apps.api.src.services.cosmos.DocumentsRepo`` we use."""

    async def get(self, document_id: str, scope: str) -> Any: ...

    async def upsert(self, document: Any) -> Any: ...

    async def update_status(
        self,
        document_id: str,
        scope: str,
        status: str,
        error: tuple[str, str] | None = None,
    ) -> Any: ...


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PipelineInvariantError(Exception):
    """Raised when a defense-in-depth invariant is violated.

    These never escape the public ``process_*`` methods — they are caught,
    logged, and reflected as ``RunOutcome(status="failed", ...)``.
    """


# ---------------------------------------------------------------------------
# Blob-URL invariant (duplicated from apps/api/src/services/storage.py)
# ---------------------------------------------------------------------------

_BLOB_HOST_SUFFIX = ".blob.core.windows.net"


def _assert_blob_in_owned_account(
    blob_uri: str, *, expected_account: str
) -> None:
    """Defense-in-depth gate (data-model.md §3).

    Mirrors ``apps.api.src.services.storage.assert_blob_in_owned_account``
    so the ingest worker rejects attacker-controlled URLs without depending
    on the api package. See module docstring for the shared-lib note.
    """
    if not blob_uri or not isinstance(blob_uri, str):
        raise PipelineInvariantError("blob URI is empty or not a string")
    parsed = urlparse(blob_uri)
    if parsed.scheme != "https":
        raise PipelineInvariantError(
            f"blob URI must use https (got scheme={parsed.scheme!r})"
        )
    host = (parsed.hostname or "").lower()
    if not host.endswith(_BLOB_HOST_SUFFIX):
        raise PipelineInvariantError(
            f"blob URI host {host!r} is not an Azure Blob endpoint"
        )
    expected = f"{expected_account.lower()}{_BLOB_HOST_SUFFIX}"
    if host != expected:
        raise PipelineInvariantError(
            f"blob URI host {host!r} is not the platform-owned account {expected!r}"
        )
    if "sig=" in (parsed.query or "").lower():
        raise PipelineInvariantError("blob URI carries a SAS signature; rejected")
    if not parsed.path or parsed.path == "/":
        raise PipelineInvariantError("blob URI is missing container/blob path")


def _container_and_blob_from_url(blob_url: str) -> tuple[str, str]:
    """Split ``https://<acct>.blob.core.windows.net/<container>/<rest>``."""
    path = urlparse(blob_url).path.lstrip("/")
    container, _, blob_name = path.partition("/")
    if not container or not blob_name:
        raise PipelineInvariantError(
            f"blob URI does not include both container and blob: {blob_url}"
        )
    return container, blob_name


# ---------------------------------------------------------------------------
# Deps + pipeline
# ---------------------------------------------------------------------------


@dataclass
class PipelineDeps:
    """Injected dependencies for :py:class:`IngestionPipeline`."""

    docintel: DocIntelService
    storage: BlobServiceClient
    docs_repo: DocumentsRepo
    indexer_client: SearchIndexerClient
    search_client: SearchClient
    settings: IngestSettings = field(default_factory=get_settings)


# Tokens are approximated by characters / 4 (close enough for chunking;
# tiktoken is intentionally not a hard dependency — see pyproject.toml).
_CHARS_PER_TOKEN: Final[int] = 4


_INDEXER_TERMINAL_SUCCESS = {"success"}
_INDEXER_TERMINAL_FAILURE = {"transientFailure", "persistentFailure", "failed"}


class IngestionPipeline:
    """Orchestrate crack → (chunk →) embed → upsert for shared-corpus blobs.

    All public ``process_*`` methods are best-effort: they catch exceptions
    from any step, classify the failure into the controlled
    ``errorReason`` vocabulary (T069 / data-model §7), update the
    ``Document`` row, and return a :py:class:`RunOutcome`. They never raise.
    """

    SHARED_SCOPE: Final[str] = "shared"

    def __init__(self, deps: PipelineDeps) -> None:
        self._deps = deps
        self._settings = deps.settings

    # ------------------------------------------------------------------
    # Public entrypoints
    # ------------------------------------------------------------------

    async def process_blob_created(
        self, blob_url: str, document_id: str
    ) -> RunOutcome:
        return await self._process_create_or_change(
            blob_url, document_id, event_type="Microsoft.Storage.BlobCreated"
        )

    async def process_blob_changed(
        self, blob_url: str, document_id: str
    ) -> RunOutcome:
        # Same workflow as BlobCreated for shared corpus: re-run the indexer.
        # The skillset's change-tracking + the indexer's high-water mark
        # take care of incremental processing.
        return await self._process_create_or_change(
            blob_url, document_id, event_type="Microsoft.Storage.BlobChanged"
        )

    async def process_blob_deleted(self, document_id: str) -> RunOutcome:
        """Delete passages from ``kb-index`` and tombstone the Document row.

        Strategy: search for all passage ids matching ``documentId eq
        '<id>' and scope eq 'shared'``, then issue a single
        ``delete_documents`` call. Done in two hops so that if an old
        ingest persisted passages with mismatched ids we still find and
        remove them. (Cheaper one-hop alternative: assume our id scheme
        and call ``delete_documents`` with a synthesized id list — but
        that breaks if the skillset re-keyed passages.)
        """
        try:
            passage_ids = await self._collect_passage_ids(document_id)
            if passage_ids:
                await self._deps.search_client.delete_documents(
                    documents=[{"id": pid} for pid in passage_ids],
                )
            with contextlib.suppress(_NotFoundLike):
                await self._deps.docs_repo.update_status(
                    document_id, self.SHARED_SCOPE, "deleted"
                )
            return RunOutcome(
                status="succeeded",
                document_id=document_id,
                event_type="Microsoft.Storage.BlobDeleted",
                cosmos_status="deleted",
                passage_count=len(passage_ids),
            )
        except Exception as exc:  # noqa: BLE001
            await self._record_failure(
                document_id, "upsert-failed", repr(exc)
            )
            return RunOutcome(
                status="failed",
                document_id=document_id,
                event_type="Microsoft.Storage.BlobDeleted",
                message=repr(exc),
                cosmos_status="failed",
                reason="upsert-failed",
            )

    # ------------------------------------------------------------------
    # Core create/change flow
    # ------------------------------------------------------------------

    async def _process_create_or_change(
        self, blob_url: str, document_id: str, *, event_type: str
    ) -> RunOutcome:
        # Step 0: defensive blob URL validation.
        try:
            _assert_blob_in_owned_account(
                blob_url, expected_account=self._settings.STORAGE_ACCOUNT_NAME
            )
        except PipelineInvariantError as exc:
            await self._record_failure(document_id, "upsert-failed", str(exc))
            return RunOutcome(
                status="failed",
                document_id=document_id,
                event_type=event_type,
                message=str(exc),
                cosmos_status="failed",
                reason="upsert-failed",
            )

        # Step 1: MIME + size pre-flight (T069).
        preflight = await self._preflight(blob_url, document_id, event_type)
        if preflight is not None:
            return preflight

        # Step 2: trigger the AI Search indexer (which runs the skillset =
        # DocIntelLayout + Split + AzureOpenAIEmbedding).
        await self._set_status(document_id, "cracking")
        try:
            await self._deps.indexer_client.run_indexer(
                self._settings.SHARED_CORPUS_INDEXER
            )
        except Exception as exc:  # noqa: BLE001
            return await self._fail(
                document_id, "embed-failed", repr(exc), event_type=event_type
            )

        # Step 3: poll for completion (bounded).
        await self._set_status(document_id, "indexing")
        try:
            run_outcome = await self._wait_for_indexer()
        except _IndexerTimeout:
            # Treat timeout as failure rather than hanging the worker.
            return await self._fail(
                document_id,
                "embed-failed",
                "indexer poll timeout",
                event_type=event_type,
            )
        except Exception as exc:  # noqa: BLE001
            return await self._fail(
                document_id, "embed-failed", repr(exc), event_type=event_type
            )

        if run_outcome.status == "failed":
            return await self._fail(
                document_id,
                "embed-failed",
                run_outcome.error or "indexer failure",
                event_type=event_type,
            )

        # Step 4: success → indexed.
        await self._set_status(document_id, "indexed")
        return RunOutcome(
            status="succeeded",
            document_id=document_id,
            event_type=event_type,
            cosmos_status="indexed",
            passage_count=run_outcome.processed,
            indexer_run_id=run_outcome.run_id,
        )

    # ------------------------------------------------------------------
    # T069: MIME + size pre-flight
    # ------------------------------------------------------------------

    async def _preflight(
        self, blob_url: str, document_id: str, event_type: str
    ) -> RunOutcome | None:
        container, blob_name = _container_and_blob_from_url(blob_url)
        blob_client = self._deps.storage.get_blob_client(
            container=container, blob=blob_name
        )

        try:
            props = await blob_client.get_blob_properties()
        except ResourceNotFoundError:
            await self._record_failure(
                document_id, "upsert-failed", "blob not found at preflight"
            )
            return RunOutcome(
                status="failed",
                document_id=document_id,
                event_type=event_type,
                message="blob not found at preflight",
                cosmos_status="failed",
                reason="upsert-failed",
            )
        except HttpResponseError as exc:
            await self._record_failure(
                document_id, "upsert-failed", f"preflight error: {exc!s}"
            )
            return RunOutcome(
                status="failed",
                document_id=document_id,
                event_type=event_type,
                message=f"preflight error: {exc!s}",
                cosmos_status="failed",
                reason="upsert-failed",
            )

        size_bytes = int(getattr(props, "size", 0) or 0)
        content_type = _extract_content_type(props)

        if content_type not in ALLOWED_MIME_TYPES:
            detail = f"content_type={content_type!r}"
            await self._record_skip(document_id, "unsupported-mime", detail)
            return RunOutcome(
                status="skipped",
                document_id=document_id,
                event_type=event_type,
                message=f"unsupported-mime: {detail}",
                cosmos_status="skipped",
                reason="unsupported-mime",
            )

        if size_bytes > self._settings.MAX_INGEST_BLOB_BYTES:
            detail = (
                f"size_bytes={size_bytes} > cap={self._settings.MAX_INGEST_BLOB_BYTES}"
            )
            await self._record_skip(document_id, "oversize", detail)
            return RunOutcome(
                status="skipped",
                document_id=document_id,
                event_type=event_type,
                message=f"oversize: {detail}",
                cosmos_status="skipped",
                reason="oversize",
            )

        return None

    # ------------------------------------------------------------------
    # Indexer polling
    # ------------------------------------------------------------------

    async def _wait_for_indexer(self) -> _IndexerRunOutcome:
        timeout = self._settings.INDEXER_POLL_TIMEOUT_SECONDS
        interval = max(self._settings.INDEXER_POLL_INTERVAL_SECONDS, 0.1)
        deadline = asyncio.get_event_loop().time() + timeout

        while True:
            status = await self._deps.indexer_client.get_indexer_status(
                self._settings.SHARED_CORPUS_INDEXER
            )
            last = getattr(status, "last_result", None)
            last_status = (getattr(last, "status", None) or "").lower()
            if last_status in _INDEXER_TERMINAL_SUCCESS:
                start_time = getattr(last, "start_time", None)
                return _IndexerRunOutcome(
                    status="success",
                    processed=int(getattr(last, "item_count", 0) or 0),
                    run_id=str(start_time) if start_time else None,
                )
            if last_status in {s.lower() for s in _INDEXER_TERMINAL_FAILURE}:
                err = getattr(last, "error_message", None)
                return _IndexerRunOutcome(
                    status="failed",
                    processed=int(getattr(last, "item_count", 0) or 0),
                    error=str(err) if err else "indexer reported failure",
                )

            if asyncio.get_event_loop().time() >= deadline:
                raise _IndexerTimeout()
            await asyncio.sleep(interval)

    async def _collect_passage_ids(self, document_id: str) -> list[str]:
        """Return all ``id`` fields in ``kb-index`` matching this document.

        Bypasses the SC-011 scope-filter wrapper because (a) the shared
        corpus is admin-curated (no per-user PII), and (b) we are
        deleting our own passages by document id, not querying for
        retrieval. We still narrow with ``scope eq 'shared'`` to avoid
        nuking a hypothetical user-scoped passage that happened to share
        a ``documentId``.
        """
        safe_id = _odata_string_literal(document_id)
        filter_expr = f"documentId eq {safe_id} and scope eq 'shared'"
        ids: list[str] = []
        result = await self._deps.search_client.search(
            search_text="*",
            filter=filter_expr,
            select=["id"],
            top=1000,
        )
        async for hit in result:
            pid = hit.get("id") if isinstance(hit, dict) else getattr(hit, "id", None)
            if pid:
                ids.append(str(pid))
        return ids

    # ------------------------------------------------------------------
    # Status / Cosmos helpers
    # ------------------------------------------------------------------

    async def _set_status(self, document_id: str, status: DocumentStatus) -> None:
        with contextlib.suppress(Exception):
            await self._deps.docs_repo.update_status(
                document_id, self.SHARED_SCOPE, status
            )

    async def _record_failure(
        self, document_id: str, reason: ErrorReason, detail: str
    ) -> None:
        with contextlib.suppress(Exception):
            await self._deps.docs_repo.update_status(
                document_id,
                self.SHARED_SCOPE,
                "failed",
                error=(_ERROR_CODES[reason], f"{reason}: {detail}"),
            )

    async def _record_skip(
        self, document_id: str, reason: ErrorReason, detail: str
    ) -> None:
        with contextlib.suppress(Exception):
            await self._deps.docs_repo.update_status(
                document_id,
                self.SHARED_SCOPE,
                "skipped",
                error=(_ERROR_CODES[reason], f"{reason}: {detail}"),
            )

    async def _fail(
        self,
        document_id: str,
        reason: ErrorReason,
        detail: str,
        *,
        event_type: str | None = None,
    ) -> RunOutcome:
        await self._record_failure(document_id, reason, detail)
        return RunOutcome(
            status="failed",
            document_id=document_id,
            event_type=event_type,
            message=f"{reason}: {detail}",
            cosmos_status="failed",
            reason=reason,
        )

    # ------------------------------------------------------------------
    # Direct-push variant (for the future user-upload path, T110).
    # ------------------------------------------------------------------
    #
    # Not exercised by the BlobCreated/Changed flow above. Kept here so
    # the user-upload path can compose them without a second module.

    async def _crack_and_chunk(
        self, blob_url: str
    ) -> list[tuple[int, str]]:
        """Crack via DocIntel and split markdown into ``(chunk_order, text)``
        passages of approximately ``CHUNK_SIZE_TOKENS`` with
        ``CHUNK_OVERLAP_TOKENS`` overlap.

        Token counting is approximate (4 chars / token) — see
        :data:`_CHARS_PER_TOKEN`.
        """
        layout = await self._deps.docintel.analyze_layout(blob_url)
        markdown = (layout.markdown or "").strip()
        chunk_chars = self._settings.CHUNK_SIZE_TOKENS * _CHARS_PER_TOKEN
        overlap_chars = self._settings.CHUNK_OVERLAP_TOKENS * _CHARS_PER_TOKEN
        if chunk_chars <= 0:
            raise PipelineInvariantError("CHUNK_SIZE_TOKENS must be > 0")
        if overlap_chars >= chunk_chars:
            raise PipelineInvariantError(
                "CHUNK_OVERLAP_TOKENS must be < CHUNK_SIZE_TOKENS"
            )
        passages: list[tuple[int, str]] = []
        if not markdown:
            return passages
        step = chunk_chars - overlap_chars
        order = 0
        for start in range(0, len(markdown), step):
            chunk = markdown[start : start + chunk_chars]
            if chunk.strip():
                passages.append((order, chunk))
                order += 1
        return passages

    async def _direct_upsert_passages(
        self,
        *,
        document_id: str,
        title: str,
        passages: list[tuple[int, str]],
        scope: str = "shared",
        user_oid: str | None = None,
        conversation_id: str | None = None,
    ) -> int:
        """Upsert per-passage docs to ``kb-index`` (data-model §5).

        Used by the user-upload variant; the index's
        ``AzureOpenAIVectorizer`` populates ``contentVector`` at index
        time. Returns the number of passages upserted.
        """
        now_iso = datetime.now(UTC).isoformat()
        docs: list[dict[str, Any]] = []
        for order, content in passages:
            docs.append(
                {
                    "id": f"{document_id}-{order:04d}",
                    "documentId": document_id,
                    "scope": scope,
                    "userOid": user_oid,
                    "conversationId": conversation_id,
                    "title": title,
                    "content": content,
                    "page": 0,
                    "chunkOrder": order,
                    "lastIndexedAt": now_iso,
                }
            )
        if not docs:
            return 0
        await self._deps.search_client.upload_documents(documents=docs)
        return len(docs)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _IndexerRunOutcome:
    status: Literal["success", "failed"]
    processed: int = 0
    run_id: str | None = None
    error: str | None = None


class _IndexerTimeout(Exception):
    pass


class _NotFoundLike(Exception):
    pass


def _extract_content_type(props: Any) -> str:
    """Pull ``content_type`` out of a ``BlobProperties``-like object.

    Accepts both the SDK's nested ``content_settings.content_type`` shape
    and a flat ``content_type`` attribute (for test mocks).
    """
    cs = getattr(props, "content_settings", None)
    if cs is not None:
        ct = getattr(cs, "content_type", None)
        if ct:
            return str(ct).lower().split(";", 1)[0].strip()
    flat = getattr(props, "content_type", None)
    if flat:
        return str(flat).lower().split(";", 1)[0].strip()
    return ""


_ODATA_SAFE = re.compile(r"^[A-Za-z0-9_\-./:]+$")


def _odata_string_literal(value: str) -> str:
    """Wrap a string for OData ``eq`` comparison.

    Document ids are ULID/UUID-ish (``d_<ulid>``) by convention. We refuse
    anything outside a conservative character class to avoid OData
    injection. This is defense-in-depth — callers should already be
    feeding us trusted ids from the queue payload.
    """
    if not isinstance(value, str) or not _ODATA_SAFE.match(value):
        raise PipelineInvariantError(
            f"document id {value!r} contains characters not allowed in OData literal"
        )
    return f"'{value}'"


# ---------------------------------------------------------------------------
# Factory (used by main.py / tests)
# ---------------------------------------------------------------------------


def build_default_clients(
    settings: IngestSettings | None = None,
    credential: AsyncTokenCredential | None = None,
) -> tuple[BlobServiceClient, SearchIndexerClient, SearchClient]:
    """Build managed-identity-bound SDK clients for the pipeline.

    Wiring helper for ``apps/ingest/src/main.py`` (T066). Tests inject
    mocks instead of calling this.
    """
    s = settings or get_settings()
    cred = credential or DefaultAzureCredential()
    blob = BlobServiceClient(
        account_url=f"https://{s.STORAGE_ACCOUNT_NAME}{_BLOB_HOST_SUFFIX}",
        credential=cred,
    )
    indexer = SearchIndexerClient(endpoint=s.SEARCH_ENDPOINT, credential=cred)
    search = SearchClient(
        endpoint=s.SEARCH_ENDPOINT,
        index_name=s.SEARCH_INDEX_NAME,
        credential=cred,
    )
    return blob, indexer, search


__all__ = [
    "ALLOWED_MIME_TYPES",
    "DocIntelService",
    "DocumentStatus",
    "DocumentsRepo",
    "ErrorReason",
    "IngestionPipeline",
    "PipelineDeps",
    "PipelineInvariantError",
    "RunOutcome",
    "RunStatus",
    "build_default_clients",
]
