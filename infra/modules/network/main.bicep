// =============================================================================
// Network Module — VNet, Subnets, NSGs, Private DNS Zones
// =============================================================================
// targetScope  : resourceGroup
// Owns         : VNet (10.0.0.0/22) + 5 subnets + 5 NSGs + 13 Private DNS Zones
//                + VNet links from each DNS zone back to the VNet.
//
// Constitution Principle I (zero public endpoints)
//   - No publicNetworkAccess fields here (data-plane only). NSGs deny inbound
//     from Internet by default. Bastion + Bastion subnet rules are applied so
//     PR-N (bastion module) can drop a Host in without touching this module.
//
// Constitution Principle II (idempotent IaC)
//   - All names are caller-supplied (deterministic from main.bicep). No use of
//     uniqueString() or runtime randomness.
//
// AVM USAGE
//   - VNet, Subnets, NSGs              : hand-rolled (see README rationale)
//   - Private DNS Zones + VNet links   : avm/res/network/private-dns-zone:0.7.1
//
// CONSUMERS
//   - main.bicep (PR-O / T029 / T030) — uncomments the module call shown in the
//     T017/PR-B placeholder block.
// =============================================================================

targetScope = 'resourceGroup'

// =============================================================================
// PARAMETERS
// =============================================================================

@description('Azure region for all resources in this module.')
param location string

@description('Tags applied to every resource in this module.')
param tags object

// VNet ------------------------------------------------------------------------

@description('VNet resource name (deterministic, from caller).')
param vnetName string

@description('VNet address space CIDR. Default 10.0.0.0/22 = 1024 IPs total.')
param vnetAddressPrefix string = '10.0.0.0/22'

// Subnet names (from caller for testability) ----------------------------------

@description('Container Apps Environment infrastructure subnet name.')
param snetAcaName string = 'snet-aca'

@description('Private Endpoints + jumpbox VM subnet name.')
param snetPeName string = 'snet-pe'

@description('RESERVED subnet name for future expansion (no resources deployed).')
param snetJobsName string = 'snet-jobs'

@description('Azure Bastion subnet — MUST be exactly "AzureBastionSubnet".')
param snetBastionName string = 'AzureBastionSubnet'

@description('Azure API Management subnet name (VNet-injected, internal mode).')
param snetApimName string = 'snet-apim'

// Subnet CIDRs ----------------------------------------------------------------

@description('Container Apps subnet CIDR. /24 = 256 IPs (Consumption profile minimum is /27).')
param snetAcaPrefix string = '10.0.0.0/24'

@description('Private Endpoints + jumpbox subnet CIDR.')
param snetPePrefix string = '10.0.1.0/24'

@description('Reserved subnet CIDR for future expansion.')
param snetJobsPrefix string = '10.0.2.0/24'

@description('Azure Bastion subnet CIDR. /26 minimum required by Azure for Basic/Standard SKUs.')
param snetBastionPrefix string = '10.0.3.0/26'

@description('APIM subnet CIDR. /27 minimum (1 internal VIP + reserved + scaling).')
param snetApimPrefix string = '10.0.3.64/27'

// NSG names (from caller) -----------------------------------------------------

@description('NSG name for snet-aca.')
param nsgAcaName string

@description('NSG name for snet-pe.')
param nsgPeName string

@description('NSG name for snet-jobs (reserved).')
param nsgJobsName string

@description('NSG name for AzureBastionSubnet.')
param nsgBastionName string

@description('NSG name for snet-apim.')
param nsgApimName string

// Private DNS -----------------------------------------------------------------

@description('When true, Private DNS zones are NOT created — caller must wire up DNS forwarding to the VNet themselves. Default false: this module creates and links all 13 zones.')
param customerProvidedDns bool = false

