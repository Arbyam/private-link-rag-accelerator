"""Ingest worker settings (T066).

Mirrors the env-var names used by ``apps/api/src/config.py`` so the worker
and API container share the same operator-facing surface, but is intentionally
*not* a fork — only the variables the ingest worker needs are declared, and
nothing here is shared with the API runtime.

No secrets belong here. AAD-only authentication via ``DefaultAzureCredential``
is used for every Azure dependency.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated
from urllib.parse import urlparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _validate_https_url(value: str, *, field: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"{field} must be an https:// URL with a host")
    return value


class IngestSettings(BaseSettings):
    """Runtime configuration for the ACA Job ingest worker."""

    model_config = SettingsConfigDict(
        env_file=None,
        case_sensitive=False,
        extra="ignore",
    )

    # Storage (CloudEvent queue)
    STORAGE_ACCOUNT_NAME: Annotated[str, Field(min_length=1)]
    INGESTION_QUEUE_NAME: str = "ingestion-events"

    # Cosmos (ingestion-runs + documents)
    COSMOS_ACCOUNT_ENDPOINT: Annotated[str, Field(min_length=1)]
    COSMOS_DATABASE: str = "rag"
    COSMOS_CONTAINER_INGESTION_RUNS: str = "ingestion-runs"
    COSMOS_CONTAINER_DOCUMENTS: str = "documents"

    # Azure AI Search (passages target)
    SEARCH_ENDPOINT: Annotated[str, Field(min_length=1)]
    SEARCH_INDEX_NAME: str = "kb-index"

    # Azure OpenAI (embeddings)
    AOAI_ENDPOINT: Annotated[str, Field(min_length=1)]
    AOAI_EMBEDDING_DEPLOYMENT: Annotated[str, Field(min_length=1)]

    # Document Intelligence (cracking)
    DOCINTEL_ENDPOINT: Annotated[str, Field(min_length=1)]

    # Observability
    APPLICATIONINSIGHTS_CONNECTION_STRING: str | None = None
    DEBUG: bool = False

    @field_validator("COSMOS_ACCOUNT_ENDPOINT")
    @classmethod
    def _v_cosmos(cls, v: str) -> str:
        return _validate_https_url(v, field="COSMOS_ACCOUNT_ENDPOINT")

    @field_validator("SEARCH_ENDPOINT")
    @classmethod
    def _v_search(cls, v: str) -> str:
        return _validate_https_url(v, field="SEARCH_ENDPOINT")

    @field_validator("AOAI_ENDPOINT")
    @classmethod
    def _v_aoai(cls, v: str) -> str:
        return _validate_https_url(v, field="AOAI_ENDPOINT")

    @field_validator("DOCINTEL_ENDPOINT")
    @classmethod
    def _v_docintel(cls, v: str) -> str:
        return _validate_https_url(v, field="DOCINTEL_ENDPOINT")


@lru_cache(maxsize=1)
def get_ingest_settings() -> IngestSettings:
    return IngestSettings()  # type: ignore[call-arg]
