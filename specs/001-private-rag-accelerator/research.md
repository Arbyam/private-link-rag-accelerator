# Phase 0 — Research & Decisions

**Feature**: Private End-to-End RAG Accelerator
**Branch**: `001-private-rag-accelerator`
**Date**: 2026-05-08

This document records the decisions taken during Phase 0 to resolve every
"NEEDS CLARIFICATION" item that would otherwise block planning. Each decision
follows the **Decision / Rationale / Alternatives considered** format.

---

## D1 — Compute platform: Azure Container Apps (internal)

**Decision**: Two Azure Container Apps (`web`, `api`) plus one Container Apps
Job (`ingest`) on a single Container Apps Environment with
`vnetConfiguration.internal=true` (no public ingress) and a dedicated
infrastructure subnet.

**Rationale**:

- ACA's `internal=true` mode gives a private static IP for ingress with built-in
  Envoy + KEDA autoscale, directly satisfying FR-004 (no public hostname).
- Container Apps Jobs are first-class for the ingestion worker (event-triggered
  via Storage Queue, scale-to-zero, per-execution timeouts) — exactly the shape
  needed for batch corpus indexing without a long-lived consumer.
- Single Environment shares VNet + Log Analytics + Dapr if ever added; keeps
  cost down vs separate environments per app.
- KEDA-based scale-to-zero on `web`/`api` saves cost during idle demo periods;
  `min-replicas=1` is the parameter to flip for production.

**Alternatives considered**:

- **App Service (Premium V3) + private endpoint**: Works, but ACA gives better
  cost/scale knobs for the three-service shape and first-class jobs. Recorded
  as ADR-0001.
- **AKS**: Overkill for an accelerator — adds cluster ops burden that
  contradicts SC-001 (≤15 min hands-on deploy).
- **Functions on Flex Consumption**: Good for ingest, but the chat orchestrator
  benefits from long-lived SSE streaming connections that ACA handles more
  cleanly than Functions.

---

## D2 — Chat model: Azure OpenAI **gpt-5** family

**Decision**: Default chat deployment is `gpt-5` (Azure OpenAI). Embedding
deployment is `text-embedding-3-large` (3072 dims). Both deployed regionally,
behind a Private Endpoint, with `publicNetworkAccess=Disabled`.

**Rationale**:

- **`gpt-4o` is being deprecated in Azure**; building net-new on a deprecated
  model would force a forced migration during a customer pilot — unacceptable
  for an accelerator.
- gpt-5 is current generation, supports the multi-turn + tool-call patterns the
  orchestrator already uses, and is widely available across the regions SLED
  customers deploy to (East US 2, South Central US, North Central US, West US 3).
- Embedding-3-large at 3072 dims gives strong retrieval quality for English
  enterprise text; the AI Search vector field is sized accordingly.
- Both model deployments are parameterized — customers can swap to a regional
  fallback or a fine-tuned variant by changing `chatModel`/`embeddingModel`
  without IaC structural changes. Recorded as ADR-0003.

**Alternatives considered**:

- **gpt-4o**: Deprecated path. Rejected.
- **gpt-4.1 / gpt-4-turbo**: Older generation, no upside over gpt-5 for this
  workload, similar or higher cost.
- **Self-hosted open-weights via AML / KAITO**: Significant ops burden, breaks
  "easy to set up" principle.
- **PTU (provisioned throughput)**: Production-only opt-in (`enablePtu=true`)
  parameter; default is pay-as-you-go S0.

---

## D3 — Retrieval: AI Search S1 with **integrated vectorization** + semantic ranker + hybrid

**Decision**: Single AI Search index `kb-index` on a Standard (S1) service,
using **integrated vectorization** (skillset → AzureOpenAIEmbedding skill),
**semantic ranker** enabled, and **hybrid search** (BM25 + vector + semantic
re-rank) at query time. Per-user/scope isolation via a `scope` filter field.

**Rationale**:

- Integrated vectorization removes a whole class of pipeline code from the
  ingestion worker — Search owns chunking + embedding via skillset, the worker
  just hands it cracked layout from Document Intelligence.
- Semantic ranker is a measurable quality lift on enterprise QA corpora and
  meets SC-006 (≥85% correct citation rate on benchmark set).
