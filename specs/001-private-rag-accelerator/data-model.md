# Phase 1 — Data Model

**Feature**: Private End-to-End RAG Accelerator
**Date**: 2026-05-08

This document maps the entities defined in [spec.md](./spec.md) to concrete
storage shapes. It is normative for implementation; contracts in
[`contracts/`](./contracts/) reference these shapes by name.

---

## 1. Storage placement summary

| Entity              | Store                | Container / Index           | Partition key       | TTL                          |
|---------------------|----------------------|-----------------------------|---------------------|------------------------------|
| Conversation + Turns| Cosmos DB for NoSQL  | `conversations`             | `/userId`           | 30 d sliding (FR-030)        |
| Document (metadata) | Cosmos DB for NoSQL  | `documents`                 | `/scope`            | none for `shared`; 30 d sliding for `user:*` (parent conversation TTL) |
| Document (binary)   | Blob Storage         | `shared-corpus`, `user-uploads/{userOid}/{conversationId}/{docId}/...` | n/a | lifecycle policy mirrors Cosmos TTL for user-uploads |
| Passage (chunk + vector) | Azure AI Search | `kb-index`                  | n/a (filter by `scope`) | manual purge on Document delete |
| User                | Microsoft Entra ID   | n/a (directory)             | n/a                 | n/a                          |
| Ingestion Run       | Cosmos DB for NoSQL  | `ingestion-runs`            | `/scope`            | 90 d sliding (operational telemetry) |

Three Cosmos containers total. AI Search has one index. Storage has one
account with two containers.

---

## 2. Cosmos `conversations` container

**Partition key**: `/userId` — single-partition reads for "list my
conversations".

**TTL**: container default 2,592,000 seconds (30 d). Each turn write resets
the document's `_ts`, giving sliding retention as required by FR-030.

**Document shape** (`Conversation`):

```jsonc
{
  "id": "c_01J9X8YZ...",          // ULID; unique within partition
  "userId": "oid:11111111-...-...",// Entra object ID, opaque
  "title": "Title generated from first user turn",
  "createdAt": "2026-05-08T14:22:00Z",
  "updatedAt": "2026-05-08T14:35:11Z",
  "turns": [                       // Embedded; capped (see invariants)
    {
      "turnId": "t_01J9X8YZA...",
      "role": "user",
      "content": "What does Title IX require for...",
      "createdAt": "2026-05-08T14:22:00Z"
    },
    {
      "turnId": "t_01J9X8YZB...",
      "role": "assistant",
      "content": "Title IX requires schools to...",
      "citations": [
        {
          "passageId": "p_01J9...",
          "documentId": "d_01J9...",
          "scope": "shared",
          "snippet": "...the school must...",
          "page": 12,
          "score": 0.83
        }
      ],
      "model": "gpt-5",
      "promptTokens": 1450,
      "completionTokens": 312,
      "createdAt": "2026-05-08T14:22:08Z"
    }
  ],
  "uploadedDocumentIds": ["d_01J9..."], // user-scoped Documents bound to this conversation
  "status": "active",              // "active" | "deletePending"
  "_ts": 1746717311                // Cosmos system; drives sliding TTL
}
```

**Invariants**:

- `userId` MUST equal the partition key value.
- `turns` MAY be capped at 200 entries; older turns roll into a sibling
  `Conversation` document if exceeded (rare for 30-d window).
- `citations[*].scope` MUST be either `"shared"` or `"user:" + this.userId` —
  cross-user citations are a security bug (covered by SC-011 isolation tests).
- `uploadedDocumentIds[*]` MUST reference Documents whose `scope =
  "user:" + this.userId` AND whose `parentConversationId` equals `this.id`.

---

## 3. Cosmos `documents` container

**Partition key**: `/scope` — values are `"shared"` or `"user:<oid>"`. Keeps
all of a user's uploads in one logical partition for fast cleanup.

**TTL**: per-document `ttl` field. `shared` documents have no TTL.
`user:*` documents inherit the parent conversation's expiry (the ingest
worker writes `ttl` based on conversation `updatedAt`).

**Document shape** (`Document`):

