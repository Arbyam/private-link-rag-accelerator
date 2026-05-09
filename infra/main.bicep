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

@description('Optional list of Entra ID group object IDs granted read/chat access to the RAG application. Leave empty to allow all authenticated users. Consumed by Phase 3 access policy (PR-S+).')
#disable-next-line no-unused-params
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

@description('Enable availability-zone redundancy on resources that support it (Storage, Cosmos DB, ACR, etc.). Increases cost; recommended for prod. Currently locked OFF in modules per Phase 2a v3 cost plan; surfaced here for Phase 2b zone-redundant variants.')
#disable-next-line no-unused-params
param enableZoneRedundancy bool = false

@description('Enable Customer-Managed Key encryption on Cosmos DB, Storage, and Azure OpenAI via Key Vault. Requires Key Vault to be healthy before CMK resources deploy. Surfaced here for Phase 2b CMK variants; not yet wired.')
#disable-next-line no-unused-params
param enableCustomerManagedKey bool = false

// ── AI / Cognitive Services ──────────────────────────────────────────────────

@description('Azure OpenAI chat-completion model deployment name. Must be available in the selected region (pre-flight script T014 validates availability).')
param chatModel string = 'gpt-5'

@description('Azure OpenAI text-embedding model deployment name.')
param embeddingModel string = 'text-embedding-3-large'

// ── SKUs ─────────────────────────────────────────────────────────────────────

@description('Azure AI Search SKU. Default "basic" per Phase 2a v3 budget plan (~$74/mo, supports private endpoints, 15 GB / 3 indexes — sufficient for demo). Use "standard" or higher for production vector/hybrid search workloads. Locked at "basic" inside modules/search; surfaced here as a knob for Phase 2b.')
@allowed(['free', 'basic', 'standard', 'standard2', 'standard3'])
#disable-next-line no-unused-params
param aiSearchSku string = 'basic'

@description('Azure API Management SKU. Default "Developer" per Phase 2a v3 budget plan (~$50/mo, internal VNet mode, no SLA — acceptable for demo). "Premium" (~$2,800/mo) required only for production SLA + multi-region. StandardV2 is disqualified — it cannot run fully internal (violates SC-004). Locked at "Developer" inside modules/apim; surfaced here as a knob for Phase 2b.')
@allowed(['Developer', 'Premium'])
#disable-next-line no-unused-params
param apimSku string = 'Developer'

@description('APIM publisher e-mail address. Displayed in the developer portal and used for system notifications. Override per environment in the parameter file.')
@minLength(1)
param apimPublisherEmail string = 'azd@example.com'

@description('APIM publisher display name shown in the developer portal.')
@minLength(1)
@maxLength(100)
param apimPublisherName string = 'RAG Accelerator'

// ── Cost & Budget ────────────────────────────────────────────────────────────

@description('Cosmos DB capacity mode. Default "Serverless" per Phase 2a v3 budget plan (~$3/mo for demo workload, pay-per-RU, no minimum). Use "Provisioned" for predictable production throughput with autoscale. Locked at "Serverless" inside modules/cosmos; surfaced here as a knob for Phase 2b.')
@allowed(['Serverless', 'Provisioned'])
#disable-next-line no-unused-params
param cosmosCapacityMode string = 'Serverless'

@description('Monthly spend threshold in USD. A budget alert fires when actual spend reaches 100% of this value. Default 500 per Phase 2a v3 hard ceiling — total estimated demo cost is ~$318/mo with 36% headroom. Wired by a follow-up budget module (out of scope for PR-O).')
@minValue(100)
#disable-next-line no-unused-params
param budgetMonthlyUsd int = 500

// ── Operations ───────────────────────────────────────────────────────────────

@description('SSH public key (single line, e.g. `ssh-rsa AAAA…`) for the Linux jumpbox admin user. Only consumed when deployJumpbox=true (or deployBastion=true). Replace the placeholder before deployment.')
@secure()
param jumpboxAdminPublicKey string = ''

