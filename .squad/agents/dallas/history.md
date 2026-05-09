# Dallas — History

## Project Context
- **Project:** Private RAG Accelerator (private-link-solution)
- **User:** Arbyam
- **Stack:** Bicep/AVM for all Azure IaC
- **Key paths:** `infra/`, `infra/modules/`, `infra/search/kb-index.json`
- **Constitution:** Zero-trust networking, idempotent IaC, no public endpoints

## Learnings
<!-- Append infrastructure patterns, AVM versions, deployment gotchas below -->

### CI/CD Patterns (T011-T013)
- GitHub Actions OIDC auth: Use `azure/login@v2` with `id-token: write` permission
- azd federated credentials: `azd auth login --federated-credential-provider "github"`
- Internal-only ingress means smoke tests can't curl from GitHub runners; need in-VNet runner or Bastion
- Environment protection rules configured via GitHub repo settings (not in workflow YAML)
- Use `workflow_run` trigger to chain deploy-apps after deploy-infra succeeds

### Phase 1 Completion (2026-05-09)
- T001, T002, T003, T014 completed; PR #2 shipped
- Established directory skeleton, azure.yaml config, devcontainer setup, CI/CD workflows
- Commits: 7a3e8e6, 79f3556, cd8cbc8

### Phase 2a — PR-A: main.bicep Shell (T015, T016) — 2026-05-08
**PR #3 merged:** `phase-2a/pr-a-main-bicep-shell` → `001-private-rag-accelerator`

#### main.bicep Structure
- `targetScope = 'subscription'` — creates resource group, then scopes all modules to `rg`
- All 17 module blocks commented out with `// {TaskID} / {PR-label} — description` markers; PR-O (T029/T030) uncomments and wires them
- Layer ordering baked into comments: Layer 1 (network+identity) → Layer 2 (platform) → Layer 2.5 (APIM) → Layer 3 (data plane, openai before search) → Layer 4 (compute) → Layer 5 (wiring/RBAC) → Layer 6 (polish)

#### Naming Convention
- Pattern: `{namingPrefix}-{environmentName}-{regionShort}` as `baseName`; resource type prefix prepended
- Region short-codes stored in a `var regionShortMap` object; safe-access operator `regionShortMap[?location] ?? location` for unknown regions
- Special cases: ACR and Storage use `replace(..., '-', '')` to strip hyphens; Storage further `take(..., 24)` for 24-char limit
- All 23 resource names in a single `var names = { ... }` map — one source of truth, prevents drift

#### Parameter File Strategy
- `main.parameters.dev.json`: Developer APIM, basic AI Search, 1000 RU/s, $500 budget, zone-redundancy=false
- `main.parameters.prod.json`: Premium APIM, standard AI Search, 4000 RU/s, $5000 budget, zone-redundancy=true
- Required params (`namingPrefix`, `adminGroupObjectId`) have empty string defaults in files — callers must override
- `apimPublisherEmail` defaults to `azd@example.com`; override per environment before real deployment

#### APIM SKU Parameterization
- `@allowed(['Developer', 'Premium'])` — StandardV2 explicitly excluded (violates SC-004 — can't run fully internal)
- Developer SKU supports internal VNet mode; suitable for dev/test at ~$60/mo vs Premium ~$2,800/mo
- Default in main.bicep is 'Developer'; dev param file uses 'Developer', prod param file uses 'Premium'

#### Bicep Validation
- `az bicep build --file infra/main.bicep` exits 0 (zero errors)
- Warnings only: unused-params (expected — modules commented out) + use-safe-access (fixed with `[?key] ?? fallback`)
- `use-safe-access` linter rule: prefer `obj[?key] ?? default` over `contains(obj, key) ? obj[key] : default`

### Phase 2a — PR-A.1: SKU defaults realigned to $500/mo ceiling — 2026-05-08
**PR #4 merged** (squash, auto-merge): `phase-2a/pr-a1-sku-budget-defaults` → `001-private-rag-accelerator`
- Defaults: apimSku=Developer, aiSearchSku=basic, cosmosCapacityMode=Serverless, budgetMonthlyUsd=500
- Added `deployJumpbox` flag (default true); `deployBastion` default flipped to false
- Cosmos param renamed: `cosmosAutoscaleMaxRu` → `cosmosCapacityMode` (allowed: Serverless | Provisioned)
- Bicep build clean (exit 0); only expected unused-param warnings (modules still placeholder-commented)
- Recovery commit — previous spawn made the edits but never committed/pushed before context loss

## Team Update — 2026-05-08T22:49:14-07:00 (Scribe broadcast)

Shared facts effective immediately for all squad members:

- **\/month cost ceiling** — HARD constraint on total demo Azure spend. Supersedes any prior SKU choices. Killed APIM Premium, Bastion Standard, AI Search S1.
- **Default model = `claude-opus-4.7`** for every spawned agent (saved to `.squad/config.json`). Includes Scribe + Ralph.
- **Phase 2a/2b split** — Phase 2a = T015–T032 + T032a (IaC foundation, 17 PRs). Phase 2b = T033+ (app foundations, deferred).
- **Autonomy directive** — Lead opens PRs with `gh pr create --fill` then `gh pr merge <n> --squash --auto --delete-branch`. No "go" approvals. Escalate only for `infra/main.bicep`/`infra/modules/*` architecture changes, zero-trust weakening, unfinishable tasks, or scope creep.
- **Phase 2a v3 plan locked** — total ~\/mo, \ headroom. APIM Developer, Bastion Developer, AI Search Basic, Cosmos Serverless. See `.squad/agents/ripley/phase-2-plan.md`.

See `.squad/decisions.md` for full text.
