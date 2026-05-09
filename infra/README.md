# Private RAG Accelerator — Infrastructure

> **Phase 2a foundational IaC.** Subscription-scope Bicep deployment of a zero-trust, cost-optimized (~$318/mo target) Private Link RAG environment on Azure. All data-plane services run with `publicNetworkAccess: Disabled` behind Azure Private Endpoints; the only intentional public surface is an optional Bastion public IP (not deployed by default).

## Quick reference

| Property | Value |
|---|---|
| Cost ceiling | **$500/mo** (Arbyam directive 2026-05-08, hard cap) |
| Validated cost | **~$318/mo** (Ripley v3 plan, $182 / 36% headroom) |
| Default region | `eastus2` |
| Deployment scope | Subscription |
| Composition entry | [`infra/main.bicep`](./main.bicep) |
| Parameter files | [`infra/main.parameters.dev.json`](./main.parameters.dev.json), [`infra/main.parameters.prod.json`](./main.parameters.prod.json) |
| Module count | 13 |
| Private DNS zones | 13 (managed by `network` module unless `customerProvidedDns=true`) |
| Private endpoints | 9 (Storage blob+queue, Cosmos, Search, OpenAI, DocIntel, Key Vault, ACR, AMPLS) |
| Tooling | `azd` (Azure Developer CLI) + Bicep |

## How to deploy

The accelerator is wired for `azd up`. High level flow:

1. Authenticate (`azd auth login` and `az login --scope https://management.azure.com/.default`).
2. Provide a target subscription (`azd env set AZURE_SUBSCRIPTION_ID …`) and region.
3. Set required parameters, in particular `namingPrefix`, `adminGroupObjectId`, and (if `deployJumpbox=true`) `jumpboxAdminPublicKey`.
4. Run `azd provision` to deploy infrastructure, then `azd deploy` for application code (Phase 2b+).

For the operator runbook (pre-flight checks, model-quota validation, post-deploy smoke tests) see `specs/001-private-rag-accelerator/quickstart.md`.

## Architecture overview

- **Networking** — single VNet `10.0.0.0/22` with five subnets: `snet-aca` (Container Apps), `snet-pe` (Private Endpoints + jumpbox), `snet-jobs` (reserved), `AzureBastionSubnet` (reserved), `snet-apim` (APIM internal VNet injection). Five NSGs (`aca`, `pe`, `jobs`, `bastion`, `apim`).
- **DNS** — 13 Private DNS zones VNet-linked to the spoke. Set `customerProvidedDns=true` to skip zone creation when bringing your own hub-spoke DNS.
- **Identity** — three User-Assigned Managed Identities (`mi-api`, `mi-ingest`, `mi-web`) with RBAC fan-out to every data-plane service. Zero secrets in app config.
- **Data plane** — Storage (blob+queue+EG topic), Cosmos NoSQL Serverless, Azure AI Search Basic, Azure OpenAI (GPT-5 + text-embedding-3-large), Document Intelligence, Key Vault.
- **Compute** — Azure Container Apps Environment (internal ingress) hosting `web`, `api`, and an `ingest` job; backed by ACR Premium with image-pull MI auth.
- **API gateway** — Azure API Management Developer SKU, fully internal VNet mode (`virtualNetworkType: 'Internal'`).
- **Observability** — Log Analytics + Application Insights wrapped by an Azure Monitor Private Link Scope (AMPLS) so monitor traffic stays on-VNet.
- **Operator access** — optional Bastion Developer (free, gated) + Linux jumpbox VM in `snet-pe` for in-VNet smoke tests.

## Module catalog

All AVM versions below are pinned (no `latest`, no floating ranges) per the AVM pin policy. Versions reflect what is committed at the head of this branch — see `infra/AVM-AUDIT.md` (PR-P artifact, may not yet exist) for the canonical inventory.

---

### `network` — Foundational network (T017)