- Hybrid retrieval beats vector-only on rare proper nouns (case numbers,
  statute IDs) which are common in SLED corpora.
- A **single index with a `scope` filter** is simpler and cheaper than per-user
  indexes and still satisfies SC-011 (cross-user isolation enforced at every
  query). Recorded as ADR-0005.
- S1 is the **floor** SKU supporting Private Endpoint. Documented in
  Complexity Tracking.

**Alternatives considered**:

- **Per-user AI Search index**: Hits index-count limits fast, makes shared
  corpus updates fan-out, no benefit over a filtered single index when MI-based
  query enforcement is already trusted (the API never accepts a client-supplied
  `scope`).
- **AI Search Basic**: No Private Endpoint support — violates Principle I.
- **PostgreSQL pgvector + custom semantic re-ranker**: Higher ops burden, no
  managed integrated vectorization, no managed semantic ranker.
- **Cosmos DB integrated vector search**: Promising and worth re-evaluating for
  v2; today AI Search has materially better hybrid + semantic ranker maturity.

---

## D4 — Document cracking: Azure AI Document Intelligence (prebuilt-layout)

**Decision**: Use Document Intelligence `prebuilt-layout` for every ingested
file (PDF, image, Office). Output (markdown + tables + figures) is the input
to AI Search's integrated vectorization skillset.

**Rationale**:

- Single API handles PDFs (text + scanned), TIFF/PNG/JPG, DOCX/XLSX/PPTX —
  satisfies FR-009 / FR-010 with one dependency.
- Markdown output is the modern, model-friendly representation; preserves
  headings, tables, and reading order — directly improves chunking quality.
- Private Endpoint supported. Managed-identity auth supported.

**Alternatives considered**:

- **Tesseract / open-source OCR**: Worse on forms/tables; would require a
  separate code path per format.
- **AI Search built-in OCR/Document Extraction skills only**: Weaker on
  scanned PDFs and complex layouts; we already pay for Search S1 — pairing it
  with Document Intelligence is the standard high-quality pattern.

---

## D5 — State store: Cosmos DB for NoSQL (per spec)

**Decision**: Cosmos DB for NoSQL with two containers:

- `conversations` partitioned by `/userId` — one document per conversation,
  embedded turns array; **TTL 30 days, sliding** (touched on each turn).
- `documents` partitioned by `/scope` (`shared` or `user:<oid>`) — one document
  per ingested artifact, holds metadata + ingestion status. User-scoped docs
  inherit the parent conversation's TTL.

**Rationale**:

- Spec FR-030 explicitly recommends Cosmos.
- Native TTL satisfies SC-012 (purge within 24 h of expiry) without a sweeper
  job — Cosmos guarantees background purge, and we add a manual purge endpoint
  for SC-012's 1-h on-delete SLA.
- `/userId` partition gives perfect single-partition reads for "my
  conversations" — fast and cheap.
- Continuous-7-day backup is cheap and meets POC needs; production parameter
  flips to continuous-30-day.
- Autoscale RU/s with low max (1000) keeps demo cost predictable.

**Alternatives considered**:

- **Azure SQL / PostgreSQL Flex**: No native sliding TTL; would need a custom
  job. Document-shaped chat data is a poor relational fit. ADR-0002.
- **Cosmos serverless**: Considered as a default — autoscale at 1000 max is
  cheaper for the expected demo load and predictable; serverless wins only at
  spiky-low loads.

---

## D6 — Document storage: Azure Blob Storage with two containers

**Decision**: Single StorageV2 account with two containers — `shared-corpus`
(admin-curated) and `user-uploads` (prefixed `{userOid}/{conversationId}/...`).
No SAS tokens; all access via managed identity + RBAC. Soft delete enabled,
versioning off (cost), HNS off (no need for Data Lake hierarchical semantics).

**Rationale**:

- Single account → single Private Endpoint, simpler cost and DNS.
- Container-level + path-prefix RBAC scoping is sufficient since the API never
  hands raw blob URLs to clients (citations route through `/citations/...`).
- Event Grid system topic on Blob Created → Storage Queue → ACA Job is the
  modern replacement for the old "indexers polling blob" pattern; Reactive,
  cheap, and works inside private network.

**Alternatives considered**:

- **One account per scope**: 2× private endpoints, 2× DNS overhead, no real
  benefit.
