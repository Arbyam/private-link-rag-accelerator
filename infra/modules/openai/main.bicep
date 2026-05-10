// =============================================================================
// Module: openai
// Task:   T025 (Phase 2a / PR-I)
// Purpose: Azure OpenAI account (Cognitive Services kind=OpenAI) with private
//          endpoint, no public network access, Entra-only auth, and two model
//          deployments (chat + embeddings) per research.md D2.
//
// Wiring contract:
//   - Inputs:  peSubnetId (snet-pe), pdnsOpenaiId (privatelink.openai.azure.com),
//              lawId (Log Analytics workspace).
//   - Outputs: resourceId, name, endpoint, chatDeploymentName,
//              embeddingDeploymentName.
//
// Notes:
//   - AVM `cognitive-services/account` 0.14.2 already applies `@batchSize(1)`
//     to the deployments resource, so the well-known OpenAI race where two
//     `Microsoft.CognitiveServices/accounts/deployments` deploys collide is
//     handled inside the AVM module — no extra `dependsOn` chain is needed in
//     this caller.
//   - Role assignments to per-app MIs are deferred to PR-O (T029) so we keep
//     this module pure (no cross-module coupling beyond the network/PE inputs).
// =============================================================================

targetScope = 'resourceGroup'

metadata name = 'Azure OpenAI module'
metadata description = '''
Deploys an Azure OpenAI account configured for zero-trust:
- kind: OpenAI, SKU: S0 (pay-per-token)
- Public network access disabled, network ACLs default Deny
- Local auth disabled (Entra ID only — apps use managed identity)
- customSubDomainName set (required for private endpoint + token auth)
- Private endpoint into snet-pe with privatelink.openai.azure.com DNS
- Two model deployments: chat (gpt-5) + embeddings (text-embedding-3-large)
- Diagnostic settings shipped to a Log Analytics workspace
Uses AVM `avm/res/cognitive-services/account` for the heavy lifting.
'''

// ─────────────────────────────────────────────────────────────────────────────
// Parameters
// ─────────────────────────────────────────────────────────────────────────────

@description('Azure OpenAI account name. Must be globally unique. 2–64 chars, alphanumerics and hyphens. Used as the customSubDomainName.')
@minLength(2)
@maxLength(64)
param name string

@description('Azure region for the account. Must be a region where both the chat and embedding model deployments are available (e.g., eastus2, southcentralus, northcentralus, westus3 per research.md D2).')
param location string

@description('Resource tags applied to the account and its private endpoint.')
param tags object = {}

@description('Resource ID of the private-endpoint subnet (snet-pe) in the platform VNet.')
param peSubnetId string

@description('Resource ID of the privatelink.openai.azure.com private DNS zone (linked to the platform VNet).')
param pdnsOpenaiId string

@description('Resource ID of the Log Analytics workspace receiving diagnostic logs.')
param lawId string

@description('Chat model name. Defaults to gpt-5 per research.md D2.')
param chatModel string = 'gpt-5'

@description('Chat model version. Pin a specific version for reproducibility; bump deliberately.')
param chatModelVersion string = '2025-08-07'

@description('Chat model deployment name (used by the application as the deployment id).')
param chatDeploymentName string = 'gpt-5'

@description('Chat deployment TPM capacity in thousands (Standard SKU). 10 = 10K TPM, plenty for demo workloads.')
@minValue(1)
@maxValue(1000)
param chatCapacity int = 10

@description('Embedding model name. Defaults to text-embedding-3-large (3072 dims) per research.md D2.')
param embeddingModel string = 'text-embedding-3-large'

@description('Embedding model version.')
param embeddingModelVersion string = '1'

@description('Embedding model deployment name (used by the application as the deployment id).')
param embeddingDeploymentName string = 'text-embedding-3-large'

@description('Embedding deployment TPM capacity in thousands (Standard SKU).')
@minValue(1)
@maxValue(1000)
param embeddingCapacity int = 10

@description('Model deployment SKU. ``GlobalStandard`` is the default (and is the only SKU that supports gpt-5 / 2025-08-07 — Azure rejects ``Standard`` for that model). Switch to ``Standard`` if you are deploying a model that supports it AND you need strict region-locked Private Link semantics.')
@allowed([
  'Standard'
  'GlobalStandard'
])
param deploymentSku string = 'GlobalStandard'