- **AVM:** `br/public:avm/res/network/private-dns-zone:0.7.1` (13 zones via `for` loop). VNet, subnets, NSGs are hand-rolled (no AVM coverage required).
- **Cost:** ~$7/mo (13 DNS zones × $0.50) + $0 (VNet/NSGs)

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `location` | string | ✅ | — | Azure region |
| `tags` | object | ✅ | — | Standard tag set |
| `vnetName` | string | ✅ | — | VNet resource name |
| `vnetAddressPrefix` | string | — | `10.0.0.0/22` | VNet CIDR (1024 IPs) |
| `snetAcaName` | string | — | `snet-aca` | Container Apps subnet name |
| `snetPeName` | string | — | `snet-pe` | Private Endpoint + jumpbox subnet name |
| `snetJobsName` | string | — | `snet-jobs` | Reserved subnet name |
| `snetBastionName` | string | — | `AzureBastionSubnet` | Bastion subnet (Azure-mandated name) |
| `snetApimName` | string | — | `snet-apim` | APIM injection subnet name |
| `snetAcaPrefix` | string | — | `10.0.0.0/24` | ACA subnet CIDR (256) |
| `snetPePrefix` | string | — | `10.0.1.0/24` | PE subnet CIDR (256) |
| `snetJobsPrefix` | string | — | `10.0.2.0/24` | Reserved subnet CIDR (256) |
| `snetBastionPrefix` | string | — | `10.0.3.0/26` | Bastion subnet CIDR (64) |
| `snetApimPrefix` | string | — | `10.0.3.64/27` | APIM subnet CIDR (32) |
| `nsgAcaName` | string | ✅ | — | NSG name for ACA subnet |
| `nsgPeName` | string | ✅ | — | NSG name for PE subnet |
| `nsgJobsName` | string | ✅ | — | NSG name for jobs subnet |
| `nsgBastionName` | string | ✅ | — | NSG name for Bastion subnet |
| `nsgApimName` | string | ✅ | — | NSG name for APIM subnet |
| `customerProvidedDns` | bool | — | `false` | Skip Private DNS zone creation |
| `privateDnsZoneNames` | array | — | 13 names | Override DNS zone list (default below) |

Default DNS zones: `privatelink.openai.azure.com`, `privatelink.search.windows.net`, `privatelink.documents.azure.com`, `privatelink.blob.core.windows.net`, `privatelink.queue.core.windows.net`, `privatelink.vaultcore.azure.net`, `privatelink.azurecr.io`, `privatelink.cognitiveservices.azure.com`, `privatelink.monitor.azure.com`, `privatelink.oms.opinsights.azure.com`, `privatelink.ods.opinsights.azure.com`, `privatelink.agentsvc.azure-automation.net`, `azure-api.net`.

| Output | Type | Description |
|---|---|---|
| `vnetId` | string | VNet resource ID |
| `vnetName` | string | VNet name |
| `snetAcaId` / `snetPeId` / `snetJobsId` / `snetBastionId` / `snetApimId` | string | Subnet resource IDs |
| `pdnsOpenaiId` | string | DNS zone ID for `privatelink.openai.azure.com` |
| `pdnsSearchId` | string | DNS zone ID for `privatelink.search.windows.net` |
| `pdnsCosmosId` | string | DNS zone ID for `privatelink.documents.azure.com` |
| `pdnsBlobId` | string | DNS zone ID for `privatelink.blob.core.windows.net` |
| `pdnsQueueId` | string | DNS zone ID for `privatelink.queue.core.windows.net` |
| `pdnsKeyVaultId` | string | DNS zone ID for `privatelink.vaultcore.azure.net` |
| `pdnsAcrId` | string | DNS zone ID for `privatelink.azurecr.io` |
| `pdnsCognitiveId` | string | DNS zone ID for `privatelink.cognitiveservices.azure.com` |
| `pdnsMonitorId` | string | DNS zone ID for `privatelink.monitor.azure.com` |
| `pdnsOmsId` | string | DNS zone ID for `privatelink.oms.opinsights.azure.com` |
| `pdnsOdsId` | string | DNS zone ID for `privatelink.ods.opinsights.azure.com` |
| `pdnsAgentSvcId` | string | DNS zone ID for `privatelink.agentsvc.azure-automation.net` |
| `pdnsApimId` | string | DNS zone ID for `azure-api.net` |
| `privateDnsZoneIdList` | array | Ordered list of all 13 zone IDs (matches `privateDnsZoneNames`) |
| `privateDnsZoneNamesOut` | array | Echo of input names array |
| `nsgIds` | object | Map of NSG name → resource ID |

**Notes:** The 13 named DNS outputs (`pdnsOpenaiId` etc.) are emitted alongside the array form (`privateDnsZoneIdList`) because Bicep `for`-loop modules cannot be referenced as a typed map at compile time — the named outputs are the workaround consumed by every PE-bearing downstream module. When `customerProvidedDns=true`, all `pdns*Id` outputs return `''`.

---

### `identity` — User-Assigned Managed Identities (T018)

- **AVM:** `br/public:avm/res/managed-identity/user-assigned-identity:0.4.1` (×3)
- **Cost:** $0 (UAMIs are free)

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `location` | string | — | `resourceGroup().location` | Region |
| `tags` | object | — | `{}` | Tag set |
| `identityApiName` | string | ✅ | — | Name for `mi-api` |
| `identityIngestName` | string | ✅ | — | Name for `mi-ingest` |
| `identityWebName` | string | ✅ | — | Name for `mi-web` |