```jsonc
{
  "id": "d_01J9X8YZC...",
  "scope": "user:oid:11111111-...", // or "shared"
  "parentConversationId": "c_01J9...", // null for "shared"
  "uploadedByUserId": "oid:11111111-...", // null for "shared" (admin-curated)
  "fileName": "case-2024-1142.pdf",
  "mimeType": "application/pdf",
  "sizeBytes": 1843294,
  "sha256": "9f2a...",
  "blobUri": "https://stXXXX.blob.core.windows.net/user-uploads/oid:1111.../c_01J9.../d_01J9.../case-2024-1142.pdf",
  "ingestion": {
    "status": "indexed",            // "queued" | "cracking" | "indexing" | "indexed" | "failed" | "skipped"
    "runId": "r_01J9...",
    "startedAt": "2026-05-08T14:22:01Z",
    "completedAt": "2026-05-08T14:22:38Z",
    "passageCount": 42,
    "errorReason": null,
    "errorCode": null
  },
  "language": "en",
  "checksum": "9f2a...",            // for change detection on shared corpus
  "ttl": 2592000,                   // seconds; null for shared
  "_ts": 1746717311
}
```

**Invariants**:

- `scope` MUST start with `"user:"` for any document where
  `parentConversationId != null`.
- `passageCount` MUST equal the number of `kb-index` documents whose
  `documentId == this.id`.
- `blobUri` MUST point to a blob in the storage account this deployment owns
  (validated at write time).

---

## 4. Cosmos `ingestion-runs` container

**Partition key**: `/scope`.

**Document shape** (`IngestionRun`):

```jsonc
{
  "id": "r_01J9...",
  "scope": "shared",
  "trigger": "eventgrid",          // "eventgrid" | "manual" | "user-upload"
  "startedAt": "2026-05-08T14:21:55Z",
  "completedAt": "2026-05-08T14:24:11Z",
  "status": "completed",           // "running" | "completed" | "failed" | "partial"
  "perDocument": [
    { "documentId": "d_01J9...", "outcome": "indexed", "durationMs": 37000 },
    { "documentId": "d_01J9...", "outcome": "skipped", "errorReason": "unsupported-mime" }
  ],
  "totals": { "indexed": 14, "skipped": 1, "failed": 0 },
  "ttl": 7776000,                  // 90 d
  "_ts": 1746717851
}
```

---

## 5. AI Search index `kb-index`

Single index. Per-user isolation enforced at query time by mandatory `scope`
filter set server-side from the caller's Entra `oid`. The API NEVER accepts a
client-supplied `scope`.

**Schema** (also expressed in [`contracts/search-index.json`](./contracts/search-index.json)):

| Field            | Type             | Searchable | Filterable | Facetable | Sortable | Vector            | Notes |
|------------------|------------------|------------|------------|-----------|----------|-------------------|-------|
| `id`             | Edm.String (key) | no         | yes        | no        | no       | —                 | passage id `p_<ulid>` |
| `documentId`     | Edm.String       | no         | yes        | yes       | no       | —                 | parent `Document.id` |
| `scope`          | Edm.String       | no         | **yes (REQUIRED FILTER)** | yes | no | —    | `"shared"` or `"user:<oid>"` |
| `userOid`        | Edm.String       | no         | yes        | no        | no       | —                 | redundant with scope; simplifies user-purge filter |
| `conversationId` | Edm.String       | no         | yes        | no        | no       | —                 | for user-scoped passages |
| `content`        | Edm.String       | yes        | no         | no        | no       | —                 | analyzer `en.microsoft` |
| `contentVector`  | Collection(Edm.Single) | no   | no         | no        | no       | dim 3072 (text-embedding-3-large), `hnsw` algorithm | populated by Azure OpenAI Embedding skill (integrated vectorization) |
| `title`          | Edm.String       | yes        | yes        | no        | no       | —                 | document title |
| `page`           | Edm.Int32        | no         | yes        | no        | yes      | —                 | source page (1-based) |
| `chunkOrder`     | Edm.Int32        | no         | yes        | no        | yes      | —                 | within-document order |
| `lastIndexedAt`  | Edm.DateTimeOffset | no       | yes        | no        | yes      | —                 | for staleness debugging |