@description('Principal IDs that receive `Cognitive Services OpenAI User` on this account (call chat / embedding deployments). Wired by PR-O / T029 — typically api + ingest UAMIs.')
param openAiUserPrincipalIds array = []

// ─────────────────────────────────────────────────────────────────────────────
// Cognitive Services account (AVM, kind: OpenAI)
// Reference: https://github.com/Azure/bicep-registry-modules/tree/main/avm/res/cognitive-services/account
// Pinned to 0.14.2 (latest stable as of 2026-05-08; T031 audit bump). 0.14.2 applies
// @batchSize(1) to the deployments resource which serialises model
// deployments and avoids the well-known parallel-deploy 409 race.
// ─────────────────────────────────────────────────────────────────────────────

module account 'br/public:avm/res/cognitive-services/account:0.14.2' = {
  name: 'aoai-${uniqueString(name)}'
  params: {
    name: name
    location: location
    tags: tags

    kind: 'OpenAI'
    sku: 'S0'

    // customSubDomainName is REQUIRED for token-based (Entra) auth and for
    // private endpoint resolution. We mirror the resource name.
    customSubDomainName: name

    // --- Zero-trust posture (Constitution Principle I) ---
    publicNetworkAccess: 'Disabled'
    disableLocalAuth: true
    networkAcls: {
      defaultAction: 'Deny'
      ipRules: []
      virtualNetworkRules: []
    }

    // --- Model deployments (serialised by AVM via @batchSize(1)) ---
    deployments: [
      {
        name: chatDeploymentName
        model: {
          format: 'OpenAI'
          name: chatModel
          version: chatModelVersion
        }
        sku: {
          name: deploymentSku
          capacity: chatCapacity
        }
      }
      {
        name: embeddingDeploymentName
        model: {
          format: 'OpenAI'
          name: embeddingModel
          version: embeddingModelVersion
        }
        sku: {
          name: deploymentSku
          capacity: embeddingCapacity
        }
      }
    ]

    // --- Private endpoint to snet-pe with privatelink.openai.azure.com DNS group ---
    privateEndpoints: [
      {
        name: 'pe-${name}'
        subnetResourceId: peSubnetId
        service: 'account'
        privateDnsZoneGroup: {
          privateDnsZoneGroupConfigs: [
            {
              privateDnsZoneResourceId: pdnsOpenaiId
            }
          ]
        }
        tags: tags
      }
    ]

    // --- Diagnostics → LAW ---
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
// RBAC — Cognitive Services OpenAI User (T029 / PR-O)
// ─────────────────────────────────────────────────────────────────────────────
var roleCogSvcsOpenAiUser = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
)

resource aoaiExisting 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: name
  dependsOn: [
    account
  ]
}

resource raOpenAiUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in openAiUserPrincipalIds: {
  scope: aoaiExisting
  name: guid(aoaiExisting.id, principalId, 'CognitiveServicesOpenAIUser')
  properties: {
    principalId: principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: roleCogSvcsOpenAiUser
  }
}]

// ─────────────────────────────────────────────────────────────────────────────
// Outputs — consumed by PR-O (T029) wiring layer:
//   - resourceId: role assignments (Cognitive Services OpenAI User to mi-api / mi-ingest),
//                 and AI Search shared private link target (PR-J).
//   - endpoint:   environment variable for api/ingest containers.
//   - {chat,embedding}DeploymentName: environment variables for the SDK clients.
// ─────────────────────────────────────────────────────────────────────────────

@description('Resource ID of the Azure OpenAI account.')
output resourceId string = account.outputs.resourceId

@description('Name of the Azure OpenAI account.')
output name string = account.outputs.name

@description('Cognitive Services endpoint URI (e.g., https://<name>.openai.azure.com/).')
output endpoint string = account.outputs.endpoint

@description('Chat model deployment name (used as the deployment id by Azure OpenAI SDK clients).')
output chatDeploymentName string = chatDeploymentName

@description('Embedding model deployment name (used as the deployment id by Azure OpenAI SDK clients).')
output embeddingDeploymentName string = embeddingDeploymentName
