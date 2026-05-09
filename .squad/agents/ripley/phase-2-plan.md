# Phase 2a Architecture Plan — Foundational IaC (T015–T032 + T032a APIM)

**Author:** Ripley (Lead)  
**Date:** 2026-05-08  
**Status:** ✅ APPROVED — Lead sign-off applied (2026-05-08T20:13:37-07:00)  
**Branch:** `001-private-rag-accelerator`  
**Phase 1 baseline:** PR #2 merged (commit `11c7b47`)  
**Revision:** v3 — Cost-validated under $500/month hard ceiling (Arbyam directive 2026-05-08T20:13:37-07:00)

> **TL;DR — v3 changes from v2:** Arbyam imposed a **$500/month hard cap** for the entire demo. v2's Premium APIM ($2,800/mo) and Standard Bastion ($140/mo) are disqualified. v3 validates every SKU against Azure pricing and SC-004 zero-trust compliance. **Total estimated cost: ~$318/month** with $182 headroom. All data-plane services retain private endpoints with `publicNetworkAccess: Disabled`. Zero cuts to functionality required.

---

## 0. Cost-Validated Budget Table ($500/month ceiling)

**Region:** East US 2 (default per plan.md)  
**Constraint:** $500/month hard cap — Arbyam directive, non-negotiable  
**Pricing basis:** Azure public pricing verified 2026-05-08; all figures rounded UP conservatively  

| # | Resource | Module | SKU / Tier | PE? | Est. Monthly | Pricing Source / Notes |
|---|----------|--------|-----------|-----|---:|-------------|
| 1 | Virtual Network | network | — | n/a | $0 | Free |
| 2 | Private DNS Zones (×13) | network | — | n/a | $7 | 13 zones × $0.50/zone/mo |
| 3 | NSGs (×4–5) | network | — | n/a | $0 | Free |
| 4 | Azure Bastion | — | **Developer** | n/a | **$0** | Free; shared Microsoft pool; portal-only RDP/SSH; no Bastion resource deployed |
| 5 | Jumpbox VM | bastion | Standard_B2s | n/a | $36 | 2 vCPU / 4 GiB; can deallocate when idle ($0 when stopped) |
| 6 | Container Registry | registry | **Premium** | ✅ | **$50** | Only PE-capable tier; 500 GB included; $1.667/day |
| 7 | AI Search | search | **Basic** | ✅ | **$74** | 1 SU; 15 GB storage; PE confirmed on Basic+ |
| 8 | API Management | apim | **Developer** | ✅ᵃ | **$50** | Internal VNet mode; no SLA (fine for demo); ~$48–60/mo |
| 9 | Container Apps (×2 apps + 1 job) | containerapps | Consumption | n/a | $5 | Scale-to-zero; free grants cover light demo usage |
| 10 | Cosmos DB | cosmos | **Serverless** | ✅ | $3 | ~$0.25/1M RUs + $0.25/GB; demo workload is minimal |
| 11 | Azure OpenAI | openai | Pay-per-token | ✅ | $10 | GPT-5 + text-embedding-3-large; demo token volume low |
| 12 | Document Intelligence | docintel | **S0** | ✅ | $3 | Pay-per-page; F0 does NOT support PE — S0 required |
| 13 | Storage Account | storage | Standard LRS | ✅ (blob+queue) | $3 | Hot tier; 2 containers; demo data small |
| 14 | Key Vault | keyvault | Standard | ✅ | $1 | RBAC-auth; CMK-only in v1 |
| 15 | Log Analytics Workspace | monitoring | Pay-per-GB | n/a | $8 | 30-day retention (free tier); minimal demo volume |
| 16 | Application Insights | monitoring | Workspace-based | n/a | $2 | Inherits LAW pricing; light demo traffic |
| 17 | AMPLS | monitoring | — | ✅ | $0 | AMPLS resource free; PE cost counted below |
| 18 | Private Endpoints (×9) | various | — | — | **$66** | 9 PEs × $7.30/mo ($0.01/hr) |
| — | **TOTAL** | | | | **$318** | **Headroom: $182 (36%)** |

ᵃ APIM Developer uses VNet injection (internal mode) — all endpoints resolve to VNet-internal VIP. This is NOT a Private Endpoint; it's full VNet injection which is stronger. No public IP exposed.

### Private Endpoint Inventory (9 total)

| # | PE Target | DNS Zone |
|---|-----------|----------|
| 1 | Azure OpenAI | `privatelink.openai.azure.com` |
| 2 | AI Search | `privatelink.search.windows.net` |
| 3 | Cosmos DB | `privatelink.documents.azure.com` |
| 4 | Blob Storage | `privatelink.blob.core.windows.net` |
| 5 | Queue Storage | `privatelink.queue.core.windows.net` |
| 6 | Key Vault | `privatelink.vaultcore.azure.net` |
| 7 | ACR | `privatelink.azurecr.io` |
| 8 | Document Intelligence | `privatelink.cognitiveservices.azure.com` |
| 9 | AMPLS | `privatelink.monitor.azure.com` (+ 3 companion zones) |

### v3 SKU Changes from v2

| Resource | v2 SKU | v3 SKU | Monthly Savings | Rationale |
|----------|--------|--------|---:|-----------|
| APIM | Premium ($2,800) | Developer ($50) | $2,750 | Developer supports internal VNet mode; no SLA acceptable for demo |
| Bastion | Standard ($140) | Developer ($0) | $140 | Free; portal-only RDP/SSH; single concurrent session OK for demo |
| AI Search | Standard S1 ($245) | Basic ($74) | $171 | Basic supports PE; 15 GB / 3 indexes sufficient for demo |
| Cosmos DB | Autoscale (min ~$24) | Serverless ($3) | $21 | Pay-per-RU; no minimum; PE supported |
| ACR | Premium ($167 est.) | Premium ($50 actual) | $117 | v2 used wrong price estimate; actual is $50/mo |
| **Total savings** | | | **$3,199** | From ~$3,500+ down to ~$318 |