| Output | Type | Description |
|---|---|---|
| `identityApiId` / `identityIngestId` / `identityWebId` | string | UAMI resource IDs |
| `identityApiPrincipalId` / `identityIngestPrincipalId` / `identityWebPrincipalId` | string | Principal IDs (for RBAC role assignments) |
| `identityApiClientId` / `identityIngestClientId` / `identityWebClientId` | string | Client IDs (for `AZURE_CLIENT_ID` app config) |
| `identities` | object | Map of `{ api, ingest, web }` with all three IDs collated |

---

### `monitoring` — Log Analytics + App Insights + AMPLS (T019)

- **AVM:** `br/public:avm/res/operational-insights/workspace:0.15.1`, `br/public:avm/res/insights/component:0.7.1`. AMPLS + scoped resources + private endpoint are hand-rolled.
- **Cost:** ~$10/mo ($8 LAW + $2 AppInsights, AMPLS itself is free; PE counted in shared inventory)

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `location` | string | ✅ | — | Region |
| `tags` | object | ✅ | — | Tag set |
| `lawName` | string | ✅ | — | Log Analytics workspace name |
| `appInsightsName` | string | ✅ | — | App Insights component name |
| `amplsName` | string | ✅ | — | AMPLS resource name |
| `retentionInDays` | int | — | `30` | LAW retention (free tier ceiling) |
| `peSubnetId` | string | ✅ | — | Subnet ID for AMPLS PE (`snet-pe`) |
| `privateEndpointName` | string | — | `pe-${amplsName}` | AMPLS PE name |
| `privateDnsZoneIdMonitor` | string | ✅ | — | `privatelink.monitor.azure.com` zone ID |
| `privateDnsZoneIdOms` | string | ✅ | — | `privatelink.oms.opinsights.azure.com` zone ID |
| `privateDnsZoneIdOds` | string | ✅ | — | `privatelink.ods.opinsights.azure.com` zone ID |
| `privateDnsZoneIdAgentSvc` | string | ✅ | — | `privatelink.agentsvc.azure-automation.net` zone ID |
| `privateDnsZoneIdBlob` | string | ✅ | — | `privatelink.blob.core.windows.net` zone ID (for ingest profiler/snapshot blobs) |

| Output | Type | Description |
|---|---|---|
| `lawId` / `lawName` | string | Workspace resource ID + name |
| `appInsightsId` | string | App Insights component ID |
| `appInsightsConnectionString` | string | Connection string (consumed as `@secure()` upstream) |
| `appInsightsInstrumentationKey` | string | Legacy iKey |
| `amplsId` | string | AMPLS resource ID |
| `amplsPrivateEndpointId` | string | PE resource ID |

**Notes:** LAW + App Insights are deployed with `publicNetworkAccessForIngestion='Disabled'` and `publicNetworkAccessForQuery='Disabled'`. Five DNS zones are wired into the AMPLS PE because Azure Monitor's private link surface spans monitor / OMS / ODS / agentsvc / blob.

---

### `registry` — Azure Container Registry (T020)

- **AVM:** `br/public:avm/res/container-registry/registry:0.12.1`
- **Cost:** ~$50/mo (Premium SKU — only PE-capable tier; 500 GB included)

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `location` | string | ✅ | — | Region |
| `tags` | object | — | `{}` | Tag set |
| `acrName` | string | ✅ | — | Registry name (alphanumeric, ≤50) |
| `acrSku` | string | — | `Premium` | `@allowed(['Premium'])` — only PE-capable tier |
| `peSubnetId` | string | ✅ | — | PE subnet ID |
| `privateDnsZoneId` | string | ✅ | — | `privatelink.azurecr.io` zone ID |
| `softDeleteRetentionDays` | int | — | `7` | Manifest soft-delete window |
| `acrPullPrincipalIds` | array | — | `[]` | Principal IDs granted `AcrPull` (api/ingest/web MIs) |

| Output | Type | Description |
|---|---|---|
| `acrId` | string | Registry resource ID |
| `acrName` | string | Registry name |
| `acrLoginServer` | string | `<name>.azurecr.io` (used as ACA `acrLoginServer` env) |
| `peId` | string | First PE resource ID |

---

### `keyvault` — Azure Key Vault (T021)