@description('Private DNS zone names to create and link to the VNet. Defaults cover all Phase 2a data-plane services + APIM internal endpoints.')
param privateDnsZoneNames array = [
  'privatelink.openai.azure.com'
  'privatelink.search.windows.net'
  'privatelink.documents.azure.com'
  #disable-next-line no-hardcoded-env-urls
  'privatelink.blob.core.windows.net'
  #disable-next-line no-hardcoded-env-urls
  'privatelink.queue.core.windows.net'
  'privatelink.vaultcore.azure.net'
  'privatelink.azurecr.io'
  'privatelink.cognitiveservices.azure.com'
  'privatelink.monitor.azure.com'
  'privatelink.oms.opinsights.azure.com'
  'privatelink.ods.opinsights.azure.com'
  'privatelink.agentsvc.azure-automation.net'
  'azure-api.net'
]

// =============================================================================
// VARIABLES
// =============================================================================

var vnetLinkName = 'link-${vnetName}'

// Common deny-inbound-internet rule used by every subnet's NSG. APIM and
// Bastion stack their targeted Allow rules at lower priorities BEFORE this one.
var denyInboundInternetRule = {
  name: 'Deny-Internet-Inbound'
  properties: {
    priority:                 4096
    direction:                'Inbound'
    access:                   'Deny'
    protocol:                 '*'
    sourceAddressPrefix:      'Internet'
    sourcePortRange:          '*'
    destinationAddressPrefix: '*'
    destinationPortRange:     '*'
  }
}

// =============================================================================
// NSGs — created BEFORE the VNet so subnets reference them at deploy time
// =============================================================================

// snet-aca --------------------------------------------------------------------
// ACA Consumption manages most outbound traffic itself. We allow VNet-internal
// traffic and Azure LB probe; deny direct Internet inbound.
resource nsgAca 'Microsoft.Network/networkSecurityGroups@2024-05-01' = {
  name:     nsgAcaName
  location: location
  tags:     tags
  properties: {
    securityRules: [
      {
        name: 'Allow-AzureLoadBalancer-Inbound'
        properties: {
          priority:                 100
          direction:                'Inbound'
          access:                   'Allow'
          protocol:                 '*'
          sourceAddressPrefix:      'AzureLoadBalancer'
          sourcePortRange:          '*'
          destinationAddressPrefix: '*'
          destinationPortRange:     '*'
        }
      }
      {
        name: 'Allow-VNet-Inbound'
        properties: {
          priority:                 110
          direction:                'Inbound'
          access:                   'Allow'
          protocol:                 '*'
          sourceAddressPrefix:      'VirtualNetwork'
          sourcePortRange:          '*'
          destinationAddressPrefix: 'VirtualNetwork'
          destinationPortRange:     '*'
        }
      }
      denyInboundInternetRule
    ]
  }
}

// snet-pe ---------------------------------------------------------------------
// PE NICs bypass NSGs at the platform level, but we apply VNet-only rules so
// the jumpbox VM is hardened. SSH/RDP only from the Bastion subnet.
resource nsgPe 'Microsoft.Network/networkSecurityGroups@2024-05-01' = {
  name:     nsgPeName
  location: location
  tags:     tags
  properties: {
    securityRules: [
      {
        name: 'Allow-VNet-HTTPS-Inbound'
        properties: {
          priority:                 100
          direction:                'Inbound'
          access:                   'Allow'
          protocol:                 'Tcp'
          sourceAddressPrefix:      'VirtualNetwork'
          sourcePortRange:          '*'
          destinationAddressPrefix: 'VirtualNetwork'
          destinationPortRange:     '443'
        }
      }
      {
        name: 'Allow-Bastion-To-Jumpbox-Inbound'
        properties: {
          priority:                 110
          direction:                'Inbound'
          access:                   'Allow'
          protocol:                 'Tcp'
          sourceAddressPrefix:      snetBastionPrefix
          sourcePortRange:          '*'
          destinationAddressPrefix: '*'
          destinationPortRanges:    ['22', '3389']
        }
      }
      denyInboundInternetRule
    ]
  }
}

// snet-jobs (RESERVED) --------------------------------------------------------
// No resources deploy here in Phase 2a. NSG denies inbound Internet so an
// accidental future deploy doesn't expose a public surface. Kept minimal.
resource nsgJobs 'Microsoft.Network/networkSecurityGroups@2024-05-01' = {
  name:     nsgJobsName
  location: location
  tags:     tags
  properties: {
    securityRules: [
      denyInboundInternetRule
    ]
  }
}

