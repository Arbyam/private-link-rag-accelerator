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

### Phase 2a — PR-E: registry module (T020) — 2026-05-08
**PR #6 merged** (squash, auto-merge): `phase-2a/pr-e-registry-module` → `001-private-rag-accelerator`
- AVM `br/public:avm/res/container-registry/registry:0.12.1` (latest stable; ACR registry has 28 versions on MCR, 0.12.1 selected as newest)
- Pinned `acrSku` to Premium-only via `@allowed(['Premium'])` — codifies SC-004 (only PE-capable tier); guards against accidental SKU downgrade in param files
- Zero-trust: `publicNetworkAccess: 'Disabled'`, `acrAdminUserEnabled: false`, `anonymousPullEnabled: false`
- PE wiring shape: AVM expects `privateEndpoints[].privateDnsZoneGroup.privateDnsZoneGroupConfigs[].privateDnsZoneResourceId` — single zone `privatelink.azurecr.io`
- Soft delete + retention both enabled, single `softDeleteRetentionDays` param (default 7) controls both windows
- Outputs: `acrId`, `acrName`, `acrLoginServer`, `peId` (peId via `registry.outputs.privateEndpoints[0].resourceId`) — AcrPull RBAC deferred to PR-O wiring per scope discipline
- Bicep build clean (`az bicep build` exit 0); only Bicep CLI upgrade nag warning
- **Gotcha — parallel-agent branch collision:** `git checkout -b phase-2a/pr-e-registry-module` reportedly switched to that branch, but the *commit* landed on `phase-2a/pr-d-monitoring-module` because parallel Dallas spawns had pre-created sibling branches at the same base SHA. Recovered by `git reset --hard <base>` on the wrong branch + cherry-pick onto pr-e. Working tree was also intermittently swapped between branches across PowerShell sync sessions. **Mitigation for next PR:** verify `git branch --show-current` before AND after each commit, and consider using disposable worktrees (`git worktree add`) when squad is running multiple infra agents simultaneously.

### Phase 2a — PR-D: Monitoring module (T019) — 2026-05-08
**PR #9 merged** (squash, auto-merge, branch deleted): `phase-2a/pr-d-monitoring-module` → `001-private-rag-accelerator`

#### Module Composition
- **LAW** via `br/public:avm/res/operational-insights/workspace:0.15.1` — PerGB2018, `dataRetention: 30`, public ingest+query disabled.
- **App Insights** via `br/public:avm/res/insights/component:0.7.1` — workspace-based (`workspaceResourceId` → LAW), public ingest+query disabled.
- **AMPLS** hand-rolled (`Microsoft.Insights/privateLinkScopes@2021-07-01-preview`) at `location: 'global'`. No AVM module exists yet.
- **PE** hand-rolled, `groupIds: ['azuremonitor']` (single group), with a single `privateDnsZoneGroup` registering all 5 monitor zones.

#### AMPLS Gotchas (hand-rolled — read these before touching)
1. **AMPLS has no `publicNetworkAccess` property** — privacy is enforced exclusively via `accessModeSettings.{ingestionAccessMode,queryAccessMode} = 'PrivateOnly'`. The per-resource flags on LAW/App Insights are defense in depth; AMPLS is the source of truth.
2. **Single PE drives 5 DNS zones**: `monitor.azure.com`, `oms.opinsights.azure.com`, `ods.opinsights.azure.com`, `agentsvc.azure-automation.net`, `blob.core.windows.net`. Missing any one causes intermittent ingestion failures, not hard errors. The DNS zone group registers all 5 together.
3. **`blob.core.windows.net` is shared with Storage** — `main.bicep` (PR-O) MUST pass the same zone resource ID to both `monitoring` and `storage`. Two zones with the same name in the same VNet → non-deterministic resolution.
4. AMPLS scoped resources (`privateLinkScopes/scopedResources`) are not user-visible in the portal; names like `${lawName}-link` exist only for idempotency.

#### Module Boundary Decision: No diagnostic settings inside this module
Each consuming module owns its own `Microsoft.Insights/diagnosticSettings` and wires `lawId` from this module's outputs. Keeps the dependency graph one-way and avoids circular refs in `main.bicep`. README documents this as the "diagnostic settings stub" contract.

