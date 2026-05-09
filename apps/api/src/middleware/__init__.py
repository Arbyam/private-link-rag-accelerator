"""Cross-cutting ASGI middleware for the RAG API."""

from .error_handler import register_error_handlers
from .logging import configure_logging, get_logger, pii_safe_context, redact_pii
from .request_id import REQUEST_ID_HEADER, RequestIdMiddleware, get_request_id

__all__ = [
    "REQUEST_ID_HEADER",
    "RequestIdMiddleware",
    "configure_logging",
    "get_logger",
    "get_request_id",
    "pii_safe_context",
    "redact_pii",
    "register_error_handlers",
]