// AzureBastionSubnet ----------------------------------------------------------
// Required NSG rules per Microsoft Bastion docs. Applied unconditionally so
// the NSG is idempotent across deployBastion=true|false transitions.
// Ref: https://learn.microsoft.com/azure/bastion/bastion-nsg
resource nsgBastion 'Microsoft.Network/networkSecurityGroups@2024-05-01' = {
  name:     nsgBastionName
  location: location
  tags:     tags
  properties: {
    securityRules: [
      {
        name: 'Allow-HttpsInBound-FromInternet'
        properties: {
          priority:                 100
          direction:                'Inbound'
          access:                   'Allow'
          protocol:                 'Tcp'
          sourceAddressPrefix:      'Internet'
          sourcePortRange:          '*'
          destinationAddressPrefix: '*'
          destinationPortRange:     '443'
        }
      }
      {
        name: 'Allow-GatewayManager-Inbound'
        properties: {
          priority:                 110
          direction:                'Inbound'
          access:                   'Allow'
          protocol:                 'Tcp'
          sourceAddressPrefix:      'GatewayManager'
          sourcePortRange:          '*'
          destinationAddressPrefix: '*'
          destinationPortRange:     '443'
        }
      }
      {
        name: 'Allow-AzureLoadBalancer-Inbound'
        properties: {
          priority:                 120
          direction:                'Inbound'
          access:                   'Allow'
          protocol:                 'Tcp'
          sourceAddressPrefix:      'AzureLoadBalancer'
          sourcePortRange:          '*'
          destinationAddressPrefix: '*'
          destinationPortRange:     '443'
        }
      }
      {
        name: 'Allow-BastionHostCommunication-Inbound'
        properties: {
          priority:                 130
          direction:                'Inbound'
          access:                   'Allow'
          protocol:                 '*'
          sourceAddressPrefix:      'VirtualNetwork'
          sourcePortRange:          '*'
          destinationAddressPrefix: 'VirtualNetwork'
          destinationPortRanges:    ['8080', '5701']
        }
      }
      {
        name: 'Allow-SshRdp-Outbound-To-VNet'
        properties: {
          priority:                 100
          direction:                'Outbound'
          access:                   'Allow'
          protocol:                 'Tcp'
          sourceAddressPrefix:      '*'
          sourcePortRange:          '*'
          destinationAddressPrefix: 'VirtualNetwork'
          destinationPortRanges:    ['22', '3389']
        }
      }
      {
        name: 'Allow-AzureCloud-Outbound'
        properties: {
          priority:                 110
          direction:                'Outbound'
          access:                   'Allow'
          protocol:                 'Tcp'
          sourceAddressPrefix:      '*'
          sourcePortRange:          '*'
          destinationAddressPrefix: 'AzureCloud'
          destinationPortRange:     '443'
        }
      }
      {
        name: 'Allow-BastionHostCommunication-Outbound'
        properties: {
          priority:                 120
          direction:                'Outbound'
          access:                   'Allow'
          protocol:                 '*'
          sourceAddressPrefix:      'VirtualNetwork'
          sourcePortRange:          '*'
          destinationAddressPrefix: 'VirtualNetwork'
          destinationPortRanges:    ['8080', '5701']
        }
      }
      {
        name: 'Allow-GetSessionInformation-Outbound'
        properties: {
          priority:                 130
          direction:                'Outbound'
          access:                   'Allow'
          protocol:                 'Tcp'
          sourceAddressPrefix:      '*'
          sourcePortRange:          '*'
          destinationAddressPrefix: 'Internet'
          destinationPortRanges:    ['80', '443']
        }
      }
    ]
  }
}

