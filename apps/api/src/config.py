"""Application settings (T033).

All values are loaded from environment variables. **No secrets** belong here —
secrets MUST be retrieved at runtime from Key Vault via managed identity.

Field names match the env-var names verbatim (case-insensitive lookup).
See specs/001-private-rag-accelerator/tasks.md T033 for the canonical list.
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
        raise ValueError(f"{field} must be an https:// URL (got scheme={parsed.scheme!r})")
    if not parsed.netloc:
        raise ValueError(f"{field} must include a host")
    return value


class Settings(BaseSettings):
    """RAG API runtime configuration.

    Pydantic Settings v2. Reads from process environment; case-insensitive.
    """

    model_config = SettingsConfigDict(
        env_file=None,
        case_sensitive=False,
        extra="ignore",
    )

    # Identity / Entra
    AZURE_TENANT_ID: Annotated[str, Field(min_length=1)]
    AZURE_CLIENT_ID: Annotated[str, Field(min_length=1)]

    # Cosmos DB
    COSMOS_ACCOUNT_ENDPOINT: Annotated[str, Field(min_length=1)]

    # Azure AI Search
    SEARCH_ENDPOINT: Annotated[str, Field(min_length=1)]
    SEARCH_INDEX_NAME: str = "kb-index"

    # Azure OpenAI
    AOAI_ENDPOINT: Annotated[str, Field(min_length=1)]
    AOAI_CHAT_DEPLOYMENT: Annotated[str, Field(min_length=1)]
    AOAI_EMBEDDING_DEPLOYMENT: Annotated[str, Field(min_length=1)]

    # Storage
    STORAGE_ACCOUNT_NAME: Annotated[str, Field(min_length=1)]

    # Document Intelligence
    DOCINTEL_ENDPOINT: Annotated[str, Field(min_length=1)]

    # Authorization groups
    ADMIN_GROUP_OBJECT_ID: str | None = None
    ALLOWED_USER_GROUP_OBJECT_IDS: list[str] = Field(default_factory=list)

    # Upload sizing
    MAX_UPLOAD_BYTES: int = 52_428_800  # 50 MiB
    CONVO_CAP_BYTES: int = 262_144_000  # 250 MiB

    # Optional / well-known
    APPLICATIONINSIGHTS_CONNECTION_STRING: str | None = None
    DEBUG: bool = False

    @field_validator("ALLOWED_USER_GROUP_OBJECT_IDS", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        if v is None or v == "":
            return []
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

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
def get_settings() -> Settings:
    """Singleton accessor for FastAPI dependency injection."""
    return Settings()  # type: ignore[call-arg]
