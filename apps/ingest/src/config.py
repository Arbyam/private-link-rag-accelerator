"""Ingest worker runtime configuration (T067).

Mirrors the env-var surface of :mod:`apps.api.src.config` for the variables the
ingest pipeline needs. Kept intentionally minimal — full Settings parity is
deferred until the shared-lib refactor (see ``.squad/decisions/inbox/``).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated
from urllib.parse import urlparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _validate_https_url(value: str, *, field: str) -> str:
    if not value or not value.strip():
        raise ValueError(f"{field} must not be empty")
    parsed = urlparse(value)
    if parsed.scheme != "https":
        raise ValueError(
            f"{field} must be an https:// URL (got scheme={parsed.scheme!r})"
        )
    if not parsed.netloc:
        raise ValueError(f"{field} must include a host")
    return value


class IngestSettings(BaseSettings):
    """Ingest worker configuration. Loads from process environment."""

    model_config = SettingsConfigDict(
        env_file=None,
        case_sensitive=False,
        extra="ignore",
    )

    AZURE_TENANT_ID: Annotated[str, Field(min_length=1)]
    AZURE_CLIENT_ID: Annotated[str, Field(min_length=1)]

    STORAGE_ACCOUNT_NAME: Annotated[str, Field(min_length=1)]

    SEARCH_ENDPOINT: Annotated[str, Field(min_length=1)]
    SEARCH_INDEX_NAME: str = "kb-index"
    SHARED_CORPUS_INDEXER: str = "kb-indexer"

    DOCINTEL_ENDPOINT: Annotated[str, Field(min_length=1)]
    AOAI_ENDPOINT: Annotated[str, Field(min_length=1)]
    AOAI_EMBEDDING_DEPLOYMENT: str = "text-embedding-3-large"

    # Size cap for blob-triggered ingest. Default 100 MiB — admin-curated
    # shared-corpus may legitimately carry larger files than user uploads
    # (50 MiB cap, see apps/api/src/config.py::MAX_UPLOAD_BYTES). We
    # deliberately pick a separate, larger ceiling here to make the intent
    # explicit; both still satisfy data-model.md §8.
    MAX_INGEST_BLOB_BYTES: int = 104_857_600

    # Indexer-run polling
    INDEXER_POLL_TIMEOUT_SECONDS: float = 300.0
    INDEXER_POLL_INTERVAL_SECONDS: float = 5.0

    # Chunking knobs (used by the user-upload direct-push variant; see
    # IngestionPipeline._crack_and_chunk).
    CHUNK_SIZE_TOKENS: int = 800
    CHUNK_OVERLAP_TOKENS: int = 150

    @field_validator("SEARCH_ENDPOINT")
    @classmethod
    def _v_search(cls, v: str) -> str:
        return _validate_https_url(v, field="SEARCH_ENDPOINT")

    @field_validator("DOCINTEL_ENDPOINT")
    @classmethod
    def _v_docintel(cls, v: str) -> str:
        return _validate_https_url(v, field="DOCINTEL_ENDPOINT")

    @field_validator("AOAI_ENDPOINT")
    @classmethod
    def _v_aoai(cls, v: str) -> str:
        return _validate_https_url(v, field="AOAI_ENDPOINT")


@lru_cache(maxsize=1)
def get_settings() -> IngestSettings:
    return IngestSettings()  # type: ignore[call-arg]


__all__ = ["IngestSettings", "get_settings"]
