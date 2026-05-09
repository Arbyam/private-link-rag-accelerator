metadata name = 'AI Search module'
metadata description = '''
Deploys an Azure AI Search service (Basic SKU) configured for zero-trust:
- publicNetworkAccess = Disabled, networkRuleSet bypass = None (no IP rules)
- disableLocalAuth = true (Entra ID / RBAC only — no admin or query keys)
- Free semantic ranker enabled (Basic SKU includes the `free` tier)
- System-assigned managed identity (used by shared private links + RBAC to
  AOAI/Storage emitted in T029)
- Private endpoint into snet-pe with privatelink.search.windows.net DNS
- Shared private link resources to Azure OpenAI (groupId `openai_account`)
  and Storage Blob (groupId `blob`) so integrated vectorization and indexer
  data sources reach AOAI/Storage privately
- Diagnostic settings (allLogs + AllMetrics) shipped to a Log Analytics workspace
Cost: Basic SKU = ~$74/month (1 SU, 15 GB, 3 indexes). Locked at Basic by
phase-2-plan v3 — do NOT raise to Standard/S1 ($245/mo) without escalation.
Uses AVM `avm/res/search/search-service` 0.12.1 for the heavy lifting.
'''

// ─────────────────────────────────────────────────────────────────────────────
// Parameters
// ─────────────────────────────────────────────────────────────────────────────

@description('Globally unique AI Search service name (2–60 chars, lowercase alphanumerics and hyphens, must start/end with alphanumeric).')
@minLength(2)
@maxLength(60)
param name string

@description('Azure region for the AI Search service.')
param location string

@description('Resource tags to apply.')
param tags object = {}

@description('Resource ID of the private endpoint subnet (snet-pe).')
param peSubnetId string

@description('Resource ID of the privatelink.search.windows.net Private DNS Zone.')
param pdnsSearchId string

@description('Resource ID of the Log Analytics workspace receiving diagnostic logs.')
param lawId string

@description('Resource ID of the Azure OpenAI account that AI Search will reach via shared private link (groupId `openai_account`).')
param aoaiResourceId string

@description('Resource ID of the Storage Account that AI Search indexers will reach via shared private link (groupId `blob`).')
param storageBlobResourceId string

// ─────────────────────────────────────────────────────────────────────────────
// AI Search (AVM)
// ─────────────────────────────────────────────────────────────────────────────

module search 'br/public:avm/res/search/search-service:0.12.1' = {
  name: 'search-${uniqueString(name)}'
  params: {
    name: name
    location: location
    tags: tags

    // SKU LOCKED at `basic` — $74/month, supports PE + up to 10 SPLs.
    // Do NOT bump to standard/S1 without escalating (phase-2-plan v3).
    sku: 'basic'
    replicaCount: 1
    partitionCount: 1

    // Free semantic ranker tier is included with Basic SKU.
    semanticSearch: 'free'

    // Entra-only data plane auth (RBAC). No admin/query keys.
    disableLocalAuth: true

    // System-assigned MI — used by shared private links and by T029
    // role assignments (Cognitive Services OpenAI User, Storage Blob
    // Data Reader) so AI Search reaches AOAI/Storage with no secrets.
    managedIdentities: {
      systemAssigned: true
    }

    // Zero-trust posture: no public access, no service bypass, no IP rules.
    publicNetworkAccess: 'Disabled'
    networkRuleSet: {
      bypass: 'None'
      ipRules: []
    }

    privateEndpoints: [
      {
        name: 'pe-${name}'
        subnetResourceId: peSubnetId
        service: 'searchService'
        privateDnsZoneGroup: {
          privateDnsZoneGroupConfigs: [
            {
              privateDnsZoneResourceId: pdnsSearchId
            }
          ]
        }
        tags: tags
      }
    ]

    // Shared private links — AVM child module auto-approves cross-resource
    // SPLs in the same subscription. First-deploy approval can take up to
    // ~10 minutes per Azure docs.
    sharedPrivateLinkResources: [
      {
        name: 'spl-${name}-aoai'
        groupId: 'openai_account'
        privateLinkResourceId: aoaiResourceId
        requestMessage: 'AI Search ${name} -> Azure OpenAI (integrated vectorization) for private-rag-accelerator'
      }
      {
        name: 'spl-${name}-blob'
        groupId: 'blob'
        privateLinkResourceId: storageBlobResourceId
        requestMessage: 'AI Search ${name} -> Storage Blob (indexer data source) for private-rag-accelerator'
      }
    ]

    diagnosticSettings: [
      {
        name: 'diag-to-law'
        workspaceResourceId: lawId
        logCategoriesAndGroups: [
          {
            categoryGroup: 'allLogs'
          }
        ]
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
// Outputs
// ─────────────────────────────────────────────────────────────────────────────

@description('Resource ID of the AI Search service.')
output resourceId string = search.outputs.resourceId

@description('Name of the AI Search service.')
output name string = search.outputs.name

@description('Search service endpoint (https://<name>.search.windows.net).')
output endpoint string = search.outputs.endpoint

@description('System-assigned managed identity principal ID. Consumed by T029 to grant AI Search RBAC on AOAI (Cognitive Services OpenAI User) and Storage (Storage Blob Data Reader).')
output principalId string = search.outputs.?systemAssignedMIPrincipalId ?? ''
