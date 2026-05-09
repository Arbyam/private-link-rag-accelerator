"""Tests for `services/search.py` — SC-011 isolation guarantee (T039).

Each test maps to an attack vector documented in the PR description's
threat-model coverage table.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.services.search import (
    ScopedSearchClient,
    ScopeFilterMissingError,
    SearchResults,
)

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class _AsyncDocIter:
    """Minimal async iterator that yields a fixed list of dict documents,
    mirroring the shape of `azure.search.documents.aio.AsyncSearchItemPaged`.
    """

    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs

    def __aiter__(self) -> _AsyncDocIter:
        self._i = 0
        return self

    async def __anext__(self) -> dict[str, Any]:
        if self._i >= len(self._docs):
            raise StopAsyncIteration
        doc = self._docs[self._i]
        self._i += 1
        return doc


def _fake_client(docs: list[dict[str, Any]] | None = None) -> MagicMock:
    """Return a MagicMock that quacks like SearchClient for our purposes."""
    client = MagicMock(name="SearchClient")
    client.search = AsyncMock(return_value=_AsyncDocIter(docs or []))
    client.close = AsyncMock(return_value=None)
    return client


def _wrapper(client: MagicMock) -> ScopedSearchClient:
    # Bypass DefaultAzureCredential — inject the fake client directly.
    return ScopedSearchClient.__new__(ScopedSearchClient)._init_for_test(client)  # type: ignore[attr-defined]


# Monkey-patch a tiny helper so tests don't need real Settings/credentials.
def _init_for_test(self: ScopedSearchClient, client: MagicMock) -> ScopedSearchClient:
    self._settings = None  # type: ignore[assignment]
    self._owns_credential = False
    self._credential = None
    self._client = client  # type: ignore[assignment]
    return self


ScopedSearchClient._init_for_test = _init_for_test  # type: ignore[attr-defined]


def _last_filter(client: MagicMock) -> str:
    assert client.search.await_count >= 1
    kwargs = client.search.await_args.kwargs
    return kwargs["filter"]


def _last_kwargs(client: MagicMock) -> dict[str, Any]:
    return client.search.await_args.kwargs


# ---------------------------------------------------------------------------
# Tests (1)..(9) per task spec.
# ---------------------------------------------------------------------------


# (1) search_shared injects `scope eq 'shared'` filter.
@pytest.mark.asyncio
async def test_search_shared_injects_shared_scope_filter() -> None:
    client = _fake_client()
    sut = _wrapper(client)

    result = await sut.search_shared("hello", top=3)

    assert isinstance(result, SearchResults)
    flt = _last_filter(client)
    assert "scope eq 'shared'" in flt
    assert "user:" not in flt


# (2) search_user injects `scope eq 'user:<oid>'` filter.
@pytest.mark.asyncio
async def test_search_user_injects_user_scope_filter() -> None:
    client = _fake_client()
    sut = _wrapper(client)
    oid = "11111111-2222-3333-4444-555555555555"

    await sut.search_user("hello", oid=oid)

    flt = _last_filter(client)
    assert f"scope eq 'user:{oid}'" in flt
    assert "shared" not in flt


# (3) search_combined injects OR'd shared+user filter.
@pytest.mark.asyncio
async def test_search_combined_injects_or_filter() -> None:
    client = _fake_client()
    sut = _wrapper(client)
    oid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    await sut.search_combined("hello", oid=oid)

    flt = _last_filter(client)
    assert "scope eq 'shared'" in flt
    assert f"scope eq 'user:{oid}'" in flt
    assert " or " in flt


# (4) raw_search without scope filter raises ScopeFilterMissingError.
@pytest.mark.asyncio
async def test_raw_search_rejects_filter_without_scope() -> None:
    client = _fake_client()
    sut = _wrapper(client)

    with pytest.raises(ScopeFilterMissingError):
        await sut.raw_search(filter="title eq 'foo'")

    client.search.assert_not_called()


# (5) raw_search with `scope eq 'shared'` succeeds.
@pytest.mark.asyncio
async def test_raw_search_accepts_shared_scope() -> None:
    client = _fake_client()
    sut = _wrapper(client)

    await sut.raw_search(filter="scope eq 'shared'")

    flt = _last_filter(client)
    assert flt == "scope eq 'shared'"


# (6) raw_search with `scope eq 'user:<oid>'` succeeds.
@pytest.mark.asyncio
async def test_raw_search_accepts_user_scope() -> None:
    client = _fake_client()
    sut = _wrapper(client)
    oid = "12345678-1234-1234-1234-123456789abc"

    await sut.raw_search(filter=f"scope eq 'user:{oid}'")

    flt = _last_filter(client)
    assert flt == f"scope eq 'user:{oid}'"


# (7) search_user with OData-injection oid raises ValueError.
@pytest.mark.asyncio
async def test_search_user_rejects_odata_injection_in_oid() -> None:
    client = _fake_client()
    sut = _wrapper(client)

    with pytest.raises(ValueError):
        await sut.search_user("hello", oid="abc' or 1 eq 1 or 'x' eq '")

    client.search.assert_not_called()


# (8) Caller-supplied extra filter is AND-combined; scope filter is preserved.
@pytest.mark.asyncio
async def test_extra_filter_is_and_combined_with_scope() -> None:
    client = _fake_client()
    sut = _wrapper(client)
    oid = "00000000-1111-2222-3333-444444444444"

    await sut.search_combined("hello", oid=oid, filter="page lt 10")

    flt = _last_filter(client)
    assert "scope eq 'shared'" in flt
    assert f"scope eq 'user:{oid}'" in flt
    assert "page lt 10" in flt
    assert " and " in flt


# (9) Vector query passthrough — `vector` arg becomes a `vector_queries` entry.
@pytest.mark.asyncio
async def test_vector_query_passthrough() -> None:
    client = _fake_client()
    sut = _wrapper(client)
    embedding = [0.1, 0.2, 0.3]

    await sut.search_shared("hello", top=4, vector=embedding)

    kwargs = _last_kwargs(client)
    assert "vector_queries" in kwargs
    vqs = kwargs["vector_queries"]
    assert len(vqs) == 1
    vq = vqs[0]
    # SDK's VectorizedQuery exposes attrs; dict fallback exposes keys.
    vector_payload = getattr(vq, "vector", None) or vq["vector"]
    fields_payload = getattr(vq, "fields", None) or vq["fields"]
    assert list(vector_payload) == embedding
    assert fields_payload == "contentVector"


# Bonus assertion: `ScopedSearchClient` does NOT expose a `.search()` method
# that would bypass the wrapper. Listed separately because the task says
# "MUST NOT expose the bare SearchClient.search()".
def test_wrapper_does_not_expose_bare_search_method() -> None:
    assert not hasattr(ScopedSearchClient, "search"), (
        "ScopedSearchClient must NOT expose a `.search()` method — "
        "callers MUST use search_shared / search_user / search_combined / raw_search"
    )
