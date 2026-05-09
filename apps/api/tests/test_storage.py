"""Tests for `apps/api/src/services/storage.py` (T038)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Provide the env-vars required by Settings before importing the module.
_REQUIRED_ENV: dict[str, str] = {
    "AZURE_TENANT_ID": "00000000-0000-0000-0000-000000000001",
    "AZURE_CLIENT_ID": "00000000-0000-0000-0000-000000000002",
    "COSMOS_ACCOUNT_ENDPOINT": "https://cos.example.documents.azure.com",
    "SEARCH_ENDPOINT": "https://srch.example.search.windows.net",
    "AOAI_ENDPOINT": "https://aoai.example.openai.azure.com",
    "AOAI_CHAT_DEPLOYMENT": "gpt-4o",
    "AOAI_EMBEDDING_DEPLOYMENT": "embed-3",
    "STORAGE_ACCOUNT_NAME": "stowned",
    "DOCINTEL_ENDPOINT": "https://di.example.cognitiveservices.azure.com",
}


@pytest.fixture(autouse=True)
def _env() -> Iterator[None]:
    saved = {k: os.environ.get(k) for k in _REQUIRED_ENV}
    os.environ.update(_REQUIRED_ENV)
    # Clear cached settings so each test sees the fixture env.
    from src import config

    config.get_settings.cache_clear()
    yield
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    config.get_settings.cache_clear()


# ---------------------------------------------------------------------------
# assert_blob_in_owned_account — invariant table
# ---------------------------------------------------------------------------


def test_assert_accepts_owned_account() -> None:
    from src.services.storage import assert_blob_in_owned_account

    assert_blob_in_owned_account(
        "https://stowned.blob.core.windows.net/user-uploads/oid/conv/doc/file.pdf"
    )


def test_assert_rejects_other_account() -> None:
    from src.services.storage import (
        InvariantViolationError,
        assert_blob_in_owned_account,
    )

    with pytest.raises(InvariantViolationError, match="platform-owned account"):
        assert_blob_in_owned_account(
            "https://attacker.blob.core.windows.net/user-uploads/x.pdf"
        )


def test_assert_rejects_http() -> None:
    from src.services.storage import (
        InvariantViolationError,
        assert_blob_in_owned_account,
    )

    with pytest.raises(InvariantViolationError, match="https"):
        assert_blob_in_owned_account(
            "http://stowned.blob.core.windows.net/user-uploads/x.pdf"
        )


def test_assert_rejects_sas_query() -> None:
    from src.services.storage import (
        InvariantViolationError,
        assert_blob_in_owned_account,
    )

    with pytest.raises(InvariantViolationError, match="SAS"):
        assert_blob_in_owned_account(
            "https://stowned.blob.core.windows.net/user-uploads/x.pdf"
            "?sv=2024-11-04&sig=ZZZZ&se=2026-01-01T00:00:00Z"
        )


def test_assert_rejects_non_blob_host() -> None:
    from src.services.storage import (
        InvariantViolationError,
        assert_blob_in_owned_account,
    )

    with pytest.raises(InvariantViolationError, match="Azure Blob endpoint"):
        assert_blob_in_owned_account("https://stowned.file.core.windows.net/share/x")


def test_assert_rejects_empty() -> None:
    from src.services.storage import (
        InvariantViolationError,
        assert_blob_in_owned_account,
    )

    with pytest.raises(InvariantViolationError):
        assert_blob_in_owned_account("")


def test_assert_rejects_missing_path() -> None:
    from src.services.storage import (
        InvariantViolationError,
        assert_blob_in_owned_account,
    )

    with pytest.raises(InvariantViolationError, match="path"):
        assert_blob_in_owned_account("https://stowned.blob.core.windows.net/")


# ---------------------------------------------------------------------------
# Container helpers
# ---------------------------------------------------------------------------


def test_default_container_names() -> None:
    from src.services import storage

    os.environ.pop("AZURE_STORAGE_CORPUS_CONTAINER", None)
    os.environ.pop("AZURE_STORAGE_USER_UPLOADS_CONTAINER", None)
    assert storage.get_corpus_container() == "shared-corpus"
    assert storage.get_user_uploads_container() == "user-uploads"


def test_container_names_overridable() -> None:
    from src.services import storage

    os.environ["AZURE_STORAGE_CORPUS_CONTAINER"] = "alt-corpus"
    os.environ["AZURE_STORAGE_USER_UPLOADS_CONTAINER"] = "alt-uploads"
    try:
        assert storage.get_corpus_container() == "alt-corpus"
        assert storage.get_user_uploads_container() == "alt-uploads"
    finally:
        os.environ.pop("AZURE_STORAGE_CORPUS_CONTAINER", None)
        os.environ.pop("AZURE_STORAGE_USER_UPLOADS_CONTAINER", None)


# ---------------------------------------------------------------------------
# upload_blob / download_blob — exercise correct container/blob routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_blob_routes_to_correct_container() -> None:
    from src.services import storage

    fake_blob = MagicMock()
    fake_blob.upload_blob = AsyncMock()
    fake_blob.url = "https://stowned.blob.core.windows.net/shared-corpus/foo.txt"

    fake_svc = MagicMock()
    fake_svc.get_blob_client = MagicMock(return_value=fake_blob)

    async def _fake_get() -> Any:
        return fake_svc

    with patch.object(storage, "get_blob_service_client", _fake_get):
        url = await storage.upload_blob(
            "shared-corpus", "foo.txt", b"hello", content_type="text/plain"
        )

    fake_svc.get_blob_client.assert_called_once_with(
        container="shared-corpus", blob="foo.txt"
    )
    fake_blob.upload_blob.assert_awaited_once()
    args, kwargs = fake_blob.upload_blob.call_args
    assert args[0] == b"hello"
    assert kwargs["overwrite"] is True
    assert kwargs["content_settings"] is not None
    assert kwargs["content_settings"].content_type == "text/plain"
    assert url.endswith("/shared-corpus/foo.txt")


@pytest.mark.asyncio
async def test_download_blob_routes_to_correct_container() -> None:
    from src.services import storage

    stream = MagicMock()
    stream.readall = AsyncMock(return_value=b"payload")

    fake_blob = MagicMock()
    fake_blob.download_blob = AsyncMock(return_value=stream)

    fake_svc = MagicMock()
    fake_svc.get_blob_client = MagicMock(return_value=fake_blob)

    async def _fake_get() -> Any:
        return fake_svc

    with patch.object(storage, "get_blob_service_client", _fake_get):
        out = await storage.download_blob("user-uploads", "oid/conv/doc/x.pdf")

    fake_svc.get_blob_client.assert_called_once_with(
        container="user-uploads", blob="oid/conv/doc/x.pdf"
    )
    assert out == b"payload"


@pytest.mark.asyncio
async def test_generate_user_delegation_sas_uses_mi_key() -> None:
    from src.services import storage

    fake_key = MagicMock()
    fake_svc = MagicMock()
    fake_svc.get_user_delegation_key = AsyncMock(return_value=fake_key)

    async def _fake_get() -> Any:
        return fake_svc

    with (
        patch.object(storage, "get_blob_service_client", _fake_get),
        patch.object(storage, "generate_blob_sas", return_value="sv=X&sig=Y") as gen,
    ):
        url = await storage.generate_user_delegation_sas_for_download(
            "oid/conv/doc/x.pdf", container="user-uploads", ttl_minutes=10
        )

    fake_svc.get_user_delegation_key.assert_awaited_once()
    gen.assert_called_once()
    kwargs = gen.call_args.kwargs
    assert kwargs["account_name"] == "stowned"
    assert kwargs["container_name"] == "user-uploads"
    assert kwargs["blob_name"] == "oid/conv/doc/x.pdf"
    assert kwargs["user_delegation_key"] is fake_key
    assert url == (
        "https://stowned.blob.core.windows.net/user-uploads/oid/conv/doc/x.pdf?sv=X&sig=Y"
    )


@pytest.mark.asyncio
async def test_sas_ttl_must_be_bounded() -> None:
    from src.services import storage

    with pytest.raises(ValueError):
        await storage.generate_user_delegation_sas_for_download("x", ttl_minutes=0)
    with pytest.raises(ValueError):
        await storage.generate_user_delegation_sas_for_download("x", ttl_minutes=120)
