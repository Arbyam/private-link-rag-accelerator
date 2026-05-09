"""Shared test fixtures."""

from __future__ import annotations

import os

# Provide dummy env so `Settings()` validates without real Azure config.
_TEST_ENV: dict[str, str] = {
    "AZURE_TENANT_ID": "00000000-0000-0000-0000-000000000000",
    "AZURE_CLIENT_ID": "00000000-0000-0000-0000-000000000001",
    "COSMOS_ACCOUNT_ENDPOINT": "https://example-cosmos.documents.azure.com:443/",
    "SEARCH_ENDPOINT": "https://example-search.search.windows.net",
    "AOAI_ENDPOINT": "https://example-aoai.openai.azure.com/",
    "AOAI_CHAT_DEPLOYMENT": "gpt-5",
    "AOAI_EMBEDDING_DEPLOYMENT": "text-embedding-3-large",
    "STORAGE_ACCOUNT_NAME": "stexample",
    "DOCINTEL_ENDPOINT": "https://example-di.cognitiveservices.azure.com/",
}

for _k, _v in _TEST_ENV.items():
    os.environ.setdefault(_k, _v)