@description('Linux admin username for the jumpbox VM.')
param jumpboxAdminUsername string = 'azureuser'

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
// MODULE WIRING (T029 / T030 / PR-O)
// =============================================================================
// Modules are invoked in dependency order:
//   1. network            VNet / subnets / NSGs / 13 PDNS zones
//   2. identity           UAMIs: api, ingest, web
//   3. monitoring         LAW + AppInsights + AMPLS PE
//   4. registry           ACR + AcrPull -> 3 app MIs
//   5. keyvault           KV + Secrets User -> api,ingest + Admin -> adminGroup
//   6. storage            StorageV2 + 2 PEs + EG topic + Blob/Queue RBAC
//   7. openai             AOAI + 2 model deployments + Cog Svcs OpenAI User RBAC
//   8. cosmos             Cosmos NoSQL + 3 containers + sqlRoleAssignments
//   9. docintel           DocIntel + Cog Svcs User RBAC
//  10. search             AI Search Basic + SPLs to AOAI/Storage + Index RBAC
//  11. containerapps      ACA env + web/api apps + ingest job
//  12. bastion            Gated; Bastion Developer + jumpbox VM
//  13. apim               APIM Developer / internal VNet
//
// IMPORTANT: openai + storage deploy BEFORE search — AI Search shared private
// links to AOAI/Storage require those resources to exist on first deploy.
// =============================================================================

// ── Layer 1: Foundation ───────────────────────────────────────────────────────

// T017 / PR-B
module network 'modules/network/main.bicep' = {
  name: 'network'
  scope: rg
  params: {
    location:             location
    tags:                 tags
    vnetName:             names.vnet
    vnetAddressPrefix:    vnetAddressPrefix
    snetAcaName:          'snet-aca'
    snetAcaPrefix:        snetAcaPrefix
    snetPeName:           'snet-pe'
    snetPePrefix:         snetPePrefix
    snetJobsName:         'snet-jobs'
    snetJobsPrefix:       snetJobsPrefix
    snetBastionName:      'AzureBastionSubnet'
    snetBastionPrefix:    snetBastionPrefix
    snetApimName:         'snet-apim'
    snetApimPrefix:       snetApimPrefix
    nsgAcaName:           names.nsgAca
    nsgPeName:            names.nsgPe
    nsgJobsName:          names.nsgJobs
    nsgBastionName:       names.nsgBastion
    nsgApimName:          names.nsgApim
    customerProvidedDns:  customerProvidedDns
  }
}

// T018 / PR-C
module identity 'modules/identity/main.bicep' = {
  name: 'identity'
  scope: rg
  params: {
    location:           location
    tags:               tags
    identityApiName:    names.identityApi
    identityIngestName: names.identityIngest
    identityWebName:    names.identityWeb
  }
}

// ── Layer 2: Platform Services ────────────────────────────────────────────────

// T019 / PR-D
module monitoring 'modules/monitoring/main.bicep' = {
  name: 'monitoring'
  scope: rg
  params: {
    location:                  location
    tags:                      tags
    lawName:                   names.law
    appInsightsName:           names.appInsights
    amplsName:                 names.ampls
    peSubnetId:                network.outputs.snetPeId
    privateDnsZoneIdMonitor:   network.outputs.pdnsMonitorId
    privateDnsZoneIdOms:       network.outputs.pdnsOmsId
    privateDnsZoneIdOds:       network.outputs.pdnsOdsId
    privateDnsZoneIdAgentSvc:  network.outputs.pdnsAgentSvcId
    privateDnsZoneIdBlob:      network.outputs.pdnsBlobId
  }
}

// T020 / PR-E — ACR + AcrPull -> web/api/ingest UAMIs (closes T020 RBAC fan-out)
module registry 'modules/registry/main.bicep' = {
  name: 'registry'
  scope: rg
  params: {
    location:             location
    tags:                 tags
    acrName:              names.acr
    peSubnetId:           network.outputs.snetPeId
    privateDnsZoneId:     network.outputs.pdnsAcrId
    acrPullPrincipalIds:  [
      identity.outputs.identityWebPrincipalId
      identity.outputs.identityApiPrincipalId
      identity.outputs.identityIngestPrincipalId
    ]
  }
}