**Semantic configuration**: `kb-semantic`, prioritizing `title` (titleField),
`content` (contentFields), no `keywordsFields`.

**Vector profile**: `kb-hnsw` (HNSW, m=4, efConstruction=400, efSearch=500,
metric=cosine).

**Skillset**: `kb-skillset`:

1. `#Microsoft.Skills.Util.DocumentIntelligenceLayoutSkill` — re-uses Doc
   Intelligence cracker output if not already pre-cracked.
2. `#Microsoft.Skills.Text.SplitSkill` — by `pages`, max 2000 chars, overlap
   200.
3. `#Microsoft.Skills.Text.AzureOpenAIEmbeddingSkill` — points to deployed
   `text-embedding-3-large`.

**Indexer**: `kb-indexer` is **disabled** (we push, don't pull). The ingest
worker handles cracking with Doc Intelligence and pushes pre-chunked docs to
the skillset for embedding only.

**Mandatory query-time filter** (enforced by API middleware):

```text
scope eq 'shared' or scope eq 'user:<callerOid>'
```

Cross-user reads are mathematically impossible if this filter is present.
SC-011 isolation tests fuzz this assumption.

---

## 6. Blob Storage layout

Account: `st<prefix><uniquesuffix>`. Two containers:

- **`shared-corpus`** — admin-curated.
  - Path: `<sourceFolder>/<fileName>` (mirrors source layout).
  - RBAC: `Storage Blob Data Reader` to API MI; `Storage Blob Data Contributor`
    to ingest job MI.
- **`user-uploads`** — per-user, per-conversation uploads.
  - Path: `<userOid>/<conversationId>/<documentId>/<fileName>`.
  - Lifecycle policy: delete blobs older than 30 d (matches conversation TTL,
    catches any leak).
  - RBAC: API MI uses **scope reduction** at SAS-less blob client level — every
    write/read passes the userOid path prefix; defense-in-depth.

Event Grid system topic on `Microsoft.Storage.BlobCreated` /
`BlobDeleted` for `shared-corpus` only — feeds the Storage Queue that triggers
the ingest job. `user-uploads` are processed inline by the API on `POST /uploads`.

---

## 7. State transitions

### Document.ingestion.status

```text
queued ──► cracking ──► indexing ──► indexed
   │           │             │
   │           ▼             ▼
   │        failed        failed
   ▼
skipped (unsupported MIME, oversize, content-safety reject)
```

Transitions are written by the ingest worker; failures populate `errorReason`
and `errorCode` and surface to the admin dashboard (FR-013).

### Conversation.status

```text
active ──► deletePending ──► (purged by background sweeper within 1 h)
```

Soft-delete sets `status=deletePending` and writes a tombstone for audit;
sweeper Job runs hourly to purge Cosmos doc, all child Documents (Cosmos +
Blob), and corresponding `kb-index` entries.

---

## 8. Validation rules (cross-cutting)

- **Identity binding**: every write to `conversations` and `documents` MUST be
  authorized by an Entra access token whose `oid` matches the partition's
  `userId` (or whose group membership includes `adminGroupId` for `shared`).
- **Scope filter mandatory**: API MUST reject any internal call to AI Search
  that lacks the `scope` filter. Enforced via a thin wrapper around
  `SearchClient.search`.
- **Size cap**: per-upload size cap default 50 MB; per-conversation cumulative
  cap 250 MB. Reject with HTTP 413 if exceeded.
- **MIME allowlist**: PDF, plain text, DOCX, XLSX, PPTX, PNG, JPEG, TIFF.
  Anything else → `Document.ingestion.status = skipped`,
  `errorReason = "unsupported-mime"`.

---

## 9. Indexes

- Cosmos `conversations` — default index policy is fine; exclude `turns/*` from
  indexing to reduce RU cost (we always read by id within the partition).
- Cosmos `documents` — default; include `ingestion.status` for admin queries.
- Cosmos `ingestion-runs` — default; include `status` and `startedAt`.

---

This data model is sufficient to generate API contracts and tests. Proceed to
contracts.
