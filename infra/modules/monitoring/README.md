# `infra/modules/monitoring`

Observability foundation for the Private RAG Accelerator. Provides Log
Analytics, workspace-based Application Insights, and an Azure Monitor Private
Link Scope (AMPLS) so all telemetry ingestion and query traffic flows over
private endpoints — no public Monitor endpoints are exposed.

**Task:** T019 (Phase 2a, PR-D)
**Layer:** 2 (platform — depends on `network` for the PE subnet and private DNS zones)
**Constitution alignment:** Principle I (zero public endpoints), Principle II (idempotent IaC, AVM where mature)

---

## Resources Created

| # | Resource | Type | AVM? | Notes |
|---|----------|------|------|-------|
| 1 | Log Analytics workspace | `Microsoft.OperationalInsights/workspaces` | ✅ `avm/res/operational-insights/workspace:0.15.1` | `PerGB2018`, public ingest+query disabled |
| 2 | Application Insights | `Microsoft.Insights/components` | ✅ `avm/res/insights/component:0.7.1` | Workspace-based, public ingest+query disabled |
| 3 | Azure Monitor Private Link Scope | `Microsoft.Insights/privateLinkScopes` | ❌ Hand-rolled | Global, `PrivateOnly` ingestion+query |
| 4 | AMPLS scoped resource (LAW) | `…/privateLinkScopes/scopedResources` | ❌ Hand-rolled | Links LAW into the AMPLS |
| 5 | AMPLS scoped resource (App Insights) | `…/privateLinkScopes/scopedResources` | ❌ Hand-rolled | Links App Insights into the AMPLS |
| 6 | AMPLS private endpoint | `Microsoft.Network/privateEndpoints` | ❌ Hand-rolled | `groupIds: ['azuremonitor']` |
| 7 | Private DNS zone group | `…/privateDnsZoneGroups` | ❌ Hand-rolled | Registers all 5 monitor private DNS zones |

---

## Inputs

| Name | Type | Default | Required | Purpose |
|------|------|---------|----------|---------|
| `location` | string | — | ✅ | Region for LAW/App Insights/PE (AMPLS itself is `global`) |
| `tags` | object | `{}` | | Applied to all resources |
| `lawName` | string | — | ✅ | Log Analytics workspace name |
| `appInsightsName` | string | — | ✅ | App Insights component name |
| `amplsName` | string | — | ✅ | AMPLS resource name (global uniqueness scoped to RG) |
| `retentionInDays` | int (30–730) | `30` | | Workspace + AppInsights retention |
| `peSubnetId` | string | — | ✅ | Subnet for AMPLS PE (typically `snet-pe`) |
| `privateEndpointName` | string | `pe-${amplsName}` | | Override if naming convention diverges |
| `privateDnsZoneIdMonitor` | string | — | ✅ | `privatelink.monitor.azure.com` zone resource ID |
| `privateDnsZoneIdOms` | string | — | ✅ | `privatelink.oms.opinsights.azure.com` zone resource ID |
| `privateDnsZoneIdOds` | string | — | ✅ | `privatelink.ods.opinsights.azure.com` zone resource ID |
| `privateDnsZoneIdAgentSvc` | string | — | ✅ | `privatelink.agentsvc.azure-automation.net` zone resource ID |
| `privateDnsZoneIdBlob` | string | — | ✅ | `privatelink.blob.core.windows.net` zone resource ID (used by the LA agent storage endpoint) |

---

## Outputs

| Name | Type | Consumers |
|------|------|-----------|
| `lawId` | string | Diagnostic settings on every other module |
| `lawName` | string | Convenience for `Microsoft.Insights/diagnosticSettings` references |
| `appInsightsId` | string | APIM diagnostics, ACA app definitions |
| `appInsightsConnectionString` | string | ACA app/job env vars (`APPLICATIONINSIGHTS_CONNECTION_STRING`) |
| `appInsightsInstrumentationKey` | string | Legacy SDKs only — prefer the connection string |
| `amplsId` | string | Diagnostics consumers; future scoped-resource additions |
| `amplsPrivateEndpointId` | string | Optional downstream wiring/audit |