### Zero-Trust Compliance per SKU

| Resource | Tier | PE Support | `publicNetworkAccess` | SC-004 Compliant |
|----------|------|-----------|----------------------|-----------------|
| ACR | Premium | ✅ | `Disabled` | ✅ |
| AI Search | Basic | ✅ | `disabled` | ✅ |
| APIM | Developer | ✅ VNet-injected internal | No public gateway | ✅ |
| Cosmos DB | Serverless | ✅ | `Disabled` | ✅ |
| Azure OpenAI | Standard | ✅ | `Disabled` | ✅ |
| Doc Intelligence | S0 | ✅ | `Disabled` | ✅ |
| Storage | Standard LRS | ✅ (blob+queue) | `Disabled` | ✅ |
| Key Vault | Standard | ✅ | `Disabled` | ✅ |
| AMPLS | — | ✅ | Private-only ingestion | ✅ |
| Container Apps | Consumption | N/A (internal VNet) | `internal: true` | ✅ |
| Bastion | Developer | N/A (shared pool) | Azure-managed | ✅ (portal access only) |

**Verdict:** All 11 data-plane services maintain zero public endpoints. SC-004 fully satisfied at $318/month.

---

## A. Scope Confirmation

### Phase 2a = T015–T032 + T032a (Pure IaC)

This plan covers **Phase 2a** only. Phase 2b (T033–T047, cross-cutting app foundations) ships as a separate sprint after Phase 2a is validated with `bicep build` + `what-if`.

| ID | Summary | Parallel? |
|----|---------|-----------|
| T015 | `infra/main.bicep` — subscription-scope orchestrator | No (foundation) |
| T016 | `infra/main.parameters.json` — all deployment parameters | No (foundation) |
| T017 | `infra/modules/network/` — VNet, subnets, NSGs, Private DNS Zones | Yes |
| T018 | `infra/modules/identity/` — 3 user-assigned managed identities | Yes |
| T019 | `infra/modules/monitoring/` — LAW, App Insights, AMPLS, Budget | Yes |
| T020 | `infra/modules/registry/` — ACR Premium, PE, AcrPull roles | Yes |
| T021 | `infra/modules/keyvault/` — Key Vault Standard, PE | Yes |
| T022 | `infra/modules/storage/` — StorageV2, PE (blob+queue), containers, lifecycle, Event Grid | Yes |
| T023 | `infra/modules/cosmos/` — Cosmos NoSQL, PE, 3 containers | Yes |
| T024 | `infra/modules/search/` — AI Search Basic, PE, shared private links | Yes |
| T025 | `infra/modules/openai/` — Azure OpenAI, PE, 2 model deployments | Yes |
| T026 | `infra/modules/docintel/` — Document Intelligence, PE | Yes |
| T027 | `infra/modules/containerapps/` — ACA env (internal), 2 apps + 1 job | No (depends T017–T020) |
| T028 | `infra/modules/bastion/` — Jumpbox VM (Bastion Developer = no IaC resource) | Yes |
| T029 | Cross-cutting RBAC — role assignments in each resource module | No (depends T017–T028) |
| T030 | Wire `main.bicep` — module invocation order + outputs | No (depends all modules) |
| T031 | AVM refactor pass — swap hand-rolled to `br/public:avm/*` | No (depends T017–T028) |
| T032 | `infra/README.md` — module documentation | Yes |
| **T032a** | **`infra/modules/apim/` — APIM module + main.bicep wiring** | **Yes (after network+identity+monitoring)** |

### What ships after Phase 2a

```
infra/
├── main.bicep                      # Subscription-scope orchestrator (creates RG + invokes modules)
├── main.parameters.json            # Single parameterized config
├── modules/
│   ├── network/main.bicep          # VNet /22, 5 subnets, NSGs, 13+ Private DNS Zones
│   ├── identity/main.bicep         # 3 user-assigned MIs (mi-api, mi-ingest, mi-web)
│   ├── monitoring/main.bicep       # LAW, App Insights, AMPLS + PE, Budget alert
│   ├── storage/main.bicep          # StorageV2, 2 containers, PE (blob+queue), lifecycle, Event Grid
│   ├── cosmos/main.bicep           # Cosmos NoSQL, PE, 3 containers with TTL
│   ├── search/main.bicep           # AI Search Basic, PE, shared private links to AOAI/Storage
│   ├── openai/main.bicep           # Azure OpenAI, PE, gpt-5 + embedding deployments
│   ├── docintel/main.bicep         # Document Intelligence, PE
│   ├── keyvault/main.bicep         # Key Vault Standard, PE, RBAC auth
│   ├── registry/main.bicep         # ACR Premium, PE, AcrPull roles
│   ├── apim/main.bicep             # APIM Developer (internal VNet mode), system MI, diagnostics
│   ├── containerapps/main.bicep    # ACA env (internal=true), web/api apps + ingest job
│   └── bastion/main.bicep          # Jumpbox VM only (Bastion Developer = portal-native, no IaC resource)
└── README.md                       # Module documentation with AVM versions
```

### What is NOT in Phase 2a (deferred)

