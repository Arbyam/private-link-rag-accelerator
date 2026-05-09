// =============================================================================
// Private RAG Accelerator — Subscription-Scope Orchestrator
// =============================================================================
// targetScope  : subscription
// Deploys      : resource group + all Phase 2a modules (see module placeholders)
//
// NAMING CONVENTION
// -----------------
// Pattern  : {namingPrefix}-{resource-type}-{env}-{regionShort}
// Examples :
//   rg-rag-dev-eus2          → resource group
//   vnet-rag-dev-eus2        → virtual network
//   kv-rag-dev-eus2          → key vault
//   apim-rag-dev-eus2        → API Management
//   acrragdeveus2            → container registry  (no hyphens, alphanumeric)
//   stragdeveus2             → storage account     (no hyphens, ≤24 chars)
//
// Region short-codes (map in `variables` section):
//   eastus2 → eus2   westus2 → wus2   westeurope → weu   northeurope → neu
//
// All names are derived deterministically from namingPrefix + env + regionShort.
// uniqueString() is NEVER used for primary resource names — full idempotency.
//
// TAGS
// ----
// Every resource receives: { env, project, owner, costCenter, managedBy: 'azd' }
//
// ZERO-TRUST POSTURE
// ------------------
// No parameter may default to publicNetworkAccess:Enabled or equivalent.
// APIM must always be virtualNetworkType:'Internal'.
// The only intentional public endpoint is the Azure Bastion public IP (by design).
// =============================================================================

targetScope = 'subscription'

// =============================================================================
// PARAMETERS
// =============================================================================

// ── Identity & Naming ────────────────────────────────────────────────────────

@description('Short prefix used to derive deterministic names for all resources (e.g. "rag"). 2–8 alphanumeric characters.')
@minLength(2)
@maxLength(8)
param namingPrefix string

@description('Azure region for all resources (e.g. "eastus2"). Must support all required resource types.')
param location string = 'eastus2'

@description('Deployment environment label. Drives SKU defaults and cost-gate semantics.')
@allowed(['dev', 'staging', 'prod'])
param environmentName string = 'dev'

@description('Object ID of the Entra ID security group granted admin RBAC on Key Vault, AI Search, Cosmos DB, and Azure OpenAI.')
param adminGroupObjectId string

@description('Optional list of Entra ID group object IDs granted read/chat access to the RAG application. Leave empty to allow all authenticated users.')
param allowedUserGroupObjectIds array = []

@description('Cost-center tag value applied to every resource for FinOps chargeback reporting.')
@minLength(2)
@maxLength(20)
param costCenter string = 'platform'

@description('Owner tag value (team name or alias) applied to every resource for resource accountability.')
@minLength(2)
@maxLength(40)
param owner string = 'platform-team'

// ── Networking ───────────────────────────────────────────────────────────────

@description('VNet address space CIDR. Default 10.0.0.0/22 provides 1024 IPs across all subnets.')
param vnetAddressPrefix string = '10.0.0.0/22'

@description('Container Apps Environment subnet CIDR. /24 = 256 IPs; hosts ACA infrastructure (apps + jobs share one environment).')
param snetAcaPrefix string = '10.0.0.0/24'

@description('Private Endpoints + jumpbox VM subnet CIDR. /24 = 256 IPs; all PaaS private endpoints land here.')
param snetPePrefix string = '10.0.1.0/24'

@description('RESERVED subnet CIDR for future expansion (second ACA env, Azure Functions, etc.). No delegation applied. /24 = 256 IPs.')
param snetJobsPrefix string = '10.0.2.0/24'

@description('Azure Bastion subnet CIDR. Must be named AzureBastionSubnet; /26 minimum per Azure requirement.')
param snetBastionPrefix string = '10.0.3.0/26'

@description('Azure API Management subnet CIDR. /27 = 32 IPs; minimum for APIM VNet injection (1 VIP + reserved + scaling headroom).')
param snetApimPrefix string = '10.0.3.64/27'

@description('When true, Private DNS zones are NOT created — caller must provide DNS forwarding to the VNet. Default false = accelerator creates and manages DNS zones.')
param customerProvidedDns bool = false

