# ADR-0002: Cosmos DB for NoSQL over PostgreSQL

- Status: Accepted
- Date: 2026-05-09
- Decider(s): Squad team (Lead, Kane/Backend)

## Context

The accelerator's state store holds three shapes:

- **Conversations** — one document per conversation, embedded turns array,
  partitioned by `userId`, with a 30-day **sliding** TTL touched on each
  turn (data-model §2).
- **Documents (metadata)** — one row per ingested artifact with status,
  partitioned by `scope` (`shared` or `user:<oid>`); user-scoped docs
  inherit the parent conversation TTL (data-model §3).
- **Ingestion runs** — batch run audit records (data-model §4).

Requirements:

- Native **TTL** with reliable purge (SC-012 — purge within 24 h of
  expiry; 1 h on user-initiated delete).
- **Single-partition reads** for "my conversations" (chat-list UX hot path).
- **Managed-identity data-plane auth** (FR-003 — no shared keys).
- Private Endpoint support (Principle I).
- Predictable, low cost at demo idle (≤ ~$700/mo target, SC-009).
- Spec FR-030 explicitly recommends Cosmos.

## Decision

Use **Azure Cosmos DB for NoSQL** in **Serverless** capacity mode with three
containers:

- `conversations` partitioned by `/userId` — TTL 2,592,000 s (30 days),
  sliding (touched per turn).
- `documents` partitioned by `/scope` — user-scoped TTL inherited from
  parent conversation.
- `ingestion-runs` — operational audit container.

All access via system-assigned managed identity + the Cosmos DB Built-in
Data Contributor / Reader role (data-plane RBAC, AAD-only;
`disableLocalAuth=true`).

## Consequences

### Positive

- **Native sliding TTL** removes a whole class of sweeper-job complexity;
  Cosmos guarantees background purge inside the SC-012 window.
- **Per-`userId` partitioning** gives O(1) point reads for the conversation
  list — by far the hottest UI query.
- **Serverless billing** matches the demo + spike workload pattern; idle
  cost rounds to ~$3/mo (`docs/cost.md` §2). Production parameter
  (`cosmosCapacityMode=Provisioned`) flips to autoscale RU/s without IaC
  structural changes.
- **AAD data-plane RBAC** (Cosmos DB Data Contributor / Reader) means no
  account keys ever issued — directly satisfies FR-003.
- Continuous-7-day backup cheap and on by default; production flips to
  continuous-30-day.
- Document-shaped chat data fits NoSQL naturally — embedded `turns` array
  avoids a relational join on every conversation render.

### Negative

- **No SQL joins** — any cross-container analytics needs an Azure Synapse
  Link or app-side join. Acceptable for the chat workload; flagged for
  future analytics layer.
- **RU consumption surprises** — large query fan-outs or unbounded ORDER BY
  can blow past serverless burst limits. Mitigated by partition-key-scoped
  reads and result paging.
- **Vendor lock-in** to Cosmos's API; not a portable PostgreSQL schema.
- **Schemaless** — drift between writers and readers must be enforced in
  app code (Pydantic models in `apps/api/src/models/`).

### Neutral

- Cosmos's **integrated vector search** is improving; we re-evaluate it for
  v2. For v1 the retrieval index lives in AI Search (ADR-0004, ADR-0005),
  not Cosmos.

## Alternatives considered

- **Azure SQL / PostgreSQL Flexible Server** — no native sliding TTL; we'd
  add a sweeper job. Document-shaped chat data is a poor relational fit
  (JSONB works but loses the typing benefit). PostgreSQL pgvector also
  considered for retrieval; rejected separately in ADR-0004.
- **Cosmos Provisioned (autoscale, max 1000 RU/s)** — was the v1 default in
  research.md D5; replaced by Serverless under the $500/mo cost ceiling
  (see [`.squad/decisions.md`](../../.squad/decisions.md), Phase 2a v3
  cost-validated plan). Production toggles back to Provisioned via
  parameter.
- **Table Storage** — too primitive for embedded turns arrays + TTL
  semantics.

## References

- [`specs/001-private-rag-accelerator/spec.md`](../../specs/001-private-rag-accelerator/spec.md) — FR-003, FR-030, SC-012.
- [`specs/001-private-rag-accelerator/research.md`](../../specs/001-private-rag-accelerator/research.md) — D5 (State store).
- [`specs/001-private-rag-accelerator/data-model.md`](../../specs/001-private-rag-accelerator/data-model.md) §§2–4.
- [`.squad/decisions.md`](../../.squad/decisions.md) — Phase 2a v3 cost-validated plan (Serverless lock).
