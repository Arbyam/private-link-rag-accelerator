// =============================================================================
// Module: apim
// Task:   T032a (Phase 2a / PR-L)
// Purpose: Azure API Management — Developer SKU, Internal VNet mode.
//          All endpoints (gateway, portal, management, scm, devportal) resolve
//          to a VNet-internal VIP only. NO public IP on the gateway.
//
//          Phase 2a ships the APIM service + base hardening only:
//            - System-assigned managed identity (consumed by PR-O for RBAC to
//              AOAI / Key Vault / etc.)
//            - TLS 1.0 / 1.1 disabled, weak ciphers disabled, HTTP/2 enabled
//            - Diagnostics → LAW (GatewayLogs + AllMetrics)
//            - App Insights logger (built-in APIM logger resource)
//
//          Out-of-scope (Phase 3):
//            - AI gateway policies (rate-limit, token-quota, content-filter)
//            - Backend declarations (AOAI, Search, ACA apps)
//            - API definitions / OpenAPI imports
//
// Deployment time WARNING: Developer + Internal VNet injection takes
// ~30–45 minutes for first deploy (~10 min added by VNet injection).
// Subsequent updates are faster but plan accordingly.
//
// NSG dependency: APIM internal VNet mode requires specific NSG rules on
// `snet-apim`. The network module owns nsgApim and already provides the core
// rules (Management 3443, LB Probe 6390, Storage/KV/AzureMonitor outbound).
// Two follow-ups recommended for nsgApim before APIM serves traffic:
//   - Outbound TCP 1433 to service tag `Sql`     (APIM internal SQL DB)
//   - Outbound TCP 5671/5672/443 to `EventHub`   (APIM diagnostics path)
// See module README for the full required-rule list.
// =============================================================================

targetScope = 'resourceGroup'

metadata name = 'API Management module (internal VNet, Developer SKU)'

// ─────────────────────────────────────────────────────────────────────────────
// Parameters
// ─────────────────────────────────────────────────────────────────────────────

@description('Globally-unique APIM service name (1–50 chars, alphanumerics and hyphens; must start with a letter).')
@minLength(1)
@maxLength(50)
param name string

@description('Azure region for the APIM instance. Must offer Developer SKU + VNet injection.')
param location string

@description('Resource tags applied to the APIM service.')
param tags object = {}

@description('Resource ID of the dedicated APIM subnet (snet-apim, /27). VNet-injected, NOT a private endpoint subnet.')
param peSubnetId string

@description('Resource ID of the Log Analytics workspace receiving GatewayLogs + metrics.')
param lawId string

@description('Resource ID of the Application Insights component used by the built-in APIM logger.')
param appInsightsId string

@secure()
@description('Connection string for Application Insights. Used as credentials for the built-in APIM logger.')
param appInsightsConnectionString string

@description('APIM publisher contact email (placeholder; override per environment).')
param publisherEmail string = 'arbaaz@example.com'

@description('APIM publisher display name shown in the developer portal.')
param publisherName string = 'Private RAG Accelerator'

// SKU is intentionally NOT a parameter on this module: Phase 2a v3 cost ceiling
// locks APIM to Developer ($50/mo). Production callers needing Premium should
// fork or extend this module rather than parameterise the SKU here, to avoid
// accidental $2,800/mo bills.
var apimSku = 'Developer'
var apimSkuCount = 1

