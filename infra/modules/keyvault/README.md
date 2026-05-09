# `infra/modules/keyvault`

Azure Key Vault module for the Private RAG Accelerator. Deploys a Standard-SKU
vault that is **only** reachable through a private endpoint in `snet-pe` and
authorized exclusively via Azure RBAC.

## Purpose

- Holds CMK keys (when `enableCustomerManagedKey=true`) and any
  Key Vault–referenced secrets needed by APIM named values or future
  components. App-to-service auth is managed identity by default — no app
  secrets live in Key Vault in v1.
- Zero public surface: `publicNetworkAccess: 'Disabled'`, network ACLs
  `defaultAction: 'Deny'`, no firewall IP exceptions.
- All access goes through a private endpoint resolved via the
  `privatelink.vaultcore.azure.net` private DNS zone.

## Module source

Wraps [`avm/res/key-vault/vault`](https://github.com/Azure/bicep-registry-modules/tree/main/avm/res/key-vault/vault)
at version **0.13.3** (`br/public:avm/res/key-vault/vault:0.13.3`).

## Inputs

| Name | Type | Required | Description |
|---|---|---|---|
| `location` | `string` | yes | Azure region. |
| `tags` | `object` | no (default `{}`) | Tags applied to vault and PE. |
| `vaultName` | `string` (3–24) | yes | Globally unique Key Vault name. |
| `peSubnetId` | `string` | yes | Resource ID of `snet-pe`. |
| `privateDnsZoneId` | `string` | yes | Resource ID of `privatelink.vaultcore.azure.net`. |
| `lawId` | `string` | yes | Resource ID of the Log Analytics workspace for diagnostics. |
| `softDeleteRetentionInDays` | `int` (7–90) | no (default `7`) | Soft-delete retention window. |

## Outputs

| Name | Description |
|---|---|
| `kvId` | Vault resource ID. |
| `kvName` | Vault name. |
| `kvUri` | Vault DNS URI (`https://<name>.vault.azure.net/`). |
| `peId` | Private endpoint resource ID. |

## RBAC model — RBAC only, no access policies

`enableRbacAuthorization: true`. **All grants** must be made via
`Microsoft.Authorization/roleAssignments` against the vault scope using the
built-in roles below. Access policies are never used for new vaults in this
codebase.

| Role | Used by |
|---|---|
| Key Vault Secrets User | APIM named-value MI, app workloads needing read access |
| Key Vault Secrets Officer | Operator/admin group |
| Key Vault Crypto User | Cosmos / Storage / AOAI MIs (CMK key wrap/unwrap) |
| Key Vault Administrator | `adminGroupObjectId` (break-glass) |

Role assignments themselves are wired in PR-N (RBAC) and PR-O (main wiring),
not in this module.

## Private-only access

- `publicNetworkAccess: 'Disabled'`
- `networkAcls.defaultAction: 'Deny'`, `bypass: 'AzureServices'`
- Single private endpoint targeting subresource `vault` in `snet-pe`,
  registered into the `privatelink.vaultcore.azure.net` zone.
- The vault is unreachable from the public internet; clients must resolve
  the privatelink CNAME via the hub's private DNS zone (linked to the spoke
  VNet by the network module).

## Soft-delete & purge protection

- `enableSoftDelete: true`
- `softDeleteRetentionInDays: 7` — minimum value, picked to keep storage
  cost in line with the **$500/mo** demo ceiling. Production deployments
  should override to 90.
- `enablePurgeProtection: true` — once on, cannot be disabled. Required for
  CMK scenarios on Cosmos / Storage / AOAI.

## Diagnostic settings

A single diagnostic setting (`diag-to-law`) ships:

- `categoryGroup: 'allLogs'` (AuditEvent + AzurePolicyEvaluationDetails, etc.)
- `category: 'AllMetrics'`

…to the Log Analytics workspace passed via `lawId` (output of the
`monitoring` module).

## Cost

≈ **$2/month** in the demo footprint (Standard SKU has no monthly resource
fee; cost is operations-based and dominated by the private endpoint —
~$7.30/mo PE billed against the network module). Vault-side ops for the
demo are negligible.

## Constitution alignment

- **Principle I (zero public endpoints):** `publicNetworkAccess: 'Disabled'`,
  network ACLs default `Deny`, private endpoint only.
- **Principle II (idempotent IaC):** Pure declarative AVM call; same inputs
  produce the same state; no inline secrets — Key Vault references / managed
  identity only.

## Validation

```powershell
az bicep build --file infra/modules/keyvault/main.bicep --outdir $env:TEMP
```

Should exit with code 0 and no warnings.

## Wiring

`infra/main.bicep` consumes this module in PR-O (T029/T030). Wiring example:

```bicep
module keyvault 'modules/keyvault/main.bicep' = {
  name: 'keyvault'
  scope: rg
  params: {
    location: location
    tags: tags
    vaultName: names.keyvault
    peSubnetId: network.outputs.peSubnetId
    privateDnsZoneId: network.outputs.dnsZoneIds.keyvault
    lawId: monitoring.outputs.lawId
  }
}
```