- **Phase 2b (T033–T047):** Cross-cutting app foundations (config.py, auth, routers, services, postprovision hooks). Ships after Phase 2a IaC is validated.
- **Phase 3 (T048–T055):** Infra tests (Pester compile/what-if/no-public-endpoints), azd end-to-end, ADRs.
- **APIM backend wiring:** Registering Container Apps and AOAI as APIM backends happens in Phase 2b/3 when those apps exist and serve traffic.
- **APIM policies:** JWT validation, rate limiting, token-tracking, retry-on-429 — all deferred to Phase 2b/3. Phase 2a deploys the APIM instance + base config only.

---

## B. Network Topology

### VNet Design

| Property | Value |
|----------|-------|
| **Address space** | `10.0.0.0/22` (1024 addresses) |
| **Region** | Parameterized (`location`), default East US 2 |

### Subnets

| Subnet | CIDR | Purpose | Delegation | NSG |
|--------|------|---------|------------|-----|
| `snet-aca` | `10.0.0.0/24` (256) | Container Apps Environment infrastructure (apps + jobs) | `Microsoft.App/environments` | Outbound: allow HTTPS to VNet; deny internet (ACA manages egress) |
| `snet-pe` | `10.0.1.0/24` (256) | All Private Endpoints + jumpbox VM | None | Default deny inbound from internet; allow inbound from VNet |
| `snet-jobs` | `10.0.2.0/24` (256) | **RESERVED** — future expansion (second ACA env, Azure Functions, etc.) | None (reserved) | Default deny all |
| `AzureBastionSubnet` | `10.0.3.0/26` (64) | **RESERVED** — only provisioned when `bastionSku` = `'Basic'` or `'Standard'` (default Developer = no subnet needed) | None (Bastion-required name) | Bastion-required NSG rules (when provisioned) |
| `snet-apim` | `10.0.3.64/27` (32) | Azure API Management (VNet-injected, internal mode) | None | APIM-required NSG rules (management port 3443, load balancer probe, etc.) |

**Resolved — snet-jobs:** ACA supports only ONE infrastructure subnet per environment. `snet-aca` hosts all apps + jobs in one environment. `snet-jobs` is **reserved** for future expansion (documented in network module but no delegation applied).

**Resolved — jumpbox placement:** Jumpbox VM sits in `snet-pe` to conserve IP space. Security rationale: jumpbox traffic is internal-only, authenticated via managed identity, accessed only through Bastion Developer (Azure portal).

**v3 — Bastion Developer:** Bastion Developer SKU uses a shared Microsoft-managed pool. No `AzureBastionSubnet` or public IP is needed. The subnet is **reserved** in the address space but NOT provisioned by default. When `bastionSku` is set to `'Basic'` or `'Standard'`, the network module provisions `AzureBastionSubnet` and the bastion module deploys a Bastion Host resource.

**v3 — Default subnet count: 4** (snet-aca, snet-pe, snet-jobs, snet-apim). AzureBastionSubnet conditional.

**New — snet-apim:** APIM in VNet-injected internal mode requires a dedicated subnet. /27 (32 IPs) provides the minimum required by APIM (1 internal VIP + reserved IPs + room for scaling). Carved from unused space after AzureBastionSubnet (10.0.3.64–10.0.3.95). No VNet address space expansion needed.

### Private DNS Zones

| Zone | Resource |
|------|----------|
| `privatelink.openai.azure.com` | Azure OpenAI |
| `privatelink.search.windows.net` | AI Search |
| `privatelink.documents.azure.com` | Cosmos DB |
| `privatelink.blob.core.windows.net` | Blob Storage |
| `privatelink.queue.core.windows.net` | Storage Queue (Event Grid subscription target) |
| `privatelink.vaultcore.azure.net` | Key Vault |
| `privatelink.azurecr.io` | Container Registry |
| `privatelink.cognitiveservices.azure.com` | Document Intelligence |
| `privatelink.monitor.azure.com` | AMPLS (metrics/logs ingestion) |
| `privatelink.oms.opinsights.azure.com` | AMPLS (OMS) |
| `privatelink.ods.opinsights.azure.com` | AMPLS (ODS) |
| `privatelink.agentsvc.azure-automation.net` | AMPLS (agent service) |
| `azure-api.net` | **APIM internal endpoints** (gateway, portal, management, SCM) |

**Resolved — queue PE:** `privatelink.queue.core.windows.net` confirmed — required for private-only Event Grid delivery to Storage Queue.

**New — APIM DNS:** APIM in internal VNet mode does NOT use `privatelink.*` DNS. Instead, the gateway and management endpoints resolve via `<name>.azure-api.net`, which must point to the APIM's internal VIP. A private DNS zone `azure-api.net` is created and VNet-linked, with A records for `<apim-name>.azure-api.net`, `<apim-name>.portal.azure-api.net`, `<apim-name>.management.azure-api.net`, and `<apim-name>.scm.azure-api.net` — all pointing to the internal load balancer IP.

All zones are VNet-linked. Gated by `customerProvidedDns` parameter — when `true`, zones are NOT created (customer brings their own DNS forwarding).

### DNS Resolution Path (Container Apps → APIM)

```
Container App (snet-aca) → VNet DNS → Private DNS zone (azure-api.net) → APIM internal VIP (snet-apim)
```

Container Apps in internal mode use VNet-integrated DNS. The `azure-api.net` private DNS zone linked to the VNet ensures `<apim-name>.azure-api.net` resolves to the internal IP. No custom DNS forwarders needed.

### Egress Story