- **AI Search blob indexer (pull)**: Couples ingest tightly to Search,
  bypasses our explicit ingestion-status surface (FR-013), and degrades the
  Document Intelligence integration.

---

## D7 — Frontend stack: Next.js 15 + Tailwind + shadcn/ui + Vercel AI SDK

**Decision**: Next.js 15 (App Router, RSC), TypeScript 5.5, Tailwind CSS 4,
shadcn/ui components, Vercel AI SDK 4 for streaming chat. Containerized via
`output: 'standalone'`, served by Node 22 in ACA.

**Rationale**:

- "Modern, sleek, professional" + "classic UI design" → restrained enterprise
  UI. shadcn/ui ships with neutral palette, accessible primitives, and is
  trivial to brand later. WCAG 2.1 AA primitives out of the box (FR-023).
- App Router + RSC → small client bundles, fast first paint on Bastion-bound
  thin clients.
- Vercel AI SDK normalizes SSE/streaming + tool calls + citation rendering
  patterns; reduces hand-rolled streaming code.
- Next.js standalone output is a clean container target; no Vercel platform
  dependency.

**Alternatives considered**:

- **SvelteKit**: Excellent, smaller ecosystem for enterprise component
  libraries.
- **Plain React + Vite**: Loses RSC + streaming primitives for free.
- **Blazor**: Strong fit for some Microsoft customers, but the JS ecosystem
  for chat-streaming + AI SDKs is materially ahead.

---

## D8 — Authentication & Authorization

**Decision**:

- **End users → UI**: Entra ID OIDC via NextAuth.js (Auth.js) with the
  Microsoft Entra provider. Tenant-scoped, with optional group restriction
  parameter (`allowedGroupIds`).
- **UI → API**: User's Entra ID token forwarded as `Authorization: Bearer`;
  validated by FastAPI middleware (JWKS cached).
- **API → Cosmos / Search / AOAI / Storage / Doc Intelligence**: System-assigned
  managed identity on each Container App, with role assignments emitted by
  Bicep (no shared keys ever issued).
- **Admin role**: Membership in a configurable Entra security group
  (`adminGroupId` parameter) → unlocks `/admin/*` routes.

**Rationale**:

- Built-in Container Apps EasyAuth was considered but rejected because we want
  the user's token in code for downstream auditing and for future on-behalf-of
  scenarios; doing it ourselves is straightforward with Auth.js.
- MSI everywhere directly satisfies FR-003 (no shared keys). Built-in role
  assignments (Cosmos DB Data Contributor, Search Index Data Contributor /
  Reader, Cognitive Services OpenAI User, Storage Blob Data Contributor /
  Reader) are emitted by Bicep at deploy time.

**Alternatives considered**:

- **App Service Easy Auth pattern**: Only works on App Service, ties us to that
  compute.
- **Federated identity from a sidecar**: Useful for cross-tenant; not needed
  here.

---

## D9 — Networking topology

**Decision**: Single VNet `/22` with four `/24` subnets:

- `snet-aca` — Container Apps Environment (delegated to
  `Microsoft.App/environments`).
- `snet-pe` — all Private Endpoints.
- `snet-jobs` — Container Apps Jobs (separate subnet to keep job network
  policy distinct).