// snet-apim -------------------------------------------------------------------
// APIM internal VNet mode required rules.
// Ref: https://learn.microsoft.com/azure/api-management/api-management-using-with-internal-vnet
resource nsgApim 'Microsoft.Network/networkSecurityGroups@2024-05-01' = {
  name:     nsgApimName
  location: location
  tags:     tags
  properties: {
    securityRules: [
      {
        name: 'Allow-ApiManagement-Management-Inbound'
        properties: {
          priority:                 100
          direction:                'Inbound'
          access:                   'Allow'
          protocol:                 'Tcp'
          sourceAddressPrefix:      'ApiManagement'
          sourcePortRange:          '*'
          destinationAddressPrefix: 'VirtualNetwork'
          destinationPortRange:     '3443'
        }
      }
      {
        name: 'Allow-AzureLoadBalancer-Probe-Inbound'
        properties: {
          priority:                 110
          direction:                'Inbound'
          access:                   'Allow'
          protocol:                 'Tcp'
          sourceAddressPrefix:      'AzureLoadBalancer'
          sourcePortRange:          '*'
          destinationAddressPrefix: 'VirtualNetwork'
          destinationPortRange:     '6390'
        }
      }
      {
        name: 'Allow-VNet-Inbound'
        properties: {
          priority:                 120
          direction:                'Inbound'
          access:                   'Allow'
          protocol:                 '*'
          sourceAddressPrefix:      'VirtualNetwork'
          sourcePortRange:          '*'
          destinationAddressPrefix: 'VirtualNetwork'
          destinationPortRange:     '*'
        }
      }
      denyInboundInternetRule
      {
        name: 'Allow-Storage-Outbound'
        properties: {
          priority:                 100
          direction:                'Outbound'
          access:                   'Allow'
          protocol:                 'Tcp'
          sourceAddressPrefix:      'VirtualNetwork'
          sourcePortRange:          '*'
          destinationAddressPrefix: 'Storage'
          destinationPortRange:     '443'
        }
      }
      {
        name: 'Allow-AzureKeyVault-Outbound'
        properties: {
          priority:                 110
          direction:                'Outbound'
          access:                   'Allow'
          protocol:                 'Tcp'
          sourceAddressPrefix:      'VirtualNetwork'
          sourcePortRange:          '*'
          destinationAddressPrefix: 'AzureKeyVault'
          destinationPortRange:     '443'
        }
      }
      {
        name: 'Allow-AzureMonitor-Outbound'
        properties: {
          priority:                 120
          direction:                'Outbound'
          access:                   'Allow'
          protocol:                 'Tcp'
          sourceAddressPrefix:      'VirtualNetwork'
          sourcePortRange:          '*'
          destinationAddressPrefix: 'AzureMonitor'
          destinationPortRanges:    ['443', '1886']
        }
      }
      {
        name: 'Allow-VNet-Outbound'
        properties: {
          priority:                 130
          direction:                'Outbound'
          access:                   'Allow'
          protocol:                 '*'
          sourceAddressPrefix:      'VirtualNetwork'
          sourcePortRange:          '*'
          destinationAddressPrefix: 'VirtualNetwork'
          destinationPortRange:     '*'
        }
      }
      {
        // APIM internal-mode dependency: gateway uses an internal SQL DB
        // for configuration storage. Required by Microsoft's published
        // network reference for VNet-injected APIM. Flagged by dallas-apim
        // README (PR #16).
        name: 'AllowOutboundSqlForApim'
        properties: {
          priority:                 200
          direction:                'Outbound'
          access:                   'Allow'
          protocol:                 'Tcp'
          sourceAddressPrefix:      'VirtualNetwork'
          sourcePortRange:          '*'
          destinationAddressPrefix: 'Sql'
          destinationPortRange:     '1433'
        }
      }
      {
        // APIM internal-mode dependency: diagnostics + telemetry stream
        // to an internal Event Hub on AMQP (5671/5672) and HTTPS (443).
        // Required by Microsoft's published network reference for
        // VNet-injected APIM. Flagged by dallas-apim README (PR #16).
        name: 'AllowOutboundEventHubForApim'
        properties: {
          priority:                 210
          direction:                'Outbound'
          access:                   'Allow'
          protocol:                 'Tcp'
          sourceAddressPrefix:      'VirtualNetwork'
          sourcePortRange:          '*'
          destinationAddressPrefix: 'EventHub'
          destinationPortRanges:    ['5671', '5672', '443']
        }
      }
    ]
  }
}

