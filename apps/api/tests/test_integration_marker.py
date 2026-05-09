"""Smoke test for the ``integration_invnet`` marker (T046).

Demonstrates the marker and verifies the auto-skip mechanism wired up
in ``tests/_shared/fixtures.py::pytest_collection_modifyitems``.

Run normally::

    pytest apps/api/tests/test_integration_marker.py -v
    # -> SKIPPED (set RUN_INVNET_TESTS=1)

Run on the in-VNet runner::

    RUN_INVNET_TESTS=1 pytest apps/api/tests/test_integration_marker.py -v
    # -> PASSED

Future engineers writing in-VNet tests should mirror the marker pattern::

    @pytest.mark.integration_invnet
    async def test_real_cosmos_round_trip(cosmos_emulator):
        ...
"""

from __future__ import annotations

import os

import pytest


@pytest.mark.integration_invnet
def test_invnet_marker_runs_only_when_enabled() -> None:
    """Trivially asserts the marker gate is honoured.

    When ``RUN_INVNET_TESTS=1`` this test is collected and runs; otherwise
    the conftest auto-skip kicks in and pytest never executes the body.
    """
    assert os.environ.get("RUN_INVNET_TESTS") == "1"
