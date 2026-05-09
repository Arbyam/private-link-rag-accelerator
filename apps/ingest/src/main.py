"""Container Apps Job entrypoint — single CloudEvent processor (T066).

This module is the ``CMD`` of the ingest worker image (see ``Dockerfile``).

KEDA scales the ACA Job per Storage Queue message (``ingestion-events``).
Each invocation:

  1. Pulls *one* message from the queue (visibility timeout = 5 min).
  2. Validates it as a CloudEvents 1.0 envelope matching
     ``contracts/ingestion-event.schema.json``.
  3. Writes a ``running`` lifecycle record to Cosmos ``ingestion-runs``
     (data-model.md §4) with ``trigger="eventgrid"`` (the schema's
     event-driven trigger value; the manual reindex path in T070 will
     use ``trigger="manual"``).
  4. Dispatches to ``handlers.shared.handle_blob_event`` (T068) for the
     actual blob create / change / delete handling. The handler returns
     a ``RunOutcome`` describing the terminal status of the work.
  5. Marks the run ``completed`` when the outcome is succeeded/skipped,
     ``failed`` on outcome ``failed`` *or* on any uncaught exception.
     Successful messages are deleted from the queue; failed messages are
     left visible so KEDA's retry / dead-letter machinery takes over.
  6. Exits ``0`` on success or no-op (empty queue / poison message
     dropped); exits ``1`` on processing failure so the ACA Job
     execution shows as failed in the portal.

This is the one-shot pattern: never loop, never sleep — let KEDA decide
when to scale us up again.

Note on the pipeline construction: T067 currently ships only a
``Protocol`` for :class:`~src.pipeline.IngestionPipeline`; the concrete
implementation lands in a follow-up. Until then ``main.py`` wires a
:class:`_NoopPipeline` that returns ``skipped`` ``RunOutcome``\\ s. The
worker's plumbing — queue I/O, validation, lifecycle records, error
trapping — is fully exercised regardless. Replace ``_NoopPipeline`` with
the concrete ``IngestionPipeline`` from T067 when it merges.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any
from uuid import uuid4

from azure.identity.aio import DefaultAzureCredential
from azure.storage.queue.aio import QueueClient
from pydantic import ValidationError

from .config import IngestSettings, get_ingest_settings
from .events import CloudEvent
from .logging_setup import configure_logging, get_logger
from .pipeline import IngestionPipeline, RunOutcome
from .runs import IngestionRunsClient, SharedDocumentsClient

_log = get_logger(__name__)

_SHARED_SCOPE = "shared"
_QUEUE_VISIBILITY_TIMEOUT_S = 300


def _new_run_id() -> str:
    return f"r_{uuid4().hex[:26]}"


class _NoopPipeline:
    """Placeholder pipeline used until T067 ships the concrete impl.

    Implements :class:`IngestionPipeline` (Protocol). Every method
    returns a ``skipped`` :class:`RunOutcome` so the rest of the worker
    plumbing (validation, run records, queue ack) can still be exercised
    end-to-end and in tests.
    """

    async def process_blob_created(self, blob_url: str, document_id: str) -> RunOutcome:
        return RunOutcome(
            status="skipped",
            document_id=document_id,
            event_type="Microsoft.Storage.BlobCreated",
            message="pipeline not yet implemented (T067)",
        )

    async def process_blob_changed(self, blob_url: str, document_id: str) -> RunOutcome:
        return RunOutcome(
            status="skipped",
            document_id=document_id,
            event_type="Microsoft.Storage.BlobChanged",
            message="pipeline not yet implemented (T067)",
        )

    async def process_blob_deleted(self, document_id: str) -> RunOutcome:
        return RunOutcome(
            status="skipped",
            document_id=document_id,
            event_type="Microsoft.Storage.BlobDeleted",
            message="pipeline not yet implemented (T067)",
        )


def _build_pipeline(_settings: IngestSettings) -> IngestionPipeline:
    """Construct the pipeline. T067 will swap this for the real one."""
    # TODO(T067): replace with the concrete IngestionPipeline once it ships.
    return _NoopPipeline()


async def _receive_one(queue: QueueClient) -> Any | None:
    """Pop one message from the queue or return ``None`` if empty.

    Uses ``messages_per_page=1`` plus ``max_messages=1`` so the underlying
    REST call asks for exactly one message. We iterate at most once.
    """
    pager = queue.receive_messages(
        messages_per_page=1,
        max_messages=1,
        visibility_timeout=_QUEUE_VISIBILITY_TIMEOUT_S,
    )
    async for msg in pager:
        return msg
    return None


def _decode_message_content(raw: Any) -> Any:
    """Storage Queue messages are usually JSON text but can be bytes."""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    if isinstance(raw, str):
        return json.loads(raw)
    return raw


async def _run() -> int:
    settings = get_ingest_settings()
    configure_logging(debug=settings.DEBUG)

    credential = DefaultAzureCredential()
    queue = QueueClient(
        account_url=f"https://{settings.STORAGE_ACCOUNT_NAME}.queue.core.windows.net",
        queue_name=settings.INGESTION_QUEUE_NAME,
        credential=credential,
    )
    runs = IngestionRunsClient(settings, credential=credential)
    docs = SharedDocumentsClient(settings, credential=credential)

    # Late import: keeps the module-level import graph free of optional deps
    # introduced by T068 and lets unit tests monkey-patch the dispatcher.
    from .handlers.shared import Repos, handle_blob_event

    exit_code = 0
    try:
        msg = await _receive_one(queue)
        if msg is None:
            _log.info("ingest_no_message", queue=settings.INGESTION_QUEUE_NAME)
            return 0

        message_id = getattr(msg, "id", None)
        try:
            payload = _decode_message_content(msg.content)
            event = CloudEvent.model_validate(payload)
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            _log.error("ingest_invalid_event", message_id=message_id, error=str(exc))
            # Drop poison: leaving it visible would just loop forever.
            await queue.delete_message(msg)
            return 0

        run_id = _new_run_id()
        await runs.start(run_id=run_id, scope=_SHARED_SCOPE, trigger="eventgrid")
        _log.info(
            "ingest_run_started",
            run_id=run_id,
            event_type=event.type,
            event_id=event.id,
            subject=event.subject,
        )

        pipeline = _build_pipeline(settings)
        repos = Repos(docs_repo=docs, runs_repo=runs)

        try:
            outcome = await handle_blob_event(
                event.model_dump(mode="json"), pipeline, repos
            )
        except Exception as exc:  # noqa: BLE001 — boundary trap, see module docs
            _log.exception(
                "ingest_run_uncaught",
                run_id=run_id,
                event_type=event.type,
                event_id=event.id,
            )
            await runs.complete(
                run_id,
                _SHARED_SCOPE,
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
            )
            # Leave the queue message visible so KEDA's retry / dead-letter
            # path can pick it up; do NOT delete on failure.
            return 1

        if outcome.status == "failed":
            _log.warning(
                "ingest_run_failed",
                run_id=run_id,
                event_type=event.type,
                document_id=outcome.document_id,
                outcome_message=outcome.message,
            )
            await runs.complete(
                run_id,
                _SHARED_SCOPE,
                status="failed",
                error=outcome.message,
                per_document=[
                    {
                        "documentId": outcome.document_id,
                        "outcome": "failed",
                        "eventType": outcome.event_type,
                    }
                ],
            )
            exit_code = 1
        else:
            await runs.complete(
                run_id,
                _SHARED_SCOPE,
                status="completed",
                per_document=[
                    {
                        "documentId": outcome.document_id,
                        "outcome": outcome.status,
                        "eventType": outcome.event_type,
                    }
                ],
            )
            await queue.delete_message(msg)
            _log.info(
                "ingest_run_completed",
                run_id=run_id,
                event_type=event.type,
                document_id=outcome.document_id,
                outcome=outcome.status,
            )
    finally:
        await queue.close()
        await runs.close()
        await docs.close()

    return exit_code


def main() -> int:
    """Synchronous entrypoint — the ``Dockerfile`` ``CMD`` calls this."""
    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())