// =============================================================================
// VNet + Subnets
// =============================================================================
// Hand-rolled (see README §Decisions). Subnets are inlined under the VNet
// resource (not declared as separate child resources) to avoid the well-known
// Azure race where parallel child-subnet deployments serialize and intermittently
// fail with "AnotherOperationInProgress".

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name:     vnetName
  location: location
  tags:     tags
  properties: {
    addressSpace: {
      addressPrefixes: [vnetAddressPrefix]
    }
    subnets: [
      {
        name: snetAcaName
        properties: {
          addressPrefix: snetAcaPrefix
          networkSecurityGroup: { id: nsgAca.id }
          delegations: [
            {
              name: 'Microsoft.App.environments'
              properties: {
                serviceName: 'Microsoft.App/environments'
              }
            }
          ]
          privateEndpointNetworkPolicies:    'Disabled'
          privateLinkServiceNetworkPolicies: 'Enabled'
        }
      }
      {
        name: snetPeName
        properties: {
          addressPrefix: snetPePrefix
          networkSecurityGroup: { id: nsgPe.id }
          privateEndpointNetworkPolicies:    'Disabled'
          privateLinkServiceNetworkPolicies: 'Enabled'
        }
      }
      {
        name: snetJobsName
        properties: {
          addressPrefix: snetJobsPrefix
          networkSecurityGroup: { id: nsgJobs.id }
          privateEndpointNetworkPolicies:    'Enabled'
          privateLinkServiceNetworkPolicies: 'Enabled'
        }
      }
      {
        name: snetBastionName
        properties: {
          addressPrefix: snetBastionPrefix
          networkSecurityGroup: { id: nsgBastion.id }
        }
      }
      {
        name: snetApimName
        properties: {
          addressPrefix: snetApimPrefix
          networkSecurityGroup: { id: nsgApim.id }
          privateEndpointNetworkPolicies:    'Enabled'
          privateLinkServiceNetworkPolicies: 'Enabled'
        }
      }
    ]
  }
}

// =============================================================================
// Private DNS Zones (AVM) — gated by customerProvidedDns flag
// =============================================================================
// registrationEnabled=false: we resolve PE A-records, not register VM hostnames.

module privateDnsZones 'br/public:avm/res/network/private-dns-zone:0.7.1' = [for zoneName in privateDnsZoneNames: if (!customerProvidedDns) {
  name: 'pdns-${uniqueString(deployment().name, zoneName)}'
  params: {
    name:     zoneName
    location: 'global'
    tags:     tags
    virtualNetworkLinks: [
      {
        name:                     vnetLinkName
        virtualNetworkResourceId: vnet.id
        registrationEnabled:      false
      }
    ]
  }
}]

// =============================================================================
// OUTPUTS
// =============================================================================

@description('Resource ID of the VNet.')
output vnetId string = vnet.id

@description('Name of the VNet.')
output vnetName string = vnet.name

@description('Resource ID of the snet-aca subnet (Container Apps Environment).')
output snetAcaId string = '${vnet.id}/subnets/${snetAcaName}'

@description('Resource ID of the snet-pe subnet (Private Endpoints + jumpbox).')
output snetPeId string = '${vnet.id}/subnets/${snetPeName}'

@description('Resource ID of the snet-jobs subnet (RESERVED, no resources deploy here in Phase 2a).')
output snetJobsId string = '${vnet.id}/subnets/${snetJobsName}'

@description('Resource ID of the AzureBastionSubnet (provisioned but Bastion Host deployed only when deployBastion=true in PR-N).')
output snetBastionId string = '${vnet.id}/subnets/${snetBastionName}'

@description('Resource ID of the snet-apim subnet (APIM VNet injection).')
output snetApimId string = '${vnet.id}/subnets/${snetApimName}'