- **No NAT Gateway** — ACA Consumption plan manages outbound via platform-managed SNAT. Within-VNet traffic stays on the backbone.
- **No Azure Firewall** — out of scope for v1 accelerator (cost + complexity). Customers with hub-spoke can layer their own firewall via VNet peering.
- All PaaS calls go through Private Endpoints (no internet egress needed for data plane).
- ACA needs outbound internet for: pulling images from ACR (private via PE), Azure management plane calls. Platform handles this.
- APIM outbound to backends uses VNet-integrated subnets (Container Apps internal FQDN resolves inside VNet).

### Bastion / Jumpbox Placement

- **Default (v3): Bastion Developer SKU** — free, portal-native RDP/SSH, no Azure resources deployed. Single concurrent session. Available in East US 2.
- Linux jumpbox VM (Ubuntu 24.04, Standard_B2s, ~$36/mo) in `snet-pe` — can be deallocated when idle ($0 when stopped)
- Gated by `deployJumpbox=true` (default). When `false`, jumpbox is skipped.
- **Optional upgrade:** Set `bastionSku='Basic'` or `'Standard'` to deploy a dedicated Bastion Host (adds ~$140+/mo, exceeds $500 budget — not recommended for demo)

---

## C. APIM Module — `infra/modules/apim/`

### C.1 SKU Decision

**Recommendation: Developer (classic) — $500/month budget constraint**

| Factor | Developer (~$50/mo) | Premium stv2 (~$2,800/mo) |
|--------|---------------------|--------------------------|
| Internal VNet mode | ✅ Full VNet injection | ✅ Full VNet injection |
| All endpoints private | ✅ Gateway, portal, management internal | ✅ All endpoints internal |
| SC-004 compliance | ✅ Compliant | ✅ Compliant |
| SLA | ❌ No SLA | ✅ 99.95% |
| Multi-region | ❌ | ✅ (not needed for demo) |
| Budget fit ($500/mo) | ✅ | ❌ DISQUALIFIED |

**Verdict:** Developer SKU supports full internal VNet injection mode with zero public endpoints. All gateway, portal, management, and SCM endpoints resolve to the VNet-internal VIP only. SC-004 compliant. No SLA is acceptable for a demo accelerator. Premium is disqualified by the $500/month hard cap.

**Parameter strategy:** `apimSku` parameter with allowed values:
- `'Developer'` (default) — demo/dev environments, ~$50/month
- `'Premium'` — production use, ~$2,800/month (customer upgrades at their discretion)

**⚠️ v3 note:** v2 defaulted to Premium. v3 defaults to Developer per Arbyam's $500/month directive. The parameter structure is unchanged — customers deploying to production simply set `apimSku='Premium'` in their parameters file.

### C.2 AVM Evaluation

**Module:** `br/public:avm/res/api-management/service`  
**Status:** ✅ GA — mature, supports VNet integration, internal mode, managed identity, diagnostic settings, and version pinning.

**Decision:** Use the AVM module. Pin to a specific version in the module reference (e.g., `br/public:avm/res/api-management/service:0.x.x`). Exact version locked at implementation time after `bicep restore` validation.

**AVM provides:**
- VNet injection configuration (internal/external mode)
- System-assigned + user-assigned managed identity
- Diagnostic settings (Log Analytics + App Insights)
- Named values, APIs, products, subscriptions
- Policy fragments

**Hand-rolled supplements (if needed):**
- APIM-specific NSG rules on `snet-apim` (not part of APIM AVM — these go in the network module)
- Private DNS zone A records for internal endpoints (go in the network module)

### C.3 Module Inputs

| Parameter | Type | Source |
|-----------|------|--------|
| `name` | string | `'${namingPrefix}-apim'` |
| `location` | string | Deployment region |
| `sku` | string | `apimSku` parameter (`'Premium'` or `'Developer'`) |
| `skuCapacity` | int | 1 (single unit) |
| `publisherEmail` | string | From `main.parameters.json` |
| `publisherName` | string | From `main.parameters.json` |
| `virtualNetworkType` | string | `'Internal'` |
| `subnetResourceId` | string | `network.outputs.snetApimId` |
| `managedIdentityType` | string | `'SystemAssigned'` |
| `diagnosticSettings` | object | Log Analytics workspace ID + App Insights connection string |
| `tags` | object | Standard accelerator tags |

### C.4 Module Outputs

| Output | Type | Consumers |
|--------|------|-----------|
| `apimResourceId` | string | RBAC wiring, backend registrations |
| `apimGatewayUrl` | string | Internal gateway URL (`https://<name>.azure-api.net`) |
| `apimManagementEndpoint` | string | Management URL (internal) |
| `apimSystemIdentityPrincipalId` | string | RBAC: Cognitive Services OpenAI User on AOAI, Storage Blob Data Reader, etc. |

### C.5 Backend Registrations (Phase 2b/3 — deferred)

Phase 2a deploys the APIM instance with base configuration only. Backend wiring happens when the backends exist and serve traffic:

| Backend | When | Wiring details |
|---------|------|---------------|
| FastAPI `api` Container App | Phase 2b | APIM backend → ACA internal FQDN; managed identity auth |
| FastAPI `ingest` Container App | Phase 2b | APIM backend → ACA internal FQDN; managed identity auth |
| Azure OpenAI (AI Gateway) | Phase 2b/3 | APIM backend → AOAI PE; token-tracking policy; retry-on-429 |

### C.6 Policies (Phase 2b/3 — deferred)

These policies will be implemented when backends are registered:

- **JWT validation** — Validate Entra ID tokens at gateway edge (issuer = tenant, audience = APIM app registration)
- **Per-tenant rate limiting** — Protect downstream AOAI/Search/Cosmos quotas
- **Token-tracking + 429-retry** — AI Gateway pattern for AOAI calls; log prompt/completion token counts
- **Logging** — All API traffic piped to App Insights; correlation IDs for distributed tracing

