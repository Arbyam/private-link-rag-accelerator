# Ripley — History

## Project Context
- **Project:** Private RAG Accelerator (private-link-solution)
- **User:** Arbyam
- **Stack:** Bicep/AVM → Python/FastAPI → Next.js 15
- **Constitution:** `.specify/memory/constitution.md` — Security-First (Principle I), Idempotent IaC (Principle II)
- **Tasks source:** `specs/001-private-rag-accelerator/tasks.md` (135 tasks, 11 phases)

## Learnings
<!-- Append architectural decisions, patterns, user preferences, key file paths below -->

### Phase 1 Completion (2026-05-09)
- Decomposed 14 tasks into 6 logical PRs with specialist assignments
- All Phase 1 tasks completed; PR #2 merged to feat/phase-1-setup
- Orchestrated parallel agent work: dallas, kane, lambert, parker, scribe

### Phase 2a Plan Revision (2026-05-08)
- Integrated 5 resolved architecture questions from Arbyam (snet-jobs reserved, queue PE added, Phase 2a/2b split, openai-before-search, jumpbox in snet-pe)
- Added APIM to Phase 2 architecture per Arbyam directive
- **APIM SKU decision: Premium (stv2) required** — StandardV2 does NOT support internal VNet mode, meaning management/portal endpoints stay publicly accessible. This violates SC-004 and Constitution Principle I. Premium is the only SKU with full internal VNet injection. Developer SKU parameterized for dev/test.
- New subnet `snet-apim` at `10.0.3.64/27` — fits within existing /22 VNet without expansion
- APIM uses AVM module `br/public:avm/res/api-management/service` (GA)
- Private DNS zone `azure-api.net` (not privatelink.*) for internal APIM endpoint resolution
- APIM backends + policies deferred to Phase 2b/3 — Phase 2a deploys instance + base config only
- Plan expanded from 16 → 17 PRs; T032a added for APIM module
- APIM provisioning time risk noted: Premium VNet-injected takes 30–45 min on first deploy
- Plan status: APPROVED by Lead, execution authorized

### Phase 2a v3 — Cost-Validated Plan (2026-05-08T20:13:37-07:00)
- **$500/month hard cap imposed by Arbyam** — non-negotiable for demo accelerator
- **Total validated cost: ~$318/month** with $182 headroom (36%)
- **APIM SKU: Developer ($50/mo)** — supports internal VNet mode (full VNet injection); all gateway/portal/management endpoints internal-only. SC-004 compliant. No SLA acceptable for demo. Premium remains available via `apimSku` parameter for production.
- **Bastion: Developer ($0)** — free, portal-native, no IaC resource. Single concurrent session. Available in East US 2. Jumpbox VM (Standard_B2s, ~$36/mo) still deployed for internal access.
- **AI Search: Basic ($74/mo)** — PE confirmed supported on Basic tier. 15 GB / 3 indexes sufficient for demo. Was Standard S1 ($245/mo) in v2.
- **ACR Premium: $50/mo** — v2 estimated $167 incorrectly; actual Azure pricing is $1.667/day = ~$50/mo. Only PE-capable tier.
- **Cosmos DB: Serverless ($3/mo)** — replaces autoscale provisioned ($24+ min). PE supported on serverless.
- **Document Intelligence: S0 required** — F0 free tier does NOT support private endpoints. S0 is pay-per-page (~$3/mo for demo volume).
- **Private Endpoints: 9 PEs × $7.30 = $66/mo** — validated at $0.01/hr per PE.
- **No functionality cuts needed** — all 11 data-plane services retained with zero public endpoints.
- **AzureBastionSubnet: conditional** — not provisioned by default (Developer SKU uses shared pool). Reserved in address space.
- **Parameter defaults updated:** `apimSku='Developer'`, `aiSearchSku='basic'`, `budgetMonthlyUsd=500`, `cosmosCapacityMode='Serverless'`, `deployBastion=false`, `deployJumpbox=true`
- **PR-A salvageable:** main.bicep shell + parameter file structure is SKU-neutral; only default values in `main.parameters.json` need updating.
- Azure pricing sources verified: Azure public pricing pages, Azure Pricing Calculator references, Microsoft Learn docs (2025-2026).

## Team Update — 2026-05-08T22:49:14-07:00 (Scribe broadcast)

Shared facts effective immediately for all squad members:

- **\/month cost ceiling** — HARD constraint on total demo Azure spend. Supersedes any prior SKU choices. Killed APIM Premium, Bastion Standard, AI Search S1.
- **Default model = `claude-opus-4.7`** for every spawned agent (saved to `.squad/config.json`). Includes Scribe + Ralph.
- **Phase 2a/2b split** — Phase 2a = T015–T032 + T032a (IaC foundation, 17 PRs). Phase 2b = T033+ (app foundations, deferred).
- **Autonomy directive** — Lead opens PRs with `gh pr create --fill` then `gh pr merge <n> --squash --auto --delete-branch`. No "go" approvals. Escalate only for `infra/main.bicep`/`infra/modules/*` architecture changes, zero-trust weakening, unfinishable tasks, or scope creep.
- **Phase 2a v3 plan locked** — total ~\/mo, \ headroom. APIM Developer, Bastion Developer, AI Search Basic, Cosmos Serverless. See `.squad/agents/ripley/phase-2-plan.md`.

See `.squad/decisions.md` for full text.