- **AVM:** `br/public:avm/res/key-vault/vault:0.13.3`
- **Cost:** ~$1/mo (Standard SKU, RBAC-auth)

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `location` | string | ✅ | — | Region |
| `tags` | object | — | `{}` | Tag set |
| `vaultName` | string | ✅ | — | Vault name (3-24 alphanumeric + hyphen) |
| `peSubnetId` | string | ✅ | — | PE subnet ID |
| `privateDnsZoneId` | string | ✅ | — | `privatelink.vaultcore.azure.net` zone ID |
| `lawId` | string | ✅ | — | Diagnostic settings sink |
| `softDeleteRetentionInDays` | int | — | `7` | Soft-delete window |
| `secretsUserPrincipalIds` | array | — | `[]` | Principals granted `Key Vault Secrets User` (api + ingest MIs) |
| `adminGroupObjectId` | string | — | `''` | Optional Entra group granted `Key Vault Administrator` |

| Output | Type | Description |
|---|---|---|
| `kvId` | string | Vault resource ID |
| `kvName` | string | Vault name |
| `kvUri` | string | `https://<name>.vault.azure.net/` |
| `peId` | string | First PE resource ID |

---

### `storage` — Storage Account + Event Grid (T022)

- **AVM:** `br/public:avm/res/storage/storage-account:0.27.1`. Event Grid system topic + queue subscription hand-rolled (no AVM coverage).
- **Cost:** ~$3/mo (Standard LRS, hot tier; 2 blob containers + 1 queue, demo data volume)

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `location` | string | ✅ | — | Region |
| `tags` | object | — | `{}` | Tag set |
| `name` | string | ✅ | — | Storage account name (≤24, lowercase alphanumeric) |
| `peSubnetId` | string | ✅ | — | PE subnet ID |
| `pdnsBlobId` | string | ✅ | — | `privatelink.blob.core.windows.net` zone ID |
| `pdnsQueueId` | string | ✅ | — | `privatelink.queue.core.windows.net` zone ID |
| `lawId` | string | ✅ | — | Diagnostic sink |
| `blobContributorPrincipalIds` | array | — | `[]` | `Storage Blob Data Contributor` (ingest MI) |
| `blobReaderPrincipalIds` | array | — | `[]` | `Storage Blob Data Reader` (api MI) |
| `queueReaderPrincipalIds` | array | — | `[]` | `Storage Queue Data Reader` (ingest MI) |

| Output | Type | Description |
|---|---|---|
| `resourceId` | string | Storage account resource ID |
| `name` | string | Storage account name |
| `primaryBlobEndpoint` | string | Blob primary endpoint URL |
| `sharedCorpusContainerName` | string | Container name for shared RAG corpus |
| `userUploadsContainerName` | string | Container name for per-user uploads |
| `ingestionQueueName` | string | Storage queue name receiving Blob → EG events |
| `eventGridSystemTopicId` | string | EG system topic resource ID |

---

### `openai` — Azure OpenAI (T025)

- **AVM:** `br/public:avm/res/cognitive-services/account:0.13.2`
- **Cost:** ~$10/mo demo (pay-per-token GPT-5 + text-embedding-3-large)

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `location` | string | ✅ | — | Region (must support both models) |
| `tags` | object | — | `{}` | Tag set |
| `name` | string | ✅ | — | Account name |
| `peSubnetId` | string | ✅ | — | PE subnet ID |
| `pdnsOpenaiId` | string | ✅ | — | `privatelink.openai.azure.com` zone ID |
| `lawId` | string | ✅ | — | Diagnostic sink |
| `chatModel` | string | — | `gpt-5` | Model name |
| `chatModelVersion` | string | — | `2025-08-07` | Model version |
| `chatDeploymentName` | string | — | `gpt-5` | Deployment alias |
| `chatCapacity` | int | — | `10` | TPM / capacity units |
| `embeddingModel` | string | — | `text-embedding-3-large` | Model name |
| `embeddingModelVersion` | string | — | `1` | Model version |
| `embeddingDeploymentName` | string | — | `text-embedding-3-large` | Deployment alias |
| `embeddingCapacity` | int | — | `10` | TPM / capacity units |
| `deploymentSku` | string | — | `Standard` | Deployment SKU |
| `openAiUserPrincipalIds` | array | — | `[]` | `Cognitive Services OpenAI User` (api + ingest MIs) |

| Output | Type | Description |
|---|---|---|
| `resourceId` | string | Account resource ID |
| `name` | string | Account name |
| `endpoint` | string | OpenAI endpoint URL |
| `chatDeploymentName` | string | Echo of chat deployment alias |
| `embeddingDeploymentName` | string | Echo of embedding deployment alias |

---

### `cosmos` — Cosmos DB NoSQL (T023)

