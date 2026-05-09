metadata name = 'Document Intelligence module'
metadata description = '''
Deploys an Azure AI Document Intelligence (Cognitive Services kind=FormRecognizer) account
configured for zero-trust:
- Public network access disabled, network ACLs default Deny
- Local auth disabled (Entra ID only)
- Custom subdomain set to the account name (required for Private Endpoint)
- Private endpoint into snet-pe with privatelink.cognitiveservices.azure.com DNS
- Diagnostic settings (logs + metrics) shipped to a Log Analytics workspace
Uses AVM `avm/res/cognitive-services/account` for the heavy lifting.
'''

// ─────────────────────────────────────────────────────────────────────────────
// Parameters
// ─────────────────────────────────────────────────────────────────────────────

@description('Globally unique Document Intelligence account name (2–64 chars, alphanumerics and hyphens). Also used as the customSubDomainName.')
@minLength(2)
@maxLength(64)
param name string

@description('Azure region for the Document Intelligence account.')
param location string

@description('Resource tags to apply to all resources created by this module.')
param tags object = {}

@description('Resource ID of the private endpoint subnet (snet-pe).')
param peSubnetId string

@description('Resource ID of the privatelink.cognitiveservices.azure.com Private DNS Zone (network module output `pdnsCognitiveId`). Shared with Azure OpenAI? No — AOAI uses privatelink.openai.azure.com; this zone is for the rest of Cognitive Services including Document Intelligence.')
param pdnsCogsvcsId string

@description('Resource ID of the Log Analytics workspace receiving diagnostic logs.')
param lawId string

@description('Cognitive Services SKU. S0 is the demo default; F0 is too constrained for the accelerator.')
@allowed([
  'S0'
  'F0'
])
param sku string = 'S0'

@description('Principal IDs that receive `Cognitive Services User` on this account (call analyze endpoints). Wired by PR-O / T029 — typically api + ingest UAMIs.')
param cognitiveServicesUserPrincipalIds array = []

// ─────────────────────────────────────────────────────────────────────────────
// Document Intelligence (AVM cognitive-services/account)
// ─────────────────────────────────────────────────────────────────────────────

module account 'br/public:avm/res/cognitive-services/account:0.13.0' = {
  name: 'docintel-${uniqueString(name)}'
  params: {
    name: name
    location: location
    tags: tags

    // Document Intelligence is the rebranded service; the API kind is still FormRecognizer.
    kind: 'FormRecognizer'
    sku: sku

    // Required for Private Endpoint connectivity to the cognitiveservices DNS zone.
    customSubDomainName: name

    // Zero-trust posture.
    publicNetworkAccess: 'Disabled'
    networkAcls: {
      defaultAction: 'Deny'
      bypass: 'AzureServices'
      ipRules: []
      virtualNetworkRules: []
    }

    // Entra-only — no shared keys.
    disableLocalAuth: true

    privateEndpoints: [
      {
        name: 'pe-${name}'
        subnetResourceId: peSubnetId
        service: 'account'
        privateDnsZoneGroup: {
          privateDnsZoneGroupConfigs: [
            {
              privateDnsZoneResourceId: pdnsCogsvcsId
            }
          ]
        }
        tags: tags
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
// RBAC — Cognitive Services User (T029 / PR-O)
// ─────────────────────────────────────────────────────────────────────────────
var roleCognitiveServicesUser = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  'a97b65f3-24c7-4388-baec-2e87135dc908'
)

resource diExisting 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: name
  dependsOn: [
    account
  ]
}

resource raCognitiveServicesUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in cognitiveServicesUserPrincipalIds: {
  scope: diExisting
  name: guid(diExisting.id, principalId, 'CognitiveServicesUser')
  properties: {
    principalId: principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: roleCognitiveServicesUser
  }
}]

// ─────────────────────────────────────────────────────────────────────────────
// Outputs
// ─────────────────────────────────────────────────────────────────────────────

@description('Resource ID of the Document Intelligence account.')
output resourceId string = account.outputs.resourceId

@description('Name of the Document Intelligence account.')
output name string = account.outputs.name

@description('Endpoint URI of the Document Intelligence account (e.g. https://<name>.cognitiveservices.azure.com/).')
output endpoint string = account.outputs.endpoint