#### Inputs Diverge from main.bicep stub
Charter inputs are `peSubnetId` + 5 `privateDnsZoneId*` params (one per zone). main.bicep stub at PR-A had `peSubnetId` only and assumed the network module would expose zone IDs as outputs. PR-O (T029) will rewire — not this PR's concern.

#### Bicep Validation
- `az bicep build --file infra/modules/monitoring/main.bicep --outdir $env:TEMP` → exit 0, no warnings.
- AVM module versions discovered via `mcr.microsoft.com/v2/bicep/avm/res/.../tags/list` REST endpoint — useful trick for any "what's the latest pinned version" question.

#### Process Note: Parallel-Agent Filesystem Race
Other agents (kane keyvault, ripley network) were working concurrently. Symptoms observed:
- After `git checkout -b phase-2a/pr-d-monitoring-module` + creating files + clean `bicep build`, a subsequent `git status` showed I'd been moved back to `001-private-rag-accelerator` and my files were gone from the working tree (.gitkeep was the only file left).
- `git commit` on what I thought was my branch landed on `001-private-rag-accelerator` (commit `c0d39fa` orphaned).
- Recovery: `git checkout phase-2a/pr-d-monitoring-module` (the empty branch existed remotely from my earlier push attempt), `git cherry-pick c0d39fa`, `git push`, `git checkout 001-private-rag-accelerator && git reset --hard origin/001-private-rag-accelerator`.
- Lesson: when multiple agents share a working tree, always re-verify `git branch --show-current` immediately before `git commit`, and stash untracked cross-agent files (`git stash push -u -m ... -- <paths>`) before any `git checkout`.

### Phase 2a — PR-A.1: SKU defaults realigned to $500/mo ceiling — 2026-05-08
**PR #4 merged** (squash, auto-merge): `phase-2a/pr-a1-sku-budget-defaults` → `001-private-rag-accelerator`
- Defaults: apimSku=Developer, aiSearchSku=basic, cosmosCapacityMode=Serverless, budgetMonthlyUsd=500
- Added `deployJumpbox` flag (default true); `deployBastion` default flipped to false
- Cosmos param renamed: `cosmosAutoscaleMaxRu` → `cosmosCapacityMode` (allowed: Serverless | Provisioned)
- Bicep build clean (exit 0); only expected unused-param warnings (modules still placeholder-commented)
- Recovery commit — previous spawn made the edits but never committed/pushed before context loss

### Phase 2a — PR-C: Identity Module (T018) — 2026-05-08T22:49:14-07:00
**PR #7 merged** (squash, auto-merge): `phase-2a/pr-c-identity-module` → `001-private-rag-accelerator`

#### Identities created
- `mi-api` (FastAPI backend) — full data-plane reach
- `mi-ingest` (ingest worker) — same surface, write-scoped
- `mi-web` (Next.js frontend) — `AcrPull` only

#### Module shape
- AVM `br/public:avm/res/managed-identity/user-assigned-identity:0.4.1` (3 instances)
- Inputs: `location`, `tags`, `identityApiName`, `identityIngestName`, `identityWebName` — match the contract pre-wired in `infra/main.bicep` T015 shell
- Outputs per identity: `{resourceId, principalId, clientId}` + aggregate `identities` map keyed by `api|ingest|web` for PR-O role-assignment loops
- README documents the full identity → role mapping (informational; assignments live in PR-O T029/T030)

#### Scope deliberately excluded
- **APIM identity** — system-assigned on the APIM resource itself (PR-N), cannot be pre-created
- **`id-deploy` UAMI** — GitHub Actions uses subscription-scoped SP + OIDC FIC, not a workload UAMI
- **`main.bicep` wiring** — already prepared in T015 shell, uncomment in PR-O

#### Validation
- `az bicep build --file infra/modules/identity/main.bicep` exits 0, no warnings

