---
description: "Dependency-ordered task list for the Private End-to-End RAG Accelerator"
---

# Tasks: Private End-to-End RAG Accelerator

**Input**: Design documents from `/specs/001-private-rag-accelerator/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Tests are INCLUDED in the task list because the spec defines hard, automated, measurable success criteria that cannot be hand-verified — specifically SC-002 (idempotent IaC), SC-004 (zero public endpoints), SC-006 (≥85% grounded-answer rate / ≥90% decline rate), SC-011 (cross-user isolation 100%), and SC-012 (retention purge SLAs). The constitution's NON-NEGOTIABLE security pillar (Principle I) also demands automated assertions against the deployed network posture.

**Organization**: Tasks are grouped by user story so each story is independently implementable, testable, and deployable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Maps task to a user story (US1–US6) for traceability
- All file paths are relative to the repository root unless noted otherwise

## Path Conventions

Per [plan.md](./plan.md) "Project Structure":

- IaC: `infra/` (Bicep, AVM-based)
- Apps: `apps/api/` (FastAPI), `apps/ingest/` (ACA Job), `apps/web/` (Next.js 15)
- Tests: per-app under `apps/<name>/tests/{unit,integration,isolation}` and `apps/web/playwright/`
- Docs: `docs/`, `docs/decisions/`
- Devloop: `.devcontainer/`, `.github/workflows/`, `azure.yaml`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Repository scaffolding, dev-loop ergonomics, and shared tooling that everything else depends on. No Azure resources created here.

- [ ] T001 Create the directory skeleton from [plan.md](./plan.md) §"Source Code (repository root)": `infra/{,modules/{network,identity,monitoring,storage,cosmos,search,openai,docintel,keyvault,registry,containerapps,bastion}}`, `apps/{api,ingest,web}/`, `docs/{decisions/}`, `.devcontainer/`, `.github/workflows/`, `scripts/`
- [ ] T002 [P] Create `azure.yaml` at the repository root declaring three azd services (`web`, `api`, `ingest`) with their Dockerfile paths, project paths, and `host: containerapp` per [plan.md](./plan.md)
- [ ] T003 [P] Create `.devcontainer/devcontainer.json` and `.devcontainer/post-create.sh` pre-installing `azd` 1.13+, `az` 2.65+, `bicep` 0.30+, Node 22, Python 3.12, Docker, `gh`, `pwsh` per [quickstart.md](./quickstart.md) §1
- [ ] T004 [P] Create `apps/api/pyproject.toml` (FastAPI 0.115+, `azure-search-documents` 11.6+, `openai` 1.x, `azure-identity` 1.x, `azure-cosmos` 4.x, `azure-storage-blob` 12.x, `azure-ai-documentintelligence` 1.x, `pytest`, `pytest-asyncio`, `ruff`, `mypy`)
- [ ] T005 [P] Create `apps/ingest/pyproject.toml` with the same SDK stack as `apps/api/` (split for independent cold-start per [plan.md](./plan.md))
- [ ] T006 [P] Create `apps/web/package.json` (Next.js 15, TypeScript 5.5, Tailwind CSS 4, shadcn/ui, Vercel AI SDK 4, NextAuth/Auth.js with Microsoft Entra provider, Vitest, Playwright, ESLint, Prettier)
- [ ] T007 [P] Create `apps/api/Dockerfile` (Python 3.12-slim, multi-stage, non-root user, healthcheck on `/healthz`)
- [ ] T008 [P] Create `apps/ingest/Dockerfile` (Python 3.12-slim, multi-stage, non-root user, no exposed port — Job)
- [ ] T009 [P] Create `apps/web/Dockerfile` (Node 22-alpine, multi-stage, `output: 'standalone'` per [research.md](./research.md) D7)
- [ ] T010 [P] Configure linting/formatting: `ruff.toml` and `mypy.ini` at repo root for Python; `apps/web/.eslintrc.cjs` and `apps/web/.prettierrc` for TS
- [ ] T011 [P] Create `.github/workflows/ci.yml` running `bicep build`, `az deployment sub validate`, `az deployment sub what-if`, `ruff`, `mypy`, `pytest -m "not integration"`, `pnpm lint`, `pnpm test`, and `gitleaks` on every PR
- [ ] T012 [P] Create `.github/workflows/deploy.yml` running `azd provision` + `azd deploy` via OIDC federated credentials (no secrets) per [plan.md](./plan.md)
- [ ] T013 [P] Create `.github/workflows/teardown.yml` (manual dispatch) running `azd down --purge`
- [ ] T014 [P] Create `scripts/preflight.ps1` validating CLI versions, region availability for `gpt-5` + `text-embedding-3-large` + AI Search S1, AOAI/Search/ACA quota, and caller RBAC at subscription scope per [quickstart.md](./quickstart.md) §4

**Checkpoint**: Repo skeleton, dev container, CI/CD workflows, and pre-flight gate exist. Engineers can clone, open the devcontainer, and the lint/test pipelines run green on an empty codebase.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Network, identity, monitoring, and the shared infrastructure layer. Nothing in any user story can run on Azure without this. **No app code lives in this phase** — this is the IaC + cross-cutting backbone that every user story binds against.

**⚠️ CRITICAL**: User-story phases (3+) MUST NOT begin until this phase is complete and `azd up` produces a green, idempotent deployment of the foundation.

### IaC backbone

- [ ] T015 Create `infra/main.bicep` as a subscription-scope orchestrator that creates the resource group and invokes resource-group-scope modules (per [research.md](./research.md) D10)
- [ ] T016 Create `infra/main.parameters.json` with parameters: `namingPrefix`, `location`, `adminGroupObjectId`, `allowedUserGroupObjectIds`, `deployBastion`, `customerProvidedDns`, `enableZoneRedundancy`, `enableCustomerManagedKey`, `chatModel`, `embeddingModel`, `aiSearchSku`, `cosmosAutoscaleMaxRu`, `budgetMonthlyUsd`
- [ ] T017 [P] Create `infra/modules/network/main.bicep` provisioning a `/22` VNet with four subnets `snet-aca`, `snet-pe`, `snet-jobs`, `AzureBastionSubnet` (`/26`), NSGs, and all Private DNS Zones from [research.md](./research.md) D9 (privatelink.openai.azure.com, .search.windows.net, .documents.azure.com, .blob.core.windows.net, .vaultcore.azure.net, .azurecr.io, .cognitiveservices.azure.com, .monitor.azure.com + AMPLS bundle); honor `customerProvidedDns` switch
- [ ] T018 [P] Create `infra/modules/identity/main.bicep` provisioning user-assigned MIs `mi-api`, `mi-ingest`, `mi-web` (one per app) — bare identities only; role assignments are emitted by each resource module after T019–T026 land
- [ ] T019 [P] Create `infra/modules/monitoring/main.bicep` provisioning Log Analytics workspace, workspace-based App Insights, **Azure Monitor Private Link Scope (AMPLS)** with private endpoint and zone group, and a Budget alert at 80%/100% of `budgetMonthlyUsd` per [research.md](./research.md) D11 / D13
- [ ] T020 [P] Create `infra/modules/registry/main.bicep` provisioning ACR Premium with `publicNetworkAccess=Disabled`, Private Endpoint in `snet-pe`, zone group, and `AcrPull` to all three app MIs
- [ ] T021 [P] Create `infra/modules/keyvault/main.bicep` provisioning Key Vault Standard with `publicNetworkAccess=Disabled`, RBAC authorization, soft-delete + purge protection, Private Endpoint
- [ ] T022 [P] Create `infra/modules/storage/main.bicep` provisioning a StorageV2 account with `publicNetworkAccess=Disabled`, two containers `shared-corpus` + `user-uploads`, Blob Private Endpoint, soft-delete on, lifecycle policy that deletes blobs in `user-uploads` older than 30 days, Event Grid system topic on `Microsoft.Storage.BlobCreated`/`BlobDeleted` for `shared-corpus` only, and a Storage Queue subscription per [data-model.md](./data-model.md) §6
- [ ] T023 [P] Create `infra/modules/cosmos/main.bicep` provisioning a Cosmos DB for NoSQL account with `publicNetworkAccess=Disabled`, Private Endpoint, continuous-7-day backup, autoscale RU/s with max = `cosmosAutoscaleMaxRu`, and three containers per [data-model.md](./data-model.md) §1: `conversations` (PK `/userId`, default TTL 2592000), `documents` (PK `/scope`, per-doc `ttl` field), `ingestion-runs` (PK `/scope`, default TTL 7776000)
- [ ] T024 [P] Create `infra/modules/search/main.bicep` provisioning AI Search **Standard (S1)** with semantic ranker enabled, `publicNetworkAccess=Disabled`, Private Endpoint, and **shared private link resources** to AOAI + Storage so the integrated vectorization skillset can call AOAI privately, per [research.md](./research.md) D3
- [ ] T025 [P] Create `infra/modules/openai/main.bicep` provisioning Azure OpenAI account with `publicNetworkAccess=Disabled`, Private Endpoint, and two model deployments — `gpt-5` (chat) and `text-embedding-3-large` (3072 dims) — per [research.md](./research.md) D2
- [ ] T026 [P] Create `infra/modules/docintel/main.bicep` provisioning Document Intelligence (Cognitive Services kind=`FormRecognizer`) with `publicNetworkAccess=Disabled` and Private Endpoint per [research.md](./research.md) D4
- [ ] T027 Create `infra/modules/containerapps/main.bicep` provisioning a Container Apps Environment with `vnetConfiguration.internal=true` (no public ingress), workload profile = Consumption, infrastructure subnet = `snet-aca`, Log Analytics linkage; declares the three apps (`web`, `api`) and one Job (`ingest`) bound to their MIs and ACR — image tags are placeholders set by `azd deploy`. Depends on T017–T020.
- [ ] T028 [P] Create `infra/modules/bastion/main.bicep` provisioning Bastion Standard host on `AzureBastionSubnet` plus a Linux jumpbox VM (per [quickstart.md](./quickstart.md) §6a); gated by `deployBastion` parameter
- [ ] T029 In each Cosmos / Search / AOAI / Storage / Doc Intelligence / Key Vault / ACR module, emit role assignments to the three app MIs from `infra/modules/identity/`: `Cosmos DB Built-in Data Contributor` (api, ingest), `Search Index Data Contributor` (ingest) / `Search Index Data Reader` (api), `Cognitive Services OpenAI User` (api, ingest), `Storage Blob Data Contributor` (ingest) / `Storage Blob Data Reader` (api), `Cognitive Services User` for Doc Intelligence (api, ingest), `AcrPull` already in T020 — per [research.md](./research.md) D8 / FR-003
- [ ] T030 Wire `infra/main.bicep` to invoke modules in dependency order: network → identity → monitoring → registry/keyvault → storage/cosmos/search/openai/docintel → containerapps → bastion; outputs include resource IDs, internal FQDNs, and the printed UI URL
- [ ] T031 Run `mcp_bicep_get_bicep_best_practices` and `mcp_bicep_list_avm_metadata`; refactor every module from T017–T028 to use AVM (`br/public:avm/*`) wherever an AVM exists at usable maturity; only the composition layer in `main.bicep` and accelerator-specific glue (e.g., AMPLS bundle, scope-RBAC fan-out) remain hand-rolled — per [plan.md](./plan.md) and [research.md](./research.md) D10
- [ ] T032 [P] Author `infra/README.md` documenting every module, its parameters, its emitted outputs, and the AVM version pinned
- [ ] T032a [P] Create `infra/modules/apim/main.bicep` provisioning Azure API Management Developer SKU with `virtualNetworkType: 'Internal'` (full VNet injection in `snet-apim`), system-assigned MI, NSG with required APIM management plane rules, TLS 1.0/1.1 disabled, and Application Insights diagnostic logging — per architecture decision 2026-05-08 (APIM-as-AI-gateway, SKU locked at Developer per $500/mo cost ceiling)

### Cross-cutting app foundations

- [ ] T033 [P] Create `apps/api/src/config.py` (Pydantic Settings; env-only; **no secrets**) loading: `AZURE_TENANT_ID`, `AZURE_CLIENT_ID` (for MI), `COSMOS_ACCOUNT_ENDPOINT`, `SEARCH_ENDPOINT`, `SEARCH_INDEX_NAME=kb-index`, `AOAI_ENDPOINT`, `AOAI_CHAT_DEPLOYMENT`, `AOAI_EMBEDDING_DEPLOYMENT`, `STORAGE_ACCOUNT_NAME`, `DOCINTEL_ENDPOINT`, `ADMIN_GROUP_OBJECT_ID`, `ALLOWED_USER_GROUP_OBJECT_IDS`, `MAX_UPLOAD_BYTES=52428800`, `CONVO_CAP_BYTES=262144000`
- [ ] T034 [P] Create `apps/api/src/main.py` minimal FastAPI app with App Insights OpenTelemetry distro, structured JSON logger that **redacts** `content` of user/assistant turns from long-lived telemetry per spec edge case "PII in chat", request-id correlation middleware, and global error handler returning the `Error` schema from [api-openapi.yaml](./contracts/api-openapi.yaml)
- [ ] T035 [P] Create `apps/api/src/services/auth.py`: validate Entra ID JWTs against tenant JWKS (cached), expose a `CurrentUser` dependency that yields `{oid, displayName, role, groups}` where `role=admin` iff `ADMIN_GROUP_OBJECT_ID` ∈ groups, else `user`; reject if `ALLOWED_USER_GROUP_OBJECT_IDS` is set and the caller is in none of them — per [research.md](./research.md) D8
- [ ] T036 [P] Create `apps/api/src/routers/health.py` exposing `GET /healthz` (unauth) per [api-openapi.yaml](./contracts/api-openapi.yaml) `/healthz` and `GET /me` returning the current user
- [ ] T037 [P] Create `apps/api/src/services/cosmos.py` exposing `CosmosClient` factory bound to the API MI (DefaultAzureCredential, AAD-RBAC), and base repos `ConversationsRepo`, `DocumentsRepo`, `IngestionRunsRepo` bound to containers from [data-model.md](./data-model.md)
- [ ] T038 [P] Create `apps/api/src/services/storage.py` exposing a `BlobServiceClient` factory bound to MI; helper `assert_blob_in_owned_account(blobUri)` per [data-model.md](./data-model.md) §3 invariant
- [ ] T039 [P] Create `apps/api/src/services/search.py` exposing a thin wrapper around `azure.search.documents.aio.SearchClient` that **MUST raise** if any caller invokes `.search(...)` without a `filter` containing `scope eq 'shared'` or `scope eq 'user:<oid>'` — enforces [data-model.md](./data-model.md) §5 mandatory filter (the SC-011 isolation guarantee)
- [ ] T040 [P] Create `apps/api/src/services/llm.py` wrapping Azure OpenAI chat (`gpt-5` per `AOAI_CHAT_DEPLOYMENT`) and embedding (`text-embedding-3-large`) via the `openai` SDK with `azure_ad_token_provider` from `azure.identity`
- [ ] T041 [P] Create `apps/api/src/services/docintel.py` wrapping `azure.ai.documentintelligence.DocumentIntelligenceClient` (MI-bound) for `prebuilt-layout` analysis returning markdown + tables per [research.md](./research.md) D4
- [ ] T042 [P] Create `apps/api/src/models/` Pydantic DTOs that 1:1 mirror the schemas in [api-openapi.yaml](./contracts/api-openapi.yaml): `Conversation`, `ConversationSummary`, `Turn`, `Citation`, `DocumentMeta`, `ChatRequest`, `AdminStats`, `Error`
- [ ] T043 [P] Create `apps/web/src/lib/auth.ts` configuring NextAuth/Auth.js with the Microsoft Entra provider (tenant-scoped, group-restricted via `ALLOWED_USER_GROUP_OBJECT_IDS`); Edge-runtime safe per [research.md](./research.md) D7 / D8
- [ ] T044 [P] Create `apps/web/src/lib/api.ts` typed client over [api-openapi.yaml](./contracts/api-openapi.yaml) (use `openapi-typescript` to generate types) that automatically attaches the user's bearer token to every backend call
- [ ] T045 [P] Create the AI Search index definition file at `infra/search/kb-index.json` (committed copy of [contracts/search-index.json](./contracts/search-index.json)) that the ingest worker uses to create/update the index on first run; include the `kb-semantic` semantic configuration and `kb-hnsw` vector profile from [data-model.md](./data-model.md) §5
- [ ] T046 Create `apps/api/tests/conftest.py` and `apps/ingest/tests/conftest.py` with shared fixtures: synthetic Entra JWTs (signed with a test JWKS), in-VNet integration-test markers, and a `cosmos_emulator` fixture for unit tests (deployed-env tests use real Cosmos via in-VNet runner per [plan.md](./plan.md) Testing)
- [ ] T047 [P] Add `azure.yaml` `postprovision` hook script `scripts/postprovision.ps1` that: (1) creates `kb-index` from `infra/search/kb-index.json` if missing, (2) seeds five sample documents from `samples/` into the `shared-corpus` blob container, (3) prints the UI URL — per [quickstart.md](./quickstart.md) §5

**Checkpoint**: `azd up` provisions the **full** private foundation idempotently with zero public endpoints. `apps/api` boots, `/healthz` and `/me` work via Bastion. The Search index is created and seeded. **No business logic exists yet.**

---

## Phase 3: User Story 3 — Solution Engineer deploys the accelerator (Priority: P1) 🎯 MVP

**Goal**: A first-time SE can take an empty resource group to a working, **private-only** environment via a documented one-command path. This story is sequenced first inside the P1 set because US1 and US2 both require a deployed environment to be testable end-to-end.

**Independent Test**: From an empty resource group, run the documented `azd up`. Within the documented time window (< 60 min wall-clock, < 15 min hands-on per SC-001) the deployment succeeds, prints the chat UI URL, and a re-run produces zero diffs (SC-002). `azd down --purge` removes 100% of resources (SC-003). External connection attempts to every PaaS endpoint fail (SC-004).

### Tests for User Story 3

- [ ] T048 [P] [US3] `infra/tests/test_compile.ps1` — Pester test that runs `bicep build infra/main.bicep` and asserts zero errors / zero warnings on every supported parameter combination (default, `enableZoneRedundancy=true`, `deployBastion=false`, `customerProvidedDns=true`)
- [ ] T049 [P] [US3] `infra/tests/test_what_if_idempotent.ps1` — Pester test that runs `azd provision` twice in CI against an ephemeral resource group; second run MUST report 0 changes (SC-002)
- [ ] T050 [P] [US3] `infra/tests/test_no_public_endpoints.ps1` — Pester + `psrule-rules-azure` test that asserts every Microsoft.Storage/Cosmos/Search/CognitiveServices/KeyVault/ContainerRegistry/App resource in the compiled ARM has `publicNetworkAccess=Disabled` (or equivalent) — covers FR-002 / SC-004
- [ ] T051 [P] [US3] `infra/tests/test_no_shared_keys.ps1` — Pester test that greps the compiled ARM for `listKeys`, `connectionString`, `accountKey`, `primaryKey`; MUST be zero matches outside of explicitly-excluded AMPLS ingestion-key references — covers FR-003
- [ ] T052 [P] [US3] `infra/tests/test_dns_zones.ps1` — assert that a Private DNS Zone is provisioned and VNet-linked for every Private Endpoint declared in the template (FR-005)
- [ ] T053 [P] [US3] `infra/tests/test_teardown.ps1` — CI test that runs `azd up` then `azd down --purge` and asserts `az resource list -g <rg>` returns `[]` (SC-003)
- [ ] T054 [P] [US3] `apps/api/tests/integration/test_healthz_internal_only.py` — from an in-VNet runner asserts `GET /healthz` succeeds; from an out-of-VNet runner asserts the same hostname is unreachable (FR-004)

### Implementation for User Story 3

- [ ] T055 [US3] Wire the `azd up` end-to-end path: `azure.yaml` orchestrates `infra/main.bicep` → image build/push to private ACR via in-VNet build context → ACA `web`/`api`/`ingest` revision deploys → `postprovision` hook (T047). Verify on a clean subscription that T048–T054 all pass.
- [ ] T056 [US3] Add the pre-flight gate: `azure.yaml` `preprovision` hook invokes `scripts/preflight.ps1` (T014); a failure here aborts `azd up` with an actionable message
- [ ] T057 [US3] Author `docs/cost.md` with default-deployment estimated steady-state cost (≤ ~$700/mo idle target, broken down per resource family) and the production-mode cost delta — required by SC-009 / FR-028
- [ ] T058 [P] [US3] Author ADRs: `docs/decisions/0001-aca-over-app-service.md`, `0002-cosmos-nosql-over-postgres.md`, `0003-gpt5-over-gpt4o.md`, `0004-integrated-vectorization.md`, `0005-single-search-index-with-scope-filter.md`, `0006-bastion-over-jumpbox.md`, `0007-avm-where-possible.md` — per [plan.md](./plan.md)
- [ ] T059 [P] [US3] Author `docs/architecture.md` with the high-level Mermaid diagram from [quickstart.md](./quickstart.md) §9 plus a deeper request flow + ingest flow

**Checkpoint US3**: Empty subscription → working private environment via `azd up`; tests T048–T054 green; teardown clean. **MVP infrastructure delivered**; US1 and US2 can now be implemented and demonstrated against a real environment.

---

## Phase 4: User Story 2 — Administrator ingests a mixed-format document corpus (Priority: P1)

**Goal**: An admin (or SE) drops PDFs (text + scanned), TXT, DOCX, and image files into the `shared-corpus` blob container; the accelerator extracts text + visual content, generates embeddings, and makes everything searchable — with no code or manual tool invocations. This story is sequenced before US1 because US1 cannot return grounded answers against an empty index.

**Independent Test**: With the deployed environment from US3, drop a folder containing ≥1 PDF (with embedded scanned page), ≥1 TXT, ≥1 DOCX, and ≥1 PNG/JPG with text into `shared-corpus`. Within the documented window (< 2 min single doc / < 1 ingestion cycle for batch per FR-012, SC-005), all files become discoverable in `kb-index`, `documents` Cosmos entries show `ingestion.status=indexed`, and a corrupt sample file is recorded as `skipped` with a clear `errorReason`.

### Tests for User Story 2

- [ ] T060 [P] [US2] `apps/ingest/tests/integration/test_event_grid_blob_added.py` — drop a sample PDF into `shared-corpus`, assert that within N seconds the Storage Queue receives a CloudEvent matching [contracts/ingestion-event.schema.json](./contracts/ingestion-event.schema.json) and the ingest Job is invoked (FR-012)
- [ ] T061 [P] [US2] `apps/ingest/tests/integration/test_pdf_text_and_scanned.py` — ingest a PDF containing both a text layer and an embedded scanned page; assert both pages produce `kb-index` passages and the OCR'd text is searchable (FR-009 / FR-010 / acceptance scenario US2.2)
- [ ] T062 [P] [US2] `apps/ingest/tests/integration/test_image_with_text.py` — ingest a PNG screenshot of a form; assert extracted text is searchable AND the original image is retrievable through `/citations/{documentId}` (acceptance scenario US2.3)
- [ ] T063 [P] [US2] `apps/ingest/tests/integration/test_unsupported_mime_skipped.py` — drop a `.zip`; assert `Document.ingestion.status=skipped`, `errorReason="unsupported-mime"`, and the rest of the batch completes (acceptance scenario US2.5)
- [ ] T064 [P] [US2] `apps/ingest/tests/integration/test_blob_deleted_purges_index.py` — delete a blob from `shared-corpus`; assert the matching `kb-index` passages are removed within one ingestion cycle (acceptance scenario US2.4)
- [ ] T065 [P] [US2] `apps/api/tests/integration/test_admin_runs_visible.py` — call `GET /admin/runs` as an admin user; assert the most recent run from T060 is present with per-document outcomes matching [data-model.md](./data-model.md) §4 (FR-013)

### Implementation for User Story 2

- [ ] T066 [US2] Create `apps/ingest/src/main.py` Container Apps Job entrypoint: read one CloudEvent (per [contracts/ingestion-event.schema.json](./contracts/ingestion-event.schema.json)) from the Storage Queue, dispatch to `handlers/shared.py` for `BlobCreated`/`BlobDeleted`/`BlobChanged`, write start/complete records to `ingestion-runs` per [data-model.md](./data-model.md) §4
- [ ] T067 [P] [US2] Create `apps/ingest/src/pipeline.py` implementing the crack→chunk→embed→upsert pipeline: (1) Document Intelligence `prebuilt-layout` → markdown, (2) push pre-chunked text into the AI Search skillset (which runs the AzureOpenAIEmbedding skill via the shared private link), (3) upsert per-passage docs to `kb-index` with fields from [data-model.md](./data-model.md) §5 (`scope="shared"`, `userOid=null`, `conversationId=null`), (4) update `Document.ingestion.status` transitions per [data-model.md](./data-model.md) §7
- [ ] T068 [P] [US2] Create `apps/ingest/src/handlers/shared.py` for `BlobCreated`/`BlobChanged`/`BlobDeleted` events on `shared-corpus` — for delete events, issue a delete-by-filter against `kb-index` (`documentId eq '<id>'`) and remove the Cosmos `documents` row
- [ ] T069 [P] [US2] Add MIME-allowlist + size-cap enforcement in `pipeline.py` per [data-model.md](./data-model.md) §8: PDF, TXT, DOCX, XLSX, PPTX, PNG, JPEG, TIFF; oversize / unsupported → `Document.ingestion.status=skipped` with `errorReason` from the controlled vocabulary
- [ ] T070 [P] [US2] Create `apps/api/src/routers/admin.py` implementing `GET /admin/stats`, `GET /admin/runs`, `POST /admin/reindex` per [api-openapi.yaml](./contracts/api-openapi.yaml); admin role enforced by the `CurrentUser` dependency from T035; `POST /admin/reindex` enqueues a manual ingestion run with `trigger="manual"` per [data-model.md](./data-model.md) §4
- [ ] T071 [US2] Create `samples/` folder with five demo documents (1 multi-page PDF including a scanned page, 1 TXT, 1 DOCX, 1 PNG with text, 1 JPG) and wire them into the `postprovision` hook from T047 — required for SC-001 hands-on time

**Checkpoint US2**: Mixed-format corpus is ingestible end-to-end; admin dashboard surfaces per-document outcomes; tests T060–T065 green. The corpus exists for US1 to retrieve against.

---

## Phase 5: User Story 1 — End user asks questions and gets grounded answers with citations (Priority: P1)

**Goal**: An authenticated end user asks a natural-language question through the private chat UI and receives a streamed, grounded answer with citations; follow-ups respect conversation context; out-of-corpus questions trigger an explicit "I don't have that information" decline; **no traffic ever leaves the VNet**.

**Independent Test**: With the seeded shared corpus from US2, a signed-in user asks a question whose answer is in the corpus; the assistant streams a correct answer with ≥1 citation. A follow-up referencing a prior turn is answered coherently. An out-of-corpus question is declined explicitly. Packet capture from the in-VNet runner shows zero traffic to public endpoints.

### Tests for User Story 1

- [ ] T072 [P] [US1] `apps/api/tests/contract/test_openapi_chat.py` — schema-validate `POST /chat` request/response and SSE event shapes against [api-openapi.yaml](./contracts/api-openapi.yaml) (events `delta` / `citations` / `done` / `error`)
- [ ] T073 [P] [US1] `apps/api/tests/contract/test_openapi_conversations.py` — schema-validate `GET/POST /conversations`, `GET/DELETE /conversations/{id}` against [api-openapi.yaml](./contracts/api-openapi.yaml)
- [ ] T074 [P] [US1] `apps/api/tests/contract/test_openapi_citations.py` — schema-validate `GET /citations/{documentId}?page=N` returning the document binary
- [ ] T075 [P] [US1] `apps/api/tests/integration/test_chat_grounded_answer.py` — ask a question whose answer is in the seeded corpus; assert the response contains the expected fact AND ≥1 `Citation` with `scope="shared"` (acceptance scenario US1.1, FR-016)
- [ ] T076 [P] [US1] `apps/api/tests/integration/test_chat_followup_context.py` — multi-turn: ask Q1, then a context-dependent Q2 ("and what about for minors?"); assert the assistant uses prior turn context (acceptance scenario US1.2, FR-018)
- [ ] T077 [P] [US1] `apps/api/tests/integration/test_chat_decline_out_of_corpus.py` — ask a question whose answer is NOT in the corpus; assert the response includes a documented "I don't have that information" phrase and contains zero citations (acceptance scenario US1.3, FR-017)
- [ ] T078 [P] [US1] `apps/api/tests/integration/test_chat_quality_benchmark.py` — run the curated SC-006 benchmark question set; assert ≥85% of in-corpus questions return a correct citation AND ≥90% of out-of-corpus questions are declined
- [ ] T079 [P] [US1] `apps/api/tests/integration/test_chat_p95_latency.py` — fire 100 synthetic chat requests against warmed deployments; assert p95 end-to-end < 6s (SC-007)
- [ ] T080 [P] [US1] `apps/api/tests/integration/test_no_public_traffic.py` — run a chat turn while a packet sniffer on the in-VNet runner watches; assert zero packets to non-RFC1918 destinations except the deployed VNet's own ranges (acceptance scenario US1.4, FR-001)
- [ ] T081 [P] [US1] `apps/web/playwright/chat.spec.ts` — sign in, send a message, see streaming response, see citations, click a citation and see the source document open scrolled to the cited page

### Implementation for User Story 1

- [ ] T082 [P] [US1] Implement `apps/api/src/routers/conversations.py` for `GET /conversations` (paged), `POST /conversations` (create empty), `GET /conversations/{id}` (load full, scoped by `userId == caller.oid`), `DELETE /conversations/{id}` (soft-delete sets `status=deletePending`, returns 202) per [api-openapi.yaml](./contracts/api-openapi.yaml) and [data-model.md](./data-model.md) §2
- [ ] T083 [US1] Implement `apps/api/src/routers/chat.py` `POST /chat` as a Server-Sent Events stream emitting `delta`, `citations`, `done`, `error` events. For each request: (1) load conversation, (2) build retrieval query from message + last N turns, (3) call `services/search.py` hybrid search (BM25 + vector + semantic re-rank) with mandatory `scope eq 'shared' or scope eq 'user:<callerOid>'` filter, (4) stream chat completion from `services/llm.py` with retrieved passages as grounding, (5) persist user + assistant turns to `conversations` Cosmos doc per [data-model.md](./data-model.md) §2 (depends on T082)
- [ ] T084 [P] [US1] Implement `apps/api/src/routers/citations.py` `GET /citations/{documentId}?page=N` returning the original document binary from Blob; enforce that the requested document's `scope` is `shared` OR `user:<callerOid>` — reject 404 otherwise (acceptance scenario US1.4 + US5 prep + SC-011)
- [ ] T085 [US1] In `services/llm.py` add a system prompt (configurable via Cosmos `settings` doc per FR-019) that instructs the model to (a) cite at least one passage per factual claim, (b) explicitly decline with a documented phrase when retrieval is empty or low-confidence — required for FR-016 / FR-017
- [ ] T086 [P] [US1] Implement `apps/web/src/app/(auth)/` with NextAuth/Entra OIDC sign-in pages (FR-006); reject anonymous access by Next.js middleware
- [ ] T087 [P] [US1] Implement `apps/web/src/app/chat/page.tsx` (new conversation) and `apps/web/src/app/chat/[id]/page.tsx` (existing) using Vercel AI SDK 4 `useChat` hooked to `POST /chat`; handle SSE `delta`/`citations`/`done`/`error` events
- [ ] T088 [P] [US1] Implement `apps/web/src/components/chat/ChatPane.tsx`, `MessageBubble.tsx`, `CitationChip.tsx` — shadcn/ui-based, restrained enterprise palette per FR-020 (clean typography, neutral palette + one accent, generous whitespace, accessible contrast)
- [ ] T089 [US1] Implement keyboard navigation + WCAG 2.1 AA semantics across the chat surface (FR-023): focus management on streaming, screen-reader announcements for new turns, role/aria attributes on chips
- [ ] T090 [P] [US1] Implement `apps/web/src/app/layout.tsx` left-rail conversation list (calls `GET /conversations`); selecting a conversation routes to `/chat/[id]`
- [ ] T091 [US1] Wire structured logging in `routers/chat.py` to record per-request: `conversationId`, `turnId`, retrieval count, decline-vs-answer, p50/p95 latency — feeds the US6 admin dashboard later

**Checkpoint US1**: Authenticated users can chat against the seeded corpus, get grounded answers with citations, multi-turn works, declines are explicit, and zero public traffic occurs. **The headline value proposition is demonstrable.**

---

## Phase 6: User Story 4 — Solution Engineer demonstrates the security posture (Priority: P2)

**Goal**: An SE walks a customer security architect through the deployed environment in < 30 minutes (SC-010), proving zero public endpoints, MSI-only auth, private-DNS resolution, and no shared keys — using only artifacts shipped with the accelerator.

**Independent Test**: From outside the VNet, every deployed PaaS hostname either fails to resolve or refuses connection (acceptance scenario US4.1). From inside the VNet, the same hostnames resolve to private IPs in the documented `snet-pe` range (US4.2). Inspecting the deployed identity model surfaces zero shared keys / connection strings (US4.3).

### Tests for User Story 4

- [ ] T092 [P] [US4] `infra/tests/test_security_posture_external.ps1` — from a runner OUTSIDE the deployed VNet, attempt DNS resolution and TCP 443 connections to every deployed PaaS hostname; assert all attempts fail (SC-004 / acceptance scenario US4.1)
- [ ] T093 [P] [US4] `infra/tests/test_security_posture_internal.ps1` — from a runner INSIDE the deployed VNet, assert every deployed PaaS hostname resolves to an IP in the `snet-pe` range (FR-005 / acceptance scenario US4.2)
- [ ] T094 [P] [US4] `infra/tests/test_role_assignments.ps1` — query Azure RBAC for each app MI; assert the exact least-privilege role-assignment set from T029 is present and no broader roles are granted (acceptance scenario US4.3 / FR-003)

### Implementation for User Story 4

- [ ] T095 [US4] Author `docs/security-posture.md` — a checklist + screenshot-able verification walkthrough mapping each row to FR-001 through FR-005 and the test that proves it (T050, T051, T052, T092, T093, T094); designed to be walked in < 30 min per SC-010
- [ ] T096 [P] [US4] Add a `scripts/posture-report.ps1` that runs T092–T094 against the live deployment and emits a single Markdown report the SE can hand to the customer architect

**Checkpoint US4**: SE has a one-command posture report and a checklist doc that proves every privacy boundary; SC-010 verifiable.

---

## Phase 7: User Story 5 — End user reviews and trusts a citation (Priority: P2)

**Goal**: Clicking a citation opens the source document in context — for PDFs, scrolled to the cited page; for images, the original image alongside the extracted text used as grounding; load < 2s (SC-008).

**Independent Test**: For an answer with a citation pointing to page N of a PDF, the user clicks → the PDF opens scrolled to page N within 2 seconds. For a citation pointing to an image, the original image is shown alongside the extracted text used to ground the answer.

### Tests for User Story 5

- [ ] T097 [P] [US5] `apps/web/playwright/citations.spec.ts` — for an answer citing page N of a PDF, click the chip and assert the citation viewer opens scrolled to page N (acceptance scenario US5.2)
- [ ] T098 [P] [US5] `apps/web/playwright/citations_image.spec.ts` — for an answer citing an image-derived passage, assert the citation viewer shows the original image AND the extracted text snippet (acceptance scenario US5.3)
- [ ] T099 [P] [US5] `apps/web/playwright/citation_load_time.spec.ts` — assert citation viewer first-paint < 2s for a typical demo PDF (SC-008)
- [ ] T100 [P] [US5] `apps/api/tests/integration/test_citation_deleted_source.py` — delete a `shared` document, then call `GET /citations/{deletedId}`; assert 404 with body explaining the source has been removed (edge case "Citation source no longer available")

### Implementation for User Story 5

- [ ] T101 [P] [US5] Implement `apps/web/src/app/citations/[docId]/page.tsx` — embeds a PDF.js (or `<iframe>`-based) viewer for PDFs that honors `?page=N`; for images displays the binary alongside the extracted-text snippet from the citation; for office formats falls back to download
- [ ] T102 [P] [US5] In `apps/web/src/components/chat/CitationChip.tsx`, the click handler routes to `/citations/[docId]?page=N&snippet=...`; visually distinguish the cited passage (highlight) once the source loads (FR-022)
- [ ] T103 [US5] In `apps/api/src/routers/citations.py` (T084), add the "this source has been removed from the corpus" 404 body when the document was found by id-history but is no longer in `documents` — depends on T084

**Checkpoint US5**: Citation experience meets SC-008 and trust-bar for SLED users.

---

## Phase 8: End-user document upload (cuts across US1; required for full P1 spec)

**Goal**: Implements **FR-031** / FR-031a — end users upload PDFs/TXT/DOCX/images that are scoped strictly to the uploading user **and** the parent conversation, never visible to other users, never added to the shared corpus, and purged when the conversation is purged. This is split out of US1 because it has its own contract surface (`POST /uploads`), its own isolation tests, and is a clean independent increment.

**Independent Test**: Sign in as User A, upload a PDF in conversation C, ask a question grounded in that PDF — answer cites the upload with `scope="user"`. Sign in as User B, ask the same question — answer must NOT cite User A's upload (and ideally declines if no shared coverage).

### Tests for User Story 1 (upload extension)

- [ ] T104 [P] [US1] `apps/api/tests/contract/test_openapi_uploads.py` — schema-validate `POST /uploads` request/response per [api-openapi.yaml](./contracts/api-openapi.yaml)
- [ ] T105 [P] [US1] `apps/api/tests/integration/test_upload_grounds_in_conversation.py` — upload a PDF, ask a question grounded in it, assert the citation has `scope="user"` (FR-031, FR-031a, acceptance scenario US1 + spec edge case)
- [ ] T106 [P] [US1] `apps/api/tests/isolation/test_cross_user_isolation.py` — **SC-011 fuzz test**: upload as User A, then as User B fire 10,000 randomized queries; assert zero results returned to B reference any of A's `documentId`s (SC-011 / FR-031)
- [ ] T107 [P] [US1] `apps/api/tests/integration/test_upload_size_cap.py` — upload a 51 MB file, assert HTTP 413; upload files until the per-conversation cumulative cap (250 MB) is exceeded, assert HTTP 413 (data-model.md §8)
- [ ] T108 [P] [US1] `apps/api/tests/integration/test_upload_unsupported_mime.py` — upload `.zip`, assert HTTP 415 (data-model.md §8)
- [ ] T109 [P] [US1] `apps/web/playwright/upload.spec.ts` — drag-drop a PDF into the chat surface, see "indexed" confirmation, ask a grounded question, see a `your upload` citation chip distinguishable from `shared` (FR-031a)

### Implementation

- [ ] T110 [US1] Implement `apps/api/src/routers/uploads.py` `POST /uploads` per [api-openapi.yaml](./contracts/api-openapi.yaml): (1) validate MIME + size, (2) write blob to `user-uploads/{callerOid}/{conversationId}/{newDocId}/{fileName}`, (3) create `Document` row in `documents` Cosmos (scope=`user:<oid>`, parentConversationId, ttl from parent conversation), (4) directly invoke the ingest pipeline inline (no Event Grid; per [research.md](./research.md) D6) and return `DocumentMeta` with `ingestion.status="queued"`; depends on T037, T038, T067, T082
- [ ] T111 [P] [US1] Create `apps/ingest/src/handlers/user.py` (called from `routers/uploads.py` in-process **and** invocable as a Job) that runs the same crack→chunk→embed pipeline as `handlers/shared.py` but writes `kb-index` docs with `scope="user:<oid>"`, `userOid`, `conversationId` populated per [data-model.md](./data-model.md) §5
- [ ] T112 [P] [US1] Update `apps/web/src/components/upload/SessionUpload.tsx` (drag-drop) and the `MessageBubble.tsx` to render `scope="user"` citations distinctly from `scope="shared"` per FR-031a
- [ ] T113 [US1] Augment `apps/api/src/services/search.py` query builder so that for an authenticated chat call, the filter is always `scope eq 'shared' or scope eq 'user:<callerOid>'` AND for `scope eq 'user:*'` results, additionally restricts `conversationId eq '<currentConvoId>'` so user-scoped passages from a *different* conversation of the same user don't bleed into the current chat (FR-031)
- [ ] T114 [US1] Update `apps/api/src/routers/conversations.py` `DELETE /conversations/{id}` (T082) to enqueue a purge that: deletes Cosmos `documents` rows where `parentConversationId == id`, deletes blobs under `user-uploads/{oid}/{id}/...`, and deletes `kb-index` rows where `conversationId == id` — within 1h SLA per SC-012

**Checkpoint US1+upload**: Per-user, per-conversation upload + isolation works; SC-011 isolation fuzz holds; deletion cascades.

---

## Phase 9: Retention purge worker (FR-030 / SC-012)

**Goal**: Guarantee 30-day rolling retention purge within 24 h of expiry, and within 1 h of user-initiated deletion, across Cosmos, Blob, and AI Search. Cosmos TTL handles the Cosmos side; Blob and AI Search require an active sweeper.

### Tests

- [ ] T115 [P] [US1] `apps/ingest/tests/integration/test_retention_30d_purge.py` — write a `Conversation` with `_ts` shifted to be 30 d + 25 h old; assert within the next sweeper run the Cosmos doc is gone (TTL), associated `user-uploads/...` blobs are gone, and `kb-index` rows are gone — SC-012 (24 h SLA)
- [ ] T116 [P] [US1] `apps/ingest/tests/integration/test_user_initiated_delete_1h.py` — call `DELETE /conversations/{id}`, assert all three stores are clean within 1 h — SC-012 (1 h SLA)

### Implementation

- [ ] T117 [P] [US1] Create `apps/ingest/src/handlers/sweeper.py` invoked hourly by a Container Apps Job schedule trigger: (1) scan `documents` for `scope=user:*` with `_ts` older than 30 d (TTL might still be in Cosmos's purge backlog), purge their blob + `kb-index` rows, (2) scan `conversations` for `status=deletePending`, purge child docs as in T114, then mark the tombstone for permanent removal
- [ ] T118 [US1] Add the schedule trigger + role assignments in `infra/modules/containerapps/main.bicep` for the sweeper Job (depends on T027)

**Checkpoint Retention**: SC-012 SLAs verifiably met.

---

## Phase 10: User Story 6 — Administrator monitors usage, ingestion health, and grounding quality (Priority: P3)

**Goal**: An admin sees a dashboard with: indexed-document count, latest ingestion run + outcome, chat request count, decline rate, and quality signals (thumbs up/down).

**Independent Test**: After several ingestion runs and chat sessions, the dashboard reflects accurate counts within the documented refresh window.

### Tests for User Story 6

- [ ] T119 [P] [US6] `apps/api/tests/integration/test_admin_stats_accurate.py` — seed 10 documents + 5 conversations + 1 declined turn; call `GET /admin/stats`; assert counts match within the documented refresh window (acceptance scenario US6.1)
- [ ] T120 [P] [US6] `apps/api/tests/integration/test_admin_decline_rate.py` — submit 10 chat requests of which 3 are declined; assert `declineRate7d ≈ 0.3` (acceptance scenario US6.2)
- [ ] T121 [P] [US6] `apps/web/playwright/admin_dashboard.spec.ts` — sign in as admin, see all dashboard cards populated; sign in as non-admin, see HTTP 403 redirect

### Implementation

- [ ] T122 [P] [US6] Extend `apps/api/src/routers/admin.py` (from T070) to compute `AdminStats` per [api-openapi.yaml](./contracts/api-openapi.yaml): `sharedDocuments`, `sharedPassages`, `totalConversations`, `totalUsers`, `chatRequests24h`, `declineRate7d`, `lastIngestionRun` — sourced from Cosmos + App Insights KQL
- [ ] T123 [P] [US6] Implement `apps/web/src/app/admin/page.tsx` rendering the dashboard cards; admin-gated by NextAuth session role
- [ ] T124 [P] [US6] Add a thumbs-up/down control in `apps/web/src/components/chat/MessageBubble.tsx`; `POST /feedback` endpoint in `routers/chat.py` writes a feedback row (in-line under the conversation turn) — feeds the quality signal in T122

**Checkpoint US6**: Dashboard accurate, role-gated.

---

## Phase 11: Polish & Cross-Cutting Concerns

**Purpose**: Tighten what already works; address quality, docs, accessibility, and the long-tail of edge cases listed in [spec.md](./spec.md) "Edge Cases".

- [ ] T125 [P] Run `pnpm exec axe` accessibility audit across all chat + admin + citations pages; fix violations to reach WCAG 2.1 AA on the primary chat + citation flows (FR-023)
- [ ] T126 [P] Add unsupported-browser banner per spec edge case; document supported browsers in `docs/architecture.md`
- [ ] T127 [P] Add IdP-outage guardrail: NextAuth error page that explicitly states "identity provider unreachable; sign-in is unavailable; anonymous access is not provided" — spec edge case
- [ ] T128 [P] Add bounded retry budget to `services/llm.py` (3 attempts, exponential backoff, total budget 8s) and a non-technical user-facing error on persistent failure — spec edge case
- [ ] T129 [P] Add content-safety screening (Azure AI Content Safety, called via MI behind PE) on both admin- and user-uploaded documents per spec edge case "very large or sensitive document"
- [ ] T130 [P] Add an MFA-equivalent admin re-auth gate before `POST /admin/reindex` and bulk delete operations — defense in depth for FR-008
- [ ] T131 [P] Performance: enable ACA min-replicas=1 on `web` and `api` for SC-007 cold-start avoidance; document in `docs/cost.md` the cost delta of scale-to-zero vs always-on
- [ ] T132 [P] Run `mcp_bicep_get_deployment_snapshot` against `infra/main.bicepparam` for the default and `enableZoneRedundancy=true` parameter sets; commit the snapshots under `infra/snapshots/` for drift review (used by SC-002 idempotency CI)
- [ ] T133 [P] Run `mcp_azure_mcp_wellarchitectedframework` review against the deployed environment; capture findings + remediations in `docs/waf-review.md`
- [ ] T134 Run `quickstart.md` end-to-end on a fresh subscription; confirm < 60 min wall-clock, < 15 min hands-on (SC-001); update doc verbiage on any friction discovered
- [ ] T135 Run the full test matrix (T048–T124) green on CI in a single `deploy.yml` run as the release-readiness gate

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)** — no dependencies; can start immediately
- **Foundational (Phase 2)** — depends on Setup; **BLOCKS every user-story phase** (no Azure resources exist before this)
- **US3 (Phase 3, P1)** — depends on Foundational; sequenced first because **US1 and US2 cannot be tested without a deployed environment**
- **US2 (Phase 4, P1)** — depends on Foundational + US3 (needs deployed Search/Storage/DocIntel); sequenced before US1 because US1 needs an indexed corpus
- **US1 (Phase 5, P1)** — depends on Foundational + US3 + US2 (needs corpus to retrieve against)
- **US4 (Phase 6, P2)** — depends on Foundational + US3 (verifies what US3 deployed)
- **US5 (Phase 7, P2)** — depends on US1 (needs citations to click) + US2 (needs documents)
- **End-user upload extension (Phase 8)** — depends on US1 + US2 (extends the chat path with user-scoped grounding)
- **Retention purge (Phase 9)** — depends on Phase 8 (purges the artifacts Phase 8 creates)
- **US6 (Phase 10, P3)** — depends on US1 + US2 (needs traffic + ingestion runs to display)
- **Polish (Phase 11)** — depends on all desired user stories being complete

### User Story Dependencies (summary)

- **US3 (deploy)** — independent (foundational)
- **US2 (ingest)** — needs US3 deployment
- **US1 (chat)** — needs US2 (corpus) and US3 (deployment)
- **US4 (security demo)** — needs US3 only; can run in parallel with US1/US2
- **US5 (citation review)** — needs US1 + US2
- **Upload extension** — extends US1; can be developed in parallel with US5
- **Retention purge** — needs upload extension
- **US6 (dashboard)** — needs US1 + US2

### Within Each User Story

- Tests written FIRST and asserted to FAIL before implementation
- Models/DTOs (Phase 2) → Services → Routers/Endpoints → UI
- For Bicep modules: AVM-first refactor (T031) happens once after the hand-rolled modules pass `bicep build`

### Parallel Opportunities

- All Setup tasks marked [P] (T002–T014) — different files, no dependencies
- All Foundational module-creation tasks (T017–T028) marked [P] — different `infra/modules/*` directories
- All Foundational app-shell tasks (T033–T045) marked [P] — different files
- US2 tests (T060–T065) all [P]; US1 tests (T072–T081) all [P]; US4 tests (T092–T094) all [P]; US5 tests (T097–T100) all [P]; US6 tests (T119–T121) all [P]
- US1 web-side tasks (T086–T088, T090) parallel to US1 api-side tasks (T082–T085) — different directories
- US4 and US5 phases can overlap if staffed (different concerns: posture vs UX)

---

## Parallel Example: Phase 2 Foundational

```text
# Once T015 (main.bicep skeleton) lands, fan out to module authors:
Task: "Create infra/modules/network/main.bicep"            # T017
Task: "Create infra/modules/identity/main.bicep"           # T018
Task: "Create infra/modules/monitoring/main.bicep"         # T019
Task: "Create infra/modules/registry/main.bicep"           # T020
Task: "Create infra/modules/keyvault/main.bicep"           # T021
Task: "Create infra/modules/storage/main.bicep"            # T022
Task: "Create infra/modules/cosmos/main.bicep"             # T023
Task: "Create infra/modules/search/main.bicep"             # T024
Task: "Create infra/modules/openai/main.bicep"             # T025
Task: "Create infra/modules/docintel/main.bicep"           # T026
Task: "Create infra/modules/bastion/main.bicep"            # T028

# Concurrently on the apps side:
Task: "apps/api/src/config.py"                              # T033
Task: "apps/api/src/main.py"                                # T034
Task: "apps/api/src/services/auth.py"                       # T035
Task: "apps/api/src/services/cosmos.py"                     # T037
Task: "apps/api/src/services/storage.py"                    # T038
Task: "apps/api/src/services/search.py"                     # T039
Task: "apps/api/src/services/llm.py"                        # T040
Task: "apps/api/src/services/docintel.py"                   # T041
Task: "apps/web/src/lib/auth.ts"                            # T043
Task: "apps/web/src/lib/api.ts"                             # T044
```

## Parallel Example: User Story 1 tests

```text
# Once US2 lands, fan out US1 tests to authors:
Task: "Contract: chat OpenAPI"                              # T072
Task: "Contract: conversations OpenAPI"                     # T073
Task: "Contract: citations OpenAPI"                         # T074
Task: "Integration: grounded answer"                        # T075
Task: "Integration: follow-up context"                      # T076
Task: "Integration: out-of-corpus decline"                  # T077
Task: "Integration: SC-006 quality benchmark"               # T078
Task: "Integration: SC-007 p95 < 6s"                        # T079
Task: "Integration: zero public traffic"                    # T080
Task: "Playwright: chat E2E"                                # T081
```

---

## Implementation Strategy

### MVP First (US3 → US2 → US1)

The P1 set has an internal ordering forced by physics, not preference:

1. Complete Phase 1 (Setup) and Phase 2 (Foundational) — IaC + dev loop
2. Complete Phase 3 (US3) — `azd up` works end-to-end → empty private environment
3. Complete Phase 4 (US2) — corpus is ingestible → searchable knowledge exists
4. Complete Phase 5 (US1) — chat works against the corpus → headline value demoable
5. **STOP and VALIDATE**: run `quickstart.md` §7 end-to-end as MVP acceptance
6. Demo the MVP — every P1 acceptance scenario passes

### Incremental Delivery (P2 / P3)

7. Add Phase 6 (US4 security demo) → SE has a posture report → close customer-architect conversations
8. Add Phase 7 (US5 citation viewer) → citations are trustworthy → SLED users sign on
9. Add Phase 8 (upload extension) → end users can ground on their own docs → satisfies FR-031
10. Add Phase 9 (retention sweeper) → SC-012 SLAs guaranteed
11. Add Phase 10 (US6 dashboard) → admins have ongoing visibility
12. Phase 11 (polish) → accessibility, content safety, WAF review, full-matrix release gate

### Parallel Team Strategy

With multiple engineers, after Phase 2 completes:

- **Engineer A** (IaC): drives US3 (Phase 3) and US4 (Phase 6)
- **Engineer B** (backend): drives US2 (Phase 4), US1 backend (Phase 5), upload backend (Phase 8), retention (Phase 9)
- **Engineer C** (frontend): drives US1 web (Phase 5 web tasks), US5 (Phase 7), upload UI (Phase 8 web), US6 dashboard (Phase 10)

Stories integrate at the contracts boundary ([api-openapi.yaml](./contracts/api-openapi.yaml), [search-index.json](./contracts/search-index.json), Cosmos schemas, ingestion-event schema), so parallel work is low-conflict.

---

## Notes

- Every task carries a checkbox, a Tnnn ID, optional [P] / [US#] labels, and a concrete file path or resource as required by the speckit.tasks format
- Tests are first-class because the spec defines hard, automated SCs (SC-002, SC-004, SC-006, SC-011, SC-012); the constitution's NON-NEGOTIABLE security pillar requires automated assertions, not manual review
- Cross-user isolation (SC-011) is enforced at *three* layers — `services/search.py` filter wrapper (T039), `routers/citations.py` scope check (T084), and the SC-011 fuzz harness (T106) — defense in depth
- The AVM-refactor task (T031) is sequenced after hand-rolled modules pass `bicep build` so that engineers can move fast first and harden second; the constitution allows this as long as the final committed state uses AVM where available
- Avoid: vague tasks, same-file conflicts within a phase, cross-story dependencies that would break independent testability
