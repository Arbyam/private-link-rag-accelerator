"""Azure OpenAI chat + embedding wrapper (T040).

Auth: managed identity via `DefaultAzureCredential` with a bearer-token
provider scoped to Cognitive Services. **No API keys** are accepted or
read anywhere in this module.

Public surface:
    LLMService.chat_completion(messages, ...)   -> ChatResponse
    LLMService.chat_stream(messages, ...)       -> AsyncIterator[ChatStreamEvent]
    LLMService.embed(texts)                     -> list[list[float]]

PII discipline:
    Only token counts, latency and finish_reason are passed to the
    structlog binder. Message/prompt/response content is never logged
    (the global `_PiiRedactingFilter` in `middleware/logging.py`
    further scrubs the `content`/`prompt`/`response` keys defensively).
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any

from azure.identity.aio import DefaultAzureCredential, get_bearer_token_provider
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncAzureOpenAI,
    AuthenticationError,
    BadRequestError,
    RateLimitError,
)

from ..config import Settings, get_settings
from ..middleware.error_handler import (
    AppError,
    UpstreamError,
    UpstreamRateLimitError,
)
from ..middleware.logging import get_logger
from ..models.chat import (
    ChatMessage,
    ChatResponse,
    ChatStreamCitations,
    ChatStreamDelta,
    ChatStreamDone,
    ChatStreamError,
    ChatStreamEvent,
    ChatUsage,
)

_log = get_logger(__name__)

# Pin to a stable Azure OpenAI data-plane API version. 2024-10-21 is the
# current GA stable for chat completions + embeddings on Azure OpenAI.
AZURE_OPENAI_API_VERSION = "2024-10-21"

# ---------------------------------------------------------------------------
# Grounding policy (FR-016, FR-017, FR-019) — T085
# ---------------------------------------------------------------------------
# The exact phrase the assistant must emit when retrieval is empty or all
# scores fall below the confidence threshold. Exported so the chat router
# and tests can match on it without duplicating the literal.
DECLINE_PHRASE: str = "I don't have that information in the available documents."

# Default system prompt enforcing FR-016 (per-claim citation) and FR-017
# (explicit decline). Administrators may override this verbatim by writing a
# `chat.systemPrompt` field into the Cosmos `settings` doc (FR-019).
DEFAULT_SYSTEM_PROMPT: str = (
    "You are a private knowledge assistant. Answer the user's question using "
    "ONLY the provided passages. For every factual claim, cite at least one "
    "passage by its index in square brackets, e.g. [1]. If the passages do "
    "not contain the answer or your confidence is low, respond exactly with: "
    f"'{DECLINE_PHRASE}' Do not speculate. Do not use general knowledge "
    "outside the passages. Be concise."
)

# Cosmos location for the admin-editable settings singleton. Kept as
# module-level constants (rather than env-driven) because the container
# layout is fixed in infra; the *contents* are what admins edit.
_SETTINGS_CONTAINER: str = "settings"
_SETTINGS_DOC_ID: str = "global"
_SETTINGS_PARTITION: str = "global"

# Process-lifetime cache. None == not yet loaded. Use
# `reset_system_prompt_cache()` in tests to bust between cases.
_system_prompt_cache: dict[str, str] = {}


def reset_system_prompt_cache() -> None:
    """Clear the cached system prompt. Intended for tests only."""
    _system_prompt_cache.clear()


async def get_system_prompt(cosmos_client: Any) -> str:
    """Return the admin-configured system prompt, or `DEFAULT_SYSTEM_PROMPT`.

    Reads the singleton `settings/global` document from Cosmos and returns
    its `chat.systemPrompt` field if present and non-empty. Falls back to
    `DEFAULT_SYSTEM_PROMPT` on any of:

      * settings container missing
      * settings doc missing
      * `chat.systemPrompt` absent / empty / not a string
      * any Cosmos error (logged, never raised — the assistant must keep
        running with the safe default rather than fail open)

    Result is cached for the process lifetime; call
    `reset_system_prompt_cache()` to force a re-read.
    """
    if "value" in _system_prompt_cache:
        return _system_prompt_cache["value"]

    prompt = DEFAULT_SYSTEM_PROMPT
    try:
        cfg = get_settings()
        db = cosmos_client.get_database_client(cfg.COSMOS_DATABASE)
        container = db.get_container_client(_SETTINGS_CONTAINER)
        item = await container.read_item(
            item=_SETTINGS_DOC_ID,
            partition_key=_SETTINGS_PARTITION,
        )
        chat_section = item.get("chat") if isinstance(item, dict) else None
        candidate = (
            chat_section.get("systemPrompt") if isinstance(chat_section, dict) else None
        )
        if isinstance(candidate, str) and candidate.strip():
            prompt = candidate
            _log.info("llm.system_prompt.override_loaded", source="cosmos.settings")
        else:
            _log.info("llm.system_prompt.default_used", reason="field_missing_or_empty")
    except Exception as exc:  # noqa: BLE001 — fall back to default on any failure
        _log.info(
            "llm.system_prompt.default_used",
            reason="cosmos_lookup_failed",
            error=type(exc).__name__,
        )

    _system_prompt_cache["value"] = prompt
    return prompt

# text-embedding-3-large native dimensionality.
EMBEDDING_DIMENSIONS = 3072

# Conservative ceiling for batched embedding input — well below the
# documented 8192-token-per-input ceiling on text-embedding-3-large, with
# headroom for callers that haven't pre-truncated. Char-based; we don't
# require tiktoken at runtime.
_EMBED_INPUT_CHAR_LIMIT = 28_000


def _scope_for_cognitive_services() -> str:
    return "https://cognitiveservices.azure.com/.default"


class LLMService:
    """Async wrapper around `AsyncAzureOpenAI`."""

    def __init__(
        self,
        *,
        client: AsyncAzureOpenAI,
        chat_deployment: str,
        embedding_deployment: str,
    ) -> None:
        self._client = client
        self._chat_deployment = chat_deployment
        self._embedding_deployment = embedding_deployment

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> LLMService:
        cfg = settings or get_settings()
        credential = DefaultAzureCredential()
        token_provider = get_bearer_token_provider(
            credential, _scope_for_cognitive_services()
        )
        client = AsyncAzureOpenAI(
            azure_endpoint=cfg.AOAI_ENDPOINT,
            azure_ad_token_provider=token_provider,
            api_version=AZURE_OPENAI_API_VERSION,
        )
        return cls(
            client=client,
            chat_deployment=cfg.AOAI_CHAT_DEPLOYMENT,
            embedding_deployment=cfg.AOAI_EMBEDDING_DEPLOYMENT,
        )

    async def aclose(self) -> None:
        await self._client.close()

    # ---------------------------------------------------------------- chat
    async def chat_completion(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        """Non-streaming chat completion against the configured deployment."""
        payload = [{"role": m.role.value, "content": m.content} for m in messages]
        started = time.perf_counter()
        try:
            completion: Any = await self._client.chat.completions.create(
                model=self._chat_deployment,
                messages=payload,  # type: ignore[arg-type]
                temperature=temperature,
                max_tokens=max_tokens,
                stream=False,
                **kwargs,
            )
        except Exception as exc:  # noqa: BLE001 — translated below
            raise _translate_openai_error(exc) from exc

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        choice = completion.choices[0] if completion.choices else None
        content = (choice.message.content or "") if choice and choice.message else ""
        finish_reason = choice.finish_reason if choice else None
        usage = (
            ChatUsage(
                prompt_tokens=completion.usage.prompt_tokens,
                completion_tokens=completion.usage.completion_tokens,
                total_tokens=completion.usage.total_tokens,
            )
            if completion.usage
            else None
        )

        _log.info(
            "llm.chat_completion",
            deployment=self._chat_deployment,
            elapsed_ms=elapsed_ms,
            finish_reason=finish_reason,
            prompt_tokens=usage.prompt_tokens if usage else None,
            completion_tokens=usage.completion_tokens if usage else None,
        )
        return ChatResponse(
            content=content,
            finish_reason=finish_reason,
            usage=usage,
            model=getattr(completion, "model", None),
        )

    async def chat_stream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.2,
        **kwargs: Any,
    ) -> AsyncIterator[ChatStreamEvent]:
        """Stream chat completion deltas as SSE-compatible events.

        Yields events that serialize to JSON shapes consumed by the web
        client (`apps/web/src/lib/api.ts` ChatStreamEvent):
            {"type": "delta", "data": {"text": "..."}}
            {"type": "done",  "data": {"finish_reason": "stop", ...}}
            {"type": "error", "data": {"code": "...", "message": "..."}}
        """
        payload = [{"role": m.role.value, "content": m.content} for m in messages]
        started = time.perf_counter()
        finish_reason: str | None = None
        delta_count = 0
        try:
            stream: Any = await self._client.chat.completions.create(
                model=self._chat_deployment,
                messages=payload,  # type: ignore[arg-type]
                temperature=temperature,
                stream=True,
                **kwargs,
            )
            async for chunk in stream:
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                if choice.finish_reason:
                    finish_reason = choice.finish_reason
                delta = choice.delta
                text = (delta.content if delta else None) or ""
                if text:
                    delta_count += 1
                    yield ChatStreamDelta(data={"text": text})
        except Exception as exc:  # noqa: BLE001
            translated = _translate_openai_error(exc)
            yield ChatStreamError(
                data={"code": translated.code, "message": translated.message}
            )
            return

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        _log.info(
            "llm.chat_stream",
            deployment=self._chat_deployment,
            elapsed_ms=elapsed_ms,
            delta_count=delta_count,
            finish_reason=finish_reason,
        )
        yield ChatStreamDone(data={"finish_reason": finish_reason})

    # Re-export the citations event type so router-layer callers can
    # build their own citation events to interleave with our stream.
    StreamCitations = ChatStreamCitations

    # ----------------------------------------------------------- embeddings
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return embedding vectors (dim=3072) for each input string.

        Each input is char-truncated to a conservative ceiling that keeps
        us comfortably under the 8192 token-per-input limit of
        text-embedding-3-large. Dimension is asserted on every result so
        an accidentally re-pointed deployment trips fast in tests.
        """
        if not texts:
            return []
        prepared = [_truncate(t) for t in texts]
        started = time.perf_counter()
        try:
            result = await self._client.embeddings.create(
                model=self._embedding_deployment,
                input=prepared,
            )
        except Exception as exc:  # noqa: BLE001
            raise _translate_openai_error(exc) from exc

        vectors = [item.embedding for item in result.data]
        if len(vectors) != len(texts):
            raise UpstreamError(
                "Embedding response count mismatch",
                details={
                    "expected": len(texts),
                    "received": len(vectors),
                },
            )
        for idx, vec in enumerate(vectors):
            if len(vec) != EMBEDDING_DIMENSIONS:
                raise UpstreamError(
                    "Unexpected embedding dimension",
                    details={
                        "index": idx,
                        "expected": EMBEDDING_DIMENSIONS,
                        "received": len(vec),
                    },
                )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        _log.info(
            "llm.embed",
            deployment=self._embedding_deployment,
            elapsed_ms=elapsed_ms,
            count=len(vectors),
            prompt_tokens=result.usage.prompt_tokens if result.usage else None,
        )
        return vectors


