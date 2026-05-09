# Storage module (T022 / PR-G)

Bicep module that provisions a zero-trust **Azure Storage Account (StorageV2 / Standard_LRS / Hot)** for the Private RAG Accelerator's ingestion path.

Built on AVM `br/public:avm/res/storage/storage-account:0.27.1`.

## What this module deploys

- StorageV2 account, Standard_LRS, Hot access tier
- Five private endpoints into `snet-pe`: `blob`, `file`, `table`, `dfs`, `queue`
- One private blob container, **`documents`**, for ingestion artifacts
- Diagnostic settings → Log Analytics (metrics; storage account-scope log categories live on sub-resources)

## Zero-trust posture (Constitution Principle I)

| Setting | Value |
|---|---|
| `publicNetworkAccess` | `Disabled` |
| `networkAcls.defaultAction` | `Deny` |
| `networkAcls.bypass` | `AzureServices` |
| `allowBlobPublicAccess` | `false` |
| `allowSharedKeyAccess` | `false` (Entra-only) |
| `defaultToOAuthAuthentication` | `true` |
| `minimumTlsVersion` | `TLS1_2` |
| `supportsHttpsTrafficOnly` | `true` |

All access is via Entra ID + RBAC — there are no shared keys to leak.

## Inputs

| Name | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | Globally-unique storage account name (3–24 lowercase alphanumerics) |
| `location` | string | yes | Azure region |
| `tags` | object | yes | Resource tags |
| `peSubnetId` | string | yes | Resource ID of `snet-pe` |
| `pdnsBlobId` | string | yes | `privatelink.blob.core.windows.net` zone ID |
| `pdnsFileId` | string | yes | `privatelink.file.core.windows.net` zone ID |
| `pdnsTableId` | string | yes | `privatelink.table.core.windows.net` zone ID |
| `pdnsDfsId` | string | yes | `privatelink.dfs.core.windows.net` zone ID |
| `pdnsQueueId` | string | yes | `privatelink.queue.core.windows.net` zone ID |
| `lawId` | string | yes | Log Analytics workspace resource ID |

## Outputs

| Name | Type | Description |
|---|---|---|
| `resourceId` | string | Storage account resource ID |
| `name` | string | Storage account name |
| `primaryBlobEndpoint` | string | `https://<name>.blob.core.windows.net/` |
| `documentsContainerName` | string | Always `documents` |

## Cost

Per Phase 2a v3 plan row 13: **~$3/mo** (LRS, Hot, demo-sized data). Five private endpoints add ~$45/mo combined (PE pricing is non-negotiable for SC-004).

## RBAC

Role assignments (`Storage Blob Data Reader` / `Storage Blob Data Contributor` to per-app UAMIs) are intentionally **not** in this module. PR-O wires those after the storage account, identities, and applications all exist.

## Wiring

This module is **not** referenced from `infra/main.bicep` yet. Wiring is the responsibility of PR-O (T029/T030). Until then, the module compiles standalone and its outputs define the contract callers should expect.

### Note on file/table/dfs DNS zones

The current `infra/modules/network/main.bicep` only provisions Blob and Queue private DNS zones. PR-O must either extend the network module to add `privatelink.{file,table,dfs}.core.windows.net` zones or supply matching zone IDs from another source before invoking this module. The module's input contract intentionally accepts all five zone IDs so the wiring layer has a single point to address this.

## Validation

```pwsh
az bicep build --file infra/modules/storage/main.bicep
```

Exit code 0, zero warnings.

## Idempotency

`azd up` re-runs are safe: the AVM module is declarative and the container list is convergent.
