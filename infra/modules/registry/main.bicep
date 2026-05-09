// =============================================================================
// Module: registry
// Task:   T020 (Phase 2a / PR-E)
// Purpose: Azure Container Registry (Premium) with private endpoint, no public
//          network access, no admin user, no anonymous pull. Premium SKU is
//          required because it is the only PE-capable ACR tier (SC-004).
//
// Wiring contract:
//   - Inputs:  peSubnetId (snet-pe), privateDnsZoneId (privatelink.azurecr.io)
//   - Outputs: acrId, acrName, acrLoginServer, peId
//
// AcrPull role assignments are NOT performed here. The PR-O wiring layer
// consumes `acrId` from this module's outputs and assigns AcrPull to the
// per-app UAMIs (mi-api, mi-ingest, mi-web) produced by PR-C.
// =============================================================================

targetScope = 'resourceGroup'

@description('Azure region for the registry. Should match the resource group region.')
param location string

@description('Resource tags applied to the registry and its private endpoint.')
param tags object = {}

@description('Globally-unique ACR name. Lowercase alphanumerics, 5–50 chars. Caller is responsible for stripping hyphens.')
@minLength(5)
@maxLength(50)
param acrName string

@description('ACR SKU. Pinned to Premium — only tier supporting private endpoints (SC-004).')
@allowed([
  'Premium'
])
param acrSku string = 'Premium'

@description('Resource ID of the private-endpoint subnet (snet-pe) in the platform VNet.')
param peSubnetId string

@description('Resource ID of the privatelink.azurecr.io private DNS zone (linked to the platform VNet).')
param privateDnsZoneId string

@description('Soft-delete retention in days for deleted manifests/repositories. 7 is the AVM default.')
@minValue(1)
@maxValue(90)
param softDeleteRetentionDays int = 7

// =============================================================================
// AVM: Container Registry
// Reference: https://github.com/Azure/bicep-registry-modules/tree/main/avm/res/container-registry/registry
// Version pinned to 0.12.1 (latest stable as of 2026-05-08).
// =============================================================================
module registry 'br/public:avm/res/container-registry/registry:0.12.1' = {
  name: 'acr-${acrName}'
  params: {
    name: acrName
    location: location
    tags: tags
    acrSku: acrSku

    // --- Zero-trust posture (Constitution Principle I) ---
    publicNetworkAccess: 'Disabled'
    acrAdminUserEnabled: false
    anonymousPullEnabled: false

    // --- Data protection ---
    softDeletePolicyStatus: 'enabled'
    softDeletePolicyDays: softDeleteRetentionDays
    retentionPolicyStatus: 'enabled'
    retentionPolicyDays: softDeleteRetentionDays

    // --- Private endpoint to snet-pe with privatelink.azurecr.io DNS group ---
    privateEndpoints: [
      {
        name: 'pe-${acrName}'
        subnetResourceId: peSubnetId
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
  }
}

// =============================================================================
// Outputs — consumed by PR-O (T029/T030) wiring layer:
//   - acrId is used to assign AcrPull to per-app UAMIs
//   - acrLoginServer is fed into Container App image references
//   - peId is surfaced for diagnostics / connectivity tests
// =============================================================================
@description('Resource ID of the container registry.')
output acrId string = registry.outputs.resourceId

@description('Name of the container registry.')
output acrName string = registry.outputs.name

@description('Login server FQDN for the registry (e.g., myacr.azurecr.io).')
output acrLoginServer string = registry.outputs.loginServer

@description('Resource ID of the private endpoint into snet-pe.')
output peId string = registry.outputs.privateEndpoints[0].resourceId