// ── Feature Flags ────────────────────────────────────────────────────────────

@description('Deploy Azure Bastion Standard host (~$140/mo). Default false per Phase 2a v3 budget plan — Bastion Developer (free portal-only RDP/SSH) is used instead. Set true only if you need a dedicated Bastion host with native client / multi-session support.')
param deployBastion bool = false

@description('Deploy a Linux jumpbox VM (Ubuntu 24.04, Standard_B2s) in snet-pe for in-VNet console / smoke-test access. ~$36/mo when running, $0 when deallocated. Default true per Phase 2a v3 plan — required because internal-only ingress blocks GitHub-runner curl.')
param deployJumpbox bool = true

@description('Enable availability-zone redundancy on resources that support it (Storage, Cosmos DB, ACR, etc.). Increases cost; recommended for prod.')
param enableZoneRedundancy bool = false

@description('Enable Customer-Managed Key encryption on Cosmos DB, Storage, and Azure OpenAI via Key Vault. Requires Key Vault to be healthy before CMK resources deploy.')
param enableCustomerManagedKey bool = false

// ── AI / Cognitive Services ──────────────────────────────────────────────────

@description('Azure OpenAI chat-completion model deployment name. Must be available in the selected region (pre-flight script T014 validates availability).')
param chatModel string = 'gpt-5'

@description('Azure OpenAI text-embedding model deployment name.')
param embeddingModel string = 'text-embedding-3-large'

// ── SKUs ─────────────────────────────────────────────────────────────────────

@description('Azure AI Search SKU. Default "basic" per Phase 2a v3 budget plan (~$74/mo, supports private endpoints, 15 GB / 3 indexes — sufficient for demo). Use "standard" or higher for production vector/hybrid search workloads.')
@allowed(['free', 'basic', 'standard', 'standard2', 'standard3'])
param aiSearchSku string = 'basic'

@description('Azure API Management SKU. Default "Developer" per Phase 2a v3 budget plan (~$50/mo, internal VNet mode, no SLA — acceptable for demo). "Premium" (~$2,800/mo) required only for production SLA + multi-region. StandardV2 is disqualified — it cannot run fully internal (violates SC-004).')
@allowed(['Developer', 'Premium'])
param apimSku string = 'Developer'

@description('APIM publisher e-mail address. Displayed in the developer portal and used for system notifications. Override per environment in the parameter file.')
@minLength(1)
param apimPublisherEmail string = 'azd@example.com'

@description('APIM publisher display name shown in the developer portal.')
@minLength(1)
@maxLength(100)
param apimPublisherName string = 'RAG Accelerator'

// ── Cost & Budget ────────────────────────────────────────────────────────────

@description('Cosmos DB capacity mode. Default "Serverless" per Phase 2a v3 budget plan (~$3/mo for demo workload, pay-per-RU, no minimum). Use "Provisioned" for predictable production throughput with autoscale.')
@allowed(['Serverless', 'Provisioned'])
param cosmosCapacityMode string = 'Serverless'

@description('Monthly spend threshold in USD. A budget alert fires when actual spend reaches 100% of this value. Default 500 per Phase 2a v3 hard ceiling — total estimated demo cost is ~$318/mo with 36% headroom.')
@minValue(100)
param budgetMonthlyUsd int = 500

// =============================================================================
// VARIABLES — Naming, tags, derived values
// =============================================================================

// Region short-code lookup — add new regions here as needed
var regionShortMap = {
  eastus:          'eus'
  eastus2:         'eus2'
  westus:          'wus'
  westus2:         'wus2'
  westus3:         'wus3'
  centralus:       'cus'
  northcentralus:  'ncus'
  southcentralus:  'scus'
  westeurope:      'weu'
  northeurope:     'neu'
  uksouth:         'uks'
  ukwest:          'ukw'
  australiaeast:   'aue'
  southeastasia:   'sea'
  eastasia:        'eas'
  japaneast:       'jpe'
  canadacentral:   'cac'
  brazilsouth:     'brs'
  swedencentral:   'swc'
}

