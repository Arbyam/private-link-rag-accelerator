metadata name = 'Monitoring'
metadata description = '''
Observability foundation: Log Analytics workspace (PerGB2018), workspace-based
Application Insights, and an Azure Monitor Private Link Scope (AMPLS) with
private endpoint for fully private telemetry ingestion and query.

Constitution alignment:
- Principle I (zero public endpoints): LAW + App Insights have public network
  access disabled for both ingestion and query. AMPLS is configured for
  PrivateOnly access modes and reachable only via PE.
- Principle II (idempotent IaC): Pinned AVM module versions; symbolic refs;
  no nested deployment state coupling.
'''

// ─────────────────────────────────────────────────────────────────────────────
// Parameters
// ─────────────────────────────────────────────────────────────────────────────

@description('Azure region for regional resources (LAW, App Insights, PE). AMPLS itself is global.')
param location string

@description('Tags applied to all resources in this module.')
param tags object = {}

@description('Log Analytics workspace name.')
param lawName string

@description('Application Insights component name.')
param appInsightsName string

@description('Azure Monitor Private Link Scope (AMPLS) name. AMPLS is a global resource.')
param amplsName string

@description('Retention period (days) for Log Analytics. Workspace-based App Insights inherits this. Kept low to fit the $500/mo demo budget.')
@minValue(30)
@maxValue(730)
param retentionInDays int = 30

@description('Resource ID of the subnet that will host the AMPLS private endpoint. Must be in the same VNet as workloads that send telemetry.')
param peSubnetId string

@description('Name of the AMPLS private endpoint.')
param privateEndpointName string = 'pe-${amplsName}'

@description('Resource ID of the privatelink.monitor.azure.com private DNS zone.')
param privateDnsZoneIdMonitor string

@description('Resource ID of the privatelink.oms.opinsights.azure.com private DNS zone.')
param privateDnsZoneIdOms string

@description('Resource ID of the privatelink.ods.opinsights.azure.com private DNS zone.')
param privateDnsZoneIdOds string

@description('Resource ID of the privatelink.agentsvc.azure-automation.net private DNS zone.')
param privateDnsZoneIdAgentSvc string

@description('Resource ID of the privatelink.blob.core.windows.net private DNS zone (used by the Log Analytics agent storage endpoint).')
param privateDnsZoneIdBlob string

// ─────────────────────────────────────────────────────────────────────────────
// Log Analytics Workspace (AVM)
// ─────────────────────────────────────────────────────────────────────────────

module law 'br/public:avm/res/operational-insights/workspace:0.15.1' = {
  name: 'monitoring-law'
  params: {
    name: lawName
    location: location
    tags: tags
    skuName: 'PerGB2018'
    dataRetention: retentionInDays
    publicNetworkAccessForIngestion: 'Disabled'
    publicNetworkAccessForQuery: 'Disabled'
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Application Insights (workspace-based, AVM)
// ─────────────────────────────────────────────────────────────────────────────

module appInsights 'br/public:avm/res/insights/component:0.7.1' = {
  name: 'monitoring-appi'
  params: {
    name: appInsightsName
    location: location
    tags: tags
    workspaceResourceId: law.outputs.resourceId
    applicationType: 'web'
    kind: 'web'
    publicNetworkAccessForIngestion: 'Disabled'
    publicNetworkAccessForQuery: 'Disabled'
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Azure Monitor Private Link Scope (AMPLS) — hand-rolled, no AVM module exists
// ─────────────────────────────────────────────────────────────────────────────
// AMPLS is a global resource. accessModeSettings=PrivateOnly enforces that
// telemetry ingestion and query traffic for scoped resources MUST traverse the
// private endpoint, even when the underlying workspace/component allows public.

resource ampls 'Microsoft.Insights/privateLinkScopes@2021-07-01-preview' = {
  name: amplsName
  location: 'global'
  tags: tags
  properties: {
    accessModeSettings: {
      ingestionAccessMode: 'PrivateOnly'
      queryAccessMode: 'PrivateOnly'
    }
  }
}

resource amplsLawScope 'Microsoft.Insights/privateLinkScopes/scopedResources@2021-07-01-preview' = {
  parent: ampls
  name: '${lawName}-link'
  properties: {
    linkedResourceId: law.outputs.resourceId
  }
}

resource amplsAppInsightsScope 'Microsoft.Insights/privateLinkScopes/scopedResources@2021-07-01-preview' = {
  parent: ampls
  name: '${appInsightsName}-link'
  properties: {
    linkedResourceId: appInsights.outputs.resourceId
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// AMPLS Private Endpoint + Private DNS Zone Group
// ─────────────────────────────────────────────────────────────────────────────
// The PE for `azuremonitor` group requires all five private DNS zones registered
// together so client SDKs resolve the full ingestion/query/agent surface area.

resource amplsPrivateEndpoint 'Microsoft.Network/privateEndpoints@2024-01-01' = {
  name: privateEndpointName
  location: location
  tags: tags
  properties: {
    subnet: {
      id: peSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: 'ampls-connection'
        properties: {
          privateLinkServiceId: ampls.id
          groupIds: [
            'azuremonitor'
          ]
        }
      }
    ]
  }
}

resource amplsPrivateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-01-01' = {
  parent: amplsPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'privatelink-monitor-azure-com'
        properties: {
          privateDnsZoneId: privateDnsZoneIdMonitor
        }
      }
      {
        name: 'privatelink-oms-opinsights-azure-com'
        properties: {
          privateDnsZoneId: privateDnsZoneIdOms
        }
      }
      {
        name: 'privatelink-ods-opinsights-azure-com'
        properties: {
          privateDnsZoneId: privateDnsZoneIdOds
        }
      }
      {
        name: 'privatelink-agentsvc-azure-automation-net'
        properties: {
          privateDnsZoneId: privateDnsZoneIdAgentSvc
        }
      }
      {
        name: 'privatelink-blob-core-windows-net'
        properties: {
          privateDnsZoneId: privateDnsZoneIdBlob
        }
      }
    ]
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Outputs
// ─────────────────────────────────────────────────────────────────────────────

@description('Resource ID of the Log Analytics workspace.')
output lawId string = law.outputs.resourceId

@description('Name of the Log Analytics workspace.')
output lawName string = law.outputs.name

@description('Resource ID of the Application Insights component.')
output appInsightsId string = appInsights.outputs.resourceId

@description('Application Insights connection string. Treat as secret-ish (instrumentation key embedded).')
output appInsightsConnectionString string = appInsights.outputs.connectionString

@description('Application Insights instrumentation key (legacy SDKs).')
output appInsightsInstrumentationKey string = appInsights.outputs.instrumentationKey

@description('Resource ID of the Azure Monitor Private Link Scope.')
output amplsId string = ampls.id

@description('Resource ID of the AMPLS private endpoint.')
output amplsPrivateEndpointId string = amplsPrivateEndpoint.id
