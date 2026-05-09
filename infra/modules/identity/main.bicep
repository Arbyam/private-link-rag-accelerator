// =============================================================================
// Identity module — user-assigned managed identities (T018 / PR-C)
// =============================================================================
// Deploys the user-assigned managed identities (UAMIs) used by every Phase 2a
// compute principal in the Private RAG Accelerator. UAMIs replace shared keys
// throughout the architecture per Constitution Principle I (zero-trust).
//
// Per Ripley's Phase 2a plan §F (Principle I) the workload identities are:
//   - mi-api    → FastAPI backend Container App  (Cosmos / Search / AOAI / Storage / Doc Intel)
//   - mi-ingest → Ingest worker Container App    (Cosmos / Search / AOAI / Storage / Doc Intel)
//   - mi-web    → Next.js frontend Container App (ACR pull only — calls APIM, not PaaS direct)
//
// APIM uses its own SYSTEM-assigned identity (created on the APIM resource
// itself in PR-N) and is intentionally NOT part of this module.
//
// No deployment identity (id-deploy) is provisioned here: GitHub Actions auths
// to Azure via OIDC federated credentials on a service principal scoped at the
// subscription, not via a UAMI inside the workload RG.
//
// Role assignments and main.bicep wiring live in PR-O (T029/T030).
// =============================================================================

targetScope = 'resourceGroup'

// ── Parameters ──────────────────────────────────────────────────────────────

@description('Azure region for the managed identities. Should match the parent resource group.')
param location string = resourceGroup().location

@description('Tags applied to every identity resource for cost / ownership tracking.')
param tags object = {}

@description('Name of the user-assigned managed identity for the FastAPI backend Container App.')
@minLength(3)
@maxLength(128)
param identityApiName string

@description('Name of the user-assigned managed identity for the ingest worker Container App.')
@minLength(3)
@maxLength(128)
param identityIngestName string

@description('Name of the user-assigned managed identity for the Next.js frontend Container App.')
@minLength(3)
@maxLength(128)
param identityWebName string

// ── Resources (AVM: avm/res/managed-identity/user-assigned-identity) ────────

module miApi 'br/public:avm/res/managed-identity/user-assigned-identity:0.4.1' = {
  name: 'uami-api'
  params: {
    name: identityApiName
    location: location
    tags: tags
  }
}

module miIngest 'br/public:avm/res/managed-identity/user-assigned-identity:0.4.1' = {
  name: 'uami-ingest'
  params: {
    name: identityIngestName
    location: location
    tags: tags
  }
}

module miWeb 'br/public:avm/res/managed-identity/user-assigned-identity:0.4.1' = {
  name: 'uami-web'
  params: {
    name: identityWebName
    location: location
    tags: tags
  }
}

// ── Outputs ─────────────────────────────────────────────────────────────────
// Individual outputs match the contract pre-wired in infra/main.bicep (T015).
// The `identities` map is a convenience aggregate for downstream consumers
// (e.g. PR-O role-assignment loops).

@description('Resource ID of the FastAPI backend (api) user-assigned managed identity.')
output identityApiId string = miApi.outputs.resourceId

@description('Principal (object) ID of the api UAMI — used for role assignments.')
output identityApiPrincipalId string = miApi.outputs.principalId

@description('Client ID of the api UAMI — used for federated credential / token requests.')
output identityApiClientId string = miApi.outputs.clientId

@description('Resource ID of the ingest worker user-assigned managed identity.')
output identityIngestId string = miIngest.outputs.resourceId

@description('Principal (object) ID of the ingest UAMI — used for role assignments.')
output identityIngestPrincipalId string = miIngest.outputs.principalId

@description('Client ID of the ingest UAMI — used for federated credential / token requests.')
output identityIngestClientId string = miIngest.outputs.clientId

@description('Resource ID of the Next.js frontend (web) user-assigned managed identity.')
output identityWebId string = miWeb.outputs.resourceId

@description('Principal (object) ID of the web UAMI — used for role assignments (AcrPull only).')
output identityWebPrincipalId string = miWeb.outputs.principalId

@description('Client ID of the web UAMI.')
output identityWebClientId string = miWeb.outputs.clientId

@description('Aggregate map { api | ingest | web } → { resourceId, principalId, clientId } for downstream consumers.')
output identities object = {
  api: {
    resourceId: miApi.outputs.resourceId
    principalId: miApi.outputs.principalId
    clientId: miApi.outputs.clientId
    name: identityApiName
  }
  ingest: {
    resourceId: miIngest.outputs.resourceId
    principalId: miIngest.outputs.principalId
    clientId: miIngest.outputs.clientId
    name: identityIngestName
  }
  web: {
    resourceId: miWeb.outputs.resourceId
    principalId: miWeb.outputs.principalId
    clientId: miWeb.outputs.clientId
    name: identityWebName
  }
}