// T021 / PR-F — Key Vault + Secrets User (api/ingest) + optional Admin (adminGroup)
module keyvault 'modules/keyvault/main.bicep' = {
  name: 'keyvault'
  scope: rg
  params: {
    location:                 location
    tags:                     tags
    vaultName:                names.keyvault
    peSubnetId:               network.outputs.snetPeId
    privateDnsZoneId:         network.outputs.pdnsKeyVaultId
    lawId:                    monitoring.outputs.lawId
    adminGroupObjectId:       adminGroupObjectId
    secretsUserPrincipalIds:  [
      identity.outputs.identityApiPrincipalId
      identity.outputs.identityIngestPrincipalId
    ]
  }
}

// ── Layer 3: Data Plane ───────────────────────────────────────────────────────

// T022 / PR-G — Storage + Blob (Contributor:ingest, Reader:api) + Queue Reader:ingest
module storage 'modules/storage/main.bicep' = {
  name: 'storage'
  scope: rg
  params: {
    location:                     location
    tags:                         tags
    #disable-next-line BCP334 // names.storage is take()-truncated; min-length 3 always satisfied for non-empty namingPrefix
    name:                         names.storage
    peSubnetId:                   network.outputs.snetPeId
    pdnsBlobId:                   network.outputs.pdnsBlobId
    pdnsQueueId:                  network.outputs.pdnsQueueId
    lawId:                        monitoring.outputs.lawId
    blobContributorPrincipalIds:  [
      identity.outputs.identityIngestPrincipalId
    ]
    blobReaderPrincipalIds:       [
      identity.outputs.identityApiPrincipalId
    ]
    queueReaderPrincipalIds:      [
      identity.outputs.identityIngestPrincipalId
    ]
  }
}

// T025 / PR-I — Azure OpenAI + Cog Svcs OpenAI User -> api/ingest
module openai 'modules/openai/main.bicep' = {
  name: 'openai'
  scope: rg
  params: {
    location:                location
    tags:                    tags
    name:                    names.openai
    peSubnetId:              network.outputs.snetPeId
    pdnsOpenaiId:            network.outputs.pdnsOpenaiId
    lawId:                   monitoring.outputs.lawId
    chatModel:               chatModel
    chatDeploymentName:      chatModel
    embeddingModel:          embeddingModel
    embeddingDeploymentName: embeddingModel
    openAiUserPrincipalIds:  [
      identity.outputs.identityApiPrincipalId
      identity.outputs.identityIngestPrincipalId
    ]
  }
}

// T023 / PR-H — Cosmos NoSQL + sqlRoleAssignments (Built-in Data Contributor)
module cosmos 'modules/cosmos/main.bicep' = {
  name: 'cosmos'
  scope: rg
  params: {
    location:                     location
    tags:                         tags
    name:                         names.cosmos
    peSubnetId:                   network.outputs.snetPeId
    pdnsCosmosId:                 network.outputs.pdnsCosmosId
    lawId:                        monitoring.outputs.lawId
    dataContributorPrincipalIds:  [
      identity.outputs.identityApiPrincipalId
      identity.outputs.identityIngestPrincipalId
    ]
  }
}

// T026 / PR-K — Document Intelligence + Cog Svcs User -> api/ingest
module docintel 'modules/docintel/main.bicep' = {
  name: 'docintel'
  scope: rg
  params: {
    location:                          location
    tags:                              tags
    name:                              names.docintel
    peSubnetId:                        network.outputs.snetPeId
    pdnsCogsvcsId:                     network.outputs.pdnsCognitiveId
    lawId:                             monitoring.outputs.lawId
    cognitiveServicesUserPrincipalIds: [
      identity.outputs.identityApiPrincipalId
      identity.outputs.identityIngestPrincipalId
    ]
  }
}

