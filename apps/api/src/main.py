"""FastAPI ASGI entrypoint for the Private RAG Accelerator API (T034).

Wires:
  * structured JSON logging with PII redaction (long-lived telemetry sink),
  * Application Insights via the `azure-monitor-opentelemetry` distro,
  * OpenTelemetry FastAPI instrumentation,
  * x-request-id correlation middleware,
  * global error handler returning the canonical `Error` schema,
  * CORS (currently `*`; locked down in prod via `azure.yaml` env override),
  * the `/healthz` + `/me` router (more routers added in subsequent waves).
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .middleware.error_handler import register_error_handlers
from .middleware.logging import configure_logging, get_logger
from .middleware.request_id import RequestIdMiddleware
from .routers import admin, citations, conversations, health

API_TITLE = "Private RAG Accelerator API"
API_VERSION = "0.1.0"


def _configure_telemetry(log: Any) -> None:
    """Initialize Application Insights via OpenTelemetry distro.

    Reads `APPLICATIONINSIGHTS_CONNECTION_STRING` from env. If unset, logs a
    warning and continues so local/dev runs don't fail.
    """
    conn = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if not conn:
        log.warning(
            "appinsights_connection_string_unset",
            note="telemetry disabled; set APPLICATIONINSIGHTS_CONNECTION_STRING in prod",
        )
        return
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor

        configure_azure_monitor(connection_string=conn)
        log.info("appinsights_configured")
    except Exception as exc:  # noqa: BLE001 — must never break startup
        log.warning("appinsights_configure_failed", error=str(exc))


def create_app() -> FastAPI:
    debug = os.environ.get("DEBUG", "false").lower() in {"1", "true", "yes"}
    configure_logging(debug=debug)
    log = get_logger(__name__)
    _configure_telemetry(log)

    app = FastAPI(
        title=API_TITLE,
        version=API_VERSION,
        docs_url="/docs" if debug else None,
        redoc_url=None,
        openapi_url="/openapi.json" if debug else None,
    )

    # CORS: permissive for now — locked down in prod via azure.yaml env override.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["x-request-id"],
    )

    app.add_middleware(RequestIdMiddleware)
    register_error_handlers(app)

    app.include_router(health.router)
    app.include_router(admin.router)
    app.include_router(citations.router)
    app.include_router(conversations.router)

    # Instrument FastAPI with OTel only after routes are registered so the
    # instrumentor sees the full route tree.
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
    except Exception as exc:  # noqa: BLE001
        log.warning("otel_fastapi_instrument_failed", error=str(exc))

    log.info("api_startup_complete", version=API_VERSION)
    return app


app = create_app()
