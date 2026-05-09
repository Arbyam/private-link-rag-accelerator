"""Unit tests for `services.llm` (T040).

Mocks the `AsyncAzureOpenAI` client — no network or Azure access.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from openai import APIStatusError, AuthenticationError, RateLimitError

from src.middleware.error_handler import UpstreamError, UpstreamRateLimitError
from src.models.chat import ChatMessage, ChatRole
from src.services.llm import EMBEDDING_DIMENSIONS, LLMService


def _make_service(client: Any) -> LLMService:
    return LLMService(
        client=client,
        chat_deployment="gpt-5",
        embedding_deployment="text-embedding-3-large",
    )


def _completion(content: str = "hello", finish_reason: str = "stop") -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content),
                finish_reason=finish_reason,
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
        ),
        model="gpt-5",
    )


def _fake_response() -> httpx.Response:
    return httpx.Response(status_code=429, request=httpx.Request("POST", "https://x"))


@pytest.mark.asyncio
async def test_chat_completion_uses_chat_deployment() -> None:
    create = AsyncMock(return_value=_completion("hi there"))
    client = MagicMock()
    client.chat.completions.create = create

    svc = _make_service(client)
    resp = await svc.chat_completion(
        [ChatMessage(role=ChatRole.USER, content="ping")],
        temperature=0.1,
        max_tokens=64,
    )

    assert resp.content == "hi there"
    assert resp.finish_reason == "stop"
    assert resp.usage is not None
    assert resp.usage.total_tokens == 30

    kwargs = create.await_args.kwargs
    assert kwargs["model"] == "gpt-5"
    assert kwargs["temperature"] == 0.1
    assert kwargs["max_tokens"] == 64
    assert kwargs["stream"] is False
    assert kwargs["messages"] == [{"role": "user", "content": "ping"}]


@pytest.mark.asyncio
async def test_chat_completion_maps_rate_limit_to_429() -> None:
    create = AsyncMock(
        side_effect=RateLimitError(
            "slow down", response=_fake_response(), body=None
        )
    )
    client = MagicMock()
    client.chat.completions.create = create

    svc = _make_service(client)
    with pytest.raises(UpstreamRateLimitError) as ei:
        await svc.chat_completion([ChatMessage(role=ChatRole.USER, content="x")])
    assert ei.value.status_code == 429


@pytest.mark.asyncio
async def test_chat_completion_maps_auth_to_503() -> None:
    create = AsyncMock(
        side_effect=AuthenticationError(
            "no token",
            response=httpx.Response(
                status_code=401, request=httpx.Request("POST", "https://x")
            ),
            body=None,
        )
    )
    client = MagicMock()
    client.chat.completions.create = create

    svc = _make_service(client)
    with pytest.raises(UpstreamError) as ei:
        await svc.chat_completion([ChatMessage(role=ChatRole.USER, content="x")])
    assert ei.value.status_code == 503


@pytest.mark.asyncio
async def test_chat_stream_yields_deltas_then_done() -> None:
    async def _stream():  # type: ignore[no-untyped-def]
        for piece in ("hel", "lo"):
            yield SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content=piece), finish_reason=None
                    )
                ]
            )
        yield SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content=""), finish_reason="stop"
                )
            ]
        )

    create = AsyncMock(return_value=_stream())
    client = MagicMock()
    client.chat.completions.create = create

    svc = _make_service(client)
    events = [
        e async for e in svc.chat_stream([ChatMessage(role=ChatRole.USER, content="hi")])
    ]
    types = [e.type for e in events]
    assert types == ["delta", "delta", "done"]
    assert events[0].data == {"text": "hel"}
    assert events[1].data == {"text": "lo"}
    assert events[2].data == {"finish_reason": "stop"}

    assert create.await_args.kwargs["stream"] is True


@pytest.mark.asyncio
async def test_chat_stream_emits_error_event_on_failure() -> None:
    create = AsyncMock(
        side_effect=APIStatusError(
            "boom",
            response=httpx.Response(
                status_code=500, request=httpx.Request("POST", "https://x")
            ),
            body=None,
        )
    )
    client = MagicMock()
    client.chat.completions.create = create

    svc = _make_service(client)
    events = [
        e async for e in svc.chat_stream([ChatMessage(role=ChatRole.USER, content="x")])
    ]
    assert len(events) == 1
    assert events[0].type == "error"
    assert events[0].data["code"] == "service_unavailable"


@pytest.mark.asyncio
async def test_embed_returns_vectors_and_validates_dimension() -> None:
    vec = [0.0] * EMBEDDING_DIMENSIONS
    response = SimpleNamespace(
        data=[SimpleNamespace(embedding=vec), SimpleNamespace(embedding=vec)],
        usage=SimpleNamespace(prompt_tokens=4),
    )
    create = AsyncMock(return_value=response)
    client = MagicMock()
    client.embeddings.create = create

    svc = _make_service(client)
    out = await svc.embed(["a", "b"])

    assert len(out) == 2
    assert all(len(v) == EMBEDDING_DIMENSIONS for v in out)
    kwargs = create.await_args.kwargs
    assert kwargs["model"] == "text-embedding-3-large"
    assert kwargs["input"] == ["a", "b"]


@pytest.mark.asyncio
async def test_embed_rejects_wrong_dimension() -> None:
    bad_response = SimpleNamespace(
        data=[SimpleNamespace(embedding=[0.0, 0.0, 0.0])],
        usage=SimpleNamespace(prompt_tokens=1),
    )
    create = AsyncMock(return_value=bad_response)
    client = MagicMock()
    client.embeddings.create = create

    svc = _make_service(client)
    with pytest.raises(UpstreamError):
        await svc.embed(["x"])


@pytest.mark.asyncio
async def test_embed_truncates_long_input() -> None:
    vec = [0.0] * EMBEDDING_DIMENSIONS
    response = SimpleNamespace(
        data=[SimpleNamespace(embedding=vec)],
        usage=SimpleNamespace(prompt_tokens=1),
    )
    create = AsyncMock(return_value=response)
    client = MagicMock()
    client.embeddings.create = create

    svc = _make_service(client)
    big = "x" * 100_000
    await svc.embed([big])
    sent = create.await_args.kwargs["input"][0]
    assert len(sent) <= 28_000


@pytest.mark.asyncio
async def test_embed_empty_returns_empty() -> None:
    client = MagicMock()
    svc = _make_service(client)
    assert await svc.embed([]) == []
