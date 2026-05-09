# `infra/modules/registry` — Azure Container Registry (Premium, PE-only)

**Task:** T020 — Phase 2a / PR-E
**AVM module:** [`br/public:avm/res/container-registry/registry:0.12.1`](https://github.com/Azure/bicep-registry-modules/tree/main/avm/res/container-registry/registry)

## Purpose

Provisions the platform Azure Container Registry that hosts images for every
container app and job in the accelerator. Premium SKU is mandatory because
it is the only ACR tier that supports private endpoints — required by
**SC-004** and **Constitution Principle I (zero public endpoints)**.

## Security posture

| Control | Setting | Why |
|---|---|---|
| `publicNetworkAccess` | `Disabled` | No public network plane reachable. |
| Anonymous pull | `Disabled` | All pulls must authenticate. |
| Admin user | `Disabled` | Forces Entra-ID / managed-identity auth — no shared secrets. |
| Private endpoint | `snet-pe` | Single ingress path through the platform VNet. |
| Private DNS | `privatelink.azurecr.io` | Internal name resolution; no public DNS leak. |
| Soft delete | `enabled` (7 days default) | Recoverable from accidental manifest delete. |
| Retention policy | `enabled` (7 days default) | Untagged manifests purged on schedule. |

Authentication uses the per-app User-Assigned Managed Identities created in
PR-C (`mi-api`, `mi-ingest`, `mi-web`). The **AcrPull** role assignment is
NOT performed in this module — it lives in the PR-O wiring layer
(T029/T030), which consumes `acrId` from this module's outputs.

## Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `location` | `string` | — | Azure region. |
| `tags` | `object` | `{}` | Tags applied to the registry and its PE. |
| `acrName` | `string` | — | Globally-unique ACR name (5–50 chars, lowercase alphanumeric). Caller strips hyphens. |
| `acrSku` | `string` | `'Premium'` | Pinned to `Premium` — only PE-capable tier. |
| `peSubnetId` | `string` | — | Resource ID of `snet-pe`. |
| `privateDnsZoneId` | `string` | — | Resource ID of `privatelink.azurecr.io`. |
| `softDeleteRetentionDays` | `int` | `7` | Soft-delete + untagged-retention window (1–90). |

## Outputs

| Name | Description | Consumer |
|---|---|---|
| `acrId` | Registry resource ID. | PR-O — AcrPull role assignments to per-app UAMIs. |
| `acrName` | Registry name. | App config / diagnostics. |
| `acrLoginServer` | FQDN (e.g., `myacr.azurecr.io`). | Container Apps `image:` references. |
| `peId` | Private-endpoint resource ID. | Diagnostics / connectivity tests. |

## Cost

**~$50/month** (Premium SKU, $1.667/day, 500 GB included). Per-day pricing
applies even when no images are pushed; this is unavoidable for any
PE-enabled ACR. Egress and overage storage are pay-as-you-go.

## Validation

```powershell
az bicep build --file infra/modules/registry/main.bicep --outdir $env:TEMP
```

Must exit `0` with no errors.

## Related

- **PR-B / network** — produces `peSubnetId` (snet-pe) and `privateDnsZoneId` (`privatelink.azurecr.io`).
- **PR-C / identity** — produces the `mi-api`, `mi-ingest`, `mi-web` UAMIs that consume AcrPull.
- **PR-O / wiring** — assigns AcrPull on `acrId` for each consumer UAMI.
- **PR-J / containerapps** — references `acrLoginServer` for image pulls.
