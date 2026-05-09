"""Admin router (T070).

Endpoints (per ``contracts/api-openapi.yaml``):

* ``GET  /admin/stats``    — aggregated dashboard counters (``AdminStats``).
* ``GET  /admin/runs``     — recent ingestion runs (newest-first).
* ``POST /admin/reindex``  — enqueue a manual full re-ingestion of the
  shared corpus (returns 202 + ``{ runId }``).

Authorization
-------------
Every route in this router depends on :func:`require_admin`, which wraps the
``current_user`` dependency from :mod:`apps.api.src.services.auth` (T035) and
rejects callers whose computed role is not ``"admin"`` (i.e. who are not
members of ``ADMIN_GROUP_OBJECT_ID``) with HTTP 403.

Reindex semantics
-----------------
We synthesize a CloudEvents 1.0 envelope (``type =
"Microsoft.Storage.BlobCreated"`` — the only ingest-relevant value in
``contracts/ingestion-event.schema.json``), tag it with a custom
``trigger="manual"`` extension property, and enqueue it onto the same
``ingestion-events`` Storage Queue that Event Grid feeds. The CloudEvent's
``id`` doubles as the new ``IngestionRun.id`` (data-model.md §4) so the
ingest worker can correlate the queue message back to the row this router
just created with ``trigger="manual"``.

Stub fields (filled in by T122)
-------------------------------
``chatRequests24h`` and ``declineRate7d`` are sourced from App Insights KQL
in T122; they are returned as 0 / 0.0 for now so the dashboard can render.
``totalUsers`` requires Graph or a per-user counter not yet implemented and
is also stubbed to 0. ``sharedPassages`` requires an AI Search COUNT and is
out-of-scope for T070; stubbed to 0.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import uuid4

from azure.cosmos import exceptions as cosmos_exc
from fastapi import APIRouter, Depends, Query, Response, status

from ..middleware.error_handler import PermissionDenied
from ..middleware.logging import get_logger
from ..models import CurrentUser
from ..models.admin import AdminStats, LastIngestionRun
from ..services.auth import current_user
from ..services.cosmos import (
    DocumentsRepo,
    IngestionRunRecord,
    IngestionRunsRepo,
    get_documents_repo,
    get_ingestion_runs_repo,
)
from ..services.queue import enqueue_cloud_event

_log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Admin role gate
# ---------------------------------------------------------------------------


async def require_admin(
    user: CurrentUser = Depends(current_user),  # noqa: B008 — FastAPI DI idiom
) -> CurrentUser:
    """FastAPI dependency: forward ``current_user`` only if role is admin.

    Raises :class:`PermissionDenied` (403) for non-admin callers. The
    ``current_user`` dep already enforces a valid bearer token, so this
    layer never sees an anonymous request.
    """
    if user.role != "admin":
        raise PermissionDenied(
            "Admin role required",
            details={"reason": "admin_role_required"},
        )
    return user


router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


# ---------------------------------------------------------------------------
# GET /admin/stats
# ---------------------------------------------------------------------------


async def _count_shared_indexed_documents(repo: DocumentsRepo) -> int:
    """Cross-partition COUNT on shared-scope, indexed documents.

    We hit the partition directly (``/scope = "shared"``) so this is a
    single-partition query and cheap.
    """
    container = repo._container  # noqa: SLF001 — repo deliberately doesn't expose this
    query = (
        "SELECT VALUE COUNT(1) FROM c "
        "WHERE c.scope = 'shared' AND c.ingestion.status = 'indexed'"
    )
    try:
        async for value in container.query_items(
            query=query,
            partition_key="shared",
        ):
            if isinstance(value, int):
                return value
            return 0
    except cosmos_exc.CosmosHttpResponseError as exc:
        _log.warning("admin_stats_doc_count_failed", error=str(exc))
        return 0
    return 0


def _to_last_run(record: IngestionRunRecord) -> LastIngestionRun:
    return LastIngestionRun(
        id=record.id,
        status=record.status,
        startedAt=record.startedAt,
        completedAt=record.completedAt,
    )


@router.get(
    "/stats",
    response_model=AdminStats,
    summary="Operational dashboard stats (admin only)",
)
async def get_admin_stats(
    docs_repo: Annotated[DocumentsRepo, Depends(get_documents_repo)],
    runs_repo: Annotated[IngestionRunsRepo, Depends(get_ingestion_runs_repo)],
) -> AdminStats:
    shared_documents = await _count_shared_indexed_documents(docs_repo)
    recent = await runs_repo.list_recent(scope="shared", limit=1)
    last_run = _to_last_run(recent[0]) if recent else None

    # Stubs — see module docstring; T122 wires real values.
    return AdminStats(
        sharedDocuments=shared_documents,
        sharedPassages=0,
        totalConversations=0,
        totalUsers=0,
        chatRequests24h=0,
        declineRate7d=0.0,
        lastIngestionRun=last_run,
    )


# ---------------------------------------------------------------------------
# GET /admin/runs
# ---------------------------------------------------------------------------


@router.get(
    "/runs",
    summary="List recent ingestion runs (admin only)",
)
async def list_admin_runs(
    runs_repo: Annotated[IngestionRunsRepo, Depends(get_ingestion_runs_repo)],
    scope: Annotated[str, Query(pattern="^(shared|user)$")] = "shared",
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> list[dict[str, Any]]:
    # The OpenAPI ``scope`` enum is the abstracted "shared"/"user" form;
    # the Cosmos partition key is the full scope string. Only ``"shared"`` is
    # exposed today (per-user run partitions are out of scope for T070).
    partition = "shared" if scope == "shared" else scope
    runs = await runs_repo.list_recent(scope=partition, limit=limit)
    return [r.model_dump(mode="json", exclude_none=True) for r in runs]


# ---------------------------------------------------------------------------
# POST /admin/reindex
# ---------------------------------------------------------------------------


def _new_run_id() -> str:
    return f"r_{uuid4().hex}"


def _utcnow() -> datetime:
    return datetime.now(UTC)


@router.post(
    "/reindex",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Force a full re-ingestion of the shared corpus (admin only)",
)
async def post_admin_reindex(
    response: Response,
    runs_repo: Annotated[IngestionRunsRepo, Depends(get_ingestion_runs_repo)],
    user: Annotated[CurrentUser, Depends(require_admin)],
) -> dict[str, str]:
    run_id = _new_run_id()
    started_at = _utcnow()

    record = IngestionRunRecord(
        id=run_id,
        scope="shared",
        trigger="manual",
        startedAt=started_at,
        status="running",
        perDocument=[],
        totals={},
        ttl=7_776_000,  # 90 d (data-model.md §4)
    )
    await runs_repo.create(record)

    # CloudEvents 1.0 envelope — matches contracts/ingestion-event.schema.json
    # except for the ``trigger`` extension property, which the ingest worker
    # reads to short-circuit per-blob filtering and reprocess the whole
    # ``shared-corpus`` container.
    event: dict[str, Any] = {
        "specversion": "1.0",
        "type": "Microsoft.Storage.BlobCreated",
        "source": "/admin/reindex",
        "id": run_id,
        "time": started_at.isoformat().replace("+00:00", "Z"),
        "subject": "/blobServices/default/containers/shared-corpus",
        "datacontenttype": "application/cloudevents+json",
        "data": {
            "url": "",
            "contentType": "application/octet-stream",
        },
        "trigger": "manual",
        "triggeredBy": user.oid,
    }
    await enqueue_cloud_event(event)

    _log.info(
        "admin_reindex_enqueued",
        run_id=run_id,
        triggered_by=user.oid,
    )

    response.status_code = status.HTTP_202_ACCEPTED
    return {"runId": run_id}


__all__ = ["require_admin", "router"]
