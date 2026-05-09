"""Citations router (T084).

Serves the original document binary behind a cited passage so the web UI's
citation chips can deep-link the user back to the source.

Endpoint
--------
``GET /citations/{documentId}?page=N``

* ``page`` is optional; we return the **full** document binary either way.
  The web client uses ``#page=N`` style fragments (or PDF.js' viewer params)
  to scroll to the cited page.

Scope gate (SC-011)
-------------------
A caller may retrieve a document **only** when its ``scope`` is one of:

* ``"shared"`` — admin-curated corpus, anyone authenticated may read it.
* ``"user:<callerOid>"`` — the caller's own uploaded document, scoped to
  their conversation.

Anything else (including ``"user:<otherOid>"``) MUST return ``404`` — never
``403`` — so we don't leak the existence of another user's document.
The same 404 is returned when the document id doesn't exist at all.

Streaming
---------
We resolve the blob via :class:`~azure.storage.blob.aio.BlobClient` and
stream the chunks back through :class:`StreamingResponse` so a 100 MB PDF
never sits fully in API memory.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated
from urllib.parse import unquote, urlparse

from azure.cosmos import exceptions as cosmos_exc
from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import StreamingResponse

from ..middleware.error_handler import NotFoundError
from ..middleware.logging import get_logger
from ..models import CurrentUser
from ..services.auth import current_user
from ..services.cosmos import (
    DocumentRecord,
    DocumentsRepo,
    get_documents_repo,
)
from ..services.storage import (
    assert_blob_in_owned_account,
    get_blob_service_client,
    get_corpus_container,
    get_user_uploads_container,
)

_log = get_logger(__name__)

router = APIRouter(tags=["citations"])


_DEFAULT_CONTENT_TYPE = "application/octet-stream"


def _scope_allowed(doc_scope: str, caller_oid: str) -> bool:
    if doc_scope == "shared":
        return True
    return doc_scope == f"user:{caller_oid}"


def _parse_blob_uri(blob_uri: str) -> tuple[str, str]:
    """Split ``https://<acct>.blob.core.windows.net/<container>/<path...>``.

    Returns ``(container_name, blob_name)``. Raises :class:`ValueError` if
    the path doesn't carry both segments.
    """
    parsed = urlparse(blob_uri)
    path = (parsed.path or "").lstrip("/")
    if not path or "/" not in path:
        raise ValueError(f"blobUri is missing container/blob path: {blob_uri!r}")
    container, _, name = path.partition("/")
    if not container or not name:
        raise ValueError(f"blobUri is missing container/blob path: {blob_uri!r}")
    return unquote(container), unquote(name)


def _container_for_scope(scope: str) -> str:
    """Fallback container derivation when the document has no `blobUri`."""
    if scope == "shared":
        return get_corpus_container()
    return get_user_uploads_container()


async def _resolve_blob_location(doc: DocumentRecord) -> tuple[str, str]:
    """Return ``(container, blob_name)`` for the document.

    Prefers the on-record ``blobUri`` (validated to live in the owned
    storage account). Falls back to a scope-derived container if a future
    record carries only ``blobPath`` — keeps us forward-compatible with the
    naming the user-facing prompt referenced.
    """
    extras = doc.model_extra or {}
    blob_path = extras.get("blobPath")
    container_name = extras.get("containerName")

    if doc.blobUri:
        assert_blob_in_owned_account(doc.blobUri)
        container, name = _parse_blob_uri(doc.blobUri)
        return container, name

    if isinstance(blob_path, str) and blob_path:
        container = (
            container_name
            if isinstance(container_name, str) and container_name
            else _container_for_scope(doc.scope)
        )
        return container, blob_path.lstrip("/")

    raise NotFoundError("Document not found")


async def _stream_blob(container: str, name: str) -> AsyncIterator[bytes]:
    svc = await get_blob_service_client()
    blob_client = svc.get_blob_client(container=container, blob=name)
    downloader = await blob_client.download_blob()
    async for chunk in downloader.chunks():
        yield chunk


@router.get(
    "/citations/{documentId}",
    summary="Stream the source document for a citation, in-context",
    responses={
        200: {
            "description": "Document binary",
            "content": {
                "application/octet-stream": {},
                "application/pdf": {},
                "image/png": {},
                "image/jpeg": {},
            },
        },
        404: {"description": "Document not found or out of scope"},
    },
)
async def get_citation_document(
    documentId: Annotated[str, Path(min_length=1)],  # noqa: N803 — path-param name from contract
    docs_repo: Annotated[DocumentsRepo, Depends(get_documents_repo)],
    user: Annotated[CurrentUser, Depends(current_user)],
    page: Annotated[int | None, Query(ge=1)] = None,  # noqa: ARG001 — accepted per contract; UI uses it client-side
) -> StreamingResponse:
    # Lookup. We don't know the partition key up front (caller only supplies
    # documentId), so try `shared` first — the cheap, common case — and fall
    # back to the caller's own user partition. Any other scope is unreachable
    # by construction: we never query `user:<other>`.
    doc: DocumentRecord | None = None
    for scope in ("shared", f"user:{user.oid}"):
        try:
            doc = await docs_repo.get(documentId, scope)
            break
        except NotFoundError:
            continue
        except cosmos_exc.CosmosHttpResponseError:
            continue

    if doc is None or not _scope_allowed(doc.scope, user.oid):
        # Same response for "doesn't exist" and "exists but not yours".
        raise NotFoundError("Document not found")

    try:
        container, blob_name = await _resolve_blob_location(doc)
    except (ValueError, NotFoundError) as exc:
        _log.warning(
            "citation_blob_resolve_failed",
            document_id=documentId,
            error=str(exc),
        )
        raise NotFoundError("Document not found") from exc

    content_type = doc.mimeType or _DEFAULT_CONTENT_TYPE
    headers = {
        "Content-Disposition": f'inline; filename="{doc.fileName}"',
        "Cache-Control": "private, max-age=0, no-store",
    }

    _log.info(
        "citation_served",
        document_id=documentId,
        scope=doc.scope,
        caller_oid=user.oid,
    )

    return StreamingResponse(
        _stream_blob(container, blob_name),
        media_type=content_type,
        headers=headers,
    )


__all__ = ["router"]