// T024 / PR-J — AI Search Basic + SPLs (AOAI, Storage) + Index RBAC
// IMPLICIT deps: openai + storage (via output references in params).
module search 'modules/search/main.bicep' = {
  name: 'search'
  scope: rg
  params: {
    location:                     location
    tags:                         tags
    name:                         names.search
    peSubnetId:                   network.outputs.snetPeId
    pdnsSearchId:                 network.outputs.pdnsSearchId
    lawId:                        monitoring.outputs.lawId
    aoaiResourceId:               openai.outputs.resourceId
    storageBlobResourceId:        storage.outputs.resourceId
    indexContributorPrincipalIds: [
      identity.outputs.identityIngestPrincipalId
    ]
    indexReaderPrincipalIds:      [
      identity.outputs.identityApiPrincipalId
    ]
  }
}

// ── Layer 4: Compute ──────────────────────────────────────────────────────────

// T027 / PR-M — ACA env + web app + api app + ingest job
// Env vars are sourced from data-plane outputs so apps reach dependencies via
// Entra MI (no secrets in env, no shared keys anywhere).
module containerapps 'modules/containerapps/main.bicep' = {
  name: 'containerapps'
  scope: rg
  params: {
    location:                     location
    tags:                         tags
    name:                         names.acaEnv
    peSubnetId:                   network.outputs.snetAcaId
    lawId:                        monitoring.outputs.lawId
    appInsightsConnectionString:  monitoring.outputs.appInsightsConnectionString
    acrLoginServer:               registry.outputs.acrLoginServer
    miWebId:                      identity.outputs.identityWebId
    miApiId:                      identity.outputs.identityApiId
    miIngestId:                   identity.outputs.identityIngestId
    ingestionStorageAccountName:  storage.outputs.name
    ingestionQueueName:           storage.outputs.ingestionQueueName
    appEnvVars: {
      AZURE_OPENAI_ENDPOINT:           openai.outputs.endpoint
      AZURE_OPENAI_CHAT_DEPLOYMENT:    openai.outputs.chatDeploymentName
      AZURE_OPENAI_EMBED_DEPLOYMENT:   openai.outputs.embeddingDeploymentName
      AZURE_SEARCH_ENDPOINT:           search.outputs.endpoint
      AZURE_COSMOS_ENDPOINT:           cosmos.outputs.endpoint
      AZURE_COSMOS_DATABASE:           cosmos.outputs.databaseName
      AZURE_STORAGE_ACCOUNT:           storage.outputs.name
      AZURE_STORAGE_BLOB_ENDPOINT:     storage.outputs.primaryBlobEndpoint
      AZURE_STORAGE_CORPUS_CONTAINER:  storage.outputs.sharedCorpusContainerName
      AZURE_STORAGE_UPLOADS_CONTAINER: storage.outputs.userUploadsContainerName
      AZURE_DOCINTEL_ENDPOINT:         docintel.outputs.endpoint
      AZURE_KEYVAULT_URI:              keyvault.outputs.kvUri
    }
    apiExtraEnvVars: {
      AZURE_CLIENT_ID: identity.outputs.identityApiClientId
    }
    ingestExtraEnvVars: {
      AZURE_CLIENT_ID: identity.outputs.identityIngestClientId
    }
    webExtraEnvVars: {
      AZURE_CLIENT_ID: identity.outputs.identityWebClientId
    }
  }
}

// T028 / PR-N — Bastion Developer (gated) + Linux jumpbox VM in snet-pe
module bastion 'modules/bastion/main.bicep' = if (deployBastion || deployJumpbox) {
  name: 'bastion'
  scope: rg
  params: {
    deployBastion:    deployBastion || deployJumpbox
    name:             baseName
    location:         location
    tags:             tags
    bastionSubnetId:  network.outputs.snetBastionId
    vmSubnetId:       network.outputs.snetPeId
    lawId:            monitoring.outputs.lawId
    adminUsername:    jumpboxAdminUsername
    adminPublicKey:   jumpboxAdminPublicKey
  }
}

