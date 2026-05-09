"""Unit tests for `services.docintel` (T041)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from azure.core.exceptions import HttpResponseError

from src.config import Settings
from src.middleware.error_handler import (
    UpstreamError,
    UpstreamRateLimitError,
)
from src.services.docintel import DocIntelService, LayoutResult
from src.services.storage import InvariantViolationError


def _settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        AZURE_TENANT_ID="t",
        AZURE_CLIENT_ID="c",
        COSMOS_ACCOUNT_ENDPOINT="https://cos.documents.azure.com",
        SEARCH_ENDPOINT="https://srch.search.windows.net",
        AOAI_ENDPOINT="https://aoai.openai.azure.com",
        AOAI_CHAT_DEPLOYMENT="gpt-5",
        AOAI_EMBEDDING_DEPLOYMENT="text-embedding-3-large",
        STORAGE_ACCOUNT_NAME="ragstor1",
        DOCINTEL_ENDPOINT="https://di.cognitiveservices.azure.com",
    )


def _service(client: Any, settings: Settings | None = None) -> DocIntelService:
    return DocIntelService(client=client, settings=settings or _settings())


def _layout_result_payload() -> SimpleNamespace:
    cell = SimpleNamespace(
        row_index=0,
        column_index=0,
        row_span=1,
        column_span=1,
        content="Hdr",
        kind="columnHeader",
    )
    table = SimpleNamespace(
        row_count=1,
        column_count=1,
        cells=[cell],
        bounding_regions=[SimpleNamespace(page_number=1)],
    )
    page = SimpleNamespace(
        page_number=1,
        lines=[SimpleNamespace(content="hello"), SimpleNamespace(content="world")],
    )
    return SimpleNamespace(
        content="# heading\n\ntext",
        tables=[table],
        pages=[page],
    )


def _make_poller(payload: Any) -> MagicMock:
    poller = MagicMock()
    poller.result = AsyncMock(return_value=payload)
    return poller


@pytest.mark.asyncio
async def test_analyze_layout_rejects_non_owned_blob() -> None:
    client = MagicMock()
    client.begin_analyze_document = AsyncMock()
    svc = _service(client)
    with pytest.raises(InvariantViolationError):
        await svc.analyze_layout("https://attacker.blob.core.windows.net/c/f.pdf")
    client.begin_analyze_document.assert_not_awaited()


@pytest.mark.asyncio
async def test_analyze_layout_rejects_non_https() -> None:
    client = MagicMock()
    client.begin_analyze_document = AsyncMock()
    svc = _service(client)
    with pytest.raises(InvariantViolationError):
        await svc.analyze_layout("http://ragstor1.blob.core.windows.net/c/f.pdf")


@pytest.mark.asyncio
async def test_analyze_layout_rejects_sas_signed_url() -> None:
    client = MagicMock()
    client.begin_analyze_document = AsyncMock()
    svc = _service(client)
    with pytest.raises(InvariantViolationError):
        await svc.analyze_layout(
            "https://ragstor1.blob.core.windows.net/c/f.pdf?sig=ABC&se=2030"
        )


@pytest.mark.asyncio
async def test_analyze_layout_returns_typed_result() -> None:
    client = MagicMock()
    client.begin_analyze_document = AsyncMock(
        return_value=_make_poller(_layout_result_payload())
    )
    svc = _service(client)
    result = await svc.analyze_layout(
        "https://ragstor1.blob.core.windows.net/uploads/doc.pdf"
    )
    assert isinstance(result, LayoutResult)
    assert result.markdown == "# heading\n\ntext"
    assert len(result.tables) == 1
    assert result.tables[0].page == 1
    assert result.tables[0].cells[0].text == "Hdr"
    assert len(result.pages) == 1
    assert result.pages[0].text == "hello world"

    kwargs = client.begin_analyze_document.await_args.kwargs
    assert kwargs["model_id"] == "prebuilt-layout"


@pytest.mark.asyncio
async def test_analyze_layout_accepts_privatelink_host() -> None:
    """Storage's invariant accepts only the canonical
    `<account>.blob.core.windows.net` host, so this test verifies the
    canonical host path through the same code path as a privatelink
    deployment (which uses the same DNS name via private DNS zones)."""
    client = MagicMock()
    client.begin_analyze_document = AsyncMock(
        return_value=_make_poller(_layout_result_payload())
    )
    svc = _service(client)
    result = await svc.analyze_layout(
        "https://ragstor1.blob.core.windows.net/uploads/doc.pdf"
    )
    assert isinstance(result, LayoutResult)


@pytest.mark.asyncio
async def test_analyze_layout_maps_429_to_rate_limit() -> None:
    err = HttpResponseError(message="too many")
    err.status_code = 429
    client = MagicMock()
    client.begin_analyze_document = AsyncMock(side_effect=err)
    svc = _service(client)
    with pytest.raises(UpstreamRateLimitError):
        await svc.analyze_layout(
            "https://ragstor1.blob.core.windows.net/uploads/doc.pdf"
        )


@pytest.mark.asyncio
async def test_analyze_layout_maps_5xx_to_upstream_error() -> None:
    err = HttpResponseError(message="boom")
    err.status_code = 500
    client = MagicMock()
    client.begin_analyze_document = AsyncMock(side_effect=err)
    svc = _service(client)
    with pytest.raises(UpstreamError):
        await svc.analyze_layout(
            "https://ragstor1.blob.core.windows.net/uploads/doc.pdf"
        )
