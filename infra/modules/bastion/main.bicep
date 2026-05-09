// =============================================================================
// Module: bastion
// Task:   T028 (Phase 2a / PR-N)
// Purpose: Azure Bastion (Developer SKU, $0/mo) plus a Linux jumpbox VM (B2s,
//          ~$36/mo) for break-glass admin access into the private VNet.
//
// SKU deviation:
//   tasks.md T028 says "Bastion Standard". Phase 2a v3 plan caps cost at
//   $500/mo and switches to Developer SKU. Permanently accepted in
//   .squad/decisions/inbox/copilot-directive-20260509T062045Z-phase2a-wave3-audit.md §4.
//
// Wiring contract:
//   - Inputs:
//       deployBastion   (bool)   gate the entire module
//       bastionSubnetId (string) AzureBastionSubnet (only used to derive vnet id)
//       vmSubnetId      (string) snet-pe — jumpbox NIC lands here (VMs cannot
//                                live in AzureBastionSubnet)
//       lawId           (string) Log Analytics workspace for diag (jumpbox only —
//                                Developer-SKU Bastion does not emit
//                                BastionAuditLogs; see README)
//       adminPublicKey  (secure) SSH public key for the jumpbox
//
//   - Outputs:
//       bastionResourceId, bastionName, jumpboxResourceId,
//       jumpboxPrincipalId (system-assigned MI for later RBAC, e.g. AcrPull),
//       jumpboxPrivateIp
//
// Constitution checks:
//   - Zero public endpoints on the jumpbox (NIC has no public IP)
//   - SSH key auth only (password authentication disabled)
//   - Diagnostics → LAW for the jumpbox NIC; Developer-SKU Bastion is shared
//     Microsoft infra and does not support diagnosticSettings (see README)
//   - Auto-shutdown 18:00 UTC via DevTest Lab schedule to control burn rate
// =============================================================================

targetScope = 'resourceGroup'

// -----------------------------------------------------------------------------
// Parameters
// -----------------------------------------------------------------------------

@description('Master gate. When false, this module deploys nothing and emits empty outputs.')
param deployBastion bool = true

@description('Base name used to derive child resource names (bas-{name}, vm-jump-{name}).')
@minLength(2)
@maxLength(20)
param name string

@description('Azure region for all resources in this module.')
param location string

@description('Resource tags applied to every resource the module creates.')
param tags object = {}

@description('Resource ID of AzureBastionSubnet. Only used to derive the parent VNet resource ID for the Developer-SKU Bastion host (Developer SKU takes virtualNetworkResourceId, not subnet/PIP).')
param bastionSubnetId string

@description('Resource ID of the snet-pe subnet. The jumpbox NIC lives here — VMs are not permitted in AzureBastionSubnet.')
param vmSubnetId string

@description('Resource ID of the Log Analytics workspace for jumpbox NIC diagnostics.')
param lawId string

@description('Linux admin username for the jumpbox.')
param adminUsername string = 'azureuser'

@description('SSH public key (single line, e.g. "ssh-rsa AAAA…") for the jumpbox admin user. Password auth is disabled.')
@secure()
param adminPublicKey string

@description('Jumpbox VM size. B2s (2 vCPU / 4 GiB) is the budgeted SKU under the $500/mo cap.')
param vmSize string = 'Standard_B2s'

// -----------------------------------------------------------------------------
// Derived values
// -----------------------------------------------------------------------------

// AzureBastionSubnet is /<vnetId>/subnets/AzureBastionSubnet. Strip the suffix
// to get the VNet resource ID that the Developer-SKU Bastion host requires.
var virtualNetworkResourceId = split(bastionSubnetId, '/subnets/')[0]

var bastionName = 'bas-${name}'
var jumpboxName = 'vm-jump-${name}'

// -----------------------------------------------------------------------------
// Bastion Host (Developer SKU) — AVM br/public:avm/res/network/bastion-host:0.8.2
//   - skuName 'Developer' is free, single concurrent session, shared backend.
//   - Developer SKU does NOT take a Public IP and does NOT support
//     diagnosticSettings (verified against AVM 0.8.2 e2e test
//     `tests/e2e/developer/main.test.bicep` which omits both).
//   - The AVM module guards Premium/Standard-only flags internally; we only
//     need to provide name, vnet id, and skuName.
// -----------------------------------------------------------------------------
module bastionHost 'br/public:avm/res/network/bastion-host:0.8.2' = if (deployBastion) {
  name: 'bastion-${uniqueString(bastionName)}'
  params: {
    name: bastionName
    location: location
    tags: tags
    skuName: 'Developer'
    virtualNetworkResourceId: virtualNetworkResourceId
    enableTelemetry: false
  }
}

// -----------------------------------------------------------------------------
// Jumpbox (NIC + VM + auto-shutdown) — hand-rolled in jumpbox.bicep
// -----------------------------------------------------------------------------
module jumpbox 'jumpbox.bicep' = if (deployBastion) {
  name: 'jumpbox-${uniqueString(jumpboxName)}'
  params: {
    name: jumpboxName
    location: location
    tags: tags
    vmSubnetId: vmSubnetId
    lawId: lawId
    adminUsername: adminUsername
    adminPublicKey: adminPublicKey
    vmSize: vmSize
  }
}

// -----------------------------------------------------------------------------
// Outputs — empty strings when the module is gated off so callers can wire
// these into azd env values without conditional logic.
// -----------------------------------------------------------------------------

@description('Resource ID of the Bastion host. Empty string when deployBastion=false.')
output bastionResourceId string = deployBastion ? bastionHost!.outputs.resourceId : ''

@description('Name of the Bastion host. Empty string when deployBastion=false.')
output bastionName string = deployBastion ? bastionHost!.outputs.name : ''

@description('Resource ID of the jumpbox VM. Empty string when deployBastion=false.')
output jumpboxResourceId string = deployBastion ? jumpbox!.outputs.vmId : ''

@description('System-assigned managed identity principalId of the jumpbox VM. Used by PR-O for RBAC (e.g. AcrPull). Empty string when deployBastion=false.')
output jumpboxPrincipalId string = deployBastion ? jumpbox!.outputs.principalId : ''

@description('Private IP address of the jumpbox NIC. Empty string when deployBastion=false.')
output jumpboxPrivateIp string = deployBastion ? jumpbox!.outputs.privateIp : ''