var regionShort = regionShortMap[?location] ?? location

// Base token shared by most resource names
var baseName = '${namingPrefix}-${environmentName}-${regionShort}'

// Deterministic resource name map (one source of truth — no naming scattered across modules)
var names = {
  resourceGroup:  'rg-${baseName}'
  vnet:           'vnet-${baseName}'
  nsgAca:         'nsg-aca-${baseName}'
  nsgPe:          'nsg-pe-${baseName}'
  nsgJobs:        'nsg-jobs-${baseName}'
  nsgBastion:     'nsg-bastion-${baseName}'
  nsgApim:        'nsg-apim-${baseName}'
  identityApi:    'mi-api-${baseName}'
  identityIngest: 'mi-ingest-${baseName}'
  identityWeb:    'mi-web-${baseName}'
  law:            'law-${baseName}'
  appInsights:    'appi-${baseName}'
  ampls:          'ampls-${baseName}'
  // ACR: alphanumeric only, no hyphens
  acr:            replace('acr${namingPrefix}${environmentName}${regionShort}', '-', '')
  keyvault:       'kv-${baseName}'
  // Storage: alphanumeric only, no hyphens, ≤24 chars
  storage:        take(replace('st${namingPrefix}${environmentName}${regionShort}', '-', ''), 24)
  cosmos:         'cosmos-${baseName}'
  search:         'srch-${baseName}'
  openai:         'oai-${baseName}'
  docintel:       'di-${baseName}'
  apim:           'apim-${baseName}'
  acaEnv:         'acae-${baseName}'
  acaApi:         'aca-api-${baseName}'
  acaIngest:      'aca-ingest-${baseName}'
  acaWeb:         'aca-web-${baseName}'
  bastion:        'bas-${baseName}'
  jumpbox:        'vm-jumpbox-${baseName}'
  budget:         'budget-${baseName}'
}

// Standard tags — applied to resource group and every child resource via module params
var tags = {
  env:        environmentName
  project:    'private-rag-accelerator'
  owner:      owner
  costCenter: costCenter
  managedBy:  'azd'
}

// =============================================================================
// RESOURCE GROUP
// =============================================================================

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name:     names.resourceGroup
  location: location
  tags:     tags
}

// =============================================================================
// MODULE CALL PLACEHOLDERS
// =============================================================================
// Each block below is commented out — the module file does not exist yet.
// Module files ship in subsequent PRs (PR-B through PR-Q).
// The parameter shapes shown here define the contract each module must satisfy.
// When PR-O (T029/T030) wires everything together, these blocks are uncommented.
//
// Placeholder format:
//   // {TaskID} / {PR-label} — {one-line description of what this module does}
// =============================================================================

// ── Layer 1: Foundation ───────────────────────────────────────────────────────

// T017 / PR-B — VNet (10.0.0.0/22) + 5 subnets + NSGs + 13 Private DNS Zones (gated by customerProvidedDns)
// module network 'modules/network/main.bicep' = {
//   name: 'network'
//   scope: rg
//   params: {
//     location:             location
//     tags:                 tags
//     vnetName:             names.vnet
//     vnetAddressPrefix:    vnetAddressPrefix
//     snetAcaName:          'snet-aca'
//     snetAcaPrefix:        snetAcaPrefix
//     snetPeName:           'snet-pe'
//     snetPePrefix:         snetPePrefix
//     snetJobsName:         'snet-jobs'          // RESERVED — no delegation
//     snetJobsPrefix:       snetJobsPrefix
//     snetBastionName:      'AzureBastionSubnet' // Required name for Bastion
//     snetBastionPrefix:    snetBastionPrefix
//     snetApimName:         'snet-apim'
//     snetApimPrefix:       snetApimPrefix
//     nsgAcaName:           names.nsgAca
//     nsgPeName:            names.nsgPe
//     nsgJobsName:          names.nsgJobs
//     nsgBastionName:       names.nsgBastion
//     nsgApimName:          names.nsgApim
//     customerProvidedDns:  customerProvidedDns
//   }
// }

