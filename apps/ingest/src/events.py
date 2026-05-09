"""CloudEvents 1.0 model for shared-corpus blob events (T066).

Validates against ``contracts/ingestion-event.schema.json``. The schema only
enumerates ``Microsoft.Storage.BlobCreated`` / ``BlobDeleted``; we additionally
accept ``Microsoft.Storage.BlobChanged`` because that is the custom type the
worker emits for re-indexing existing blobs (data-model.md §6 + tasks T070).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EventType = Literal[
    "Microsoft.Storage.BlobCreated",
    "Microsoft.Storage.BlobDeleted",
    "Microsoft.Storage.BlobChanged",
]


class CloudEventData(BaseModel):
    """Payload of a Storage blob CloudEvent."""

    model_config = ConfigDict(extra="allow")

    url: str = Field(..., min_length=1)
    contentType: str
    contentLength: int | None = Field(default=None, ge=0)
    eTag: str | None = None
    api: str | None = None


class CloudEvent(BaseModel):
    """CloudEvents 1.0 envelope as delivered by Event Grid → Storage Queue."""

    model_config = ConfigDict(extra="allow")

    specversion: Literal["1.0"]
    type: EventType
    source: str = Field(..., min_length=1)
    id: str = Field(..., min_length=1)
    time: datetime
    subject: str | None = None
    datacontenttype: str | None = None
    data: CloudEventData


__all__ = ["CloudEvent", "CloudEventData", "EventType"]
