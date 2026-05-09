"""Liveness + identity probes (T036).

`GET /healthz` — unauthenticated; per `api-openapi.yaml` `/healthz`.
`GET /me`      — returns the caller's identity, role, and groups (T035).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..middleware.request_id import get_request_id
from ..models import CurrentUser, Me
from ..services.auth import current_user

router = APIRouter(tags=["health"])

_API_VERSION = "0.1.0"


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
async def me(user: CurrentUser = Depends(current_user)) -> Me:  # noqa: B008 — FastAPI DI
    return user.to_me()