// T018 / PR-C — 3 user-assigned managed identities: mi-api, mi-ingest, mi-web
// module identity 'modules/identity/main.bicep' = {
//   name: 'identity'
//   scope: rg
//   params: {
//     location:             location
//     tags:                 tags
//     identityApiName:      names.identityApi
//     identityIngestName:   names.identityIngest
//     identityWebName:      names.identityWeb
//   }
// }

// ── Layer 2: Platform Services ────────────────────────────────────────────────

// T019 / PR-D — Log Analytics Workspace, App Insights (workspace-based), AMPLS + PE, monthly Budget alert
// module monitoring 'modules/monitoring/main.bicep' = {
//   name: 'monitoring'
//   scope: rg
//   dependsOn: [network]
//   params: {
//     location:                 location
//     tags:                     tags
//     lawName:                  names.law
//     appInsightsName:          names.appInsights
//     amplsName:                names.ampls
//     peSubnetId:               network.outputs.snetPeId
//     budgetName:               names.budget
//     budgetMonthlyUsd:         budgetMonthlyUsd
//     customerProvidedDns:      customerProvidedDns
//   }
// }

// T020 / PR-E — ACR Premium + Private Endpoint + AcrPull role assignments for all 3 managed identities
// module registry 'modules/registry/main.bicep' = {
//   name: 'registry'
//   scope: rg
//   dependsOn: [network, identity]
//   params: {
//     location:                     location
//     tags:                         tags
//     acrName:                      names.acr
//     peSubnetId:                   network.outputs.snetPeId
//     identityApiPrincipalId:       identity.outputs.identityApiPrincipalId
//     identityIngestPrincipalId:    identity.outputs.identityIngestPrincipalId
//     identityWebPrincipalId:       identity.outputs.identityWebPrincipalId
//     enableZoneRedundancy:         enableZoneRedundancy
//     customerProvidedDns:          customerProvidedDns
//   }
// }

// T021 / PR-F — Key Vault Standard + Private Endpoint + RBAC auth (no legacy access policies)
// module keyvault 'modules/keyvault/main.bicep' = {
//   name: 'keyvault'
//   scope: rg
//   dependsOn: [network]
//   params: {
//     location:            location
//     tags:                tags
//     keyVaultName:        names.keyvault
//     peSubnetId:          network.outputs.snetPeId
//     adminGroupObjectId:  adminGroupObjectId
//     customerProvidedDns: customerProvidedDns
//   }
// }

// ── Layer 2.5: API Gateway ────────────────────────────────────────────────────

// T032a / PR-L — APIM (Premium or Developer SKU) in VNet-injected internal mode; system MI; diagnostics → LAW + App Insights
// NOTE: virtualNetworkType is always 'Internal' — no public endpoints. See C.1 in phase-2-plan.md for SKU rationale.
// module apim 'modules/apim/main.bicep' = {
//   name: 'apim'
//   scope: rg
//   dependsOn: [network, identity, monitoring]
//   params: {
//     location:                     location
//     tags:                         tags
//     apimName:                     names.apim
//     apimSku:                      apimSku
//     apimPublisherEmail:           apimPublisherEmail
//     apimPublisherName:            apimPublisherName
//     subnetId:                     network.outputs.snetApimId
//     lawId:                        monitoring.outputs.lawId
//     appInsightsId:                monitoring.outputs.appInsightsId
//     appInsightsConnectionString:  monitoring.outputs.appInsightsConnectionString
//     customerProvidedDns:          customerProvidedDns
//   }
// }

// ── Layer 3: Data Plane ───────────────────────────────────────────────────────
// IMPORTANT: openai deploys BEFORE search — AI Search shared private link to AOAI
// requires the AOAI resource to exist on first deploy. See phase-2-plan.md §D.

