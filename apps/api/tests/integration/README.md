# Deployed-environment integration tests (`apps/api/tests/integration/`)

These tests target a **deployed** Private RAG Accelerator environment over
the network. Unlike unit tests, they require a real Azure deployment plus
correct runner placement (in- or out-of-VNet) to exercise the network
isolation guarantees promised by the architecture.

## Markers

| Marker | Gate env var | Runner | Purpose |
| --- | --- | --- | --- |
| `integration_invnet` | `RUN_INVNET_TESTS=1` | self-hosted in-VNet | Asserts deployed surface is **reachable** from inside the VNet |
| `integration_outsidevnet` | `RUN_OUTSIDEVNET_TESTS=1` | GitHub-hosted (public) | Asserts deployed surface is **unreachable** from the public internet |

Both markers auto-skip when their gate env var is not set, so a normal
local `pytest` run produces no surprises. Marker registration lives in
`apps/api/pyproject.toml` and the auto-skip hook lives in
`apps/api/tests/_shared/fixtures.py::pytest_collection_modifyitems`.

## Required env vars

* `API_APP_FQDN` — the Container App's FQDN for the API. Matches the
  `apiAppFqdn` Bicep output and is exposed via `azd env get-values`.
  Tests that need it skip if it is unset.
* `RUN_INVNET_TESTS=1` — required to actually run in-VNet tests.
* `RUN_OUTSIDEVNET_TESTS=1` — required to actually run outside-VNet tests.

## Files

* `test_healthz_internal_only.py` — implements **T054**, the FR-004
  acceptance test (no public network ingress to the API):
  * `test_healthz_reachable_from_in_vnet` — `integration_invnet`,
    asserts `GET https://$API_APP_FQDN/healthz` returns 200 + the
    documented body shape.
  * `test_healthz_unreachable_from_outside_vnet` — both
    `integration_invnet` (so it shares the same `API_APP_FQDN` plumbing
    as the in-VNet sibling) and `integration_outsidevnet`, asserts the
    same hostname is **unreachable** from a public runner via DNS or
    TCP failure modes. Returning a 200 from the public internet is a
    privacy regression and fails the test.

## CI wiring

* T055 wires up the in-VNet runner workflow that exports
  `RUN_INVNET_TESTS=1` and `API_APP_FQDN` and invokes pytest.
* The outside-VNet variant runs on a GitHub-hosted runner with
  `RUN_OUTSIDEVNET_TESTS=1` and `API_APP_FQDN` set from the same
  deployed env. (Both markers' tests share the same hostname assertion;
  the runner placement is what makes the test meaningful.)

## Sanity-running locally

```pwsh
# Should be SKIPPED (gate env var not set):
pytest apps/api/tests/integration -v

# In-VNet test executes (and will FAIL/timeout vs an invalid FQDN — that's
# fine; the point is the test ran instead of being skipped):
$env:RUN_INVNET_TESTS = "1"
$env:API_APP_FQDN = "invalid.example.com"
pytest apps/api/tests/integration/test_healthz_internal_only.py::test_healthz_reachable_from_in_vnet -v
```