### C.7 Constitution Compliance Checklist — APIM

- [x] **No public IP / no external gateway URL** — `virtualNetworkType: 'Internal'`; all endpoints resolve to VNet-internal VIP only
- [x] **System-assigned managed identity** — for downstream auth to AOAI, Storage, Cosmos
- [x] **All secrets from Key Vault references** — no inline keys; APIM named values reference Key Vault secrets
- [x] **Diagnostic settings → Log Analytics + App Insights** — wired via AVM `diagnosticSettings` parameter
- [x] **Idempotent** — AVM module is declarative; re-running `azd up` produces no drift; deterministic naming (`${namingPrefix}-apim`)

---

## D. Module Decomposition (PR Plan)

### Execution Order (Revised)

```
Layer 0 (foundation):  main.bicep shell + parameters
Layer 1 (network):     network (VNet + 5 subnets + 13 DNS zones)
Layer 1 (identity):    identity (MIs — no dependencies)
Layer 2 (platform):    monitoring, registry, keyvault (depend on network for PE subnet)
Layer 2.5 (gateway):   apim (depends on network + identity + monitoring)
Layer 3 (data plane):  openai, docintel, storage, cosmos, search (depend on network + identity; search depends on openai)
Layer 4 (compute):     containerapps (depends on network, identity, monitoring, registry)
Layer 4 (admin):       bastion (depends on network)
Layer 5 (wiring):      main.bicep composition + RBAC cross-cut (T029/T030)
Layer 6 (polish):      AVM refactor (T031) + README (T032)
```

**Resolved — openai-before-search:** `openai` module deploys BEFORE `search` in Layer 3 so the AI Search shared private link to AOAI works on first deploy. Explicit `dependsOn` in main.bicep.

### PR Plan (Revised — 17 PRs)

| PR # | Branch | Module(s) | Task IDs | AVM Module | Specialist | Reviewer |
|------|--------|-----------|----------|------------|------------|----------|
| PR-A | `feat/phase2-main-shell` | `main.bicep` + `main.parameters.json` | T015, T016 | N/A (composition) | Dallas | Ripley |
| PR-B | `feat/phase2-network` | `network/` | T017 | `avm/res/network/virtual-network` + `avm/res/network/private-dns-zone` + `avm/res/network/network-security-group` | Dallas | Ripley |
| PR-C | `feat/phase2-identity` | `identity/` | T018 | `avm/res/managed-identity/user-assigned-identity` | Dallas | Ripley |
| PR-D | `feat/phase2-monitoring` | `monitoring/` | T019 | `avm/res/operational-insights/workspace` + `avm/res/insights/component` + hand-rolled AMPLS | Dallas | Ripley |
| PR-E | `feat/phase2-registry` | `registry/` | T020 | `avm/res/container-registry/registry` | Dallas | Ripley |
| PR-F | `feat/phase2-keyvault` | `keyvault/` | T021 | `avm/res/key-vault/vault` | Dallas | Ripley |
| PR-G | `feat/phase2-storage` | `storage/` | T022 | `avm/res/storage/storage-account` + hand-rolled Event Grid | Dallas | Ripley |
| PR-H | `feat/phase2-cosmos` | `cosmos/` | T023 | `avm/res/document-db/database-account` | Dallas | Ripley |
| PR-I | `feat/phase2-openai` | `openai/` | T025 | `avm/res/cognitive-services/account` (kind: OpenAI) | Dallas | Ripley |
| PR-J | `feat/phase2-search` | `search/` | T024 | `avm/res/search/search-service` + hand-rolled shared private links | Dallas | Ripley |
| PR-K | `feat/phase2-docintel` | `docintel/` | T026 | `avm/res/cognitive-services/account` (kind: FormRecognizer) | Dallas | Ripley |
| PR-L | `feat/phase2-apim` | `apim/` | **T032a** | **`avm/res/api-management/service`** | **Dallas** | **Ripley** |
| PR-M | `feat/phase2-containerapps` | `containerapps/` | T027 | `avm/res/app/managed-environment` + hand-rolled app/job defs | Dallas + Kane | Ripley |
| PR-N | `feat/phase2-bastion` | `bastion/` | T028 | `avm/res/compute/virtual-machine` (jumpbox only; no Bastion Host in Developer SKU) | Dallas | Ripley |
| PR-O | `feat/phase2-rbac-wiring` | Cross-cutting RBAC + `main.bicep` wiring | T029, T030 | N/A (composition) | Dallas | Ripley |
| PR-P | `feat/phase2-avm-refactor` | AVM refactor pass | T031 | All applicable AVM modules | Dallas | Ripley |
| PR-Q | `feat/phase2-infra-readme` | `infra/README.md` | T032 | N/A | Scribe | Ripley |

**Total: 17 PRs.** PR-A unblocks all. PRs B–K can run in parallel after PR-A (with J after I for search→openai dependency). PR-L (APIM) can run in parallel with G–K after B+C+D merge. PR-M depends on B, C, D, E. PR-O depends on all resource modules. PR-P depends on PR-O.

**Changes from v1 plan:**
- PR-I and PR-J swapped (openai is now PR-I, search is PR-J) to encode the deployment ordering dependency
- PR-L inserted for APIM module (T032a)
- Former PR-L through PR-P shifted to PR-M through PR-Q

### Module Call Order in main.bicep (Revised)