@description('Array of Private DNS zone resource IDs in the SAME ORDER as privateDnsZoneNames input. Callers index by position. Empty strings when customerProvidedDns=true. Bicep limitation BCP182 prevents emitting a name->id map output from module collection outputs.')
output privateDnsZoneIdList array = [for (zoneName, i) in privateDnsZoneNames: customerProvidedDns ? '' : privateDnsZones[i].?outputs.resourceId ?? '']

@description('Echo of the input zone names so callers building maps stay in sync without re-declaring the list.')
output privateDnsZoneNamesOut array = privateDnsZoneNames

// ─── Named DNS zone ID outputs (well-known zones) ───────────────────────────
// Convenience outputs so downstream modules can reference zones by purpose
// without computing array indices. Order matches privateDnsZoneNames default.

@description('Private DNS zone resource ID for Azure OpenAI (privatelink.openai.azure.com).')
output pdnsOpenaiId string = customerProvidedDns ? '' : privateDnsZones[0].?outputs.resourceId ?? ''

@description('Private DNS zone resource ID for AI Search (privatelink.search.windows.net).')
output pdnsSearchId string = customerProvidedDns ? '' : privateDnsZones[1].?outputs.resourceId ?? ''

@description('Private DNS zone resource ID for Cosmos DB NoSQL (privatelink.documents.azure.com).')
output pdnsCosmosId string = customerProvidedDns ? '' : privateDnsZones[2].?outputs.resourceId ?? ''

@description('Private DNS zone resource ID for Storage Blob (privatelink.blob.core.windows.net).')
output pdnsBlobId string = customerProvidedDns ? '' : privateDnsZones[3].?outputs.resourceId ?? ''

@description('Private DNS zone resource ID for Storage Queue (privatelink.queue.core.windows.net).')
output pdnsQueueId string = customerProvidedDns ? '' : privateDnsZones[4].?outputs.resourceId ?? ''

@description('Private DNS zone resource ID for Key Vault (privatelink.vaultcore.azure.net).')
output pdnsKeyVaultId string = customerProvidedDns ? '' : privateDnsZones[5].?outputs.resourceId ?? ''

@description('Private DNS zone resource ID for Container Registry (privatelink.azurecr.io).')
output pdnsAcrId string = customerProvidedDns ? '' : privateDnsZones[6].?outputs.resourceId ?? ''

@description('Private DNS zone resource ID for Cognitive Services / Document Intelligence (privatelink.cognitiveservices.azure.com).')
output pdnsCognitiveId string = customerProvidedDns ? '' : privateDnsZones[7].?outputs.resourceId ?? ''

@description('Private DNS zone resource ID for Azure Monitor / AMPLS (privatelink.monitor.azure.com).')
output pdnsMonitorId string = customerProvidedDns ? '' : privateDnsZones[8].?outputs.resourceId ?? ''

@description('Private DNS zone resource ID for Log Analytics OMS (privatelink.oms.opinsights.azure.com).')
output pdnsOmsId string = customerProvidedDns ? '' : privateDnsZones[9].?outputs.resourceId ?? ''

@description('Private DNS zone resource ID for Log Analytics ODS (privatelink.ods.opinsights.azure.com).')
output pdnsOdsId string = customerProvidedDns ? '' : privateDnsZones[10].?outputs.resourceId ?? ''

@description('Private DNS zone resource ID for AMPLS agent service (privatelink.agentsvc.azure-automation.net).')
output pdnsAgentSvcId string = customerProvidedDns ? '' : privateDnsZones[11].?outputs.resourceId ?? ''

@description('Private DNS zone resource ID for APIM internal endpoints (azure-api.net).')
output pdnsApimId string = customerProvidedDns ? '' : privateDnsZones[12].?outputs.resourceId ?? ''

@description('NSG resource IDs keyed by subnet short-name. Useful for downstream RBAC / diagnostics modules.')
output nsgIds object = {
  aca:     nsgAca.id
  pe:      nsgPe.id
  jobs:    nsgJobs.id
  bastion: nsgBastion.id
  apim:    nsgApim.id
}
