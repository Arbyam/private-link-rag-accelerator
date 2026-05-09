# ADR-0004: Integrated vectorization in AI Search (skillset-driven)

- Status: Accepted
- Date: 2026-05-09
- Decider(s): Squad team (Lead, Kane/Backend)

## Context

Embeddings need to be generated for every chunk indexed in `kb-index`
(data-model §5). Two ways to do that:

1. **Embed in the ingest worker** — the worker calls AOAI `embeddings` for
   each chunk and pushes pre-embedded documents to Search.
2. **Integrated vectorization** — Search runs an `AzureOpenAIEmbedding`
   skill inside its own skillset, reaching AOAI over the in-tenant Private
   Endpoint via a Shared Private Link.

The shared corpus (`shared-corpus` blob container) is bulk-ingested by an
admin and never per-user-scoped; the user-uploads path is per-conversation
and benefits from tighter app-side control.

## Decision

- **Shared-corpus ingest path:** use **integrated vectorization** — Search
  skillset runs the `AzureOpenAIEmbedding` skill against the deployed
  `text-embedding-3-large` model. The ingest worker hands Search the cracked
  layout from Document Intelligence; Search owns chunking (SplitSkill) and
  embedding.
- **User-uploads path:** the `apps/api` orchestrator calls
  `AzureOpenAI.embeddings.create()` directly (`embed()` in
  `apps/api/src/services/embeddings.py`) and pushes the resulting documents
  to the same `kb-index` with `scope = user:<oid>`.

The Search **indexer is disabled** — we always push, never pull. The
skillset is invoked imperatively from the worker. Indexer-pulled blob
ingestion would couple ingest tightly to Search and bypass our explicit
ingestion-status surface (FR-013).

## Consequences

### Positive

- Removes embedding-generation code from the ingest worker for the
  shared-corpus path → smaller worker, fewer moving parts, shorter pipeline.
- **Single private-link path** for shared-corpus embedding (Search → AOAI
  via Shared Private Link) — one less PE hop to debug compared to having
  the worker call AOAI directly.
- Skillset is declarative IaC (lives in `infra/modules/search/`) — drift is
  visible at deploy time.
- Per-user uploads keep the app-side `embed()` so the API can enforce
  scope, citation linkage, and conversation-bound TTL semantics atomically.

### Negative

- One more skillset to misconfigure. Skillset failures are opaque — debug
  surface is the AI Search "execution history" blade plus indexer logs;
  not as rich as application logs.
- Embedding cost is the same either way, but accounting moves from "AOAI
  spend by ingest worker" to "AOAI spend by Search skillset" — small
  observability gotcha for cost dashboards.
- Two embedding code paths (skillset vs `embed()`) means two places to
  change if the embedding model is swapped. Mitigated by parameterising
  the model name once in Bicep and threading it through both.

### Neutral

- Vector profile (`kb-hnsw`, m=4, efConstruction=400, efSearch=500, cosine)
  and chunking config (SplitSkill: pages, max 2000 chars, overlap 200) are
  identical across both paths — same embedding space, same retrieval
  behaviour.

## Alternatives considered

- **Embed-in-worker for both paths** — uniform code path, but more
  worker logic, longer ingest pipeline, and one more service-to-service
  hop in private network. Rejected.
- **AI Search blob indexer (pull) with integrated vectorization** —
  considered, but the indexer poll model bypasses our Cosmos
  `ingestion-runs` audit surface (FR-013) and makes per-blob retry
  semantics opaque.
- **Cosmos DB integrated vector search** — promising and worth re-visiting
  for v2; today AI Search has materially better hybrid + semantic ranker
  maturity (D3).

## References

- [`specs/001-private-rag-accelerator/research.md`](../../specs/001-private-rag-accelerator/research.md) — D3, D4, D6.
- [`specs/001-private-rag-accelerator/data-model.md`](../../specs/001-private-rag-accelerator/data-model.md) §5.
- [`specs/001-private-rag-accelerator/spec.md`](../../specs/001-private-rag-accelerator/spec.md) — FR-013.
- `infra/modules/search/` — skillset Bicep.
