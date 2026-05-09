# `infra/modules/containerapps`

**Task:** T027 (Phase 2a / PR-M)
**AVM modules:**
- `br/public:avm/res/app/managed-environment:0.13.3`
- `br/public:avm/res/app/container-app:0.22.1`
- `br/public:avm/res/app/job:0.7.1`

## Purpose

Provisions the compute layer for the Private RAG Accelerator:

1. **Container Apps Managed Environment** — Consumption-only workload profile, deployed into the `snet-aca` subnet with `internal: true` (no public ingress, no public IP, no public load balancer). All pod-to-pod traffic mTLS-encrypted (`peerTrafficEncryption: true`).
2. **`web` Container App** — Next.js 15 frontend on port 3000, internal ingress only, scale-to-zero (0–2 replicas), pulls from ACR via `mi-web` UAMI.
3. **`api` Container App** — FastAPI on port 8000, internal ingress only, always-on (1–3 replicas; chat cold-start is unacceptable), `/healthz` liveness + readiness probes, pulls via `mi-api` UAMI.
4. **`ingest` Container App Job** — Event-driven (KEDA `azure-queue` scaler against the `ingestion-events` queue), authenticated via `mi-ingest` UAMI workload-identity (no shared key), pulls via `mi-ingest`.

All three workloads receive `APPLICATIONINSIGHTS_CONNECTION_STRING` automatically; image tags are set to `placeholder` and rewritten by `azd deploy`.

## Constitution alignment

| Principle | Enforcement |
|---|---|
| I. Zero-trust networking | `internal: true` on env; `ingressExternal: false` on all apps; no public IP exposed |
| I. No shared keys | KEDA azure-queue scaler uses `identity: <miIngestId>` workload-identity auth; ACR pulls use UAMI (no admin user, no password) |
| I. Defense in depth | `peerTrafficEncryption: true` enables mTLS between revisions |
| Observability | App console logs → LAW via env `appLogsConfiguration`; per-app metrics → LAW via `diagnosticSettings`; App Insights connection string injected into all containers |
| Cost | `Consumption` workload profile only (~$5/mo per Phase 2 plan row 9); `zoneRedundant: false`; web/ingest scale-to-zero |

## Inputs

| Param | Type | Required | Notes |
|---|---|---|---|
| `name` | string | yes | Environment name. App/job names derived: `ca-web-<name>`, `ca-api-<name>`, `cj-ingest-<name>` |
| `location` | string | yes | Region (must match RG) |
| `tags` | object | no | Applied to env, both apps, and job |
| `peSubnetId` | string | yes | `snet-aca` resource ID from `network` module |
| `lawId` | string | yes | Log Analytics workspace ID from `monitoring` module |
| `appInsightsConnectionString` | secure string | yes | From `monitoring` module |
| `acrLoginServer` | string | yes | From `registry` module |
| `miWebId` / `miApiId` / `miIngestId` | string | yes | UAMI resource IDs from `identity` module. Must already have AcrPull on the registry. `mi-ingest` must additionally have **Storage Queue Data Reader** on the ingestion storage account (assigned in T029) so that KEDA can read queue depth via workload identity |
| `appEnvVars` | object | no | Common env vars (map) injected into all three workloads |
| `webExtraEnvVars` / `apiExtraEnvVars` / `ingestExtraEnvVars` | object | no | Per-workload overrides merged on top of `appEnvVars` |
| `ingestionStorageAccountName` | string | yes | Storage account hosting the queue (KEDA scaler metadata) |
| `ingestionQueueName` | string | no | Default `ingestion-events` (matches data-model.md §6) |
| `ingestQueueLength` | int | no | Default `5`; KEDA scales up by 1 replica per N messages |

## Outputs

| Output | Notes |
|---|---|
| `resourceId` / `name` / `defaultDomain` | Managed environment |
| `webAppFqdn` | Internal FQDN of `web` (resolves only inside platform VNet) |
| `apiAppFqdn` | Internal FQDN of `api` — plumb into web as `NEXT_PUBLIC_API_URL` |
| `webAppName` / `apiAppName` / `ingestJobName` | Resource names |
| `webAppResourceId` / `apiAppResourceId` / `ingestJobResourceId` | Resource IDs (consumed by `azd deploy`) |
| `webPrincipalId` / `apiPrincipalId` / `ingestPrincipalId` | UAMI principalId pass-throughs (convenience for downstream RBAC fan-out in T029) |

## KEDA workload-identity authentication

The `ingest` job's KEDA `azure-queue` scaler uses **identity-based** auth — the scale rule's `identity` field is set to `miIngestId`, and KEDA uses that UAMI's federated credentials to call the Storage Queue API. This is the only viable path because the storage account in T022 disables shared-key access. The wiring layer (T029) must assign **Storage Queue Data Reader** on the storage account to `mi-ingest`.

## Local validation

```pwsh
az bicep build --file infra/modules/containerapps/main.bicep
```

Exit 0, zero compile warnings expected.
