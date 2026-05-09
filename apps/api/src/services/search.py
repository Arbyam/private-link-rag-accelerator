"""Scoped Azure AI Search wrapper — SC-011 isolation gatekeeper (T039).

This module is the **runtime gatekeeper** for tenant/user isolation in the
Private RAG Accelerator. Per `data-model.md` §5, every query against the
`kb-index` MUST carry a `scope` filter so that cross-user reads are
mathematically impossible:

    scope eq 'shared' or scope eq 'user:<callerOid>'

The wrapper enforces this in three ways:

1. The high-level methods (`search_shared`, `search_user`, `search_combined`)
   build the `scope` filter server-side from the caller's Entra `oid` —
   callers never supply `scope` themselves.
2. The escape-hatch method (`raw_search`) requires the caller to pass a
   `filter` and validates that it includes `scope eq 'shared'` or
   `scope eq 'user:<oid>'`; otherwise it raises `ScopeFilterMissingError`.
3. The bare `SearchClient.search(...)` method is **NOT** re-exported. There is
   intentionally no `.search()` method on `ScopedSearchClient`.

Any caller that needs to query `kb-index` MUST go through this wrapper.

OData-injection note
--------------------
`oid` is interpolated into an OData filter string. We therefore validate it
matches a strict UUID shape before interpolation; any deviation (including
embedded `'`) raises `ValueError`. This is defense-in-depth — Entra `oid`
claims are GUIDs by spec, but we never trust callers to pre-validate.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from azure.core.credentials_async import AsyncTokenCredential
from azure.identity.aio import DefaultAzureCredential
from azure.search.documents.aio import SearchClient

from ..config import Settings, get_settings
from ..middleware.error_handler import AppError

__all__ = [
    "ScopeFilterMissingError",
    "ScopedSearchClient",
    "SearchHit",
    "SearchResults",
]


# Strict UUID 8-4-4-4-12 hex form (matches Entra `oid` claim shape).
_OID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

# Validates that an OData filter string contains a `scope eq 'shared'` or
# `scope eq 'user:<oid>'` clause. Whitespace-tolerant. Conservative: matches
# the literal `scope eq '...'` shape only — does NOT attempt to parse arbitrary
# OData boolean algebra (`not`, parentheses, sub-expressions). Documented limit:
# a filter that hides `scope` behind `not` or arithmetic still passes this
# check; deeper analysis is intentionally out of scope because the high-level
# helpers are the supported path. `raw_search` is an escape hatch for trusted
# server code, not user input.
_SCOPE_CLAUSE_RE = re.compile(
    r"scope\s+eq\s+'(shared|user:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})'"
)


class ScopeFilterMissingError(AppError):
    """Raised when an AI Search call is attempted without a mandatory scope filter.

    This is a **server-side bug** (the API constructed an invalid query), not a
    client error — hence status 500. SC-011 isolation tests treat any reach of
    this error as a release blocker.
    """

    status_code = 500
    code = "scope_filter_missing"


@dataclass(frozen=True, slots=True)
class SearchHit:
    """One result from `kb-index`. Field set mirrors the index schema in
    `infra/search/kb-index.json`. `score` is clamped to `[0, 1]` for
    compatibility with the public `Citation` model.
    """

    id: str
    documentId: str
    scope: str
    title: str
    content: str
    score: float
    page: int
    chunkOrder: int
    userOid: str | None = None


@dataclass(frozen=True, slots=True)
class SearchResults:
    documents: list[SearchHit] = field(default_factory=list)


def _validate_oid(oid: str) -> str:
    """Reject any oid that is not a strict UUID. Defends OData interpolation."""
    if not isinstance(oid, str) or not _OID_RE.match(oid):
        raise ValueError(
            "oid must be a UUID (8-4-4-4-12 hex); refusing to interpolate untrusted value"
        )
    return oid


def _has_scope_filter(filter_expr: str) -> bool:
    return bool(_SCOPE_CLAUSE_RE.search(filter_expr))


def _combine_filters(scope_filter: str, extra: str | None) -> str:
    """AND-combine the (mandatory) scope filter with a caller-supplied extra
    filter. Scope clause is always preserved as the leading conjunct.
    """
    if extra is None or not extra.strip():
        return scope_filter
    return f"({scope_filter}) and ({extra})"


def _clamp_score(value: object) -> float:
    try:
        score = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if score < 0.0:
        return 0.0
    if score > 1.0:
        return 1.0
    return score


def _hit_from_doc(doc: dict[str, Any]) -> SearchHit:
    return SearchHit(
        id=str(doc.get("id", "")),
        documentId=str(doc.get("documentId", "")),
        scope=str(doc.get("scope", "")),
        title=str(doc.get("title", "")),
        content=str(doc.get("content", "")),
        score=_clamp_score(doc.get("@search.score", doc.get("score", 0.0))),
        page=int(doc.get("page", 0) or 0),
        chunkOrder=int(doc.get("chunkOrder", 0) or 0),
        userOid=doc.get("userOid"),
    )


_DEFAULT_SELECT: tuple[str, ...] = (
    "id",
    "documentId",
    "scope",
    "title",
    "content",
    "page",
    "chunkOrder",
)


def _build_vector_query(vector: list[float], top: int) -> Any:
    """Construct a `VectorizedQuery` against `contentVector`.

    Falls back to a dict shape if the SDK class is unavailable (defensive,
    keeps the wrapper testable in environments with older SDKs).
    """
    try:
        from azure.search.documents.models import VectorizedQuery
    except ImportError:  # pragma: no cover - sdk shape sanity
        return {
            "vector": vector,
            "k_nearest_neighbors": top,
            "fields": "contentVector",
            "kind": "vector",
        }
    return VectorizedQuery(
        vector=vector,
        k_nearest_neighbors=top,
        fields="contentVector",
    )


class ScopedSearchClient:
    """Thin wrapper around `azure.search.documents.aio.SearchClient` that
    enforces SC-011 mandatory-scope-filter for every query path.

    The wrapper deliberately **does not** expose a `.search(...)` method —
    callers must use one of `search_shared`, `search_user`, `search_combined`,
    or the validating `raw_search` escape hatch.
    """

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        credential: AsyncTokenCredential | None = None,
        client: SearchClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._owns_credential = credential is None and client is None
        self._credential: AsyncTokenCredential | None = credential
        if client is not None:
            self._client = client
        else:
            cred: AsyncTokenCredential = credential or DefaultAzureCredential()
            self._credential = cred
            self._client = SearchClient(
                endpoint=self._settings.SEARCH_ENDPOINT,
                index_name=self._settings.SEARCH_INDEX_NAME,
                credential=cred,
            )

    async def __aenter__(self) -> ScopedSearchClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.close()
        if self._owns_credential and self._credential is not None:
            close = getattr(self._credential, "close", None)
            if close is not None:
                await close()

    # ------------------------------------------------------------------
    # Public, scope-enforcing query methods.
    # ------------------------------------------------------------------

    async def search_shared(
        self,
        query: str,
        *,
        top: int = 5,
        vector: Sequence[float] | None = None,
        filter: str | None = None,
        **kwargs: Any,
    ) -> SearchResults:
        """Search shared corpus only. Filter: `scope eq 'shared'`."""
        scope_filter = "scope eq 'shared'"
        return await self._dispatch(
            query=query,
            filter_expr=_combine_filters(scope_filter, filter),
            top=top,
            vector=vector,
            kwargs=kwargs,
        )

    async def search_user(
        self,
        query: str,
        *,
        oid: str,
        top: int = 5,
        vector: Sequence[float] | None = None,
        filter: str | None = None,
        **kwargs: Any,
    ) -> SearchResults:
        """Search the calling user's private corpus only.

        Filter: `scope eq 'user:<oid>'`. `oid` MUST be a UUID; otherwise
        `ValueError` is raised before any string interpolation.
        """
        safe_oid = _validate_oid(oid)
        scope_filter = f"scope eq 'user:{safe_oid}'"
        return await self._dispatch(
            query=query,
            filter_expr=_combine_filters(scope_filter, filter),
            top=top,
            vector=vector,
            kwargs=kwargs,
        )

    async def search_combined(
        self,
        query: str,
        *,
        oid: str,
        top: int = 5,
        vector: Sequence[float] | None = None,
        filter: str | None = None,
        **kwargs: Any,
    ) -> SearchResults:
        """Search shared corpus + calling user's private corpus.

        Filter: `(scope eq 'shared' or scope eq 'user:<oid>')`.

        This is the default path for chat retrieval (FR-006/SC-011).
        """
        safe_oid = _validate_oid(oid)
        scope_filter = f"(scope eq 'shared' or scope eq 'user:{safe_oid}')"
        return await self._dispatch(
            query=query,
            filter_expr=_combine_filters(scope_filter, filter),
            top=top,
            vector=vector,
            kwargs=kwargs,
        )

    async def raw_search(
        self,
        *,
        filter: str,
        query: str = "*",
        top: int = 5,
        vector: Sequence[float] | None = None,
        **kwargs: Any,
    ) -> SearchResults:
        """Escape hatch for trusted server code (e.g., admin purge flows).

        The supplied `filter` is validated to contain at least one
        `scope eq 'shared'` or `scope eq 'user:<oid>'` clause; otherwise
        `ScopeFilterMissingError` is raised. See module docstring for the
        documented parsing limits of this check — the high-level helpers are
        the supported path for any caller that handles untrusted input.
        """
        if not isinstance(filter, str) or not _has_scope_filter(filter):
            raise ScopeFilterMissingError(
                "AI Search query missing required scope filter "
                "(must contain `scope eq 'shared'` or `scope eq 'user:<oid>'`)",
                details={"filter": filter if isinstance(filter, str) else None},
            )
        return await self._dispatch(
            query=query,
            filter_expr=filter,
            top=top,
            vector=vector,
            kwargs=kwargs,
        )

    # ------------------------------------------------------------------
    # Internals.
    # ------------------------------------------------------------------

    async def _dispatch(
        self,
        *,
        query: str,
        filter_expr: str,
        top: int,
        vector: Sequence[float] | None,
        kwargs: dict[str, Any],
    ) -> SearchResults:
        # Defense-in-depth: even after we built the filter ourselves, re-check
        # before handing to the SDK. Catches refactor mistakes.
        if not _has_scope_filter(filter_expr):
            raise ScopeFilterMissingError(
                "Internal error: dispatched query without scope clause",
                details={"filter": filter_expr},
            )

        call_kwargs: dict[str, Any] = {
            "search_text": query,
            "filter": filter_expr,
            "top": top,
            "select": list(kwargs.pop("select", _DEFAULT_SELECT)),
        }

        # Hybrid / vector search support. Callers pass either a raw `vector`
        # (which we wrap as a single VectorizedQuery against `contentVector`)
        # or fully-formed `vector_queries` via kwargs.
        if vector is not None and "vector_queries" not in kwargs:
            call_kwargs["vector_queries"] = [_build_vector_query(list(vector), top)]

        call_kwargs.update(kwargs)

        result_iter = await self._client.search(**call_kwargs)
        hits: list[SearchHit] = []
        async for doc in result_iter:
            hits.append(_hit_from_doc(dict(doc)))
        return SearchResults(documents=hits)
