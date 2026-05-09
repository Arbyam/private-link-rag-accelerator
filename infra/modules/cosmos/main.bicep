// =============================================================================
// Module: cosmos
// Task:   T023 (Phase 2a / PR-H)
// Purpose: Azure Cosmos DB for NoSQL — Serverless capacity, zero public access,
//          Entra-only auth (no master keys), private endpoint into snet-pe with
//          privatelink.documents.azure.com DNS, full diagnostics to LAW.
//
// Scope (per Phase 2a v3 cost-locked plan, ~$3/mo):
//   - Capacity: Serverless (no autoscale RU). Continuous backup (default for
//     serverless = Continuous7Days; AVM default is fine).
//   - API: SQL (Core).
//   - 1 SQL database (`rag`) with 3 containers per data-model.md §1:
//       - conversations  / PK /userId / TTL 30d  (FR-030 sliding chat history)
//       - documents      / PK /scope  / per-doc `ttl` field (no default TTL)
//       - ingestion-runs / PK /scope  / TTL 90d  (operational telemetry)
//
// Wiring contract:
//   Inputs:  name, location, tags, peSubnetId, pdnsCosmosId, lawId
//   Outputs: resourceId, name, endpoint, databaseName, containerName
//
// Note: `containerName` output is the *primary* container (`conversations`)
// used by the chat path. The full set of container names is also exported via
// `containerNames` for consumers that need them.
//
// Role assignments to app MIs (Cosmos DB Built-in Data Contributor for api +
// ingest) are intentionally NOT performed here. PR-O wiring layer (T029)
// consumes `resourceId` and emits `Microsoft.DocumentDB/databaseAccounts/
// sqlRoleAssignments` against the built-in role 00000000-0000-0000-0000-
// 000000000002 — keys/local auth are disabled, MI is the only path.
// =============================================================================

targetScope = 'resourceGroup'

// -----------------------------------------------------------------------------
// Parameters
// -----------------------------------------------------------------------------

@description('Globally-unique Cosmos DB account name. Lowercase alphanumerics and hyphens, 3–44 chars.')
@minLength(3)
@maxLength(44)
param name string

@description('Azure region for the account. Should match the resource group region.')
param location string

@description('Resource tags applied to the account and its private endpoint.')
param tags object = {}

@description('Resource ID of the private-endpoint subnet (snet-pe) in the platform VNet.')
param peSubnetId string

@description('Resource ID of the privatelink.documents.azure.com Private DNS Zone (linked to the platform VNet).')
param pdnsCosmosId string

@description('Resource ID of the Log Analytics workspace receiving diagnostic logs and metrics.')
param lawId string

@description('SQL database name. Default `rag` per Phase 2a plan.')
param databaseName string = 'rag'

@description('Primary container (chat history). PK `/userId`, default TTL 30 days (sliding, per FR-030).')
param conversationsContainerName string = 'conversations'

@description('Document metadata container. PK `/scope`; per-document `ttl` field (no container-level default).')
param documentsContainerName string = 'documents'

@description('Ingestion telemetry container. PK `/scope`, default TTL 90 days.')
param ingestionRunsContainerName string = 'ingestion-runs'

@description('Principal IDs that receive the built-in `Cosmos DB Built-in Data Contributor` SQL role on this account (data plane — read/write all containers in the SQL API). Wired by PR-O / T029 — typically api + ingest UAMIs.')
param dataContributorPrincipalIds array = []