def _truncate(text: str) -> str:
    if len(text) <= _EMBED_INPUT_CHAR_LIMIT:
        return text
    return text[:_EMBED_INPUT_CHAR_LIMIT]


def _translate_openai_error(exc: BaseException) -> AppError:
    """Map openai SDK exceptions to our `AppError` hierarchy."""
    if isinstance(exc, AppError):
        return exc
    if isinstance(exc, AuthenticationError):
        return UpstreamError(
            "Azure OpenAI rejected managed-identity credentials",
            details={"reason": "authentication_error"},
        )
    if isinstance(exc, RateLimitError):
        return UpstreamRateLimitError(
            "Azure OpenAI rate limit exceeded",
            details={"reason": "rate_limit"},
        )
    if isinstance(exc, BadRequestError):
        # Surface request-shape problems as a 503 — they indicate an
        # orchestration bug, not a client error to expose verbatim.
        return UpstreamError(
            "Azure OpenAI rejected the request",
            details={"reason": "bad_request"},
        )
    if isinstance(exc, APITimeoutError | APIConnectionError):
        return UpstreamError(
            "Azure OpenAI connection failed",
            details={"reason": "connection_error"},
        )
    if isinstance(exc, APIStatusError):
        return UpstreamError(
            "Azure OpenAI returned an error status",
            details={"reason": "status_error", "status": exc.status_code},
        )
    return UpstreamError(
        "Unexpected Azure OpenAI failure",
        details={"reason": type(exc).__name__},
    )


__all__ = [
    "AZURE_OPENAI_API_VERSION",
    "DECLINE_PHRASE",
    "DEFAULT_SYSTEM_PROMPT",
    "EMBEDDING_DIMENSIONS",
    "ChatStreamEvent",
    "LLMService",
    "get_system_prompt",
    "reset_system_prompt_cache",
]
