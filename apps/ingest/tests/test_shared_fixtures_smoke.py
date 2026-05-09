"""Smoke test asserting the shared fixtures load in the ingest test suite (T046).

This file exists primarily so ``pytest apps/ingest`` doesn't exit code 5
("no tests collected"). It also gives future engineers a working example
of consuming the shared JWT/JWKS fixtures from inside the ingest tree.
"""

from __future__ import annotations

from collections.abc import Callable

from jose import jwt as jose_jwt


def test_make_entra_token_returns_decodable_jwt(
    make_entra_token: Callable[..., str],
    synthetic_jwks_keypair: tuple[bytes, dict[str, object]],
) -> None:
    token = make_entra_token({"oid": "ingest-tester"})
    header = jose_jwt.get_unverified_header(token)
    claims = jose_jwt.get_unverified_claims(token)
    assert header["alg"] == "RS256"
    assert header["kid"] == "test-kid-1"
    assert claims["oid"] == "ingest-tester"
    _, jwks = synthetic_jwks_keypair
    assert jwks["keys"][0]["kid"] == "test-kid-1"


def test_cosmos_emulator_default_returns_mock(cosmos_emulator: object) -> None:
    # Without COSMOS_EMULATOR_ENDPOINT set, the fixture yields a MagicMock chain.
    container = cosmos_emulator.get_database_client("db").get_container_client("c")  # type: ignore[attr-defined]
    assert container is not None