// -----------------------------------------------------------------------------
// AVM: Cosmos DB account
// Reference: https://github.com/Azure/bicep-registry-modules/tree/main/avm/res/document-db/database-account
// Version pinned to 0.15.1 (latest 0.15.x as of 2026-05-08).
// -----------------------------------------------------------------------------
module account 'br/public:avm/res/document-db/database-account:0.15.1' = {
  name: 'cosmos-${uniqueString(name)}'
  params: {
    name: name
    location: location
    tags: tags

    // --- Capacity: Serverless (Phase 2a v3 cost-locked plan) ---
    capabilitiesToAdd: [
      'EnableServerless'
    ]

    // --- Single region, no multi-region writes, no zone redundancy (cost) ---
    failoverLocations: [
      {
        failoverPriority: 0
        locationName: location
        isZoneRedundant: false
      }
    ]
    zoneRedundant: false
    automaticFailover: false

    // --- Zero-trust posture (Constitution Principle I) ---
    // No public ingress, no Azure-services bypass, no IP/VNet ACL rules.
    networkRestrictions: {
      publicNetworkAccess: 'Disabled'
      networkAclBypass: 'None'
      ipRules: []
      virtualNetworkRules: []
    }

    // Entra-only authentication. App access is via managed identity + RBAC
    // through Cosmos data-plane role assignments (wired in PR-O / T029).
    disableLocalAuthentication: true
    disableKeyBasedMetadataWriteAccess: true

    // --- Backup ---
    // Serverless accounts only support Continuous backup. AVM default
    // (Continuous, 7-day tier) satisfies the requirement; we leave it implicit
    // to avoid coupling to AVM's evolving Continuous-tier parameter shape.

    // --- TLS floor ---
    minimumTlsVersion: 'Tls12'

    // --- SQL database + containers (per data-model.md §1) ---
    sqlDatabases: [
      {
        name: databaseName
        containers: [
          {
            name: conversationsContainerName
            paths: [
              '/userId'
            ]
            kind: 'Hash'
            // 30-day sliding TTL — every turn write resets _ts (FR-030).
            defaultTtl: 2592000
            indexingPolicy: {
              automatic: true
            }
          }
          {
            name: documentsContainerName
            paths: [
              '/scope'
            ]
            kind: 'Hash'
            // Per-document `ttl` field; container-level TTL enabled but no
            // default (-1 = enabled, no expiry unless `ttl` set on the doc).
            defaultTtl: -1
            indexingPolicy: {
              automatic: true
            }
          }
          {
            name: ingestionRunsContainerName
            paths: [
              '/scope'
            ]
            kind: 'Hash'
            // 90-day operational telemetry retention.
            defaultTtl: 7776000
            indexingPolicy: {
              automatic: true
            }
          }
        ]
      }
    ]

    // --- Private endpoint into snet-pe with privatelink.documents.azure.com ---
    privateEndpoints: [
      {
        name: 'pe-${name}'
        service: 'Sql'
        subnetResourceId: peSubnetId
        privateDnsZoneGroup: {
          privateDnsZoneGroupConfigs: [
            {
              privateDnsZoneResourceId: pdnsCosmosId
            }
          ]
        }
        tags: tags
      }
    ]

    // --- Diagnostics: full logs + metrics → LAW ---
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

// -----------------------------------------------------------------------------
// Cosmos DB data-plane RBAC (T029 / PR-O)
// -----------------------------------------------------------------------------
// Cosmos data-plane access is NOT controlled by Azure RBAC role assignments;
// it uses Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments with the
// built-in role `00000000-0000-0000-0000-000000000002` (Cosmos DB Built-in
// Data Contributor). `disableLocalAuthentication: true` above means MI is the
// only path to data — there is no key fallback.
// -----------------------------------------------------------------------------
resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' existing = {
  name: name
  dependsOn: [
    account
  ]
}

var cosmosBuiltInDataContributorRoleId = '${cosmosAccount.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002'

resource cosmosDataContributorAssignments 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-05-15' = [for principalId in dataContributorPrincipalIds: {
  parent: cosmosAccount
  name: guid(cosmosAccount.id, principalId, '00000000-0000-0000-0000-000000000002')
  properties: {
    roleDefinitionId: cosmosBuiltInDataContributorRoleId
    principalId: principalId
    scope: cosmosAccount.id
  }
}]

// -----------------------------------------------------------------------------
// Outputs — consumed by PR-O (T029/T030) wiring layer.
// -----------------------------------------------------------------------------

@description('Resource ID of the Cosmos DB account.')
output resourceId string = account.outputs.resourceId

@description('Name of the Cosmos DB account.')
output name string = account.outputs.name

@description('Documents endpoint of the Cosmos DB account (e.g., https://<name>.documents.azure.com:443/).')
output endpoint string = account.outputs.endpoint

@description('Name of the SQL database created in the account.')
output databaseName string = databaseName

@description('Name of the primary chat-history container (`conversations`).')
output containerName string = conversationsContainerName

@description('Names of all containers created in the database, in declaration order.')
output containerNames array = [
  conversationsContainerName
  documentsContainerName
  ingestionRunsContainerName
]
