metadata name = 'Key Vault module'
metadata description = '''
Deploys an Azure Key Vault (Standard SKU) configured for zero-trust:
- RBAC authorization (no access policies)
- Public network access disabled, network ACLs default Deny
- Private endpoint into snet-pe with privatelink.vaultcore.azure.net DNS
- Soft delete (7 days) + purge protection enabled
- Diagnostic settings shipped to a Log Analytics workspace
Uses AVM `avm/res/key-vault/vault` for the heavy lifting.
'''

// ─────────────────────────────────────────────────────────────────────────────
// Parameters
// ─────────────────────────────────────────────────────────────────────────────

@description('Azure region for the Key Vault.')
param location string

@description('Resource tags to apply to all resources created by this module.')
param tags object = {}

@description('Globally unique Key Vault name (3–24 chars, alphanumerics and hyphens).')
@minLength(3)
@maxLength(24)
param vaultName string

@description('Resource ID of the private endpoint subnet (snet-pe).')
param peSubnetId string

@description('Resource ID of the privatelink.vaultcore.azure.net Private DNS Zone.')
param privateDnsZoneId string

@description('Resource ID of the Log Analytics workspace receiving diagnostic logs.')
param lawId string

@description('Soft-delete retention in days. Minimum 7 to fit budget envelope.')
@minValue(7)
@maxValue(90)
param softDeleteRetentionInDays int = 7

@description('Principal IDs (UAMI / SPN object IDs) that receive `Key Vault Secrets User` (read secret values) on this vault. Wired by PR-O / T029.')
param secretsUserPrincipalIds array = []

@description('Optional Entra ID group object ID granted `Key Vault Administrator` on this vault for break-glass admin access. Empty string = no admin role assignment emitted.')
param adminGroupObjectId string = ''

// ─────────────────────────────────────────────────────────────────────────────
// Role-assignment array assembly. Bicep disallows for-expressions inside
// concat()/union() function calls, so we build each segment as its own var
// and concat the vars (vars accept for-expressions).
// ─────────────────────────────────────────────────────────────────────────────
var secretsUserRoleAssignments = [for principalId in secretsUserPrincipalIds: {
  roleDefinitionIdOrName: 'Key Vault Secrets User'
  principalId: principalId
  principalType: 'ServicePrincipal'
}]

var adminRoleAssignment = empty(adminGroupObjectId) ? [] : [
  {
    roleDefinitionIdOrName: 'Key Vault Administrator'
    principalId: adminGroupObjectId
    principalType: 'Group'
  }
]

var kvRoleAssignments = concat(secretsUserRoleAssignments, adminRoleAssignment)

// ─────────────────────────────────────────────────────────────────────────────
// Key Vault (AVM)
// ─────────────────────────────────────────────────────────────────────────────

module vault 'br/public:avm/res/key-vault/vault:0.13.3' = {
  name: 'kv-${uniqueString(vaultName)}'
  params: {
    name: vaultName
    location: location
    tags: tags

    sku: 'standard'

    // RBAC only — never access policies for new vaults.
    enableRbacAuthorization: true

    // Zero-trust posture.
    publicNetworkAccess: 'Disabled'
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Deny'
      ipRules: []
      virtualNetworkRules: []
    }

    enableVaultForDeployment: false
    enableVaultForDiskEncryption: false
    enableVaultForTemplateDeployment: false

    enableSoftDelete: true
    softDeleteRetentionInDays: softDeleteRetentionInDays
    enablePurgeProtection: true

    privateEndpoints: [
      {
        name: 'pe-${vaultName}'
        subnetResourceId: peSubnetId
        service: 'vault'
        privateDnsZoneGroup: {
          privateDnsZoneGroupConfigs: [
            {
              privateDnsZoneResourceId: privateDnsZoneId
            }
          ]
        }
        tags: tags
      }
    ]

    // RBAC — AVM's native roleAssignments param emits the assignments as
    // child resources of the vault, so the resource graph guarantees they
    // sequence after vault creation. The previous standalone-resource +
    // `existing` pattern raced the registry-graph propagation and failed
    // with `RoleDefinitionDoesNotExist`.
    roleAssignments: kvRoleAssignments

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
// RBAC — handled inline via AVM's `roleAssignments` parameter (see above).
// ─────────────────────────────────────────────────────────────────────────────

// ─────────────────────────────────────────────────────────────────────────────
// Outputs
// ─────────────────────────────────────────────────────────────────────────────

@description('Resource ID of the Key Vault.')
output kvId string = vault.outputs.resourceId

@description('Name of the Key Vault.')
output kvName string = vault.outputs.name

@description('DNS-suffixed URI of the Key Vault (e.g. https://<name>.vault.azure.net/).')
output kvUri string = vault.outputs.uri

@description('Resource ID of the Key Vault private endpoint.')
output peId string = vault.outputs.privateEndpoints[0].resourceId