> **Diagnostic settings stub:** This module deliberately does **not** create
> diagnostic settings on the LAW or App Insights themselves. Each consuming
> module owns its own `Microsoft.Insights/diagnosticSettings` resource and
> wires `lawId` from this module's outputs. That keeps the dependency arrow
> one-way and avoids circular refs in `main.bicep`.

---

## Retention Strategy

`retentionInDays` defaults to **30** (the free-tier ceiling for `PerGB2018`).
At ~few-MB-per-day demo volume this keeps Log Analytics ingestion under
~$8/mo and App Insights at ~$2/mo per Ripley's Phase 2a v3 cost plan
(`.squad/agents/ripley/phase-2-plan.md`). Production workloads should raise
this to 90–180 days and accept the linear cost increase — the parameter is
gated `30..730`.

---

## AMPLS Configuration Notes (Hand-Rolled — Read These)

There is **no AVM module** for AMPLS. The hand-rolled implementation has
several subtle pitfalls:

1. **`accessModeSettings` is the only enforcement knob.** AMPLS does not
   expose a `publicNetworkAccess` property. Setting both `ingestionAccessMode`
   and `queryAccessMode` to `PrivateOnly` is what guarantees scoped resources
   only accept private-link traffic, regardless of their own
   `publicNetworkAccessForIngestion` flag. We disable the per-resource flags
   too as defense in depth, but AMPLS is the source of truth.

2. **Private endpoint group ID is `azuremonitor` (single group).** This single
   PE drives **five** companion private DNS zones — `monitor.azure.com`,
   `oms.opinsights.azure.com`, `ods.opinsights.azure.com`,
   `agentsvc.azure-automation.net`, and `blob.core.windows.net`. Missing any
   one will cause partial DNS resolution failures that surface as random
   ingestion errors. The DNS zone group registers all five together.

3. **`blob.core.windows.net` is shared with Storage.** The same private DNS
   zone is also used by the `storage` module's blob PE. Caller (`main.bicep`)
   must pass the **same** zone resource ID to both modules; do not create two
   zones with the same name in the same VNet — Azure DNS resolution will be
   non-deterministic.

4. **AMPLS is a global resource (`location: 'global'`).** Do not parameterize
   its location. All other resources here are regional.

5. **Scoped resource names are not user-visible.** We use
   `${lawName}-link` / `${appInsightsName}-link` purely for idempotency and
   diagnostic clarity — Azure does not display these anywhere.

---

## Cost Estimate (per Ripley v3)

| Component | Estimate | Notes |
|-----------|----------|-------|
| Log Analytics ingestion (PerGB2018, 30d retention) | ~$8/mo | Free tier covers 5 GB/mo at light demo volume |
| Application Insights (workspace-based) | ~$2/mo | Inherits LAW pricing |
| AMPLS resource | $0 | Free; PE costs counted separately |
| AMPLS private endpoint | ~$7/mo | One PE; counted in network module budget line |
| **Module total (excluding PE)** | **~$10/mo** | Comfortably under the $500/mo cap |

---

## Validation

```powershell
az bicep build --file infra/modules/monitoring/main.bicep --outdir $env:TEMP
```

Must exit `0` with no errors. Warnings about unused outputs in downstream
consumers are expected until `main.bicep` is wired (PR-O / T029).

---

## Wiring (for PR-O / T029, not this PR)

`main.bicep` will call this module after `network` so PE subnet and private
DNS zone IDs are available. Sketch:

```bicep
module monitoring 'modules/monitoring/main.bicep' = {
  name: 'monitoring'
  scope: rg
  dependsOn: [network]
  params: {
    location: location
    tags: tags
    lawName: names.law
    appInsightsName: names.appInsights
    amplsName: names.ampls
    retentionInDays: 30
    peSubnetId: network.outputs.snetPeId
    privateDnsZoneIdMonitor: network.outputs.privateDnsZoneIdMonitor
    privateDnsZoneIdOms: network.outputs.privateDnsZoneIdOms
    privateDnsZoneIdOds: network.outputs.privateDnsZoneIdOds
    privateDnsZoneIdAgentSvc: network.outputs.privateDnsZoneIdAgentSvc
    privateDnsZoneIdBlob: network.outputs.privateDnsZoneIdBlob
  }
}
```
