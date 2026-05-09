# `infra/modules/apim`

Azure API Management — **Developer SKU, Internal VNet mode**.
Task **T032a** (Phase 2a / PR-L).

## What this module ships (Phase 2a)

- One APIM service, **Developer** SKU (`skuCapacity: 1` — only value Developer supports).
- **`virtualNetworkType: 'Internal'`** — full VNet injection. Every endpoint
  (`gateway`, `portal`, `management`, `scm`, `devportal`) resolves to a
  VNet-internal load-balancer IP. **No public IP** on the gateway.
- VNet-injected into the dedicated **`snet-apim`** subnet (`/27`) emitted by
  the network module as `network.outputs.snetApimId`.
- **System-assigned managed identity** — consumed by PR-O for RBAC to
  AOAI / Key Vault / etc.
- TLS / cipher hardening via `customProperties`:
  - TLS 1.0, TLS 1.1, SSL 3.0 disabled (gateway and backend).
  - HTTP/2 enabled on the gateway.
  - 3DES + non-PFS CBC ciphers disabled.
- Diagnostics → Log Analytics (`allLogs` group, `AllMetrics`).
- Built-in **App Insights logger** (`Microsoft.ApiManagement/service/loggers`)
  wired against `appInsightsId` + `appInsightsConnectionString`.
  Diagnostics policies bind to this logger in Phase 3.

## Out of scope (deferred to Phase 3)

- AI gateway policies (rate-limit, token-quota, content-filter on AOAI).
- Backend declarations (AOAI, AI Search, ACA apps).
- API definitions / OpenAPI imports.
- JWT validation policy wiring (the APIM app registration is owned by the
  identity module; the policy itself is Phase 3).

## Module contract

| Direction | Name | Type | Notes |
| --- | --- | --- | --- |
| in  | `name` | string | Globally unique APIM name. |
| in  | `location` | string | Must offer Developer SKU + VNet injection. |
| in  | `tags` | object | Resource tags. |
| in  | `peSubnetId` | string | `network.outputs.snetApimId` — the dedicated `/27` APIM subnet. Note: kept as `peSubnetId` to mirror the naming used by the other zero-trust modules; this is **not** a private endpoint subnet, it is the VNet-injection subnet. |
| in  | `lawId` | string | Log Analytics workspace resource ID. |
| in  | `appInsightsId` | string | App Insights resource ID for the built-in logger. |
| in  | `appInsightsConnectionString` | `@secure()` string | Connection string for the App Insights logger. |
| in  | `publisherEmail` | string | Defaults to `arbaaz@example.com`. Override per env. |
| in  | `publisherName` | string | Defaults to `Private RAG Accelerator`. |
| out | `resourceId` | string | RBAC scope, backend registrations. |
| out | `name` | string | APIM service name. |
| out | `gatewayUrl` | string | Internal gateway URL `https://<name>.azure-api.net` (resolves to VNet-internal VIP via the `azure-api.net` private DNS zone created by the network module). |
| out | `principalId` | string | System-assigned MI principal ID. |

## SKU lock — do not bump

The SKU is **hard-coded to `Developer`** (`var apimSku = 'Developer'`). It is
not a parameter on this module by design.

The cost ceiling decision (`.squad/decisions.md` 2026-05-08T20:13:37Z) caps
the entire demo at **$500/mo**. APIM Premium is **~$2,800/mo**, which alone
blows the cap by 5.6×. v2 of the Phase 2 plan defaulted to Premium and was
explicitly killed by Arbyam. Production callers needing Premium SKU (HA, SLA,
multi-region) should fork or extend this module — do **not** turn the SKU
into a parameter here, as that re-opens the door to a $2,800 surprise bill.

## ⚠️ Deployment time

- **First deploy: ~30–45 minutes** for Developer SKU.
- VNet injection (Internal mode) adds **~10 minutes** on top.
- Subsequent updates are faster but can still take 5–15 minutes.
- Set `azd` / pipeline timeouts accordingly.

## NSG dependency on `snet-apim`

APIM internal VNet mode requires very specific NSG rules. The network module
(`infra/modules/network/main.bicep`) owns `nsgApim` and **already provides
the core ones** required for the service to come up:

| Direction | Source / Destination | Port(s) | Status in network module |
| --- | --- | --- | --- |
| Inbound  | `ApiManagement` → `VirtualNetwork`        | TCP 3443       | ✅ present |
| Inbound  | `AzureLoadBalancer` → `VirtualNetwork`    | TCP 6390       | ✅ present |
| Inbound  | `VirtualNetwork` → `VirtualNetwork`       | TCP 80/443/any | ✅ present (VNet allow-all) |
| Outbound | `VirtualNetwork` → `Storage`              | TCP 443        | ✅ present |
| Outbound | `VirtualNetwork` → `AzureKeyVault`        | TCP 443        | ✅ present |
| Outbound | `VirtualNetwork` → `AzureMonitor`         | TCP 443, 1886  | ✅ present |
| Outbound | `VirtualNetwork` → `Sql`                  | TCP 1433       | ⚠️ **missing — follow-up needed** |
| Outbound | `VirtualNetwork` → `EventHub`             | TCP 5671, 5672, 443 | ⚠️ **missing — follow-up needed** |

The two missing rules are flagged to PR-O / a network-module follow-up. They
do **not** block this PR — APIM will still create successfully without them
(the existing VNet allow-all outbound currently covers most paths inside the
VNet), but the explicit service-tag rules are required for a hardened
internal-mode posture and should land before Phase 3 traffic flows.

## Constitution checklist

- [x] **Zero public endpoints** — `virtualNetworkType: 'Internal'`; gateway,
      portal, management, scm all bind to a VNet-internal VIP.
- [x] **TLS 1.0 / 1.1 disabled** — `customProperties` flags above.
- [x] **Diagnostics → LAW + App Insights** — `diagnosticSettings` block plus
      built-in `applicationInsights` logger.
- [x] **Idempotent** — AVM `avm/res/api-management/service:0.14.1`,
      deterministic naming, no `newGuid()` used in our caller scope.

## Validation

```pwsh
az bicep build --file infra/modules/apim/main.bicep
```

Expected: exit 0, zero warnings.

## AVM module

Pinned to **`br/public:avm/res/api-management/service:0.14.1`** — latest
stable as of 2026-05-08. Verified to support:

- `Developer` SKU + `virtualNetworkType: 'Internal'` + `subnetResourceId`.
- `managedIdentities.systemAssigned` → `SystemAssigned` identity type.
- `customProperties` passthrough.
- `loggers` of `type: 'applicationInsights'` with `targetResourceId` +
  `credentials.connectionString`.
- `diagnosticSettings` (workspaceResourceId + log/metric category groups).
