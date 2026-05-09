# Implementation Plan: Private End-to-End RAG Accelerator

**Branch**: `001-private-rag-accelerator` | **Date**: 2026-05-08 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-private-rag-accelerator/spec.md`

## Summary

Build a single-subscription, network-isolated Azure RAG solution accelerator for SLED customers. **All** PaaS dependencies are reached exclusively via Private Endpoints with `publicNetworkAccess=Disabled`; service-to-service auth is managed-identity-only; the chat UI is a private-ingress Azure Container App.

**Technical approach**:

- **UI + API**: Two **Azure Container Apps** (Next.js 15 chat UI + FastAPI orchestrator) on a single internal-only Container Apps Environment with VNet integration and a private ingress.
- **Generation**: **Azure OpenAI `gpt-5` (chat)** + **`text-embedding-3-large` (embeddings)** behind a Private Endpoint. (`gpt-4o` is being deprecated in Azure; the GPT-5 family is the current default for net-new builds.)
- **Retrieval**: **Azure AI Search** (Standard) with **integrated vectorization**, **semantic ranker**, **hybrid (vector + BM25 + semantic) search**, and **scope filtering** (`shared` vs `user:<oid>`) for per-user isolation.
- **Document state + chat history**: **Azure Cosmos DB for NoSQL**, partitioned by `userId` for conversations and by `scope` for documents. Continuous backup, autoscale RU/s within demo budget.
- **Document storage**: **Azure Blob Storage** with two containers (`shared-corpus`, `user-uploads/{oid}/...`); SAS-less, RBAC-only access via managed identity.
- **Doc cracking**: **Azure AI Document Intelligence (prebuilt-layout)** for PDFs/images/Office; layout output drives integrated vectorization in AI Search.
- **Ingestion control plane**: **Azure Container Apps Jobs** (event-triggered for shared corpus via Event Grid → Storage Queue, manual/CLI for backfill) + a thin orchestrator endpoint for user uploads.
- **Auth**: **Microsoft Entra ID** OIDC at the UI; **managed identity** everywhere downstream. `easyauth`-style sidecar is not used (Container Apps' built-in auth is fine but we own the token in code for downstream OBO).
- **Identity-bound retention**: Cosmos TTL = 30 days, sliding on activity; soft-delete on user request triggers immediate purge job.
- **Network**: Single VNet, four subnets (ACA, private endpoints, jobs, bastion). Customer-supplied DNS or accelerator-provisioned Private DNS Zones (parameter switch).
- **Admin access**: **Azure Bastion** (Standard) for jumpbox-free admin in v1.
- **IaC**: **Bicep** with **Azure Verified Modules (AVM)** wherever they exist (network, key vault, storage, cosmos, search, openai, container apps, monitor); custom modules only for the accelerator-specific composition layer.
- **Deploy UX**: **`azd up`** wraps `az deployment sub create` (subscription-scope) → resource-group-scope main; pre-flight script validates region/SKU availability and quotas before apply. Repo ships a **`.devcontainer/`** + **GitHub Codespaces** config so customer engineers can go from `git clone` (or *Open in Codespaces*) to `azd up` with **zero local installs** — every CLI/SDK is pre-baked.
- **Observability**: Azure Monitor + Application Insights (workspace-based, Private Link Scope).

## Technical Context

**Language/Version**:

- Backend orchestrator: **Python 3.12** (FastAPI 0.115+, `azure-search-documents` 11.6+, `openai` 1.x with Azure provider, `azure-identity` 1.x).
- Ingestion job: **Python 3.12** (same SDK stack) — packaged separately for cold-start.
- Frontend: **TypeScript 5.5**, **Next.js 15** (App Router, RSC), **Tailwind CSS 4**, **shadcn/ui** components, **Vercel AI SDK 4** for streaming chat.
- IaC: **Bicep** (latest), **Azure Verified Modules** (br/public:avm/*), **azd** v1.13+.

**Primary Dependencies**:

- Azure OpenAI Service (gpt-5 chat, text-embedding-3-large)
- Azure AI Search Standard (S1) with integrated vectorization + semantic ranker
- Azure AI Document Intelligence (S0)
- Azure Cosmos DB for NoSQL (autoscale, continuous-7day backup)
- Azure Container Apps + Container Apps Jobs (Consumption + Dedicated as needed)
- Azure Container Registry (Premium, required for Private Link)
- Azure Storage (StorageV2, LRS for demo)
- Azure Key Vault (Standard) — only for customer-managed keys / opaque config; no app secrets
- Azure Monitor + Log Analytics + Application Insights with Private Link Scope (AMPLS)
- Azure Bastion Standard
- Microsoft Entra ID (OIDC for UI; managed identity for service-to-service)

**Storage**:

- Cosmos DB for NoSQL (two containers: `conversations` partitioned by `/userId`, `documents` partitioned by `/scope`)
- Blob Storage (two containers: `shared-corpus`, `user-uploads`)
- AI Search index `kb-index` (one index, scope filter for isolation; integrated vectorizer)

**Testing**:

- Backend: `pytest` + `pytest-asyncio` for unit; **integration tests** that hit deployed services via the bastion-side test runner (no public hops).
- Frontend: `vitest` + `@testing-library/react` for components; **Playwright** for E2E (run from inside-VNet build agent).
- IaC: `bicep build` (compile gate), `az deployment sub validate` + `az deployment sub what-if` in CI; `Pester` for ARM-template unit assertions where helpful.
- Security gates: `gitleaks` (no secrets in commits), custom `psrule-rules-azure` for "no public endpoint" assertions.

**Target Platform**:

- Azure (Public Cloud default; Gov/China are explicit opt-in parameter sets — out of scope for v1 implementation).
- Frontend: evergreen desktop browsers (Edge, Chrome, Safari, Firefox latest).
- Backend: Linux containers on amd64 (Container Apps).

**Project Type**: Web application (frontend + backend) deployed as containerized services with IaC. Plus an ingestion job worker.

**Performance Goals** (per spec SC):

- p95 chat response **< 6 s** (excluding model cold-start) on default SKUs (SC-007).
- Citation open **< 2 s** for typical demo docs (SC-008).
- Single-document ingestion (50-page PDF) end-to-end visible in index **< 2 minutes**.
- Concurrent chat throughput: **20 concurrent users** sustained on default SKUs without degradation (informs ACA min-replicas).

**Constraints**:

- **Zero public ingress** — UI only reachable from inside VNet / peered network / Bastion (FR-004).
- **Zero shared keys** at runtime (FR-003) — managed identity only; AOAI, Search, Cosmos, Storage, ACR, Document Intelligence all use RBAC, not keys.
- **Idempotent IaC** — `azd up` re-run produces zero diffs (FR-026, SC-002).
- **One-command deploy** in < 60 min wall-clock, < 15 min hands-on (SC-001).
- **Demo cost cap** — published in repo; default config targets ≤ ~$700/month idle (Standard SKUs for AI Search + Bastion are the floor).
- **Cross-user isolation** at retrieval time MUST hold in 100% of automated tests (SC-011).
- **Retention purge** within 24h of expiry / 1h of user delete (SC-012).

**Scale/Scope** (default demo profile):

- Up to **500 documents** in shared corpus, **~50,000 passages**.
- Up to **50 named users** with up to **20 conversations** each.
- Up to **10 user-uploaded documents per active conversation**, ≤ 50 MB each.
- Single region; opt-in zone-redundancy parameter for Cosmos and Storage (off by default for cost).

## Constitution Check

*GATE — must pass before Phase 0.*

| Principle | Compliance | Evidence |
|-----------|------------|----------|
| **I. Security-First / Zero Trust (NON-NEGOTIABLE)** | ✅ PASS | Every PaaS dep gets a Private Endpoint with `publicNetworkAccess=Disabled` (Storage, Cosmos, Search, AOAI, ACR, KV, Doc Intelligence, Monitor via AMPLS). Container Apps env is `internal=true` (no public IP). Auth = MSI everywhere; OIDC at UI only. Private DNS Zones provisioned + linked. Admin via Bastion. **No opt-out path** in default templates. |
| **II. Idempotent & Reproducible IaC (Bicep)** | ✅ PASS | 100% Bicep (AVM where available). `azd up` is the one-command path. CI runs `bicep build` + `what-if`. Teardown via `azd down --purge` (drains soft-delete on KV, AOAI). No portal steps on supported path. |
| **III. Documentation Parity** | ✅ PASS | Each module gets a README; ADRs in `specs/001-.../decisions/`; quickstart.md authored in Phase 1; Mermaid architecture diagram in `quickstart.md`. |
| **IV. Cost Discipline** | ⚠ ACCEPTED with documented deviation | AI Search Standard (S1) and Azure Bastion Standard are minimum SKUs that support Private Link / private-only access — cheaper tiers (Basic AI Search, Bastion Basic) would violate Principle I. **Documented in Complexity Tracking below.** Everything else is on cheapest viable tier. Estimated cost published in module READMEs. Teardown path = `azd down`. |
| **V. WAF Alignment** | ✅ PASS | Plan has explicit per-pillar trade-off section (see "WAF Trade-offs" below). Reliability features (zone redundancy, paired-region) are opt-in parameters, not removed. |

**Result**: PASS (with one accepted, documented deviation under Principle IV — see Complexity Tracking).

### WAF Trade-offs (per Constitution Principle V)

| Pillar | Default Posture | Rationale | Production Upgrade Path |
|--------|-----------------|-----------|-------------------------|
| **Security** | Maximum: zero public endpoints, MSI everywhere, CMK off by default | Constitution NON-NEGOTIABLE | Enable customer-managed keys via `customerManagedKey` parameter (Cosmos, Storage, AOAI). |
| **Reliability** | Single-region, single-zone defaults | Cost discipline (Principle IV) | `enableZoneRedundancy=true` flips Cosmos, Storage, Container Apps env, Bastion, AI Search to ZR. `pairedRegion` parameter enables Cosmos multi-region writes + AOAI fallback. |
| **Cost Optimization** | Cheapest SKUs that satisfy Principle I (S1 Search, Bastion Standard, ACA Consumption, Cosmos serverless **alternative** offered) | Demo / POC focus | `productionMode=true` swaps to S2 Search, ACA Dedicated workload profile, Cosmos provisioned autoscale 4000 RU/s. |
| **Operational Excellence** | App Insights via AMPLS, Container Apps logs to LAW, dashboards shipped | SE needs visibility during demo | Add `diagnosticSettings` per module (already done via AVM); customer can layer Defender for Cloud (out of scope). |
| **Performance Efficiency** | gpt-5 (current generation), embedding-3-large, integrated vectorization | Modern, current-gen models; deprecation-safe | `chatModel`/`embeddingModel` parameters allow swap. PTU (provisioned throughput) for AOAI is a parameter for production loads. |

## Project Structure

### Documentation (this feature)

```text
specs/001-private-rag-accelerator/
├── plan.md              # This file
├── research.md          # Phase 0 — decisions + rationale
├── data-model.md        # Phase 1 — entities, schemas, partitioning
├── quickstart.md        # Phase 1 — SE-facing one-command deploy guide
├── contracts/           # Phase 1 — interface contracts
│   ├── api-openapi.yaml         # Backend HTTP API
│   ├── search-index.json        # AI Search index schema
│   ├── cosmos-conversations.json# Cosmos `conversations` container schema
│   ├── cosmos-documents.json    # Cosmos `documents` container schema
│   └── ingestion-event.schema.json # CloudEvents schema for blob → ingestion
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 — created by /speckit.tasks
```

### Source Code (repository root)

```text
infra/                              # Bicep IaC (entry point for azd)
├── main.bicep                      # Subscription-scope orchestrator
├── main.parameters.json
├── modules/
│   ├── network/                    # VNet, subnets, NSGs, Private DNS zones
│   ├── identity/                   # User-assigned MIs + role assignments
│   ├── monitoring/                 # LAW, App Insights, AMPLS
│   ├── storage/                    # Storage account, containers, PE
│   ├── cosmos/                     # Cosmos NoSQL, containers, PE
│   ├── search/                     # AI Search S1, PE, shared private link to AOAI/Storage
│   ├── openai/                     # AOAI account, gpt-5 + embedding deployments, PE
│   ├── docintel/                   # Document Intelligence, PE
│   ├── keyvault/                   # KV, PE (CMK only)
│   ├── registry/                   # ACR Premium, PE
│   ├── containerapps/              # ACA env (internal), apps, jobs
│   └── bastion/                    # Bastion Standard, host
└── README.md