// T025 / PR-I — Azure OpenAI + Private Endpoint + gpt-5 (chat) + text-embedding-3-large deployments
// module openai 'modules/openai/main.bicep' = {
//   name: 'openai'
//   scope: rg
//   dependsOn: [network, identity]
//   params: {
//     location:                   location
//     tags:                       tags
//     openAiName:                 names.openai
//     peSubnetId:                 network.outputs.snetPeId
//     chatModel:                  chatModel
//     embeddingModel:             embeddingModel
//     identityApiPrincipalId:     identity.outputs.identityApiPrincipalId
//     identityIngestPrincipalId:  identity.outputs.identityIngestPrincipalId
//     enableCustomerManagedKey:   enableCustomerManagedKey
//     keyVaultId:                 keyvault.outputs.keyVaultId
//     customerProvidedDns:        customerProvidedDns
//   }
// }

// T022 / PR-G — StorageV2 + Private Endpoints (blob + queue) + containers + lifecycle policy + Event Grid system topic
// module storage 'modules/storage/main.bicep' = {
//   name: 'storage'
//   scope: rg
//   dependsOn: [network, identity]
//   params: {
//     location:                   location
//     tags:                       tags
//     storageName:                names.storage
//     peSubnetId:                 network.outputs.snetPeId
//     identityIngestPrincipalId:  identity.outputs.identityIngestPrincipalId
//     identityApiPrincipalId:     identity.outputs.identityApiPrincipalId
//     enableZoneRedundancy:       enableZoneRedundancy
//     enableCustomerManagedKey:   enableCustomerManagedKey
//     keyVaultId:                 keyvault.outputs.keyVaultId
//     customerProvidedDns:        customerProvidedDns
//   }
// }

// T023 / PR-H — Cosmos DB NoSQL + Private Endpoint + 3 containers (docs, chunks, leases) with TTL
// module cosmos 'modules/cosmos/main.bicep' = {
//   name: 'cosmos'
//   scope: rg
//   dependsOn: [network, identity]
//   params: {
//     location:                   location
//     tags:                       tags
//     cosmosName:                 names.cosmos
//     peSubnetId:                 network.outputs.snetPeId
//     identityApiPrincipalId:     identity.outputs.identityApiPrincipalId
//     identityIngestPrincipalId:  identity.outputs.identityIngestPrincipalId
//     cosmosCapacityMode:         cosmosCapacityMode
//     enableZoneRedundancy:       enableZoneRedundancy
//     enableCustomerManagedKey:   enableCustomerManagedKey
//     keyVaultId:                 keyvault.outputs.keyVaultId
//     customerProvidedDns:        customerProvidedDns
//   }
// }

// T026 / PR-K — Document Intelligence + Private Endpoint
// module docintel 'modules/docintel/main.bicep' = {
//   name: 'docintel'
//   scope: rg
//   dependsOn: [network, identity]
//   params: {
//     location:                   location
//     tags:                       tags
//     docIntelName:               names.docintel
//     peSubnetId:                 network.outputs.snetPeId
//     identityIngestPrincipalId:  identity.outputs.identityIngestPrincipalId
//     customerProvidedDns:        customerProvidedDns
//   }
// }

// T024 / PR-J — AI Search S1 + Private Endpoint + shared private links to AOAI + Storage
// ← explicit dependsOn openai: shared private link to AOAI requires AOAI resource to exist
// module search 'modules/search/main.bicep' = {
//   name: 'search'
//   scope: rg
//   dependsOn: [network, identity, openai]
//   params: {
//     location:                   location
//     tags:                       tags
//     searchName:                 names.search
//     aiSearchSku:                aiSearchSku
//     peSubnetId:                 network.outputs.snetPeId
//     identityApiPrincipalId:     identity.outputs.identityApiPrincipalId
//     identityIngestPrincipalId:  identity.outputs.identityIngestPrincipalId
//     openAiResourceId:           openai.outputs.openAiResourceId
//     storageAccountId:           storage.outputs.storageAccountId
//     customerProvidedDns:        customerProvidedDns
//   }
// }

// ── Layer 4: Compute ──────────────────────────────────────────────────────────