- **AVM:** `br/public:avm/res/document-db/database-account:0.15.1`
- **Cost:** ~$3/mo (Serverless capacity mode; pay-per-RU)

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `location` | string | ✅ | — | Region |
| `tags` | object | — | `{}` | Tag set |
| `name` | string | ✅ | — | Account name |
| `peSubnetId` | string | ✅ | — | PE subnet ID |
| `pdnsCosmosId` | string | ✅ | — | `privatelink.documents.azure.com` zone ID |
| `lawId` | string | ✅ | — | Diagnostic sink |
| `databaseName` | string | — | `rag` | Cosmos database name |
| `conversationsContainerName` | string | — | `conversations` | Container 1 |
| `documentsContainerName` | string | — | `documents` | Container 2 |
| `ingestionRunsContainerName` | string | — | `ingestion-runs` | Container 3 |
| `dataContributorPrincipalIds` | array | — | `[]` | Cosmos `Built-in Data Contributor` SQL role assignments (api + ingest MIs) |

| Output | Type | Description |
|---|---|---|
| `resourceId` | string | Account resource ID |
| `name` | string | Account name |
| `endpoint` | string | Cosmos endpoint URL |
| `databaseName` | string | Echo of database name |
| `containerName` | string | Conversations container (primary) |
| `containerNames` | array | All three container names |

---

### `docintel` — Azure AI Document Intelligence (T026)

- **AVM:** `br/public:avm/res/cognitive-services/account:0.13.0`
- **Cost:** ~$3/mo demo (S0 SKU; F0 does NOT support PE — S0 is the minimum for SC-004)

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `location` | string | ✅ | — | Region |
| `tags` | object | — | `{}` | Tag set |
| `name` | string | ✅ | — | Account name |
| `peSubnetId` | string | ✅ | — | PE subnet ID |
| `pdnsCogsvcsId` | string | ✅ | — | `privatelink.cognitiveservices.azure.com` zone ID |
| `lawId` | string | ✅ | — | Diagnostic sink |
| `sku` | string | — | `S0` | Pay-per-page SKU (PE-capable) |
| `cognitiveServicesUserPrincipalIds` | array | — | `[]` | `Cognitive Services User` role (api + ingest MIs) |

| Output | Type | Description |
|---|---|---|
| `resourceId` | string | Account resource ID |
| `name` | string | Account name |
| `endpoint` | string | DocIntel endpoint URL |

---

### `search` — Azure AI Search (T024)

- **AVM:** `br/public:avm/res/search/search-service:0.12.1`
- **Cost:** ~$74/mo (Basic SKU; 15 GB / 3 indexes)
- **SKU deviation:** task spec called for Standard S1 (~$245/mo); shipped at Basic per accepted deviation 2026-05-09 (`.squad/decisions.md`).

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `location` | string | ✅ | — | Region |
| `tags` | object | — | `{}` | Tag set |
| `name` | string | ✅ | — | Search service name |
| `peSubnetId` | string | ✅ | — | PE subnet ID |
| `pdnsSearchId` | string | ✅ | — | `privatelink.search.windows.net` zone ID |
| `lawId` | string | ✅ | — | Diagnostic sink |
| `aoaiResourceId` | string | ✅ | — | OpenAI account ID — used to build a Shared Private Link from Search → OpenAI |
| `storageBlobResourceId` | string | ✅ | — | Storage account ID — used to build a Shared Private Link from Search → Storage Blob |
| `indexContributorPrincipalIds` | array | — | `[]` | `Search Index Data Contributor` (ingest MI) |
| `indexReaderPrincipalIds` | array | — | `[]` | `Search Index Data Reader` (api MI) |

| Output | Type | Description |
|---|---|---|
| `resourceId` | string | Search service resource ID |
| `name` | string | Service name |
| `endpoint` | string | `https://<name>.search.windows.net` |
| `principalId` | string | System-assigned MI principal (for cross-service RBAC into AOAI/Storage) |

**Notes:** `openai` and `storage` MUST deploy before `search` because Shared Private Link approval requires the target resources to exist. Locked at Basic SKU inside the module — change requires reopening the deviation.

---

### `containerapps` — Azure Container Apps env + apps + job (T027)

