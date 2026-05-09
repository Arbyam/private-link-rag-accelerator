# Storage module (T022 / PR-G.1)

Bicep module that provisions a zero-trust **Azure Storage Account (StorageV2 / Standard_LRS / Hot)** plus the Event-Grid-driven ingestion plumbing for the Private RAG Accelerator.

Built on AVM `br/public:avm/res/storage/storage-account:0.32.0`. The Event Grid system topic + subscription are hand-rolled (no AVM coverage — see Ripley `phase-2-plan.md`).

> **History**: PR #12 (the original PR-G) closed only the storage-account skeleton. This module supersedes it and finishes the remaining T022 acceptance criteria (2 containers, soft-delete, lifecycle, Event Grid system topic + queue subscription).

## What this module deploys

- **StorageV2 account** — Standard_LRS, Hot access tier, zero-trust networking
- **2 private endpoints** in `snet-pe`: `blob` + `queue`. *(File/Table/DFS PEs were dropped per Ripley phase-2-plan row 13 — we use none of those services. Saves ~$22/mo.)*
- **3 blob containers** (all private):
  - `shared-corpus` — admin-curated KB; ingest job MI writes, API MI reads (RBAC wired in PR-O)
  - `user-uploads` — per-user, per-conversation uploads; 30-day lifecycle delete
  - `eventgrid-deadletter` — Event Grid undelivered-event destination
- **1 storage queue** — `ingestion-events` (target of the Event Grid subscription)
- **Blob soft-delete** — 7 days; container soft-delete — 7 days
- **Lifecycle policy** — `Microsoft.Storage/.../managementPolicies` rule that deletes block blobs under `user-uploads/` older than 30 days (FR-005 / SC-012). Does **not** apply to `shared-corpus`.
- **Event Grid system topic** on the storage account (`Microsoft.Storage.StorageAccounts`) with system-assigned MI
- **Event Grid subscription** `shared-corpus-to-queue` — `Microsoft.Storage.BlobCreated` + `BlobDeleted`, filtered to `subjectBeginsWith: /blobServices/default/containers/shared-corpus/`, delivered to the `ingestion-events` queue using **CloudEvents 1.0** schema (matches [`contracts/ingestion-event.schema.json`](../../../specs/001-private-rag-accelerator/contracts/ingestion-event.schema.json)). Retry: 30 attempts, TTL 60 minutes. Dead-letter to the `eventgrid-deadletter` container.
- **Diagnostic settings → Log Analytics** at the account, blob-service, and queue-service scopes. Dead-letter container logs ride on the blob-service diagnostic setting (per-container categories don't exist).

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

## RBAC — what's in this module vs PR-O

This module emits **only the RBAC required for the Event Grid system topic to function**, because shared keys are disabled and MI delivery is the only path. Two assignments at storage-account scope, principal = the system topic's system-assigned MI:

| Assignment | Why |
|---|---|
| `Storage Queue Data Message Sender` | Deliver CloudEvents to `ingestion-events` |
| `Storage Blob Data Contributor` | Write undelivered events to `eventgrid-deadletter` |

**Cross-module RBAC** — `Storage Blob Data Reader` / `Contributor` on the API and ingest UAMIs — is intentionally **not** in this module. It is wired by **PR-O (T029)** after the storage account, identities, and applications all exist.

## Inputs

| Name | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | Globally-unique storage account name (3–24 lowercase alphanumerics) |
| `location` | string | yes | Azure region |
| `tags` | object | yes | Resource tags (applied to account, PEs, system topic) |
| `peSubnetId` | string | yes | Resource ID of `snet-pe` |
| `pdnsBlobId` | string | yes | `privatelink.blob.core.windows.net` zone ID |
| `pdnsQueueId` | string | yes | `privatelink.queue.core.windows.net` zone ID |
| `lawId` | string | yes | Log Analytics workspace resource ID |

## Outputs

| Name | Type | Description |
|---|---|---|
| `resourceId` | string | Storage account resource ID |
| `name` | string | Storage account name |
| `primaryBlobEndpoint` | string | `https://<name>.blob.core.windows.net/` |
| `sharedCorpusContainerName` | string | Always `shared-corpus` |
| `userUploadsContainerName` | string | Always `user-uploads` |
| `ingestionQueueName` | string | Always `ingestion-events` |
| `eventGridSystemTopicId` | string | Resource ID of the Event Grid system topic |

## Cost

Per Phase 2a v3 plan row 13: **~$3/mo** storage (LRS, Hot, demo data). Two private endpoints add ~$15/mo combined. The Event Grid system topic itself is free; per-event charges are negligible at demo volumes (~$0.60 per million events).

## Wiring

This module is **not** referenced from `infra/main.bicep` yet. Wiring is the responsibility of PR-O (T029/T030). Until then, the module compiles standalone and its outputs define the contract callers should expect.

## Validation

```pwsh
az bicep build --file infra/modules/storage/main.bicep
```

Exit code 0, zero warnings.

## Idempotency

`azd up` re-runs are safe: the AVM module is declarative, the container/queue lists are convergent, the management policy is a single-rule object, and the Event Grid subscription's role assignments use deterministic `guid()`-based names.