```bicep
// Layer 1 — foundation
module network 'modules/network/main.bicep'
module identity 'modules/identity/main.bicep'

// Layer 2 — platform services
module monitoring 'modules/monitoring/main.bicep'    // depends: network (PE subnet)
module registry 'modules/registry/main.bicep'        // depends: network (PE subnet), identity (AcrPull)
module keyvault 'modules/keyvault/main.bicep'        // depends: network (PE subnet)

// Layer 2.5 — API gateway
module apim 'modules/apim/main.bicep'                // depends: network (snet-apim), identity, monitoring

// Layer 3 — data plane (openai BEFORE search — shared private link dependency)
module openai 'modules/openai/main.bicep'            // depends: network, identity
module storage 'modules/storage/main.bicep'          // depends: network, identity
module cosmos 'modules/cosmos/main.bicep'            // depends: network, identity
module docintel 'modules/docintel/main.bicep'        // depends: network, identity
module search 'modules/search/main.bicep'            // depends: network, identity, openai (shared PE) ← explicit dependsOn

// Layer 4 — compute
module containerapps 'modules/containerapps/main.bicep' // depends: network, identity, monitoring, registry
module bastion 'modules/bastion/main.bicep'             // depends: network; conditional on deployBastion
```

### Dependency Diagram

```
                    ┌──────────┐
                    │ main.bicep│
                    │  (shell)  │
                    └─────┬─────┘
                          │
              ┌───────────┼───────────┐
              ▼                       ▼
        ┌──────────┐           ┌──────────┐
        │ network  │           │ identity │
        │ (VNet,   │           │ (3 MIs)  │
        │ DNS, NSG)│           └────┬─────┘
        └────┬─────┘                │
             │     ┌────────────────┤
             ▼     ▼                │
     ┌────────────────┐             │
     │  monitoring    │             │
     │  registry      │◄────────────┘
     │  keyvault      │
     └───────┬────────┘
             │
             ▼
     ┌────────────────┐
     │     apim       │  ← Developer SKU (v3)
     │ (Premium/Dev)  │
     └───────┬────────┘
             │
     ┌───────┴────────────────────────┐
     ▼           ▼          ▼         ▼
 ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐
 │ openai │ │storage │ │ cosmos │ │docintel│
 └───┬────┘ └────────┘ └────────┘ └────────┘
     │
     ▼ (dependsOn)
 ┌────────┐
 │ search │
 └────────┘

     ┌────────────────────┐    ┌────────────┐
     │  containerapps     │    │  bastion   │
     │ (depends: net,id,  │    │ (conditional)│
     │  mon,reg)          │    └────────────┘
     └────────────────────┘
```

### AVM Module Mapping (Revised)

| Resource | AVM Module Path | Maturity | Notes |
|----------|----------------|----------|-------|
| Virtual Network | `avm/res/network/virtual-network` | ✅ GA | Full subnet + delegation support |
| NSG | `avm/res/network/network-security-group` | ✅ GA | Includes APIM-required rules for `snet-apim` |
| Private DNS Zone | `avm/res/network/private-dns-zone` | ✅ GA | VNet link built-in |
| User-Assigned MI | `avm/res/managed-identity/user-assigned-identity` | ✅ GA | |
| Log Analytics | `avm/res/operational-insights/workspace` | ✅ GA | |
| App Insights | `avm/res/insights/component` | ✅ GA | Workspace-based |
| AMPLS | **Hand-rolled** | ⚠️ No AVM | `Microsoft.Insights/privateLinkScopes` — no AVM exists |
| Budget | **Hand-rolled** | ⚠️ No AVM | `Microsoft.Consumption/budgets` — simple |
| ACR | `avm/res/container-registry/registry` | ✅ GA | PE + zone group built-in |
| Key Vault | `avm/res/key-vault/vault` | ✅ GA | PE + RBAC built-in |
| Storage Account | `avm/res/storage/storage-account` | ✅ GA | PE (blob+queue) + containers built-in |
| Event Grid System Topic | **Hand-rolled** | ⚠️ No AVM | `Microsoft.EventGrid/systemTopics` + subscription |
| Cosmos DB | `avm/res/document-db/database-account` | ✅ GA | PE + SQL containers built-in |
| AI Search | `avm/res/search/search-service` | ✅ GA | PE built-in; shared private links hand-rolled |
| Azure OpenAI | `avm/res/cognitive-services/account` | ✅ GA | `kind: 'OpenAI'`; model deployments built-in |
| Document Intelligence | `avm/res/cognitive-services/account` | ✅ GA | `kind: 'FormRecognizer'`; PE built-in |
| **APIM** | **`avm/res/api-management/service`** | **✅ GA** | **VNet injection, internal mode, MI, diagnostics** |
| ACA Environment | `avm/res/app/managed-environment` | ✅ GA | VNet integration built-in |
| ACA App | **Hand-rolled** | ⚠️ No AVM | `Microsoft.App/containerApps` |
| ACA Job | **Hand-rolled** | ⚠️ No AVM | `Microsoft.App/jobs` |
| Bastion Host | `avm/res/network/bastion-host` | ✅ GA | **Conditional** — only deployed when `deployBastion=true` (not in $500 demo default) |
| Virtual Machine (jumpbox) | `avm/res/compute/virtual-machine` | ✅ GA | Linux, B2s; default deployment; conditional on `deployJumpbox=true` |

**Hand-rolled count:** 4 resources (AMPLS, Budget, Event Grid system topic, ACA app/job definitions). APIM uses AVM. Everything else uses AVM.

---

## E. main.bicep Parameters (Revised)

**Single `main.parameters.json`** with environment-agnostic defaults.