- `snet-bastion` — `AzureBastionSubnet` `/26` (Bastion's required name).

Private DNS Zones for: `privatelink.openai.azure.com`,
`privatelink.search.windows.net`, `privatelink.documents.azure.com` (Cosmos),
`privatelink.blob.core.windows.net`, `privatelink.vaultcore.azure.net`,
`privatelink.azurecr.io`, `privatelink.cognitiveservices.azure.com` (Document
Intelligence), `privatelink.monitor.azure.com` + `oms.opinsights` +
`ods.opinsights` + `agentsvc` (AMPLS bundle).

A `customerProvidedDns=true` parameter switches off accelerator-managed Private
DNS Zones in favor of customer-supplied DNS forwarders (Hub/Spoke pattern).

**Rationale**:

- Four subnets keep blast radius small and align with ACA / Bastion
  requirements.
- AMPLS Private Link Scope is the only way to keep App Insights + LAW
  ingestion private; required for end-to-end zero-public-endpoint claim.

**Alternatives considered**:

- **Hub-and-spoke baked in**: Premature for v1 (Constitution Constraint:
  single-subscription default).
- **Service Endpoints instead of Private Endpoints**: Service Endpoints route
  via the Microsoft backbone but the resource still has a public endpoint —
  fails the "publicly disabled" property of Principle I.

---

## D10 — IaC: Bicep + Azure Verified Modules + azd

**Decision**: Bicep (subscription-scope `main.bicep`) using AVM
(`br/public:avm/*`) for every resource where an AVM exists at usable maturity.
`azd` v1.13+ as the developer / SE entry point (`azd up`, `azd down`).
Pre-flight script validates region availability (gpt-5, AI Search S1, AOAI
embedding) and quota before apply.

**Rationale**:

- AVM gives us battle-tested modules that already implement Private Endpoint,
  diagnostic settings, and customer-managed key parameters — we'd otherwise
  reinvent the wheel.
- azd's hooks (`postprovision`, `predeploy`) are the right place to seed
  sample data and run smoke tests.
- Subscription-scope `main.bicep` lets us create the resource group itself,
  which is required for SC-001's "empty subscription → working app" target.

**Alternatives considered**:

- **Terraform**: Constitution forbids without amendment.
- **Hand-rolled Bicep modules everywhere**: More code to maintain, slower to
  pick up upstream security fixes from AVM.

---

## D11 — Observability: App Insights + LAW + AMPLS

**Decision**: Workspace-based Application Insights, Log Analytics workspace,
linked into an Azure Monitor Private Link Scope (AMPLS) so that all SDK-side
telemetry ingest goes private. ACA `daprAIInstrumentationKey`-style env vars
replaced with managed-identity-based ingest where supported, otherwise scoped
ingestion key in Key Vault referenced via secret reference.

**Rationale**:

- AMPLS is the only way to keep telemetry off the public ingestion endpoints,
  which is required for the SC-010 security-architect verification.
- Workspace-based App Insights is the current pattern; classic is deprecated.

**Alternatives considered**:

- **Datadog / Grafana Cloud**: Out of tenant — violates "telemetry stays in
  customer tenant" assumption.
- **No AMPLS**: Default ingestion endpoints are public — violates Principle I.

---

## D12 — Admin access: Azure Bastion Standard

**Decision**: Bastion Standard host on `AzureBastionSubnet` (/26). Parameter
`deployBastion=true` (default). Customers with existing Bastion / VPN /
ExpressRoute set `deployBastion=false` and get a `~$130/mo` cost reduction.

**Rationale**:

- Bastion Standard supports native client (RDP/SSH from local machine through
  Bastion), shareable links for guest reviewers, and is the cheapest SKU
  supporting the SE demo loop.
- Documented as the largest cost line item in `docs/cost.md`; opt-out is
  prominent.

**Alternatives considered**:

- **Bastion Basic**: No native client / shareable links → SE workflow
  regression.
- **Jumpbox VM**: Operational overhead, weaker security posture (open SSH/RDP
  vs Bastion's brokered access).
- **Dev Box / AVD**: Premium cost for what is essentially admin shell access.

---

## D13 — Cost discipline guardrails

**Decision**: Default-deployment cost target is **≤ ~$700/mo idle** in East US 2,
broken down per family in `docs/cost.md`. An Azure Monitor Budget alert is
deployed by default at 80%/100% of a configurable threshold (`budgetMonthly`
parameter, default $1000). `azd down --purge` is the documented teardown,
exercised in CI.

**Rationale**:

- Bounded cost is a Constitution requirement (Principle IV).
- Deployed budget alert means the SE doesn't have to remember to add one
  manually after a customer demo.

---

## Open follow-ups (not blocking)

- **Customer-managed keys (CMK)**: Off by default for cost. Parameter
  `customerManagedKey=true` will be added in a v1.1 iteration with full ADR.
- **Sovereign cloud variants (Gov, China)**: Out of scope per spec. Will be a
  follow-up feature with its own model availability matrix.
- **Hub/spoke landing zone integration**: Out of scope per Constitution.
  `customerProvidedDns=true` is the seam that enables this in a future feature.

---

All Phase 0 unknowns are resolved. Spec contains zero `[NEEDS CLARIFICATION]`
markers. Proceed to Phase 1.
