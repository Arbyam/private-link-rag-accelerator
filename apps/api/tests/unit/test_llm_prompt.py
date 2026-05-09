"""Unit tests for the configurable LLM system prompt (T085).

Exercises FR-016 (citation per factual claim), FR-017 (documented decline
phrase) and FR-019 (admin-overridable system prompt sourced from the
Cosmos `settings` doc). No network — Cosmos client is mocked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from azure.cosmos import exceptions as cosmos_exc

from src.services.llm import (
    DECLINE_PHRASE,
    DEFAULT_SYSTEM_PROMPT,
    get_system_prompt,
    reset_system_prompt_cache,
)


@pytest.fixture(autouse=True)
def _bust_cache() -> None:
    reset_system_prompt_cache()


def _mock_cosmos_client(read_item: AsyncMock) -> MagicMock:
    container = MagicMock()
    container.read_item = read_item
    db = MagicMock()
    db.get_container_client.return_value = container
    client = MagicMock()
    client.get_database_client.return_value = db
    return client


def test_default_system_prompt_contains_decline_phrase() -> None:
    assert DECLINE_PHRASE in DEFAULT_SYSTEM_PROMPT


def test_default_system_prompt_requires_citations() -> None:
    lowered = DEFAULT_SYSTEM_PROMPT.lower()
    assert "cite" in lowered
    assert "[1]" in DEFAULT_SYSTEM_PROMPT
    # Must restrict the model to provided passages (FR-016 grounding).
    assert "only the provided passages" in lowered


def test_decline_phrase_is_documented_constant() -> None:
    # Locking down the literal so the chat router + dashboard "don't know"
    # rate counter (SC-006) can match against this exact string.
    assert DECLINE_PHRASE == "I don't have that information in the available documents."


@pytest.mark.asyncio
async def test_get_system_prompt_returns_default_when_no_settings() -> None:
    not_found = cosmos_exc.CosmosResourceNotFoundError(
        status_code=404, message="settings doc missing"
    )
    read_item = AsyncMock(side_effect=not_found)
    client = _mock_cosmos_client(read_item)

    prompt = await get_system_prompt(client)

    assert prompt == DEFAULT_SYSTEM_PROMPT
    read_item.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_system_prompt_returns_override_from_settings() -> None:
    override = "Custom org prompt. Always cite [n]. Otherwise reply: 'no idea'."
    read_item = AsyncMock(
        return_value={
            "id": "global",
            "partitionKey": "global",
            "chat": {"systemPrompt": override},
        }
    )
    client = _mock_cosmos_client(read_item)

    prompt = await get_system_prompt(client)

    assert prompt == override
    # Cached on subsequent calls — Cosmos must not be hit again.
    second = await get_system_prompt(client)
    assert second == override
    read_item.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_system_prompt_falls_back_when_field_missing() -> None:
    # Settings doc exists but has no chat.systemPrompt — use the default.
    read_item = AsyncMock(return_value={"id": "global", "chat": {}})
    client = _mock_cosmos_client(read_item)

    prompt = await get_system_prompt(client)

    assert prompt == DEFAULT_SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_get_system_prompt_falls_back_on_unexpected_error() -> None:
    read_item = AsyncMock(side_effect=RuntimeError("transient cosmos blip"))
    client = _mock_cosmos_client(read_item)

    # Must never raise — assistant stays online with the safe default.
    prompt = await get_system_prompt(client)
    assert prompt == DEFAULT_SYSTEM_PROMPT
