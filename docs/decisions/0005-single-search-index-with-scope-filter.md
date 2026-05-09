# ADR-0005: Single AI Search index with `scope` filter (vs index-per-user)

- Status: Accepted
- Date: 2026-05-09
- Decider(s): Squad team (Lead, Kane/Backend)

## Context

The accelerator retrieves passages from three logical scopes:

- **Shared corpus** (admin-curated, every user can read).
- **User uploads** (per-user, never visible to other users).
- **Per-conversation uploads** (transient, scoped to a single conversation).

SC-011 mandates that **for every chat turn, retrieval scoped to User A
MUST never return passages owned by User B**, in 100% of automated
isolation tests.

Two structural options:

1. **Per-user (or per-scope) index** — physical separation; one
   AI Search index per user.
2. **Single index with a mandatory `scope` filter** — logical separation;
   query-time filter `scope eq 'shared' or scope eq 'user:<callerOid>'`
   enforced server-side from the caller's Entra `oid` claim.

## Decision

Use a **single `kb-index`** with a mandatory `scope` filter:

- `scope` is a **required, filterable** field on every document
  (data-model §5).
- The API constructs the filter from the **server-validated**
  `oid` claim. The API **never** accepts a client-supplied `scope` value.
- Filter construction lives in `apps/api/src/services/search.py`
  (PR #29); all retrieval call sites route through this single helper.
- Unit tests fuzz the filter logic to enforce SC-011: 10 unit tests in
  PR #29 cover the well-known bypass shapes (empty oid, malformed oid,
  client-supplied override attempts, missing filter, mis-cased operator).

## Consequences

### Positive

- **Operationally simpler** — one index to back up, monitor, re-index,
  upgrade. AI Search index-count limits never become a constraint.
- **Embedding cache locality** — Search can reuse vector-index structures
  across users; per-user indexes pay an HNSW build cost per user.
- **Cheaper at the demo SKU** — Basic supports a small fixed number of
  indexes (`docs/cost.md`, [`research.md` D3](../../specs/001-private-rag-accelerator/research.md));
  per-user would force S1+ very quickly.
- **Shared-corpus updates are a single write** — no fan-out to N user
  indexes.
- **SC-011 isolation** is provable: if the filter is present and well
  formed, cross-user reads are mathematically impossible. Tests assert
  the filter is always present.

### Negative

- **A runtime bug bypassing the filter leaks across users.** This is the
  critical risk and is mitigated by:
  - Single helper choke-point (`apps/api/src/services/search.py`).
  - 10 unit tests in PR #29 covering bypass shapes.
  - The SC-011 isolation test suite (will live in `tests/security/`).
- **No physical isolation** — a hostile insider with admin keys would not
  be stopped by index boundaries (but admin keys are disabled —
  data-plane is AAD-only, FR-003).
- **Per-user purge** is a delete-by-filter operation rather than dropping
  an index; slightly more RU-cost on Search.

### Neutral

- The `scope` field doubles as the Cosmos `documents` partition key
  (data-model §3) — same logical model on both sides.

## Alternatives considered

- **Per-user AI Search index** — hits the AI Search index-count limit at
  scale, makes shared-corpus updates fan-out, and provides no extra
  guarantee over a filtered single index when MI-based query enforcement
  is already trusted (the API never accepts a client-supplied scope).
- **Two indexes (shared + per-user composite)** — modest improvement on
  the filter risk but doubles ops complexity for marginal benefit.
- **Cosmos vector search** — would collapse retrieval into the same store
  as state, but loses semantic ranker + hybrid maturity (see ADR-0004,
  D3).

## References

- [`specs/001-private-rag-accelerator/spec.md`](../../specs/001-private-rag-accelerator/spec.md) — SC-011, FR-003.
- [`specs/001-private-rag-accelerator/data-model.md`](../../specs/001-private-rag-accelerator/data-model.md) §5.
- [`specs/001-private-rag-accelerator/research.md`](../../specs/001-private-rag-accelerator/research.md) — D3.
- `apps/api/src/services/search.py` — filter helper (PR #29).