apps/
├── api/                            # FastAPI orchestrator
│   ├── src/
│   │   ├── main.py
│   │   ├── routers/
│   │   │   ├── chat.py             # POST /chat (SSE stream)
│   │   │   ├── conversations.py    # CRUD on per-user history
│   │   │   ├── uploads.py          # POST /uploads (per-session docs)
│   │   │   └── admin.py            # GET /admin/stats, /admin/runs
│   │   ├── services/
│   │   │   ├── search.py           # AI Search client (hybrid + semantic + scope filter)
│   │   │   ├── llm.py              # Azure OpenAI (gpt-5) wrapper
│   │   │   ├── docintel.py         # Document Intelligence wrapper
│   │   │   ├── cosmos.py           # Cosmos repos (conversations, documents)
│   │   │   ├── storage.py          # Blob client (MSI)
│   │   │   └── auth.py             # JWT validation, OBO helpers
│   │   ├── models/                 # Pydantic DTOs (mirrors contracts/)
│   │   └── config.py               # Pydantic settings (env-only, no secrets)
│   ├── tests/
│   │   ├── unit/
│   │   ├── integration/            # Hit deployed env from inside VNet
│   │   └── isolation/              # SC-011 cross-user isolation harness
│   ├── Dockerfile
│   └── pyproject.toml
├── ingest/                         # Container Apps Job
│   ├── src/
│   │   ├── main.py                 # Reads queue, runs Doc Intelligence, indexes
│   │   ├── pipeline.py             # Crack → chunk → embed (via integrated vec) → upsert
│   │   └── handlers/
│   │       ├── shared.py           # Event Grid → blob added/changed/deleted
│   │       └── user.py             # Direct invocation from /uploads
│   ├── tests/
│   ├── Dockerfile
│   └── pyproject.toml
└── web/                            # Next.js 15 chat UI
    ├── src/
    │   ├── app/                    # App Router
    │   │   ├── (auth)/             # Entra OIDC sign-in
    │   │   ├── chat/[id]/page.tsx  # Chat surface (SSR + streaming)
    │   │   ├── chat/page.tsx       # New conversation
    │   │   ├── citations/[docId]/page.tsx
    │   │   └── admin/page.tsx
    │   ├── components/
    │   │   ├── chat/               # ChatPane, MessageBubble, CitationChip
    │   │   ├── upload/             # SessionUpload (drag-drop)
    │   │   └── ui/                 # shadcn primitives
    │   ├── lib/
    │   │   ├── auth.ts             # NextAuth/Entra adapter
    │   │   └── api.ts              # Typed client over OpenAPI contract
    │   └── styles/
    ├── tests/
    ├── playwright/
    ├── Dockerfile
    └── package.json