- **AVM:** `br/public:avm/res/app/managed-environment:0.13.3`, `br/public:avm/res/app/container-app:0.22.1` (×2 — `web`, `api`), `br/public:avm/res/app/job:0.7.1` (`ingest`)
- **Cost:** ~$5/mo (Consumption profile, scale-to-zero; free grants cover light demo usage)

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `location` | string | ✅ | — | Region |
| `tags` | object | — | `{}` | Tag set |
| `name` | string | ✅ | — | ACA Environment name |
| `peSubnetId` | string | ✅ | — | ACA infrastructure subnet (`snet-aca`) |
| `lawId` | string | ✅ | — | Workspace for ACA logs |
| `appInsightsConnectionString` | string | ✅ | — | App Insights connection string (consumed by ACA OTel collector) |
| `acrLoginServer` | string | ✅ | — | ACR login server (`<name>.azurecr.io`) |
| `miWebId` / `miApiId` / `miIngestId` | string | ✅ | — | UAMI resource IDs to bind to web / api / ingest |
| `appEnvVars` | object | — | `{}` | Common env vars merged into all apps + the job |
| `webExtraEnvVars` | object | — | `{}` | Extra env vars for `web` (e.g. `AZURE_CLIENT_ID`) |
| `apiExtraEnvVars` | object | — | `{}` | Extra env vars for `api` |
| `ingestExtraEnvVars` | object | — | `{}` | Extra env vars for the ingest job |
| `ingestionStorageAccountName` | string | ✅ | — | Storage account hosting the Azure Queue trigger source |
| `ingestionQueueName` | string | — | `ingestion-events` | Queue name |
| `ingestQueueLength` | int | — | `5` | Queue-length trigger threshold |

| Output | Type | Description |
|---|---|---|
| `resourceId` | string | Managed Environment resource ID |
| `name` | string | Environment name |
| `defaultDomain` | string | Internal default domain (VNet-resolvable only) |
| `webAppFqdn` / `apiAppFqdn` | string | App FQDNs (internal) |
| `webAppName` / `apiAppName` / `ingestJobName` | string | Resource names |
| `webAppResourceId` / `apiAppResourceId` / `ingestJobResourceId` | string | Resource IDs |
| `webPrincipalId` / `apiPrincipalId` / `ingestPrincipalId` | string | Principal IDs of the bound UAMIs (echoed for downstream RBAC) |

**Notes:** ACA Environment is provisioned with **internal ingress only** (no public LB). All app-to-PaaS traffic uses Entra MI; no shared keys are wired through env. The ingest job is queue-triggered — Storage events → Event Grid → Storage Queue → ACA job execution.

---

### `bastion` — Bastion Developer + Linux jumpbox (T028)

- **AVM:** `br/public:avm/res/network/bastion-host:0.8.2` (gated). Jumpbox VM is composed by the local `jumpbox.bicep` sub-module.
- **Cost:** $0 Bastion Developer (free portal-only RDP/SSH) + ~$36/mo jumpbox (Standard_B2s, deallocate when idle for $0)
- **SKU deviation:** task spec called for Bastion Standard (~$140/mo); shipped at Developer per accepted deviation 2026-05-09 (`.squad/decisions.md`).

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `deployBastion` | bool | — | `true` | Deploy Bastion Host resource (only when caller passes `true`) |
| `name` | string | ✅ | — | Base name token (used to derive Bastion + VM names) |
| `location` | string | ✅ | — | Region |
| `tags` | object | — | `{}` | Tag set |
| `bastionSubnetId` | string | ✅ | — | `AzureBastionSubnet` ID |
| `vmSubnetId` | string | ✅ | — | Jumpbox subnet (`snet-pe`) |
| `lawId` | string | ✅ | — | Diagnostic sink |
| `adminUsername` | string | — | `azureuser` | Linux admin username |
| `adminPublicKey` | string | ✅ | — | SSH public key for jumpbox |
| `vmSize` | string | — | `Standard_B2s` | Jumpbox VM size |

| Output | Type | Description |
|---|---|---|
| `bastionResourceId` | string | Bastion resource ID (empty when gated off) |
| `bastionName` | string | Bastion name |
| `jumpboxResourceId` | string | Jumpbox VM resource ID |
| `jumpboxPrincipalId` | string | Jumpbox system-assigned MI principal |
| `jumpboxPrivateIp` | string | Jumpbox private IP for in-VNet smoke tests |

**Notes:** This module is gated at the orchestrator level: invoked only when `deployBastion=true` OR `deployJumpbox=true`. To upgrade to a dedicated Bastion (Basic/Standard), bump `skuName` in `main.bicep` and add a `publicIPAddressObject` — the AVM module supports both code paths.

---

### `apim` — Azure API Management (T032a / Layer 2.5)

- **AVM:** `br/public:avm/res/api-management/service:0.14.1`
- **Cost:** ~$50/mo (Developer SKU, internal VNet mode, no SLA — acceptable for demo)
- **SKU policy:** Premium stv2 (~$2,800/mo) is required only for production SLA + multi-region; explicitly disqualified by the $500/mo cap. StandardV2 is disqualified — it cannot run fully internal (violates SC-004).

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `name` | string | ✅ | — | APIM service name |
| `location` | string | ✅ | — | Region |
| `tags` | object | — | `{}` | Tag set |
| `peSubnetId` | string | ✅ | — | APIM injection subnet (`snet-apim`, /27) |
| `lawId` | string | ✅ | — | Diagnostic sink |
| `appInsightsId` | string | ✅ | — | App Insights resource ID (logger target) |
| `appInsightsConnectionString` | string | ✅ | — | App Insights connection string (logger credential) |
| `publisherEmail` | string | — | `arbaaz@example.com` | APIM publisher email |
| `publisherName` | string | — | `Private RAG Accelerator` | APIM publisher display name |