// ── Layer 2.5: API Gateway ────────────────────────────────────────────────────
// Deployed late so the App Insights connection string is available. APIM has
// no inbound dependency on the data plane (Phase 3 wires backends/policies).

// T032a / PR-L — APIM Developer SKU, Internal VNet mode, App Insights logger
module apim 'modules/apim/main.bicep' = {
  name: 'apim'
  scope: rg
  params: {
    location:                    location
    tags:                        tags
    name:                        names.apim
    peSubnetId:                  network.outputs.snetApimId
    lawId:                       monitoring.outputs.lawId
    appInsightsId:               monitoring.outputs.appInsightsId
    appInsightsConnectionString: monitoring.outputs.appInsightsConnectionString
    publisherEmail:              apimPublisherEmail
    publisherName:               apimPublisherName
  }
}

// ── Layer 6: Polish ───────────────────────────────────────────────────────────
// T031 / PR-P — AVM refactor pass
// T032 / PR-Q — infra/README.md

// =============================================================================
// OUTPUTS
// =============================================================================
// Identity / scope ------------------------------------------------------------
output resourceGroupName string = rg.name
output resourceGroupId   string = rg.id
output location          string = location
output environmentName   string = environmentName

// Networking ------------------------------------------------------------------
output vnetId            string = network.outputs.vnetId
output snetAcaId         string = network.outputs.snetAcaId
output snetPeId          string = network.outputs.snetPeId
output snetApimId        string = network.outputs.snetApimId

// Identities ------------------------------------------------------------------
output identityApiClientId    string = identity.outputs.identityApiClientId
output identityIngestClientId string = identity.outputs.identityIngestClientId
output identityWebClientId    string = identity.outputs.identityWebClientId

// Observability ---------------------------------------------------------------
output lawId                       string = monitoring.outputs.lawId
output appInsightsId               string = monitoring.outputs.appInsightsId
@secure()
output appInsightsConnectionString string = monitoring.outputs.appInsightsConnectionString

// Registry --------------------------------------------------------------------
output acrLoginServer string = registry.outputs.acrLoginServer
output acrName        string = registry.outputs.acrName

// Data plane ------------------------------------------------------------------
output keyVaultUri              string = keyvault.outputs.kvUri
output storageAccountName       string = storage.outputs.name
output storagePrimaryBlobEndpoint string = storage.outputs.primaryBlobEndpoint
output ingestionQueueName       string = storage.outputs.ingestionQueueName
output cosmosEndpoint           string = cosmos.outputs.endpoint
output cosmosDatabaseName       string = cosmos.outputs.databaseName
output openAiEndpoint           string = openai.outputs.endpoint
output openAiChatDeployment     string = openai.outputs.chatDeploymentName
output openAiEmbedDeployment    string = openai.outputs.embeddingDeploymentName
output searchEndpoint           string = search.outputs.endpoint
output docIntelEndpoint         string = docintel.outputs.endpoint

// Compute (internal FQDNs — VNet-only resolvable) -----------------------------
output acaEnvironmentId string = containerapps.outputs.resourceId
output webAppFqdn       string = containerapps.outputs.webAppFqdn
output apiAppFqdn       string = containerapps.outputs.apiAppFqdn
output webAppName       string = containerapps.outputs.webAppName
output apiAppName       string = containerapps.outputs.apiAppName
output ingestJobName    string = containerapps.outputs.ingestJobName

// "Printed UI URL" per T030 — internal HTTPS to the web Container App.
// Resolves only inside the platform VNet (or via the Bastion jumpbox).
output uiUrl string = 'https://${containerapps.outputs.webAppFqdn}'

// API Gateway -----------------------------------------------------------------
output apimGatewayUrl  string = apim.outputs.gatewayUrl
output apimResourceId  string = apim.outputs.resourceId
