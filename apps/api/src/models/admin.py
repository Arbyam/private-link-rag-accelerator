"""AdminStats schema (api-openapi.yaml#/components/schemas/AdminStats)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LastIngestionRun(BaseModel):
    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    id: str
    status: str
    startedAt: datetime
    completedAt: datetime | None = None


class AdminStats(BaseModel):
    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    sharedDocuments: int | None = Field(default=None, ge=0)
    sharedPassages: int | None = Field(default=None, ge=0)
    totalConversations: int | None = Field(default=None, ge=0)
    totalUsers: int | None = Field(default=None, ge=0)
    chatRequests24h: int | None = Field(default=None, ge=0)
    declineRate7d: float | None = Field(default=None, ge=0.0, le=1.0)
    lastIngestionRun: LastIngestionRun | None = None
