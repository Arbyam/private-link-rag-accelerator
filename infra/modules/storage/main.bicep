// =============================================================================
// Module: storage
// Task:   T022 (Phase 2a / PR-G)
// Purpose: Azure Storage Account (StorageV2 / Standard_LRS / Hot) configured for
//          zero-trust ingestion: no public network, no shared keys (Entra-only),
//          TLS 1.2, default-deny ACLs, five private endpoints (blob, file,
//          table, dfs, queue), one pre-created blob container `documents`,
//          and diagnostics shipped to a Log Analytics workspace.
//
// Wiring contract:
//   - Inputs:  peSubnetId (snet-pe), pdns*Id (one per sub-resource), lawId
//   - Outputs: resourceId, name, primaryBlobEndpoint, documentsContainerName
//
// Notes:
//   - Queue PE included per the locked Phase 2a decision
//     (".squad/decisions.md" — resolved-question: queue PE added).
//   - File/Table/DFS PEs are wired here even though the network module only
//     emits Blob+Queue private DNS zones today; PR-O is responsible for
//     supplying the additional zone IDs (or extending network/main.bicep).
//   - This module is intentionally NOT referenced from infra/main.bicep yet —
//     wiring lives in PR-O.
// =============================================================================

metadata name = 'Storage Account module'
metadata description = '''
StorageV2 (Standard_LRS, Hot) with zero-trust posture:
- publicNetworkAccess Disabled, networkAcls defaultAction Deny
- allowSharedKeyAccess false (Entra-only) + defaultToOAuthAuthentication
- allowBlobPublicAccess false, minimumTlsVersion TLS1_2
- 5 private endpoints (blob, file, table, dfs, queue) into snet-pe
- Single private blob container `documents` for ingestion artifacts
- Diagnostic settings shipped to Log Analytics
Uses AVM `avm/res/storage/storage-account` for the heavy lifting.
'''

targetScope = 'resourceGroup'

// ─────────────────────────────────────────────────────────────────────────────
// Parameters
// ─────────────────────────────────────────────────────────────────────────────

@description('Globally-unique storage account name. Lowercase alphanumerics only, 3–24 chars.')
@minLength(3)
@maxLength(24)
param name string

@description('Azure region for the storage account.')
param location string

@description('Resource tags applied to the storage account and its private endpoints.')
param tags object = {}

@description('Resource ID of the private-endpoint subnet (snet-pe).')
param peSubnetId string

@description('Resource ID of the privatelink.blob.core.windows.net Private DNS Zone.')
param pdnsBlobId string

@description('Resource ID of the privatelink.file.core.windows.net Private DNS Zone.')
param pdnsFileId string

@description('Resource ID of the privatelink.table.core.windows.net Private DNS Zone.')
param pdnsTableId string

@description('Resource ID of the privatelink.dfs.core.windows.net Private DNS Zone.')
param pdnsDfsId string

@description('Resource ID of the privatelink.queue.core.windows.net Private DNS Zone.')
param pdnsQueueId string

@description('Resource ID of the Log Analytics workspace receiving diagnostic logs.')
param lawId string

// ─────────────────────────────────────────────────────────────────────────────
// Constants
// ─────────────────────────────────────────────────────────────────────────────

var documentsContainer = 'documents'

// ─────────────────────────────────────────────────────────────────────────────
// Storage Account (AVM)
// Reference: https://github.com/Azure/bicep-registry-modules/tree/main/avm/res/storage/storage-account
// Pinned to 0.27.1 (latest 0.27.x as of 2026-05-08).
// ─────────────────────────────────────────────────────────────────────────────

module storage 'br/public:avm/res/storage/storage-account:0.27.1' = {
  name: 'st-${uniqueString(name)}'
  params: {
    name: name
    location: location
    tags: tags

    skuName: 'Standard_LRS'
    kind: 'StorageV2'
    accessTier: 'Hot'

    // --- Zero-trust posture (Constitution Principle I) ---
    publicNetworkAccess: 'Disabled'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Deny'
      ipRules: []
      virtualNetworkRules: []
    }

    // --- Pre-created blob container (private access) ---
    blobServices: {
      containers: [
        {
          name: documentsContainer
          publicAccess: 'None'
        }
      ]
    }

    // --- Five private endpoints into snet-pe ---
    privateEndpoints: [
      {
        name: 'pe-${name}-blob'
        service: 'blob'
        subnetResourceId: peSubnetId
        privateDnsZoneGroup: {
          privateDnsZoneGroupConfigs: [
            {
              privateDnsZoneResourceId: pdnsBlobId
            }
          ]
        }
        tags: tags
      }
      {
        name: 'pe-${name}-file'
        service: 'file'
        subnetResourceId: peSubnetId
        privateDnsZoneGroup: {
          privateDnsZoneGroupConfigs: [
            {
              privateDnsZoneResourceId: pdnsFileId
            }
          ]
        }
        tags: tags
      }
      {
        name: 'pe-${name}-table'
        service: 'table'
        subnetResourceId: peSubnetId
        privateDnsZoneGroup: {
          privateDnsZoneGroupConfigs: [
            {
              privateDnsZoneResourceId: pdnsTableId
            }
          ]
        }
        tags: tags
      }
      {
        name: 'pe-${name}-dfs'
        service: 'dfs'
        subnetResourceId: peSubnetId
        privateDnsZoneGroup: {
          privateDnsZoneGroupConfigs: [
            {
              privateDnsZoneResourceId: pdnsDfsId
            }
          ]
        }
        tags: tags
      }
      {
        name: 'pe-${name}-queue'
        service: 'queue'
        subnetResourceId: peSubnetId
        privateDnsZoneGroup: {
          privateDnsZoneGroupConfigs: [
            {
              privateDnsZoneResourceId: pdnsQueueId
            }
          ]
        }
        tags: tags
      }
    ]

    // --- Diagnostics → Log Analytics ---
    diagnosticSettings: [
      {
        name: 'diag-to-law'
        workspaceResourceId: lawId
        metricCategories: [
          {
            category: 'AllMetrics'
          }
        ]
      }
    ]
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Outputs — consumed by PR-O wiring layer
// ─────────────────────────────────────────────────────────────────────────────

@description('Resource ID of the storage account.')
output resourceId string = storage.outputs.resourceId

@description('Name of the storage account.')
output name string = storage.outputs.name

@description('Primary blob endpoint (https://<name>.blob.core.windows.net/).')
output primaryBlobEndpoint string = storage.outputs.primaryBlobEndpoint

@description('Name of the pre-created blob container for ingestion artifacts.')
output documentsContainerName string = documentsContainer
