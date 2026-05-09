"""Fixtures for deployed-env integration tests (T054).

Provides the ``api_fqdn`` fixture, which reads ``API_APP_FQDN`` from the
environment (matching the ``apiAppFqdn`` Bicep output exposed via
``azd env get-values``) and skips the test when it is not set.
"""

from __future__ import annotations

import os

import pytest

_API_FQDN_ENV = "API_APP_FQDN"


@pytest.fixture(scope="session")
def api_fqdn() -> str:
    """Deployed API FQDN, e.g. ``ca-api-xyz.westeurope.azurecontainerapps.io``.

    Sourced from ``API_APP_FQDN`` to match the ``apiAppFqdn`` Bicep output
    surfaced by ``azd env get-values``. Tests requesting this fixture are
    skipped if the variable is unset, which keeps local ``pytest`` runs
    green even when no deployed environment is reachable.
    """
    value = os.environ.get(_API_FQDN_ENV)
    if not value:
        pytest.skip(
            f"{_API_FQDN_ENV} not set — deployed-env integration test requires "
            "the deployed API FQDN (run `azd env get-values` and export "
            f"{_API_FQDN_ENV}).",
        )
    return value
