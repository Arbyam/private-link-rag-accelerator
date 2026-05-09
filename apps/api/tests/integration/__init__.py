"""Deployed-environment integration tests for the RAG API.

Tests in this package are gated by environment markers and only run on
specific runners with appropriate network placement:

* ``integration_invnet`` — runs on the in-VNet self-hosted runner (T055).
  Gate: ``RUN_INVNET_TESTS=1``.
* ``integration_outsidevnet`` — runs on a public GitHub-hosted runner.
  Gate: ``RUN_OUTSIDEVNET_TESTS=1``.

See :mod:`apps.api.tests.integration` README for details.
"""
