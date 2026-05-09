"""Event handler for the ``shared-corpus`` blob container (T068).

This handler dispatches CloudEvents matching
``contracts/ingestion-event.schema.json`` to the
:class:`~src.pipeline.IngestionPipeline`. Three event types are
recognized:

* ``Microsoft.Storage.BlobCreated`` — a new blob was uploaded; pipeline
  performs full extract → chunk → embed → index.
* ``Microsoft.Storage.BlobChanged`` — a custom event we emit when a
  re-upload of an existing blob is detected; pipeline re-indexes.
* ``Microsoft.Storage.BlobDeleted`` — pipeline removes any
  ``documentId``-scoped chunks from the search index, and we then drop
  the corresponding row from Cosmos ``documents``.

The handler is the **single boundary** between the eventing layer and
the pipeline; it owns:

* container routing — events for any container other than
  ``shared-corpus`` raise :class:`UnsupportedContainerError`;
* deterministic ``documentId`` derivation from the full blob URL;
* exception trapping — every dispatched call returns a
  :class:`~src.pipeline.RunOutcome` (never raises) so the worker loop
  can persist a run record and ack/nack the queue message uniformly.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlparse

from ..pipeline import IngestionPipeline, RunOutcome

logger = logging.getLogger(__name__)


SHARED_CORPUS_CONTAINER = "shared-corpus"
DOCUMENT_ID_HEX_LENGTH = 16

EVENT_BLOB_CREATED = "Microsoft.Storage.BlobCreated"
EVENT_BLOB_CHANGED = "Microsoft.Storage.BlobChanged"
EVENT_BLOB_DELETED = "Microsoft.Storage.BlobDeleted"


# A CloudEvent is consumed as a plain mapping (validated upstream against
# ingestion-event.schema.json). Using a dict alias avoids a hard
# dependency on the ``cloudevents`` SDK at this seam.
CloudEvent = dict[str, Any]


class UnsupportedContainerError(ValueError):
    """Raised when an event targets a container this handler does not own."""


class _DocumentsRepo(Protocol):
    async def delete(self, document_id: str) -> None: ...


class _IngestionRunsRepo(Protocol):
    # Reserved for future per-run persistence; kept on the bundle so the
    # worker can pass a single ``Repos`` to every handler.
    ...


@dataclass(frozen=True)
class Repos:
    """Bundle of Cosmos repositories handlers may need.

    Attributes:
        docs_repo: Repository for the ``documents`` container; used to
            remove a row on ``BlobDeleted``.
        runs_repo: Repository for the ``ingestion-runs`` container.
            Currently passed through to keep a stable handler signature.
    """

    docs_repo: _DocumentsRepo
    runs_repo: _IngestionRunsRepo


def derive_document_id(blob_url: str) -> str:
    """Compute a deterministic document id from a blob URL.

    The id is the first :data:`DOCUMENT_ID_HEX_LENGTH` hex characters of
    SHA-256 over the canonical form of the blob URL (scheme + host +
    path, query stripped). Using the URL — rather than just the blob
    path — keeps the id stable across re-uploads to the same path while
    avoiding collisions if the storage account or container is ever
    renamed.

    The output also doubles as the Cosmos ``documents`` partition key.
    """

    parsed = urlparse(blob_url)
    canonical = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return digest[:DOCUMENT_ID_HEX_LENGTH]


def _extract_blob_url(event: CloudEvent) -> str:
    data = event.get("data") or {}
    url = data.get("url")
    if not isinstance(url, str) or not url:
        raise ValueError("CloudEvent.data.url is missing or not a string")
    return url


def _container_from_url(blob_url: str) -> str:
    """Parse the container name from a blob URL.

    Storage blob URLs follow
    ``https://<account>.blob.core.windows.net/<container>/<path>``.
    """

    path = urlparse(blob_url).path.lstrip("/")
    container, _, _ = path.partition("/")
    if not container:
        raise ValueError(f"Could not extract container from blob URL: {blob_url!r}")
    return container


async def handle_blob_event(
    event: CloudEvent,
    pipeline: IngestionPipeline,
    repos: Repos,
) -> RunOutcome:
    """Dispatch a validated CloudEvent to the ingestion pipeline.

    The caller is expected to have validated ``event`` against
    ``contracts/ingestion-event.schema.json``. This function:

    1. extracts the blob URL and container,
    2. rejects events for containers other than ``shared-corpus``
       with :class:`UnsupportedContainerError`,
    3. derives a deterministic ``document_id`` (see
       :func:`derive_document_id`),
    4. dispatches on ``event["type"]``,
    5. wraps any pipeline / repo exception into a ``failed``
       :class:`RunOutcome`.

    For ``BlobDeleted`` the pipeline is invoked **first** to issue the
    delete-by-filter against ``kb-index`` (``documentId eq '<id>'``);
    only if that succeeds is the Cosmos ``documents`` row removed.
    Doing it in this order avoids leaving stale chunks in the search
    index while the metadata row is gone.
    """

    event_type = event.get("type", "")
    blob_url = _extract_blob_url(event)
    container = _container_from_url(blob_url)

    if container != SHARED_CORPUS_CONTAINER:
        raise UnsupportedContainerError(
            f"shared-corpus handler received event for container {container!r}; "
            f"expected {SHARED_CORPUS_CONTAINER!r}"
        )

    document_id = derive_document_id(blob_url)
    logger.info(
        "shared-corpus event received",
        extra={
            "event_type": event_type,
            "document_id": document_id,
            "blob_url": blob_url,
        },
    )

    try:
        if event_type == EVENT_BLOB_CREATED:
            return await pipeline.process_blob_created(blob_url, document_id)
        if event_type == EVENT_BLOB_CHANGED:
            return await pipeline.process_blob_changed(blob_url, document_id)
        if event_type == EVENT_BLOB_DELETED:
            outcome = await pipeline.process_blob_deleted(document_id)
            await repos.docs_repo.delete(document_id)
            return outcome
    except Exception as exc:  # noqa: BLE001 - boundary trap, see docstring
        logger.exception(
            "shared-corpus handler failed",
            extra={"event_type": event_type, "document_id": document_id},
        )
        return RunOutcome(
            status="failed",
            document_id=document_id,
            event_type=event_type,
            message=str(exc),
        )

    return RunOutcome(
        status="skipped",
        document_id=document_id,
        event_type=event_type,
        message=f"unhandled event type: {event_type!r}",
    )