### Learnings — 2026-05-08T22:49:14-07:00
- **Shared CWD race condition:** Multiple Dallas spawns operating in `C:\git-local\private-link-solution` simultaneously cause `git checkout` and `git add` to interleave catastrophically. My initial commit landed on a sibling branch (`phase-2a/pr-e-registry-module`) and pulled in another agent's keyvault staged files. **Fix going forward:** ALWAYS use `git worktree add C:\git-local\plk-pr-X origin/001-private-rag-accelerator -B phase-2a/pr-X-...` for an isolated workdir; never share the main repo CWD with parallel branches.
- **`gh pr merge --delete-branch` failure mode:** when run from a worktree whose post-merge target branch is checked out elsewhere, gh's branch-switch step fails after merge. Merge itself still succeeds — safe to ignore the trailing error and clean up the worktree manually.

## Team Update — 2026-05-08T22:49:14-07:00 (Scribe broadcast)

Shared facts effective immediately for all squad members:

- **\/month cost ceiling** — HARD constraint on total demo Azure spend. Supersedes any prior SKU choices. Killed APIM Premium, Bastion Standard, AI Search S1.
- **Default model = `claude-opus-4.7`** for every spawned agent (saved to `.squad/config.json`). Includes Scribe + Ralph.
- **Phase 2a/2b split** — Phase 2a = T015–T032 + T032a (IaC foundation, 17 PRs). Phase 2b = T033+ (app foundations, deferred).
- **Autonomy directive** — Lead opens PRs with `gh pr create --fill` then `gh pr merge <n> --squash --auto --delete-branch`. No "go" approvals. Escalate only for `infra/main.bicep`/`infra/modules/*` architecture changes, zero-trust weakening, unfinishable tasks, or scope creep.
- **Phase 2a v3 plan locked** — total ~\/mo, \ headroom. APIM Developer, Bastion Developer, AI Search Basic, Cosmos Serverless. See `.squad/agents/ripley/phase-2-plan.md`.

See `.squad/decisions.md` for full text.

### Phase 2a — PR-F: Key Vault Module (T021) — 2026-05-08T22:49:14-07:00
**PR #8 merged** (squash, auto-merge): `phase-2a/pr-f-keyvault-module` → `001-private-rag-accelerator`
- AVM `br/public:avm/res/key-vault/vault:0.13.3`
- Standard SKU; `enableRbacAuthorization: true` (no access policies)
- `publicNetworkAccess: Disabled`; `networkAcls.defaultAction: Deny`, `bypass: AzureServices`
- Soft delete (7d) + purge protection enabled
- Single PE in `snet-pe`, subresource `vault`, DNS zone group → `privatelink.vaultcore.azure.net`
- Diagnostic settings: `categoryGroup: 'allLogs'` + `'AllMetrics'` → LAW input
- Outputs: `kvId`, `kvName`, `kvUri`, `peId`
- Inputs minimal: `location`, `tags`, `vaultName`, `peSubnetId`, `privateDnsZoneId`, `lawId`, `softDeleteRetentionInDays` (default 7)
- Bicep build clean (`az bicep build` exit 0); only CLI upgrade nag warning

#### AVM gotcha — `enableVaultFor*` not `enabledFor*`
First attempt used the underlying Azure resource property names `enabledForDeployment`, `enabledForDiskEncryption`, `enabledForTemplateDeployment` and got `BCP037 — property not allowed`. AVM exposes them as **`enableVaultForDeployment`**, **`enableVaultForDiskEncryption`**, **`enableVaultForTemplateDeployment`**. Mnemonic: AVM normalizes the booleans to start with `enable` (matching `enableRbacAuthorization`, `enableSoftDelete`, `enablePurgeProtection`).

#### Worktree mitigation worked
PR-E history already noted parallel-agent branch thrashing. This PR proved it: my initial `git checkout -b phase-2a/pr-f-keyvault-module` succeeded, but between staging and `git commit` another agent's branch switch flipped HEAD to `phase-2a/pr-d-monitoring-module` and reset my index — `git commit` reported "nothing to commit, working tree clean". Recovery: `git worktree add ..\plk-pr-f phase-2a/pr-f-keyvault-module` to get a private working copy, recreate files, validate, commit, push from there. Worked first try. **Standing rule for parallel infra PRs: always work in `git worktree add ..\plk-pr-<x> <branch>`; do not share `C:\git-local\private-link-solution` with sibling agents.**

