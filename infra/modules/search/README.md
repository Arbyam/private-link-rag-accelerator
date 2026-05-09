# `infra/modules/search` — Azure AI Search (Basic, private)

Deploys **Azure AI Search Basic** wired for zero-trust: Private Endpoint,
shared private links to Azure OpenAI + Storage, RBAC-only data plane,
and diagnostics to Log Analytics.

> Owns task **T025** in `specs/001-private-rag-accelerator/tasks.md`
> (renumbered from T024 in phase-2-plan v3 alongside the SKU change).
> AVM dependency: [`avm/res/search/search-service@0.12.1`](https://github.com/Azure/bicep-registry-modules/tree/main/avm/res/search/search-service).

## What you get

| Setting | Value | Why |
|---|---|---|
| SKU | **`basic`** ($74/mo, 1 SU, 15 GB, 3 indexes) | Cheapest tier that supports Private Endpoint + Shared Private Link. **Locked** by phase-2-plan v3 — do **not** bump to `standard`/S1 ($245/mo) without escalating. |
| `replicaCount` / `partitionCount` | 1 / 1 | Basic minimums; no extra cost. |
| `publicNetworkAccess` | `Disabled` | Zero-trust (Constitution Principle I). |
| `networkRuleSet.bypass` | `None` | No service bypass; no IP allow-list. |
| `disableLocalAuth` | `true` | Admin & query keys disabled. Data plane auth is Entra-only via RBAC (T029 wires the role assignments). |
| `semanticSearch` | `free` | Free semantic-ranker tier (included with Basic). |
| Identity | System-assigned MI | Required for Shared Private Links and for outbound RBAC to AOAI/Storage. `principalId` is exposed as an output so T029 can grant `Cognitive Services OpenAI User` + `Storage Blob Data Reader`. |
| Private Endpoint | 1 × `searchService` in `snet-pe` | DNS zone group → `privatelink.search.windows.net`. |
| Shared Private Links | 2 (auto-approved) | `openai_account` → AOAI, `blob` → Storage. Lets integrated vectorization & indexers reach those services privately without VNet integration on the Search side. First-deploy approval can take ~10 minutes. |
| Diagnostics | `allLogs` + `AllMetrics` → LAW | Operational visibility. |

## Module contract

### Inputs (all required)

| Name | Type | Description |
|---|---|---|
| `name` | string | Globally unique service name. 2–60 chars, lowercase alphanumerics + `-`, must start/end with alphanumeric. |
| `location` | string | Azure region. |
| `tags` | object | Resource tags. |
| `peSubnetId` | string | Resource ID of `snet-pe`. |
| `pdnsSearchId` | string | Resource ID of the `privatelink.search.windows.net` Private DNS Zone. |
| `lawId` | string | Resource ID of the Log Analytics workspace. |
| `aoaiResourceId` | string | Resource ID of the Azure OpenAI account (target of the SPL with `groupId=openai_account`). The OpenAI module **must deploy before** this module — explicit `dependsOn` belongs in `infra/main.bicep`. |
| `storageBlobResourceId` | string | Resource ID of the Storage account (target of the SPL with `groupId=blob`). |

### Outputs

| Name | Type | Description |
|---|---|---|
| `resourceId` | string | Search service resource ID. |
| `name` | string | Search service name. |
| `endpoint` | string | `https://<name>.search.windows.net`. |
| `principalId` | string | System-assigned MI principal ID. Consumed by T029 RBAC fan-out (PR-O). |

## Constitution checklist

- [x] Zero public endpoints (`publicNetworkAccess: Disabled`, `bypass: None`)
- [x] Local auth disabled (`disableLocalAuth: true`) — Entra ID only
- [x] SKU is `basic` (not `standard`/S1) — budget-compliant at $74/mo
- [x] Diagnostics → LAW (`allLogs` + `AllMetrics`)
- [x] Idempotent (pure AVM + declarative SPL/PE config)

## Validation

```pwsh
az bicep build --file infra/modules/search/main.bicep
```

## Notes & limits

- **Basic SKU caps**: 15 GB storage, 3 indexes, 3 indexers. Sufficient for the
  RAG accelerator demo (single `kb-index` per `plan.md`). Customers move to
  S1 for production.
- **Shared private link approval is async.** AVM calls submit the SPL
  requests; auto-approval typically completes within ~10 minutes for
  same-subscription targets. The Bicep deployment may report success before
  the SPLs are fully `Approved`; wait before running indexers.
- **Index/skillset/indexer creation is out of scope for this module.** It is
  done at the data-plane level by the ingest job (`apps/ingest`) using the
  schema in `specs/001-private-rag-accelerator/contracts/search-index.json`.