azure.yaml                          # azd config (services + hooks)
.devcontainer/                      # Zero-install onboarding (Codespaces + local VS Code)
├── devcontainer.json               # Pre-installs azd, az, bicep, node 22, python 3.12, docker, gh, pwsh
└── post-create.sh                  # Sets up pre-commit hooks, az/azd login prompts
.github/
└── workflows/
    ├── ci.yml                      # bicep build, what-if (PR), lint/test apps
    ├── deploy.yml                  # azd provision/deploy via OIDC federated creds (no secrets)
    └── teardown.yml                # manual: azd down --purge
.azdo/                              # (optional) pipelines for in-VNet build/test agents
docs/
├── architecture.md                 # High-level overview + Mermaid
├── security-posture.md             # SC-010 verification checklist
├── cost.md                         # Default + production cost estimates
└── decisions/                      # ADRs
    ├── 0001-aca-over-app-service.md
    ├── 0002-cosmos-nosql-over-postgres.md
    ├── 0003-gpt5-over-gpt4o.md
    ├── 0004-integrated-vectorization.md
    ├── 0005-single-search-index-with-scope-filter.md
    ├── 0006-bastion-over-jumpbox.md
    └── 0007-avm-where-possible.md
```

**Structure Decision**: Web application (frontend + backend) — **three** containerized apps (`web`, `api`, `ingest`) + one IaC tree. The `apps/` and `infra/` split is mandated by `azd`'s service convention. The `ingest` worker is split from `api` so its scale-to-zero behavior and longer cold-starts don't affect chat latency.

### Repo-to-Deploy Ergonomics (SC-001)

Three supported on-ramps, ranked by friction:

1. **GitHub Codespaces** (lowest friction, recommended for first run): customer clicks *Code → Codespaces → Create*; devcontainer boots with `azd`/`az`/`bicep`/`node`/`python`/`docker`/`gh`/`pwsh` pre-installed. They run `az login --use-device-code`, `azd auth login --use-device-code`, then `azd up`. Zero local installs.
2. **Local VS Code + Dev Containers extension**: identical experience, runs in Docker on their box. Same commands.
3. **Bare local shell**: install the tools in §1 of [`quickstart.md`](./quickstart.md), then `azd up`.

All three converge on the **same `azd up` command** — there is no "second path" to maintain. The `postprovision` hook seeds five sample documents so the SE/customer can ask their first grounded question without manually uploading anything (SC-001 hands-on time).

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| **AI Search Standard (S1)** as floor SKU vs Basic | Basic tier does NOT support Private Endpoint — direct conflict with Principle I | Cannot satisfy "no public endpoints" with Basic. S1 is the cheapest SKU that supports PE + integrated vectorization + semantic ranker. |
| **Bastion Standard** vs Bastion Basic / no Bastion | Bastion Basic does not support shareable links / native client / IP-based connection needed for the SE demo loop; "no Bastion" forces customers to stand up jumpboxes (operational excellence regression) | Documented in `docs/cost.md` as the largest single line item; production customers will likely already have shared Bastion / VPN, in which case `deployBastion=false` parameter skips it entirely. |
| **Three container images** (`web`, `api`, `ingest`) instead of one monolith | Independent scale (chat is bursty / latency-sensitive; ingest is batch / CPU-heavy / scale-to-zero); independent deploy; isolation of model client surface area | A single image would couple chat tail latency to ingestion CPU spikes and force the UI to ship Python deps. |
| **Cosmos NoSQL** vs Azure SQL / PostgreSQL Flex | Native partitioning by `userId`, native TTL for FR-030 30-day retention, native private endpoint, well-priced serverless option | SQL/Postgres would require a custom sweeper job for TTL and weaker fit for document-shaped chat history. Recorded as ADR-0002. |
