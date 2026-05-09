# Network Module

Foundational networking for the Private RAG Accelerator (Phase 2a, T017 / PR-B).

This module is a **self-contained unit**: the call from `infra/main.bicep` is
wired up later in PR-O (T029/T030). Until then, `main.bicep` ships the
parameter contract as a commented placeholder block — this README documents the
matching shape so that wiring is mechanical.

---

## Purpose

Provision the trust boundary for the entire stack:

- **VNet** `10.0.0.0/22` (1024 IPs) — single VNet, no peering in Phase 2a.
- **5 subnets** with deterministic names and CIDRs.
- **5 NSGs** — one per subnet, deny-by-default for Internet inbound, scoped
  Allow rules per subnet purpose.
- **13 Private DNS zones** + a VNet link from each → this VNet, so private
  endpoints resolve to internal IPs from inside the VNet.

The module enforces **Constitution Principle I (zero public endpoints)**:
no resource here exposes a public IP or `publicNetworkAccess: Enabled` field.
Bastion's public IP, when deployed, is owned by the bastion module (PR-N).

---

## IP allocation

VNet address space: `10.0.0.0/22` — total **1024** addresses.

| Subnet                | CIDR             | IPs | Delegation                    | Purpose                                                                                 |
|-----------------------|------------------|----:|-------------------------------|-----------------------------------------------------------------------------------------|
| `snet-aca`            | `10.0.0.0/24`    | 256 | `Microsoft.App/environments`  | Container Apps Environment infrastructure (apps + jobs share one env).                  |
| `snet-pe`             | `10.0.1.0/24`    | 256 | none                          | All Private Endpoint NICs **+ jumpbox VM** (per Phase 2a v3 plan, conserves IP space).  |
| `snet-jobs`           | `10.0.2.0/24`    | 256 | none                          | **RESERVED** — no resources deploy here in Phase 2a.                                     |
| `AzureBastionSubnet`  | `10.0.3.0/26`    |  64 | none (Bastion-required name)  | Reserved for Bastion Basic/Standard. Not used by Bastion Developer (free portal-only).   |
| `snet-apim`           | `10.0.3.64/27`   |  32 | none                          | APIM VNet-injected (internal mode). /27 = APIM minimum.                                  |
| **Free**              | `10.0.3.96/27`   |  32 | —                             | Reserved headroom for future use (snet-aca-jobs split, etc.).                            |

> `snet-jobs` is intentionally reserved (not removed) to preserve the IP plan
> for a possible future second ACA env or Functions deployment without re-IPing
> the VNet. Per the v3 plan the NSG denies Internet inbound, so an accidental
> deploy can't expose a public surface.

---

## Private DNS zones

All 13 zones are created and VNet-linked when `customerProvidedDns = false`
(the default). When `true`, zones are NOT created — the caller is responsible
for DNS forwarding into this VNet.

| # | Zone                                           | Backs                                          |
|--:|------------------------------------------------|------------------------------------------------|
| 1 | `privatelink.openai.azure.com`                 | Azure OpenAI                                   |
| 2 | `privatelink.search.windows.net`               | AI Search                                      |
| 3 | `privatelink.documents.azure.com`              | Cosmos DB (NoSQL)                              |
| 4 | `privatelink.blob.core.windows.net`            | Storage (Blob)                                 |
| 5 | `privatelink.queue.core.windows.net`           | Storage (Queue) — required for private Event Grid delivery |
| 6 | `privatelink.vaultcore.azure.net`              | Key Vault                                      |
| 7 | `privatelink.azurecr.io`                       | Container Registry                             |
| 8 | `privatelink.cognitiveservices.azure.com`      | Document Intelligence (and other Cognitive)    |
| 9 | `privatelink.monitor.azure.com`                | AMPLS                                          |
|10 | `privatelink.oms.opinsights.azure.com`         | AMPLS — OMS                                    |
|11 | `privatelink.ods.opinsights.azure.com`         | AMPLS — ODS                                    |
|12 | `privatelink.agentsvc.azure-automation.net`    | AMPLS — agent service                          |
|13 | `azure-api.net`                                | APIM internal endpoints (gateway/portal/management/scm) — APIM internal mode does NOT use `privatelink.*` |

VNet links use `registrationEnabled: false` (we resolve PE A-records, not
register VM hostnames).

---

## NSG rules summary

Every NSG ends with a **`Deny-Internet-Inbound` (priority 4096)** rule.
Per-subnet Allow rules are applied at lower priorities.

