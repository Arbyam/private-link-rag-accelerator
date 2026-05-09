"""DocumentMeta schema (api-openapi.yaml#/components/schemas/DocumentMeta)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class IngestionStatus(StrEnum):
    QUEUED = "queued"
    CRACKING = "cracking"
    INDEXING = "indexing"
    INDEXED = "indexed"
    FAILED = "failed"
    SKIPPED = "skipped"


class DocumentScope(StrEnum):
    SHARED = "shared"
    USER = "user"


class DocumentIngestion(BaseModel):
    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    status: IngestionStatus
    startedAt: datetime | None = None
    completedAt: datetime | None = None
    passageCount: int | None = Field(default=None, ge=0)
    errorReason: str | None = None
    errorCode: str | None = None


class DocumentMeta(BaseModel):
    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    id: str = Field(..., min_length=1)
    scope: DocumentScope
    fileName: str = Field(..., min_length=1)
    mimeType: str = Field(..., min_length=1)
    sizeBytes: int = Field(..., ge=0)
    ingestion: DocumentIngestion