// ─────────────────────────────────────────────────────────────────────────────
// Custom properties: TLS / cipher hardening
// ─────────────────────────────────────────────────────────────────────────────
// Disable TLS 1.0 / 1.1 (gateway + backend), enable HTTP/2, disable the
// standard set of weak ciphers (3DES + CBC ciphers without PFS).
// Reference: https://learn.microsoft.com/azure/api-management/api-management-howto-manage-protocols-ciphers
var apimCustomProperties = {
  // Gateway (client-facing) protocol controls
  'Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Protocols.Tls10': 'False'
  'Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Protocols.Tls11': 'False'
  'Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Protocols.Ssl30': 'False'
  // Backend (origin-facing) protocol controls
  'Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Backend.Protocols.Tls10': 'False'
  'Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Backend.Protocols.Tls11': 'False'
  'Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Backend.Protocols.Ssl30': 'False'
  // HTTP/2 on the gateway
  'Microsoft.WindowsAzure.ApiManagement.Gateway.Protocols.Server.Http2': 'True'
  // Weak cipher disable set (matches AVM default + 3DES)
  'Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Ciphers.TripleDes168': 'False'
  'Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Ciphers.TLS_RSA_WITH_AES_128_CBC_SHA': 'False'
  'Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Ciphers.TLS_RSA_WITH_AES_256_CBC_SHA': 'False'
  'Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Ciphers.TLS_RSA_WITH_AES_128_CBC_SHA256': 'False'
  'Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Ciphers.TLS_RSA_WITH_AES_256_CBC_SHA256': 'False'
  'Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Ciphers.TLS_RSA_WITH_AES_128_GCM_SHA256': 'False'
  'Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Ciphers.TLS_ECDHE_RSA_WITH_AES_128_CBC_SHA': 'False'
  'Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Ciphers.TLS_ECDHE_RSA_WITH_AES_256_CBC_SHA': 'False'
}

// ─────────────────────────────────────────────────────────────────────────────
// AVM: API Management service
// Reference: https://github.com/Azure/bicep-registry-modules/tree/main/avm/res/api-management/service
// Version pinned to 0.14.1 (latest stable as of 2026-05-08).
// ─────────────────────────────────────────────────────────────────────────────
module apim 'br/public:avm/res/api-management/service:0.14.1' = {
  name: 'apim-${uniqueString(name)}'
  params: {
    name: name
    location: location
    tags: tags

    sku: apimSku
    skuCapacity: apimSkuCount

    publisherEmail: publisherEmail
    publisherName: publisherName

    // System-assigned MI — consumed by PR-O for RBAC (AOAI, Key Vault, etc.)
    managedIdentities: {
      systemAssigned: true
    }

    // Internal VNet injection — full VNet integration; no public IP on gateway.
    virtualNetworkType: 'Internal'
    subnetResourceId: peSubnetId

    // Hardened protocol + cipher suite.
    customProperties: apimCustomProperties

    // Built-in APIM App Insights logger. credentials must be the AI
    // connection string (instrumentation key is also accepted; conn string
    // is the modern form and what the AVM logger child expects).
    loggers: [
      {
        name: 'appinsights'
        type: 'applicationInsights'
        targetResourceId: appInsightsId
        description: 'Built-in App Insights logger (Phase 2a). Diagnostics policies bind to this logger in Phase 3.'
        isBuffered: true
        credentials: {
          connectionString: appInsightsConnectionString
        }
      }
    ]

    // Diagnostic settings → LAW. GatewayLogs + AllMetrics.
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
// Outputs — consumed by PR-O wiring layer:
//   - resourceId  : RBAC scope, backend registrations
//   - gatewayUrl  : feed into Container App config / API client base URL
//   - principalId : assign Cognitive Services OpenAI User on AOAI, Key Vault
//                   Secrets User on KV, etc. (Phase 2b/3)
// ─────────────────────────────────────────────────────────────────────────────

@description('Resource ID of the APIM service.')
output resourceId string = apim.outputs.resourceId

@description('Name of the APIM service.')
output name string = apim.outputs.name

@description('Internal gateway URL (resolves to VNet-internal VIP via the azure-api.net private DNS zone).')
output gatewayUrl string = 'https://${apim.outputs.name}.azure-api.net'

@description('Principal ID of the APIM system-assigned managed identity. Empty until first successful deployment.')
output principalId string = apim.outputs.?systemAssignedMIPrincipalId ?? ''
