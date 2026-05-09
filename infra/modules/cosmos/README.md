# `cosmos` — Azure Cosmos DB for NoSQL (Serverless, Private Endpoint)

**Task:** T023 (Phase 2a / PR-H)
**Owner:** Dallas
**AVM module:** [`avm/res/document-db/database-account:0.16.0`](https://github.com/Azure/bicep-registry-modules/tree/main/avm/res/document-db/database-account)

Provisions an Azure Cosmos DB account for the Private RAG Accelerator's chat
history, document metadata, and ingestion telemetry. Designed to the v3
cost-locked plan (~$3/mo idle).

## Posture

| Control | Value |
|---|---|
| API | SQL (Core / NoSQL) |
| Capacity | **Serverless** (`EnableServerless` capability) |
| Public network access | **Disabled** |
| Network ACL bypass | **None** (no Azure-services bypass) |
| IP / VNet rules | none |
| Local authentication | **Disabled** (`disableLocalAuthentication: true`) — apps use **managed identity + Cosmos DB Built-in Data Contributor** RBAC |
| Key-based metadata writes | **Disabled** |
| Backup | **Continuous** (AVM default; serverless accounts only support Continuous) |
| Multi-region writes | off |
| Zone redundancy | off (cost discipline; opt-in via `enableZoneRedundancy` at the composition layer per plan.md WAF table) |
| Minimum TLS | 1.2 |
| Diagnostics | All logs (`allLogs`) + all metrics → Log Analytics |

Constitution Principle I (Security-First / Zero Trust) and II
(Idempotent IaC) both pass — no public surface, no secret material exists at
rest (master keys are disabled), all data-plane auth is Entra.

## Database & containers

One SQL database (`rag` by default) with three containers, per
[`data-model.md` §1](../../../specs/001-private-rag-accelerator/data-model.md):

| Container | Partition key | Default TTL | Purpose |
|---|---|---|---|
| `conversations` | `/userId` | 2,592,000 s (30 days, sliding) | Chat history. Each turn write resets `_ts`, satisfying FR-030 sliding retention. |
| `documents` | `/scope` | `-1` (enabled, no default) | Document metadata. Per-document `ttl` field is set by the ingest worker — `shared` docs get no TTL, `user:<oid>` docs inherit the parent conversation's expiry. |
| `ingestion-runs` | `/scope` | 7,776,000 s (90 days) | Ingestion telemetry / operational records. |

`scope` values are `"shared"` or `"user:<oid>"`; this keeps a user's uploads in
one logical partition for fast cleanup on soft-delete.

### Note on the module contract

The output contract surfaces a single primary container via `containerName`
(`conversations`, the chat-history container backing the `/userId` partition).
The full set of container names is also exported via `containerNames` so the
PR-O wiring layer and the API/ingest apps can resolve every container without
hard-coding strings. This deviates slightly from the original "1 container"
phrasing in the Dallas brief; the spec sources of truth (data-model.md §1,
tasks.md T023, phase-2-plan.md "3 containers") all call for three, and we ship
to the spec.

## Wiring contract

### Inputs

| Name | Type | Description |
|---|---|---|
| `name` | `string` | Globally-unique Cosmos account name (3–44 chars, lowercase alnum + hyphens). |
| `location` | `string` | Region. |
| `tags` | `object` | Tags applied to the account and its PE. |
| `peSubnetId` | `string` | Resource ID of `snet-pe`. |
| `pdnsCosmosId` | `string` | Resource ID of the `privatelink.documents.azure.com` Private DNS Zone, linked to the platform VNet. |
| `lawId` | `string` | Resource ID of the Log Analytics workspace. |
| `databaseName` | `string` | SQL database name. Defaults to `rag`. |
| `conversationsContainerName` | `string` | Defaults to `conversations`. |
| `documentsContainerName` | `string` | Defaults to `documents`. |
| `ingestionRunsContainerName` | `string` | Defaults to `ingestion-runs`. |

### Outputs

| Name | Type | Description |
|---|---|---|
| `resourceId` | `string` | Cosmos DB account resource ID. Used by PR-O for SQL data-plane role assignments. |
| `name` | `string` | Cosmos DB account name. |
| `endpoint` | `string` | Documents endpoint (e.g. `https://<name>.documents.azure.com:443/`). Surfaced as `AZURE_COSMOS_ENDPOINT` to apps. |
| `databaseName` | `string` | SQL database name. |
| `containerName` | `string` | **Primary** container name (`conversations`). |
| `containerNames` | `array` | All three container names, in declaration order. |

### What this module does **not** do

- **No role assignments.** Cosmos DB data-plane RBAC (`Cosmos DB Built-in Data
  Contributor`, role `00000000-0000-0000-0000-000000000002`) is fanned out to
  the per-app UAMIs (`mi-api`, `mi-ingest`) by the PR-O wiring layer (T029),
  consuming `resourceId` from this module.
- **No CMK.** Customer-managed keys are an opt-in at the composition layer per
  the plan's WAF trade-off table; not configured here for the demo default.
- **No app secrets.** Local auth is disabled; there is no key to store.

## Cost

Serverless billing: ~$0.25 / 1M RU + ~$0.25 / GB/month. Phase 2a v3 plan
estimates **~$3/mo** for the demo workload (low RU, < 1 GB working set). The PE
itself is part of the shared $0.01/hr PE pool (~$7.30/mo, accounted in the
network/PE line of the cost table — not duplicated here).

## Validation

```pwsh
az bicep build --file infra/modules/cosmos/main.bicep
```

Expected: exit 0, zero warnings.
