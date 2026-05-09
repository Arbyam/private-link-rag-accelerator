"""Azure AI Document Intelligence wrapper (T041).

Wraps `azure.ai.documentintelligence.aio.DocumentIntelligenceClient` and
runs the `prebuilt-layout` model against blobs stored in **our own**
Storage account. Returns markdown + tables + per-page text suitable for
the ingestion pipeline (see research.md D4).

Auth: managed identity via `DefaultAzureCredential`. **No keys.**

Security:
    Before invoking DocIntel we delegate to
    `services.storage.assert_blob_in_owned_account` (T038), which
    enforces https, the platform-owned blob host, no caller-supplied
    SAS, and a non-empty container/blob path. This blocks an
    attacker-controlled URL from being analyzed by a managed-identity
    -bound DocIntel resource.
"""

from __future__ import annotations

import time
from typing import Any

from azure.ai.documentintelligence.aio import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import (
    AnalyzeDocumentRequest,
    AnalyzeResult,
    DocumentContentFormat,
)
from azure.core.exceptions import (
    ClientAuthenticationError,
    HttpResponseError,
    ServiceRequestError,
    ServiceResponseError,
)
from azure.identity.aio import DefaultAzureCredential
from pydantic import BaseModel, ConfigDict, Field

from ..config import Settings, get_settings
from ..middleware.error_handler import (
    AppError,
    UpstreamError,
    UpstreamRateLimitError,
)
from ..middleware.logging import get_logger
from .storage import assert_blob_in_owned_account

_log = get_logger(__name__)

LAYOUT_MODEL_ID = "prebuilt-layout"


class TableCell(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    row_index: int = Field(..., ge=0)
    column_index: int = Field(..., ge=0)
    row_span: int = Field(default=1, ge=1)
    column_span: int = Field(default=1, ge=1)
    text: str = ""
    kind: str | None = None  # "columnHeader", "rowHeader", "stubHead", ...


class TableData(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    page: int = Field(..., ge=1)
    row_count: int = Field(..., ge=0)
    column_count: int = Field(..., ge=0)
    cells: list[TableCell] = Field(default_factory=list)


class PageData(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    page_number: int = Field(..., ge=1)
    text: str = ""


class LayoutResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    markdown: str
    tables: list[TableData] = Field(default_factory=list)
    pages: list[PageData] = Field(default_factory=list)


class DocIntelService:
    """Thin async wrapper around `DocumentIntelligenceClient`."""

    def __init__(
        self,
        *,
        client: DocumentIntelligenceClient,
        settings: Settings,
    ) -> None:
        self._client = client
        self._settings = settings

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> DocIntelService:
        cfg = settings or get_settings()
        credential = DefaultAzureCredential()
        client = DocumentIntelligenceClient(
            endpoint=cfg.DOCINTEL_ENDPOINT,
            credential=credential,
        )
        return cls(client=client, settings=cfg)

    async def aclose(self) -> None:
        await self._client.close()

    async def analyze_layout(self, blob_url: str) -> LayoutResult:
        """Run `prebuilt-layout` against a blob in our Storage account.

        The blob URL is validated to belong to our account before any
        request is sent — preventing a spoofed URL from triggering a
        DocIntel call against attacker-supplied content.
        """
        assert_blob_in_owned_account(blob_url, settings=self._settings)

        started = time.perf_counter()
        try:
            poller = await self._client.begin_analyze_document(
                model_id=LAYOUT_MODEL_ID,
                body=AnalyzeDocumentRequest(url_source=blob_url),
                output_content_format=DocumentContentFormat.MARKDOWN,
            )
            result: AnalyzeResult = await poller.result()
        except Exception as exc:  # noqa: BLE001
            raise _translate_docintel_error(exc) from exc

        elapsed_ms = int((time.perf_counter() - started) * 1000)

        markdown = (result.content or "").strip()
        tables = _extract_tables(result)
        pages = _extract_pages(result)

        _log.info(
            "docintel.analyze_layout",
            elapsed_ms=elapsed_ms,
            page_count=len(pages),
            table_count=len(tables),
            markdown_chars=len(markdown),
        )
        return LayoutResult(markdown=markdown, tables=tables, pages=pages)


def _extract_tables(result: AnalyzeResult) -> list[TableData]:
    tables_raw: list[Any] = list(result.tables or [])
    out: list[TableData] = []
    for tbl in tables_raw:
        page_no = 1
        bounding = list(getattr(tbl, "bounding_regions", None) or [])
        if bounding:
            page_no = int(getattr(bounding[0], "page_number", 1) or 1)
        cells: list[TableCell] = []
        for cell in tbl.cells or []:
            cells.append(
                TableCell(
                    row_index=int(cell.row_index),
                    column_index=int(cell.column_index),
                    row_span=int(getattr(cell, "row_span", 1) or 1),
                    column_span=int(getattr(cell, "column_span", 1) or 1),
                    text=str(cell.content or ""),
                    kind=getattr(cell, "kind", None),
                )
            )
        out.append(
            TableData(
                page=page_no,
                row_count=int(tbl.row_count),
                column_count=int(tbl.column_count),
                cells=cells,
            )
        )
    return out


def _extract_pages(result: AnalyzeResult) -> list[PageData]:
    pages_raw: list[Any] = list(result.pages or [])
    out: list[PageData] = []
    for page in pages_raw:
        text = " ".join(line.content for line in (page.lines or []) if line.content)
        out.append(
            PageData(
                page_number=int(page.page_number),
                text=text,
            )
        )
    return out


def _translate_docintel_error(exc: BaseException) -> AppError:
    if isinstance(exc, AppError):
        return exc
    if isinstance(exc, ClientAuthenticationError):
        return UpstreamError(
            "Document Intelligence rejected managed-identity credentials",
            details={"reason": "authentication_error"},
        )
    if isinstance(exc, HttpResponseError):
        status = getattr(exc, "status_code", None)
        if status == 429:
            return UpstreamRateLimitError(
                "Document Intelligence rate limit exceeded",
                details={"reason": "rate_limit"},
            )
        return UpstreamError(
            "Document Intelligence returned an error status",
            details={"reason": "status_error", "status": status},
        )
    if isinstance(exc, ServiceRequestError | ServiceResponseError):
        return UpstreamError(
            "Document Intelligence connection failed",
            details={"reason": "connection_error"},
        )
    return UpstreamError(
        "Unexpected Document Intelligence failure",
        details={"reason": type(exc).__name__},
    )


__all__ = [
    "DocIntelService",
    "LAYOUT_MODEL_ID",
    "LayoutResult",
    "PageData",
    "TableCell",
    "TableData",
]