#### Outputs interface contract for PR-O wiring
- `kvId` → consumers needing scope for role assignments (PR-N)
- `kvUri` → APIM named-value secret refs, app config
- `peId` → not consumed yet but kept symmetric with PR-E (registry) and future modules


### Phase 2a — PR-B: network module (T017) — 2026-05-08
**PR #10 merged** (squash, auto-merge): phase-2a/pr-b-network-module →  01-private-rag-accelerator

#### Module shape
- VNet `10.0.0.0/22` (1024 IPs); 5 subnets inlined under `Microsoft.Network/virtualNetworks@2024-05-01` (NOT separate child subnet resources — avoids the `AnotherOperationInProgress` race when 5 subnets deploy in parallel).
- Subnets: `snet-aca` /24 (`Microsoft.App/environments` delegation), `snet-pe` /24 (PE+jumpbox, `privateEndpointNetworkPolicies: Disabled`), `snet-jobs` /24 (RESERVED, deny-all NSG only), `AzureBastionSubnet` /26 (always provisioned even when bastionSku=Developer — keeps NSG idempotent), `snet-apim` /27 carved from `10.0.3.64`.
- 5 hand-rolled NSGs; every one terminates in shared `denyInboundInternetRule` at priority 4096. APIM NSG includes the canonical `ApiManagement → :3443` mgmt rule + `AzureLoadBalancer → :6390` health probe; Bastion NSG is the full inbound/outbound matrix from the docs (Internet:443, GatewayManager, AzureLB, BastionHostCommunication 8080/5701, plus outbound VNet:22/3389 + AzureCloud:443).
- 13 Private DNS zones via AVM `br/public:avm/res/network/private-dns-zone:0.7.1` in a single `[for]` loop with `virtualNetworkLinks` shape. `registrationEnabled: false` for all.

#### AVM versions used
- `avm/res/network/private-dns-zone:0.7.1` ✅ — clean shape, exposes `virtualNetworkLinks` array, returns `outputs.resourceId`.
- VNet/subnets/NSGs hand-rolled. AVM `virtual-network` would work but inline subnets give cleaner review surface and avoid AVM's separate `subnets[*].networkSecurityGroupResourceId` indirection.

#### Bicep gotchas hit
1. **BCP247** — `toObject(range(0,len), i => names[i], i => modules[i].outputs.resourceId)` is rejected: lambda variables can't index a module collection. Workaround attempted via `var entries = [for ...]` then `toObject(entries, ...)` but that hits **BCP182** (module `outputs` not computable at start of deployment for variable for-bodies). **Resolution:** drop the map, expose 13 named outputs (`pdnsOpenaiId`, `pdnsBlobId`, …, `pdnsApimId`) plus a parallel `privateDnsZoneIdList` array. More ergonomic for downstream modules anyway.
2. **BCP318** null warnings on conditional module collections. Fix: safe-access operator — `privateDnsZones[i].?outputs.resourceId ?? ''`. Combined with the `customerProvidedDns ? '' : ...` ternary, this is null-clean.
3. `no-hardcoded-env-urls` linter flags `core.windows.net` in DNS zone literals. `#disable-next-line no-hardcoded-env-urls` placed immediately above each affected line works (the directive on the param declaration line itself does NOT propagate to inner array literal lines).
4. **Branch hygiene gotcha:** the local branch `phase-2a/pr-b-network-module` already existed (stale from a prior spawn pointing at d3cdfa9). `git checkout -b` reported "Switched to a new branch" but my work commit ended up on `001-private-rag-accelerator` instead. Recovery: `git checkout -B phase-2a/pr-b-network-module` (force re-create at HEAD), `git branch -f 001-private-rag-accelerator origin/001-private-rag-accelerator`, `git push -f`. **Lesson for future spawns:** check `git branch | Select-String <name>` before `git checkout -b`, and verify `git branch --show-current` after.

#### Validation
- `az bicep build --file infra/modules/network/main.bicep --outdir $env:TEMP\bicep-out` exits 0, **zero warnings**.