| Output | Type | Description |
|---|---|---|
| `resourceId` | string | APIM resource ID |
| `name` | string | APIM service name |
| `gatewayUrl` | string | `https://<name>.azure-api.net` |
| `principalId` | string | System-assigned MI principal (or `''` if disabled) |

**Notes:** `virtualNetworkType: 'Internal'` is enforced. APIM is deployed late in the dep order so the App Insights connection string is available for the logger; APIM has no inbound dependency on the data plane (Phase 3 wires backends/policies).

---

## Composition

`infra/main.bicep` deploys the resource group + all 13 modules at subscription scope, in dependency order:

```
                              ┌──► registry ─┐
network ──┬──► identity ──────┤    keyvault   │
          │                   │    storage   ─┤
          ├──► monitoring ────┤    openai    ─┤
          │                   │    cosmos    ─┤
          │                   │    docintel  ─┤
          │                   │    search ◄──┘ (needs openai+storage)
          │                   │
          ├────────────────► containerapps ──► (azd deploy)
          ├────────────────► bastion (gated by deployBastion || deployJumpbox)
          └────────────────► apim
```

Layer summary:

1. **Foundation** — `network`, `identity`
2. **Platform services** — `monitoring`, `registry`, `keyvault`
3. **Data plane** — `storage`, `openai`, `cosmos`, `docintel`, `search` (search depends on openai + storage)
4. **Compute** — `containerapps`, `bastion` (gated)
5. **API gateway** — `apim`

### Top-level orchestrator parameters

Selected (see `main.bicep` for full list):

| Parameter | Default | Purpose |
|---|---|---|
| `namingPrefix` | — (required) | 2–8 alphanumeric token; root of every name |
| `location` | `eastus2` | Target region |
| `environmentName` | `dev` | `dev` / `staging` / `prod` |
| `adminGroupObjectId` | — (required) | Entra group granted KV / Search / Cosmos / OpenAI admin |
| `costCenter` / `owner` | `platform` / `platform-team` | Tag values |
| `vnetAddressPrefix` + 5 subnet prefixes | `10.0.0.0/22` and children | Network sizing |
| `customerProvidedDns` | `false` | Skip Private DNS zone creation |
| `deployBastion` | `false` | Deploy dedicated Bastion Host (~$140/mo if Standard) |
| `deployJumpbox` | `true` | Deploy Linux jumpbox VM (~$36/mo) |
| `enableZoneRedundancy` | `false` | Phase 2b knob — currently locked off in modules |
| `enableCustomerManagedKey` | `false` | Phase 2b knob — currently locked off in modules |
| `chatModel` / `embeddingModel` | `gpt-5` / `text-embedding-3-large` | AOAI deployments |
| `aiSearchSku` | `basic` | Locked at Basic in module |
| `apimSku` | `Developer` | Locked at Developer in module |
| `apimPublisherEmail` / `apimPublisherName` | sample values | APIM developer portal metadata |
| `cosmosCapacityMode` | `Serverless` | Locked at Serverless in module |
| `budgetMonthlyUsd` | `500` | Hard cap; budget alert wired by follow-up |
| `jumpboxAdminPublicKey` | `''` | Required (set per-env) when jumpbox is deployed |
| `jumpboxAdminUsername` | `azureuser` | Linux admin |

### Top-level outputs

Identity / scope: `resourceGroupName`, `resourceGroupId`, `location`, `environmentName`.
Networking: `vnetId`, `snetAcaId`, `snetPeId`, `snetApimId`.
Identities: `identityApiClientId`, `identityIngestClientId`, `identityWebClientId`.
Observability: `lawId`, `appInsightsId`, `appInsightsConnectionString` (`@secure`).
Registry: `acrLoginServer`, `acrName`.
Data plane: `keyVaultUri`, `storageAccountName`, `storagePrimaryBlobEndpoint`, `ingestionQueueName`, `cosmosEndpoint`, `cosmosDatabaseName`, `openAiEndpoint`, `openAiChatDeployment`, `openAiEmbedDeployment`, `searchEndpoint`, `docIntelEndpoint`.
Compute: `acaEnvironmentId`, `webAppFqdn`, `apiAppFqdn`, `webAppName`, `apiAppName`, `ingestJobName`, `uiUrl` (= `https://<webAppFqdn>`, VNet-resolvable only).
API gateway: `apimGatewayUrl`, `apimResourceId`.

