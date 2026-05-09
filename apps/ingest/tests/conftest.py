"""Shared test fixtures for ``apps/ingest`` (T046).

Mirrors :mod:`apps.api.tests.conftest`: stubs the environment that
``Settings()``-style configs would need, then loads the shared fixture
plugin (JWT/JWKS, ``cosmos_emulator``, Azure SDK mocks, the
``integration_invnet`` marker auto-skip).

The ingest worker is a skeleton today — these fixtures exist so future
tests can be written without re-deriving the synthetic JWKS / mock
plumbing already in use under ``apps/api/tests``.
"""

from __future__ import annotations

import os

# Provide dummy env so future Settings()-style configs validate without
# requiring real Azure config. Mirror the api stub so symmetric tests work.
_TEST_ENV: dict[str, str] = {
    "AZURE_TENANT_ID": "00000000-0000-0000-0000-000000000000",
    "AZURE_CLIENT_ID": "00000000-0000-0000-0000-000000000001",
    "STORAGE_ACCOUNT_NAME": "stexample",
    "COSMOS_ACCOUNT_ENDPOINT": "https://example-cosmos.documents.azure.com:443/",
    "SEARCH_ENDPOINT": "https://example-search.search.windows.net",
    "AOAI_ENDPOINT": "https://example-aoai.openai.azure.com/",
    "AOAI_EMBEDDING_DEPLOYMENT": "text-embedding-3-large",
    "DOCINTEL_ENDPOINT": "https://example-di.cognitiveservices.azure.com/",
}

for _k, _v in _TEST_ENV.items():
    os.environ.setdefault(_k, _v)


pytest_plugins: list[str] = ["tests._shared.fixtures"]
