"""Global error handler returning the canonical `Error` schema (T034)."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..models import Error
from .logging import get_logger
from .request_id import REQUEST_ID_HEADER, get_request_id

_log = get_logger(__name__)


class AppError(Exception):
    """Base class for app-level errors that map to HTTP responses."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class AuthenticationError(AppError):
    status_code = 401
    code = "authentication_required"


class PermissionDenied(AppError):
    status_code = 403
    code = "permission_denied"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class PayloadTooLarge(AppError):
    status_code = 413
    code = "payload_too_large"


class UnsupportedMediaType(AppError):
    status_code = 415
    code = "unsupported_media_type"


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    rid = get_request_id()
    body_details: dict[str, Any] = dict(details or {})
    if rid and "request_id" not in body_details:
        body_details["request_id"] = rid
    payload = Error(code=code, message=message, details=body_details or None).model_dump(
        exclude_none=True
    )
    headers = {REQUEST_ID_HEADER: rid} if rid else None
    return JSONResponse(status_code=status_code, content=payload, headers=headers)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_request: Request, exc: AppError) -> JSONResponse:
        _log.warning("app_error", code=exc.code, status=exc.status_code)
        return _error_response(
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            details=exc.details,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _http_code_for(exc.status_code)
        return _error_response(
            status_code=exc.status_code,
            code=code,
            message=str(exc.detail) if exc.detail else code,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _error_response(
            status_code=422,
            code="validation_error",
            message="Request payload failed validation",
            details={"errors": exc.errors()},
        )

    @app.exception_handler(Exception)
    async def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
        _log.exception("unhandled_exception", error_type=type(exc).__name__)
        return _error_response(
            status_code=500,
            code="internal_error",
            message="An unexpected error occurred.",
        )


_HTTP_CODE_MAP: dict[int, str] = {
    400: "bad_request",
    401: "authentication_required",
    403: "permission_denied",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    501: "not_implemented",
    503: "service_unavailable",
}


def _http_code_for(status: int) -> str:
    return _HTTP_CODE_MAP.get(status, f"http_{status}")
