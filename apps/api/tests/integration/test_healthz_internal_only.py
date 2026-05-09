"""FR-004 acceptance test: ``/healthz`` is in-VNet only (T054).

Two complementary assertions:

* :func:`test_healthz_reachable_from_in_vnet` — from the in-VNet runner,
  ``GET https://$API_APP_FQDN/healthz`` returns 200 with the documented
  body shape. Marker: ``integration_invnet``.
* :func:`test_healthz_unreachable_from_outside_vnet` — from a public
  GitHub-hosted runner, the **same hostname** is unreachable via any of
  the acceptable failure modes (NXDOMAIN, connect/read timeout, connect
  refused, or public-DNS-points-at-private-IP-with-timeout). Marker:
  ``integration_outsidevnet`` (plus ``integration_invnet`` so the
  ``RUN_INVNET_TESTS=1`` knob alone surfaces it during in-VNet runs that
  also want a sanity check).

Per :doc:`spec` FR-004 the API must accept zero public network ingress;
returning a 200 from the public internet is a privacy regression and
fails the second test.
"""

from __future__ import annotations

import socket

import httpx
import pytest

_HEALTHZ_TIMEOUT_S = 5.0


@pytest.mark.integration_invnet
async def test_healthz_reachable_from_in_vnet(api_fqdn: str) -> None:
    """In-VNet runner: ``GET /healthz`` returns 200 + documented body shape."""
    url = f"https://{api_fqdn}/healthz"
    async with httpx.AsyncClient(timeout=_HEALTHZ_TIMEOUT_S) as client:
        response = await client.get(url)

    assert response.status_code == 200, (
        f"Expected 200 from in-VNet GET {url}, got {response.status_code}: "
        f"{response.text!r}"
    )
    body = response.json()
    assert body.get("status") == "ok", body
    assert isinstance(body.get("version"), str) and body["version"], body
    assert "request_id" in body, body


@pytest.mark.integration_invnet
@pytest.mark.integration_outsidevnet
async def test_healthz_unreachable_from_outside_vnet(api_fqdn: str) -> None:
    """Public runner: same hostname must be unreachable (FR-004).

    Acceptable outcomes (any one passes):

    * :class:`socket.gaierror` — public DNS does not resolve the name.
    * :class:`httpx.ConnectError` / :class:`httpx.ConnectTimeout` —
      TCP can't reach the endpoint (e.g., public DNS resolves to the
      private 10.x.x.x IP that's unroutable from the runner).
    * :class:`httpx.ReadTimeout` — TCP succeeds (rare on private link)
      but no application response within the short timeout.

    A successful 200 response is a privacy regression: the API should
    have no public ingress per spec FR-004.
    """
    url = f"https://{api_fqdn}/healthz"
    acceptable_exceptions: tuple[type[BaseException], ...] = (
        httpx.ConnectError,
        httpx.ConnectTimeout,
        httpx.ReadTimeout,
        socket.gaierror,
    )

    try:
        async with httpx.AsyncClient(timeout=_HEALTHZ_TIMEOUT_S) as client:
            response = await client.get(url)
    except acceptable_exceptions as exc:
        # Confirms FR-004: hostname is not reachable from the public internet.
        assert exc is not None
        return

    pytest.fail(
        f"FR-004 regression: GET {url} succeeded from outside the VNet with "
        f"status {response.status_code}. The API must have no public ingress.",
    )