## Accepted SKU deviations

| Task | Spec'd SKU | Shipped SKU | Rationale | Decision |
|---|---|---|---|---|
| T024 (Search) | Standard S1 (~$245/mo) | Basic (~$74/mo) | $500/mo budget cap; Basic supports private endpoints, 15 GB / 3 indexes — sufficient for demo | Permanent ✅ — `.squad/decisions.md` 2026-05-09 |
| T028 (Bastion) | Standard (~$140/mo) | Developer (free) + jumpbox VM (~$36/mo) | $500/mo budget cap; Developer is portal-only RDP/SSH, single concurrent session — acceptable for demo | Permanent ✅ — `.squad/decisions.md` 2026-05-09 |
| T032a (APIM) | "Premium stv2 fallback" (~$2,800/mo) | Developer (~$50/mo) | $500/mo cap supersedes; Developer is the only sub-Premium tier with full Internal VNet injection (StandardV2 disqualified) | Reaffirmed ✅ — `.squad/decisions.md` 2026-05-09 |

Customers needing production SLAs / multi-region resilience can lift these in their own parameter overrides (the `aiSearchSku` / `apimSku` / `deployBastion` knobs are surfaced on the orchestrator) but doing so will exceed the demo budget.

## AVM version pinning policy

- **Pin specific published versions, never `latest` or floating ranges.** Each `module … 'br/public:avm/res/.../<name>:<version>'` line in module `main.bicep` files names a concrete version (e.g. `0.13.3`). Documented in `.squad/decisions.md` 2026-05-09.
- **SKU `@allowed([…])` allowlists.** Where a SKU is the load-bearing zero-trust constraint (e.g. ACR `Premium`-only for PE support), the parameter is constrained at the module level so a misconfiguration becomes a deploy-time error rather than a runtime / compliance failure.
- **Recheck-and-bump cadence.** When implementing or refactoring a module, recheck the MCR tag list, pick the newest stable, and update the pin in both `main.bicep` and the module README.
- **Audit artifact.** PR-P (T031) maintains `infra/AVM-AUDIT.md` as a single-source inventory of every AVM dependency and its pinned version. If you don't see that file yet, it lands with PR-P.

### Pinned versions snapshot (from this branch)

| AVM module | Version | Used by |
|---|---|---|
| `avm/res/network/private-dns-zone` | `0.7.1` | network |
| `avm/res/managed-identity/user-assigned-identity` | `0.4.1` | identity |
| `avm/res/operational-insights/workspace` | `0.15.1` | monitoring |
| `avm/res/insights/component` | `0.7.1` | monitoring |
| `avm/res/container-registry/registry` | `0.12.1` | registry |
| `avm/res/key-vault/vault` | `0.13.3` | keyvault |
| `avm/res/storage/storage-account` | `0.27.1` | storage |
| `avm/res/cognitive-services/account` | `0.13.2` | openai |
| `avm/res/cognitive-services/account` | `0.13.0` | docintel |
| `avm/res/document-db/database-account` | `0.15.1` | cosmos |
| `avm/res/search/search-service` | `0.12.1` | search |
| `avm/res/app/managed-environment` | `0.13.3` | containerapps |
| `avm/res/app/container-app` | `0.22.1` | containerapps (web, api) |
| `avm/res/app/job` | `0.7.1` | containerapps (ingest job) |
| `avm/res/network/bastion-host` | `0.8.2` | bastion |
| `avm/res/api-management/service` | `0.14.1` | apim |

> The two `cognitive-services/account` rows are intentional — `openai` and `docintel` were pinned at different points and PR-P reconciles them.

## Testing

Build the entire composition locally:

```pwsh
az bicep build --file infra\main.bicep
```

Build a single module:

```pwsh
az bicep build --file infra\modules\<module>\main.bicep
```

What-if (no deployment):

```pwsh
az deployment sub what-if --location eastus2 --template-file infra\main.bicep --parameters infra\main.parameters.dev.json
```

For end-to-end deployment validation use `azd provision` against an empty subscription. See `specs/001-private-rag-accelerator/quickstart.md` for the full operator runbook.

## See also

- `specs/001-private-rag-accelerator/tasks.md` — task tracker
- `specs/001-private-rag-accelerator/plan.md` — original architecture plan
- `.squad/agents/ripley/phase-2-plan.md` — Phase 2a v3 cost-validated plan
- `.squad/decisions.md` — decision log (SKU deviations, AVM pin policy)
- `infra/AVM-AUDIT.md` — AVM version inventory (PR-P artifact, may not yet exist)
- Per-module READMEs under `infra/modules/<module>/README.md` for deeper rationale and examples
