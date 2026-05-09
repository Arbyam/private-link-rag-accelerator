# `infra/search/`

## `kb-index.json`

Source of truth for the Azure AI Search index schema applied at deploy time.
Committed copy of
[`specs/001-private-rag-accelerator/contracts/search-index.json`](../../specs/001-private-rag-accelerator/contracts/search-index.json),
itself derived from
[`data-model.md` §5](../../specs/001-private-rag-accelerator/data-model.md).

### How it is consumed

`scripts/postprovision.ps1` (T047), invoked by `azd up` via the `azure.yaml`
`postprovision` hook, reads this file and creates the `kb-index` index on the
Search service if it does not already exist. The ingest worker also reads it
on first run to update the index idempotently.

### Substitution placeholder

The `vectorSearch.vectorizers[0].azureOpenAIParameters.resourceUri` field
contains the placeholder `https://<aoai-resource>.openai.azure.com`. The
postprovision step substitutes it with the real Azure OpenAI endpoint emitted
by the Bicep deployment outputs before pushing the schema to AI Search.
The `deploymentId` / `modelName` (`text-embedding-3-large`, 3072 dims) match
the embedding deployment created by `infra/modules/openai/main.bicep`.

### Field semantics

| Field            | Purpose |
| ---------------- | ------- |
| `id`             | Key. Composite of `documentId` + `chunkOrder`. |
| `documentId`     | Logical document this chunk belongs to (FK to Cosmos `documents`). |
| `scope`          | **Mandatory** isolation key. `shared` or `user:<oid>`. The API server-side filter (`scope eq 'shared' or scope eq 'user:<oid>'`) enforces SC-011 cross-user isolation; this field MUST be filterable. |
| `userOid`        | Caller's Entra `oid` for user-scoped passages; not retrievable. |
| `conversationId` | Conversation that uploaded this passage (user-scope only); not retrievable. |
| `title`          | Document title; analyzed `en.microsoft`. |
| `content`        | Chunk text; analyzed `en.microsoft`. |
| `contentVector`  | `Collection(Edm.Single)`, dim **3072**, profile `kb-hnsw-profile`, not retrievable. |
| `page`           | 1-based source page. |
| `chunkOrder`     | Within-document chunk order. |
| `lastIndexedAt`  | UTC timestamp of last (re)index. |

### Vector profile `kb-hnsw`

HNSW, `m=4`, `efConstruction=400`, `efSearch=500`, `metric=cosine`.

### Semantic configuration `kb-semantic`

`titleField=title`, `prioritizedContentFields=[content]`, no
`prioritizedKeywordsFields`.
