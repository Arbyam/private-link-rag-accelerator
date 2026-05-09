"""Ingestion pipeline interface (T067 placeholder).

This module is **owned by T067**. T068 only ships the minimal interface
surface required to import :class:`IngestionPipeline` and
:class:`RunOutcome` so the shared-corpus event handler in
``handlers/shared.py`` can be implemented and tested independently.

When T067 lands, it will replace this file with the concrete pipeline
implementation. The public interface (method names, signatures, return
type) declared here is the contract handlers depend on; T067 must keep
it backward-compatible.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

RunStatus = Literal["succeeded", "failed", "skipped"]


@dataclass(frozen=True)
class RunOutcome:
    """Outcome of processing a single ingestion event.

    Attributes:
        status: Terminal status of the run.
        document_id: Deterministic document id derived from the blob URL
            (also the Cosmos ``documents`` partition key).
        event_type: CloudEvent ``type`` that produced this outcome.
        message: Optional human-readable detail (error message when
            ``status == "failed"``; reason when ``status == "skipped"``).
    """

    status: RunStatus
    document_id: str
    event_type: str
    message: str | None = None


class IngestionPipeline(Protocol):
    """Pipeline contract consumed by event handlers.

    Concrete implementation lives in T067. Handlers depend only on this
    Protocol so they can be unit-tested with a fake.
    """

    async def process_blob_created(
        self, blob_url: str, document_id: str
    ) -> RunOutcome: ...

    async def process_blob_changed(
        self, blob_url: str, document_id: str
    ) -> RunOutcome: ...

    async def process_blob_deleted(self, document_id: str) -> RunOutcome: ...