// T027 / PR-M — ACA Environment (internal=true, VNet-integrated) + api app + ingest app + ingest job
// NOTE: ACA supports one infrastructure subnet per environment; apps + jobs share snet-aca.
// module containerapps 'modules/containerapps/main.bicep' = {
//   name: 'containerapps'
//   scope: rg
//   dependsOn: [network, identity, monitoring, registry]
//   params: {
//     location:                      location
//     tags:                          tags
//     acaEnvName:                    names.acaEnv
//     acaApiName:                    names.acaApi
//     acaIngestName:                 names.acaIngest
//     acaWebName:                    names.acaWeb
//     subnetId:                      network.outputs.snetAcaId
//     identityApiId:                 identity.outputs.identityApiId
//     identityIngestId:              identity.outputs.identityIngestId
//     identityWebId:                 identity.outputs.identityWebId
//     lawId:                         monitoring.outputs.lawId
//     appInsightsConnectionString:   monitoring.outputs.appInsightsConnectionString
//     acrLoginServer:                registry.outputs.acrLoginServer
//   }
// }

// T028 / PR-N — Azure Bastion Standard + Linux jumpbox VM (Ubuntu 24.04, Standard_B2s) in snet-pe
// NOTE: Jumpbox is in snet-pe (not a dedicated subnet) — conserves IP space; internal-only, MI-authenticated.
// NOTE: Bastion Standard is the ONLY resource with a public IP — documented exception to SC-004.
// NOTE: Phase 2a v3 budget plan defaults deployBastion=false / deployJumpbox=true — Bastion Developer
//       (free portal-only RDP/SSH, shared MS pool) reaches the jumpbox without a deployed Bastion host.
//       PR-N will split this into two `if (...)` modules: bastion-only and jumpbox-only.
// module bastion 'modules/bastion/main.bicep' = if (deployBastion || deployJumpbox) {
//   name: 'bastion'
//   scope: rg
//   dependsOn: [network]
//   params: {
//     location:         location
//     tags:             tags
//     bastionName:      names.bastion
//     jumpboxName:      names.jumpbox
//     bastionSubnetId:  network.outputs.snetBastionId
//     jumpboxSubnetId:  network.outputs.snetPeId
//   }
// }

// ── Layer 5: Cross-Cutting Wiring ─────────────────────────────────────────────

// T029 + T030 / PR-O — RBAC role assignments across all resources + full main.bicep module wiring
// This PR uncomments all module blocks above, adds inter-module role assignments,
// and expands the outputs section below.

// ── Layer 6: Polish ───────────────────────────────────────────────────────────

// T031 / PR-P — AVM refactor pass: audit all modules for latest AVM versions; replace any hand-rolled with AVM where mature
// T032 / PR-Q — infra/README.md: module documentation, AVM version table, first-deploy guidance, known caveats

// =============================================================================
// OUTPUTS
// =============================================================================
// Minimal outputs from the shell — expanded in PR-O (T030) when modules are wired.
// Commented outputs below define the contract: shape and name are fixed now
// so downstream callers (azd, postprovision hooks) can be written against them.

output resourceGroupName string = rg.name
output resourceGroupId   string = rg.id
output location          string = location
output environmentName   string = environmentName

// The following outputs are uncommented in PR-O (T029/T030) once modules ship:
// output vnetId                      string = network.outputs.vnetId
// output acaEnvDefaultDomain         string = containerapps.outputs.acaEnvDefaultDomain
// output uiUrl                       string = 'https://web.${containerapps.outputs.acaEnvDefaultDomain}'
// output acrLoginServer              string = registry.outputs.acrLoginServer
// output cosmosEndpoint              string = cosmos.outputs.cosmosEndpoint
// output searchEndpoint              string = search.outputs.searchEndpoint
// output openAiEndpoint              string = openai.outputs.openAiEndpoint
// output storageAccountName          string = storage.outputs.storageAccountName
// output keyVaultUri                 string = keyvault.outputs.keyVaultUri
// output appInsightsConnectionString string = monitoring.outputs.appInsightsConnectionString
// output apimGatewayUrl              string = apim.outputs.apimGatewayUrl  // internal APIM gateway URL
// output apimResourceId              string = apim.outputs.apimResourceId  // for RBAC wiring in T029
