"""Liveness + identity probes (T036).

`GET /healthz` — unauthenticated; per `api-openapi.yaml` `/healthz`.
`GET /me`      — placeholder until T035 (auth.py) lands. When DEBUG=true a
stub identity is returned; otherwise a 501 Error envelope is returned.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from ..config import Settings, get_settings
from ..middleware.error_handler import AppError
from ..middleware.request_id import get_request_id
from ..models import Me, UserRole

router = APIRouter(tags=["health"])

_API_VERSION = "0.1.0"


class _NotImplementedYet(AppError):
    status_code = status.HTTP_501_NOT_IMPLEMENTED
    code = "not_implemented"


@router.get("/healthz", summary="Liveness probe (unauthenticated, in-VNet only)")
async def healthz() -> dict[str, str | None]:
    return {
        "status": "ok",
        "version": _API_VERSION,
        "request_id": get_request_id(),
    }


@router.get(
    "/me",
    response_model=Me,
    summary="Return the current user's identity, role, and group membership",
)
async def me(settings: Settings = Depends(get_settings)) -> Me:  # noqa: B008 — FastAPI dependency injection idiom
    # TODO(T035): replace with real Entra-token decoding once auth.py lands.
    if settings.DEBUG:
        return Me(
            oid="00000000-0000-0000-0000-000000000000",
            displayName="Debug User",
            role=UserRole.USER,
            groups=[],
        )
    raise _NotImplementedYet(
        "GET /me is not implemented yet; auth middleware (T035) is required.",
        details={"task": "T035"},
    )
