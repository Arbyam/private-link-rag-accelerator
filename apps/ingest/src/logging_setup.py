"""Structlog + stdlib JSON logging with PII redaction (T066).

Duplicates the redaction strategy used by ``apps.api.middleware.logging`` so
the ingest worker doesn't depend on the API package. Keep the two in sync if
the PII key set changes.
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

import structlog
from structlog.types import EventDict, Processor

_PII_KEYS: frozenset[str] = frozenset({"content", "text", "message", "prompt", "response"})

_pii_safe: ContextVar[bool] = ContextVar("_pii_safe", default=True)


@contextmanager
def pii_safe_context(safe: bool) -> Iterator[None]:
    token = _pii_safe.set(safe)
    try:
        yield
    finally:
        _pii_safe.reset(token)


def redact_pii(value: Any, *, force: bool | None = None) -> Any:
    do_redact = _pii_safe.get() if force is None else force
    if not do_redact:
        return value
    if isinstance(value, Mapping):
        return {
            k: ("<redacted>" if k in _PII_KEYS else redact_pii(v, force=True))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact_pii(v, force=True) for v in value]
    if isinstance(value, tuple):
        return tuple(redact_pii(v, force=True) for v in value)
    return value


def _drop_pii_processor(_logger: Any, _name: str, event: EventDict) -> EventDict:
    if not _pii_safe.get():
        return event
    for k in list(event.keys()):
        if k in _PII_KEYS:
            event[k] = "<redacted>"
    return event


def configure_logging(*, debug: bool = False) -> None:
    level = logging.DEBUG if debug else logging.INFO

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _drop_pii_processor,
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.setLevel(level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_StdlibJsonFormatter())
    root.addHandler(handler)
    root.addFilter(_PiiRedactingFilter())


class _StdlibJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class _PiiRedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not _pii_safe.get():
            return True
        for key in list(record.__dict__.keys()):
            if key in _PII_KEYS:
                record.__dict__[key] = "<redacted>"
        return True


def get_logger(name: str | None = None) -> Any:
    return structlog.get_logger(name) if name else structlog.get_logger()


__all__ = [
    "configure_logging",
    "get_logger",
    "pii_safe_context",
    "redact_pii",
]