Parameters (from T016 + APIM additions):
- `namingPrefix` (string, required) — resource name prefix
- `location` (string, required) — Azure region
- `adminGroupObjectId` (string, required) — Entra group for admin role
- `allowedUserGroupObjectIds` (array, optional) — restrict chat access
- `deployBastion` (bool, default: false) — deploys dedicated Bastion Host (adds ~$140+/mo; NOT recommended under $500 cap)
- `deployJumpbox` (bool, default: true) — deploys jumpbox VM for internal access via Bastion Developer
- `customerProvidedDns` (bool, default: false)
- `enableZoneRedundancy` (bool, default: false)
- `enableCustomerManagedKey` (bool, default: false)
- `chatModel` (string, default: 'gpt-5')
- `embeddingModel` (string, default: 'text-embedding-3-large')
- `aiSearchSku` (string, default: **'basic'**) — v3 change: was 'standard'
- `cosmosCapacityMode` (string, default: **'Serverless'**, allowed: `['Serverless', 'Provisioned']`) — v3 change: replaces `cosmosAutoscaleMaxRu`
- `budgetMonthlyUsd` (int, default: **500**) — v3 change: was 1000
- **`apimSku`** (string, default: **`'Developer'`**, allowed: `['Premium', 'Developer']`) — v3 change: was 'Premium'
- **`apimPublisherEmail`** (string, required) — APIM publisher contact email
- **`apimPublisherName`** (string, required) — APIM publisher display name

### Outputs (Revised)

`main.bicep` emits:
- Resource group name
- VNet ID
- ACA environment default domain (internal FQDN)
- UI URL (internal: `https://web.<aca-env-domain>`)
- ACR login server
- Cosmos account endpoint
- Search endpoint
- AOAI endpoint
- Storage account name
- Key Vault URI
- App Insights connection string
- **APIM gateway URL** (internal) — **NEW**
- **APIM resource ID** — **NEW**

---

## F. Constitution Compliance Checklist

### Principle I — Security-First / Zero Public Endpoints

| Module | How zero-public-endpoints is enforced |
|--------|--------------------------------------|
| network | VNet is the trust boundary. All subnets have NSGs. No public IPs except Bastion (Azure-managed). |
| storage | `publicNetworkAccess: 'Disabled'`; Blob PE + Queue PE in `snet-pe` |
| cosmos | `publicNetworkAccess: 'Disabled'`; PE in `snet-pe` |
| search | `publicNetworkAccess: 'disabled'`; PE in `snet-pe`; shared private links to AOAI + Storage |
| openai | `publicNetworkAccess: 'Disabled'`; PE in `snet-pe` |
| docintel | `publicNetworkAccess: 'Disabled'`; PE in `snet-pe` |
| keyvault | `publicNetworkAccess: 'Disabled'`; PE in `snet-pe` |
| registry | `publicNetworkAccess: 'Disabled'`; PE in `snet-pe` |
| monitoring | AMPLS PE in `snet-pe`; ingestion via private link |
| **apim** | **`virtualNetworkType: 'Internal'` — all endpoints (gateway, portal, management, SCM) resolve to VNet-internal VIP only. No public IP. Developer SKU.** |
| containerapps | `vnetConfiguration.internal: true` — no public IP, no public hostname |
| bastion | Bastion Developer: no IaC resource, portal-native. Jumpbox VM has no public IP; accessed only via portal Bastion. When `deployBastion=true` (dedicated), Bastion has Azure-managed public IP — documented exception. |

### Principle I — Managed Identity Everywhere

| Service call | Identity | Role |
|--------------|----------|------|
| api → Cosmos | mi-api | Cosmos DB Built-in Data Contributor |
| api → Search | mi-api | Search Index Data Reader |
| api → AOAI | mi-api | Cognitive Services OpenAI User |
| api → Storage | mi-api | Storage Blob Data Reader |
| api → Doc Intelligence | mi-api | Cognitive Services User |
| ingest → Cosmos | mi-ingest | Cosmos DB Built-in Data Contributor |
| ingest → Search | mi-ingest | Search Index Data Contributor |
| ingest → AOAI | mi-ingest | Cognitive Services OpenAI User |
| ingest → Storage | mi-ingest | Storage Blob Data Contributor |
| ingest → Doc Intelligence | mi-ingest | Cognitive Services User |
| web → (none direct) | mi-web | (web calls APIM, not PaaS directly) |
| all apps → ACR | mi-api, mi-ingest, mi-web | AcrPull |
| Search → AOAI (vectorizer) | Shared private link | System-assigned MI of Search service |
| Search → Storage (indexer) | Shared private link | System-assigned MI of Search service |
| **APIM → AOAI** | **APIM system MI** | **Cognitive Services OpenAI User (Phase 2b)** |
| **APIM → Key Vault** | **APIM system MI** | **Key Vault Secrets User (for named value refs)** |

### Principle II — Idempotent IaC

| Mechanism | Where |
|-----------|-------|
| Deterministic naming | `${namingPrefix}-<resource-short>` pattern; no `uniqueString` randomness |
| No `if` toggling resources in/out on re-run | Conditional resources (Bastion) use `if` on the module call — Bicep handles this idempotently |
| `what-if` CI gate | T049 (Phase 3) validates; all modules designed for it now |
| No imperative scripts during provision | All resources are declarative Bicep; postprovision is additive only |
| APIM idempotent | AVM module is declarative; same inputs → same state; `${namingPrefix}-apim` naming; Developer SKU |

### Key Vault References