| Subnet               | Inbound (Allow)                                                                       | Outbound (Allow)                                                                     |
|----------------------|---------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------|
| `snet-aca`           | `AzureLoadBalancer:*`, `VirtualNetwork:*`                                             | (Azure default — ACA Consumption manages egress)                                     |
| `snet-pe`            | `VirtualNetwork → :443`, `<bastion-cidr> → :22,3389`                                  | (Azure default)                                                                      |
| `snet-jobs`          | (none — RESERVED)                                                                     | (Azure default)                                                                      |
| `AzureBastionSubnet` | `Internet → :443`, `GatewayManager → :443`, `AzureLoadBalancer → :443`, `VNet:8080,5701` | `VNet → :22,3389`, `AzureCloud → :443`, `Internet → :80,443`, `VNet:8080,5701`        |
| `snet-apim`          | `ApiManagement → :3443`, `AzureLoadBalancer → :6390`, `VirtualNetwork:*`              | `VNet → Storage:443`, `VNet → AzureKeyVault:443`, `VNet → AzureMonitor:443/1886`, `VNet:*` |

References:
- [Bastion NSG requirements](https://learn.microsoft.com/azure/bastion/bastion-nsg)
- [APIM internal VNet NSG requirements](https://learn.microsoft.com/azure/api-management/api-management-using-with-internal-vnet)

---

## AVM modules used vs hand-rolled

| Resource                  | Source                                              | Why                                                                                                                          |
|---------------------------|-----------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------|
| Private DNS Zone + VNet link | **AVM** `br/public:avm/res/network/private-dns-zone:0.8.1` | Mature, simple wrapper, built-in `virtualNetworkLinks` array — exactly the shape we need. Reduces 13 + 13 boilerplate to one loop. |
| VNet + Subnets            | **Hand-rolled** (`Microsoft.Network/virtualNetworks@2024-05-01`) | Subnets declared **inline** under the VNet (not as separate child resources) to avoid the well-known `AnotherOperationInProgress` race when 5 subnets deploy in parallel. AVM `virtual-network` produces correct subnets but its `subnets[*].networkSecurityGroupResourceId` shape adds extra indirection without buying us anything; inline is more transparent for review. |
| NSGs                      | **Hand-rolled** (`Microsoft.Network/networkSecurityGroups@2024-05-01`) | Per-subnet rule sets are highly specific (APIM `:3443`, Bastion port matrix). AVM NSG works but our rules are clearer as-written and we own them anyway. |

> If a future task wants to swap to AVM `virtual-network` and `network-security-group`,
> the IP plan and rule contract documented here is portable.

---

## Inputs

| Name                    | Type     | Default                | Notes                                                                       |
|-------------------------|----------|------------------------|-----------------------------------------------------------------------------|
| `location`              | string   | (required)             | Region — same as VNet/subnet location.                                       |
| `tags`                  | object   | (required)             | Applied to VNet, NSGs, and DNS zones.                                        |
| `vnetName`              | string   | (required)             | From caller's deterministic name map.                                        |
| `vnetAddressPrefix`     | string   | `10.0.0.0/22`          | Override only if you need a different IP plan.                               |
| `snetAcaName`           | string   | `snet-aca`             |                                                                             |
| `snetPeName`            | string   | `snet-pe`              |                                                                             |
| `snetJobsName`          | string   | `snet-jobs`            |                                                                             |
| `snetBastionName`       | string   | `AzureBastionSubnet`   | **Must remain `AzureBastionSubnet`** if you ever deploy Bastion Basic/Standard. |
| `snetApimName`          | string   | `snet-apim`            |                                                                             |
| `snetAcaPrefix`         | string   | `10.0.0.0/24`          |                                                                             |
| `snetPePrefix`          | string   | `10.0.1.0/24`          |                                                                             |
| `snetJobsPrefix`        | string   | `10.0.2.0/24`          | Reserved.                                                                    |
| `snetBastionPrefix`     | string   | `10.0.3.0/26`          | /26 minimum for Bastion Basic/Standard.                                      |
| `snetApimPrefix`        | string   | `10.0.3.64/27`         | /27 minimum for APIM.                                                        |
| `nsgAcaName`            | string   | (required)             |                                                                             |
| `nsgPeName`             | string   | (required)             |                                                                             |
| `nsgJobsName`           | string   | (required)             |                                                                             |
| `nsgBastionName`        | string   | (required)             |                                                                             |
| `nsgApimName`           | string   | (required)             |                                                                             |
| `customerProvidedDns`   | bool     | `false`                | When `true`, this module skips creating Private DNS zones.                   |
| `privateDnsZoneNames`   | array    | (13 well-known zones)  | Override only to add zones; do not remove the defaults — downstream modules depend on them. |

---

## Outputs

| Name                       | Type   | Notes                                                                                          |
|----------------------------|--------|------------------------------------------------------------------------------------------------|
| `vnetId`                   | string | Full resource ID.                                                                               |
| `vnetName`                 | string |                                                                                                |
| `snetAcaId`                | string | Subnet resource ID.                                                                             |
| `snetPeId`                 | string |                                                                                                |
| `snetJobsId`               | string |                                                                                                |
| `snetBastionId`            | string | `AzureBastionSubnet` ID — usable by the bastion module in PR-N.                                 |
| `snetApimId`               | string |                                                                                                |
| `privateDnsZoneIdList`     | array  | Zone IDs in input order. Empty strings when `customerProvidedDns=true`.                         |
| `privateDnsZoneNamesOut`   | array  | Echo of input names so callers can build maps without re-declaring.                             |
| `pdnsOpenaiId` … `pdnsApimId` | string | **13 named outputs** — one per well-known zone. Use these from downstream modules for clarity (e.g. `network.outputs.pdnsBlobId`). Empty string when `customerProvidedDns=true`. |
| `nsgIds`                   | object | `{ aca, pe, jobs, bastion, apim }` — NSG resource IDs for diagnostics/RBAC.                     |

> A single `name → id` map output (`privateDnsZoneIds object`) was attempted but
> hits Bicep `BCP182`: module collection outputs cannot be referenced from a
> `var` `[for]` body. The named outputs above are the supported workaround and
> are more ergonomic for downstream modules anyway.

---

## How `main.bicep` will consume this (PR-O preview)

The placeholder block already exists in `infra/main.bicep` (T015/PR-A); PR-O
just removes the leading `//`. Reproduced here for reference:

```bicep
module network 'modules/network/main.bicep' = {
  name: 'network'
  scope: rg
  params: {
    location:             location
    tags:                 tags
    vnetName:             names.vnet
    vnetAddressPrefix:    vnetAddressPrefix
    snetAcaName:          'snet-aca'
    snetAcaPrefix:        snetAcaPrefix
    snetPeName:           'snet-pe'
    snetPePrefix:         snetPePrefix
    snetJobsName:         'snet-jobs'
    snetJobsPrefix:       snetJobsPrefix
    snetBastionName:      'AzureBastionSubnet'
    snetBastionPrefix:    snetBastionPrefix
    snetApimName:         'snet-apim'
    snetApimPrefix:       snetApimPrefix
    nsgAcaName:           names.nsgAca
    nsgPeName:            names.nsgPe
    nsgJobsName:          names.nsgJobs
    nsgBastionName:       names.nsgBastion
    nsgApimName:          names.nsgApim
    customerProvidedDns:  customerProvidedDns
  }
}
```

Downstream PE modules (storage, cosmos, search, openai, etc.) reference
`network.outputs.snetPeId` for the PE NIC and the relevant `pdns*Id` output
for the Private DNS zone group A-record.

---

## Dependencies

- **Upstream:** none. This is the foundation module — first to deploy in
  Layer 1.
- **Downstream (Phase 2a):** every module that creates a Private Endpoint
  (storage, cosmos, search, openai, docintel, keyvault, registry, monitoring/AMPLS),
  the containerapps module (snet-aca delegation), the apim module (snet-apim),
  and the bastion module (snet-bastion + jumpbox in snet-pe).

## Validation

```powershell
az bicep build --file infra/modules/network/main.bicep --outdir $env:TEMP
```

Expected: exit 0, zero warnings.

## Constitution checklist

- [x] No `publicNetworkAccess: Enabled` anywhere — module owns no data-plane resources.
- [x] No public IPs (Bastion's public IP, when deployed, is owned by PR-N).
- [x] All data-plane services covered by a `privatelink.*` zone (incl. `queue.core.windows.net`).
- [x] APIM `azure-api.net` zone present (APIM internal mode does NOT use a `privatelink.*` form).
- [x] Every NSG terminates in `Deny-Internet-Inbound` (priority 4096).
- [x] Idempotent — all names caller-supplied, no `uniqueString()` for primary names.