Key Vault is deployed but in v1 is **CMK-only** (per plan.md). No app secrets are stored in KV — all auth is MSI. When `enableCustomerManagedKey=true`, CMK references for Cosmos, Storage, and AOAI are wired through KV. APIM named values will reference Key Vault secrets for any API keys needed in Phase 2b/3 (e.g., if a backend requires a key during migration from key-auth to MI-auth).

---

## G. Specialist Assignment (Revised)

| Task ID | Description | Assigned To | Rationale |
|---------|-------------|-------------|-----------|
| T015 | main.bicep shell | Dallas | Bicep specialist |
| T016 | main.parameters.json | Dallas | Bicep specialist |
| T017 | network module (incl. snet-apim + APIM DNS zone) | Dallas | Core Bicep; complex (VNet + 13 DNS zones + NSGs) |
| T018 | identity module | Dallas | Bicep, simple |
| T019 | monitoring module | Dallas | Bicep; AMPLS is hand-rolled |
| T020 | registry module | Dallas | Bicep, AVM-driven |
| T021 | keyvault module | Dallas | Bicep, AVM-driven |
| T022 | storage module (incl. queue PE) | Dallas | Bicep; Event Grid glue is hand-rolled |
| T023 | cosmos module | Dallas | Bicep, AVM-driven |
| T024 | search module | Dallas | Bicep; shared private links are hand-rolled |
| T025 | openai module | Dallas | Bicep, AVM-driven |
| T026 | docintel module | Dallas | Bicep, AVM-driven |
| T027 | containerapps module | Dallas + Kane | Kane consulted for ACA app/job definitions |
| T028 | bastion module | Dallas | Bicep, AVM-driven |
| T029 | RBAC cross-cut (incl. APIM MI roles) | Dallas | RBAC role assignments across all modules |
| T030 | main.bicep wiring (incl. APIM module call) | Dallas | Composition layer |
| T031 | AVM refactor pass (incl. APIM AVM validation) | Dallas | Validate all AVM usage |
| T032 | infra/README.md | Scribe | Documentation |
| **T032a** | **APIM module** | **Dallas** | **Bicep, AVM-driven; new task** |

**Parker** writes Phase 3 infra tests (T048–T054) once Phase 2a ships.

---

## H. Risks (Revised)

### Resolved Questions (no longer open)

| # | Question | Resolution |
|---|----------|------------|
| 1 | snet-jobs subnet purpose | Reserved for future use; apps+jobs share snet-aca |
| 2 | Storage Queue PE needed? | Yes — `privatelink.queue.core.windows.net` added |
| 3 | Phase 2 scope split | Phase 2a (T015–T032+T032a IaC) → Phase 2b (T033–T047 app foundations) |
| 4 | openai-before-search ordering | Accepted — explicit `dependsOn` in main.bicep |
| 5 | Jumpbox VM in snet-pe | Accepted — conserves IP space; internal-only traffic |

### Active Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| **$500/month budget** — must be respected across all resources | High | Cost table validated; $318/mo total with $182 headroom. Budget alert at $500 via Azure Budget resource. |
| **APIM Developer no SLA** — acceptable for demo, not production | Low | Document in README. Customers set `apimSku='Premium'` for production. |
| **APIM deployment time** — Developer VNet-injected APIM takes 30–45 minutes to provision | Medium | Document in README. First-deploy patience required. Subsequent updates are faster. |
| **Bastion Developer single session** — only 1 user can connect at a time | Low | Acceptable for demo. Document limitation. |
| **AI Search Basic limits** — 15 GB storage, 3 indexes max | Low | Sufficient for demo. Customers upgrade to S1 for production. |
| **AMPLS has no AVM** — hand-rolled module may drift | Medium | Keep minimal (PE + zone group + scoped resource links). Review against Azure docs at PR time. |
| **ACA app/job definitions have no AVM** | Medium | AVM covers managed environment. App/job types are simple enough to hand-roll. |
| **Event Grid on private storage** — delivery to private Queue may need extra networking | Medium | Validate in what-if and test early. Event Grid system topic MSI publishes. |
| **AI Search shared private links** — async approval (up to 10 min) on first deploy | Medium | Accept async approval. Document in README. |
| **gpt-5 regional availability** | Low | Pre-flight script (T014) validates region availability. |
| **AVM version pinning** | Low | Pin in each module, document in README, validate with `bicep restore`. |

---

## I. Execution Timeline (Revised)

| Day | PRs | Description |
|-----|-----|-------------|
| 1 | PR-A | main.bicep shell + parameters (unblocks everything) |
| 1–2 | PR-B, PR-C | network (incl. snet-apim + APIM DNS) + identity (parallel) |
| 2–3 | PR-D, PR-E, PR-F | monitoring, registry, keyvault (parallel, depend on network) |
| 3 | PR-L | APIM module (depends on B, C, D — can run parallel with G–K) |
| 3–4 | PR-I, PR-K, PR-G, PR-H | openai, docintel, storage, cosmos (parallel) |
| 4 | PR-J | search (depends on PR-I / openai for shared PE) |
| 4–5 | PR-M, PR-N | containerapps, bastion (depend on layers 1–2) |
| 5 | PR-O | RBAC wiring + main.bicep composition |
| 5–6 | PR-P, PR-Q | AVM refactor pass + README |

**Estimated total: 5–6 working days** of elapsed time with parallel execution (unchanged from v1 despite APIM addition — it runs in parallel with data-plane modules).

---

*Phase 2a Architecture Plan v3 — Cost-validated at $318/month (under $500 ceiling). Approved by Lead (Ripley) on 2026-05-08T20:13:37-07:00. Ready for execution.*
