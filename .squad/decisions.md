# Squad Decisions

## Active Decisions

### Phase 1: Project Setup Complete (2026-05-09)
**Status:** Closed  
**PR:** https://github.com/Arbyam/private-link-rag-accelerator/pull/2

All 14 Phase 1 tasks successfully completed and merged:
- T001-T003, T014: Directory skeleton, Azure config, devcontainer, preflight (dallas)
- T004-T005, T007-T008: Backend pyproject, Dockerfiles, dependencies (kane)
- T006, T009: Frontend package.json, Dockerfile (lambert)
- T010: Linting configuration (parker)
- T011-T013: CI/CD workflows (dallas)

**Key decisions:**
- GitHub Actions OIDC federation for Azure auth
- Internal-only networking: no public ingress
- Multi-stage Docker builds for optimization
- Ruff + ESLint + Bicep linting stack

## Governance

- All meaningful changes require team consensus
- Document architectural decisions here
- Keep history focused on work, decisions focused on direction

---

## Session 2026-05-08 — Phase 2a kickoff, cost pivot, autonomy

### 2026-05-08T20:06:07-07:00 — Full autonomy mode for Lead/PRs
**By:** Arbyam (via Copilot)
**What:** Lead operates in full autonomy: `gh pr create --fill` then `gh pr merge <n> --squash --auto --delete-branch`. No "go" approvals required. Status report every 5 PRs / 30 min.
**Escalate before acting on:** `infra/main.bicep` / `infra/modules/*` architecture changes, anything weakening zero-trust (publicNetworkAccess, removing PEs, weakening JWT), unfinishable tasks, scope creep beyond `specs/001-private-rag-accelerator/tasks.md`.
**Implication:** Phase 2 architecture itself is the single escalation gate; individual module PRs run autonomously under auto-merge.

### 2026-05-08T20:13:37-07:00 — Phase 2 architecture decisions (Arbyam sign-off)
**By:** Arbyam — "Use your best judgement"
1. `snet-jobs` reserved (no delegation); apps + jobs share `snet-aca`.
2. `privatelink.queue.core.windows.net` added to private DNS zones.
3. Phase 2 split: **2a = T015–T032 + T032a** (IaC foundation), **2b = T033+** (app foundations).
4. `openai` deploys before `search` in main.bicep (shared private link first-deploy correctness).
5. Jumpbox VM lives in `snet-pe` to conserve IP space (managed identity workload, internal-only).

### 2026-05-08T20:13:37-07:00 — APIM added as Phase 2 module (T032a) [PARTIALLY SUPERSEDED]
**By:** Arbyam
**What:** New module `infra/modules/apim/`, internal VNet mode, JWT validation, AI Gateway pattern in front of AOAI, logs to LA + App Insights. New subnet `snet-apim`, private DNS for `azure-api.net`. Adds 1 PR (T032a) to Phase 2a (16 → 17).
**SKU guidance at time of writing:** "Evaluate StandardV2, fall back to Premium stv2." → **SUPERSEDED 2026-05-08T20:13:37 by /mo cost ceiling: APIM SKU is now Developer.**

### 2026-05-08T20:13:37-07:00 — HARD CONSTRAINT: /month cost ceiling
**By:** Arbyam (emphatic)
**What:** Total demo monthly Azure spend MUST NOT exceed /mo. This **supersedes any prior SKU recommendation**.
**Killed:** APIM Premium stv2 (,800), Bastion Standard (), AI Search S1 ().
**Kept (cheap tiers):** APIM Developer (~), Bastion Developer (free), AI Search Basic (~), ACA Consumption, Cosmos Serverless, AOAI/DocIntel pay-per-call. PEs (~-90) non-negotiable for SC-004.
**Constitution priority order:** (1) Principle I zero-trust, (2)  ceiling, (3) Principle II idempotent IaC, (4) feature completeness flexible.
**Lead authority:** Approve cost-validated plan once Ripley delivers; only escalate if a SKU choice forces a zero-trust tradeoff.

### 2026-05-08T20:13:37-07:00 — Ripley Phase 2a v2 plan LOCKED [SUPERSEDED by v3]
**By:** Ripley (Lead)
**What:** v2 plan integrated 5 architecture decisions + APIM at **Premium SKU (~$2,800/mo)**, citing SC-004 (claimed StandardV2 cannot run internal VNet mode).
**Status:** **SUPERSEDED** by v3 cost-validated plan below. v2 violated  ceiling.

### 2026-05-08T20:13:37-07:00 — Ripley Phase 2a v3 cost-validated plan LOCKED ✅
**By:** Ripley (Lead)
**Status:** APPROVED — cost-validated, zero-trust compliant, ready for execution.
**Total est. monthly:** **\/mo** (\ headroom under \ ceiling).
**SKU downgrades vs v2:** APIM Premium → Developer (saves \,750), Bastion Standard → Developer/free (saves \), AI Search S1 → Basic (saves \), Cosmos Autoscale → Serverless (saves \), ACR Premium repriced to ~\.
**Zero-trust preserved:** All 11 data-plane services have PE or VNet injection with `publicNetworkAccess: Disabled`. Document Intelligence F0 → S0 because F0 lacks PE support.
**Parameter default updates:** `apimSku='Developer'`, `aiSearchSku='basic'`, `budgetMonthlyUsd=500`, `cosmosCapacityMode='Serverless'` (replaces `cosmosAutoscaleMaxRu`), `deployBastion=false`, `deployJumpbox=true`.
**Plan doc:** `.squad/agents/ripley/phase-2-plan.md`.
**Greenlight:** Dallas to execute under autonomy.

### 2026-05-08T20:26:42-07:00 — Dallas PR-A: main.bicep shell merged (PR #3)
**By:** Dallas (Infra)
**Tasks:** T015, T016. **Branch:** `phase-2a/pr-a-main-bicep-shell`.
**Decisions:**
1. Shared `baseName` token (`{prefix}-{env}-{regionShort}`) + single `var names = { ... }` object — drift-resistant.
2. Adopted Bicep linter `use-safe-access` form: `regionShortMap[?location] ?? location`.
3. Both `main.parameters.dev.json` and `main.parameters.prod.json` shipped together (dev = basic SKUs/Developer APIM/\ budget; prod = standard/Premium/\ budget).
4. Outputs minimal in shell; future outputs commented as interface contract per phase-2-plan §E.

### 2026-05-08T22:39:49-07:00 — Default model = `claude-opus-4.7` for ALL agents
**By:** Arbyam (via Copilot)
**What:** Every spawned agent uses `claude-opus-4.7` by default. Saved to `.squad/config.json` → `defaultModel`. Persists across sessions until changed.
**Implications:** Layer 0 override active for all agents (Scribe + Ralph included, despite their mechanical-ops nature). Layer 3 cost-first auto-selection disabled by this directive. Fallback chain on unavailability: opus-4.7 → opus-4.6 → opus-4.5 → sonnet-4.6 → nuclear.


---

## Session 2026-05-09 — Phase 2a Wave-3 audit & post-mortem decisions

Source memos (drained from `.squad/decisions/inbox/` 2026-05-09):
- `copilot-directive-20260509T062045Z-phase2a-wave3-audit.md` (Ripley/Lead)
- `dallas-pr-b-network-dns-named-outputs.md`
- `dallas-pr-c-identity-worktree-mandate.md`
- `dallas-pr-d-monitoring-ampls-enforcement.md`
- `dallas-pr-e-registry-avm-pin-and-sku-allowlist.md`
- `dallas-pr-f-keyvault-worktree-isolation.md`

### 2026-05-09 — Worktree isolation mandate for parallel spawns ✅
**By:** Dallas (PR-C, PR-F memos) + ratified by Lead audit
**What:** Every parallel Dallas / Kane / Lambert / Parker spawn MUST execute in a disposable git worktree (`git worktree add ..\wt-{slug} -b <branch> origin/001-private-rag-accelerator`). Sharing `C:\git-local\private-link-solution` between sibling agents caused three documented incidents during wave-3: PR-C captured another agent's mid-flight `keyvault/*` files in its index; PR-E recovered via `git reset --hard` + cherry-pick; PR-F's commit reported `nothing to commit, working tree clean` after a sibling flipped HEAD between `git add` and `git commit`.
**Standard pattern:**
```powershell
git worktree add ..\wt-<slug> -b <branch> origin/001-private-rag-accelerator
cd ..\wt-<slug>
# ... work, validate, commit, push, gh pr create, gh pr merge --squash --auto --delete-branch ...
cd C:\git-local\private-link-solution
git worktree remove ..\wt-<slug> --force
git worktree prune
```
**Status:** Now codified in `.squad/team.md` Operating Rule #8. Standing rule, not optional, while parallel-agent execution is the norm.

### 2026-05-09 — T024/T025 swap correction (metadata only) ✅
**By:** Lead audit §1
**What:** The internal Phase 2a v3 plan listed PR-I as T024 (OpenAI) and PR-J as T025 (Search). `tasks.md` is canonical: **T024 = AI Search**, **T025 = Azure OpenAI**. Shipped code is correct in both PRs; only PR-J's commit message is wrong.
**Truth-table for git history readers:**
- PR #13 (`feat(infra/search)`) actually closes **T024** (despite commit message saying "Closes T025")
- PR #14 (`feat(infra/openai)`) closes **T025** (commit message correct)
**Action:** No code change; this entry is the corrective metadata.

### 2026-05-09 — T024 SKU deviation: AI Search Standard S1 → Basic — ACCEPTED PERMANENT ✅
**By:** Lead audit §3
**What:** `tasks.md` T024 specifies "AI Search Standard (S1)". v3 plan and shipped module use **Basic** under the $500/mo cost ceiling.
**Justification:**
- Basic supports private endpoints, semantic ranker (free tier), shared private link to AOAI/Storage
- 15 GB index covers demo corpus
- Saves $171/mo vs S1
- Zero Constitution principle violated; only spec verbiage diverges
- Prod environments may bump to S1 via parameter if needed
**Status:** Permanent accepted deviation. Documented in `infra/modules/search/README.md`.

### 2026-05-09 — T028 SKU deviation: Bastion Standard → Developer — ACCEPTED PERMANENT ✅
**By:** Lead audit §4
**What:** `tasks.md` T028 specifies "Bastion Standard". PR-N (#19) shipped **Developer** SKU under the $500/mo cost ceiling.
**Justification:**
- Developer free for the demo's single-session jumpbox use case
- Saves $140/mo vs Standard
- Trade-off: single concurrent session, no IP/host-based routing — acceptable for SE demo
- Constitution non-negotiables preserved: jumpbox lives in VNet; admin access never exits private network
**Status:** Permanent accepted deviation.

### 2026-05-09 — T020 AcrPull RBAC deferred to PR-O (T029) — INTENTIONAL ✅
**By:** Lead audit §6 + Dallas PR-E memo §"Non-decisions"
**What:** T020 spec calls for ACR Premium *and* `AcrPull` to all three app MIs. PR #6 ships ACR resource only; cross-module app-MI RBAC fan-out lives in the composition layer (PR-O / T029). Consistent module pattern: modules emit IDs; composition layer fans out RBAC.
**Action:** T020 status = "module-shipped, RBAC pending". PR-O closes T020 + T029 simultaneously. Document in PR-O description.

### 2026-05-09 — T022 partial-close superseded by PR #18 (PR-G.1) ✅
**By:** Lead audit §2
**What:** PR #12 partially closed T022 (Storage). It correctly enforced zero public access / MI-only auth / diagnostics-to-LAW, but missed acceptance criteria: created wrong container (`documents`) instead of `shared-corpus` + `user-uploads`; no lifecycle policy on `user-uploads` (30d delete per FR/SC-012); no Event Grid system topic on `BlobCreated`/`BlobDeleted`; no Storage Queue subscription; over-spec'd 5 PEs (only blob/queue required).
**Resolution:** PR #18 (`fix(infra/storage): finish T022 acceptance criteria`) drops the 3 unused PEs, replaces `documents` container with `shared-corpus` + `user-uploads`, adds explicit soft-delete, lifecycle policy, Event Grid system topic, and Storage Queue subscription. **PR #18 is the authoritative T022 closure.**

### 2026-05-09 — Network module emits 13 named DNS zone outputs (no map output) ✅
**By:** Dallas PR-B memo
**What:** Bicep limitations BCP247 (lambda variable inside module collection access) and BCP182 (module `outputs` not computable at start of deployment for variable for-bodies) prevented the originally-planned `privateDnsZoneIds object` map output. Module emits 13 named string outputs instead:
`pdnsBlobId`, `pdnsQueueId`, `pdnsCosmosId`, `pdnsOpenaiId`, `pdnsSearchId`, `pdnsCognitiveId`, `pdnsKeyVaultId`, `pdnsAcrId`, `pdnsMonitorId`, `pdnsOmsId`, `pdnsOdsId`, `pdnsAgentSvcId`, `pdnsApimId`.
Plus `privateDnsZoneIdList` (parallel array in input order) and `privateDnsZoneNamesOut` (echo of input names).
**Implication for PR-O wiring:** Downstream modules consume `network.outputs.pdnsBlobId` (etc.) — **must** use these exact output names. More ergonomic (typed, autocomplete-friendly) than stringly-typed map lookup. Constitution impact: none.
**Revisit when:** BCP247 and BCP182 are lifted in a future Bicep release; map output can be reintroduced additively.

### 2026-05-09 — AMPLS `accessModeSettings = PrivateOnly` is the privacy source of truth ✅
**By:** Dallas PR-D memo §1
**What:** AMPLS does NOT expose a `publicNetworkAccess` property. Privacy enforcement for telemetry is driven exclusively by:
```bicep
properties: {
  accessModeSettings: {
    ingestionAccessMode: 'PrivateOnly'
    queryAccessMode:     'PrivateOnly'
  }
}
```
Per-resource `publicNetworkAccessForIngestion = 'Disabled'` on LAW + Application Insights is **defense in depth**, not the primary enforcement.
**Break-glass guidance:** If public query is ever needed for diagnostics, change `queryAccessMode` to `'Open'` on AMPLS — that is the documented degrade path. Do NOT flip the per-resource flags; behavior is counterintuitive.
**Plus:** Monitoring module deliberately omits consumer `Microsoft.Insights/diagnosticSettings` resources (consumers create their own and consume `monitoring.outputs.lawId`) — keeps the dependency graph one-way and avoids circular references. Single PE + single DNS zone group covers all 5 monitor zones; `blob.core.windows.net` zone is shared with the Storage module — PR-O wiring MUST pass the same zone resource ID to both modules to avoid duplicate same-named zones in one VNet (non-deterministic DNS).

### 2026-05-09 — AVM version pinning + module-local SKU allowlists ✅
**By:** Dallas PR-E memo
**What:** Two patterns now standing for every Phase 2a AVM-driven module:
1. **Pin AVM to a specific published version** (e.g., ACR registry pinned to `0.12.1`), never `latest` or a floating range. Recheck MCR tag list at module-implementation time, pick the newest stable, document the pin choice in the module's leading comment / README.
2. **Use `@allowed([...])` to constrain SKU parameters to the values that satisfy zero-trust + cost constitution.** Example: ACR module uses `@allowed(['Premium'])` on `acrSku` because Premium is the only ACR tier with PE support (SC-004). Turns a runtime/compliance failure into a deploy-time error.
**Pattern to repeat:** APIM (`@allowed(['Developer'])` under cost ceiling), AI Search (`@allowed(['basic'])` likewise), Cosmos `publicNetworkAccess`, etc.
**Trade-off:** If Microsoft ships PE on a cheaper tier, modules need an explicit edit to widen `@allowed`. Audit trail is the point.

### 2026-05-09 — APIM Developer SKU locked — REAFFIRMED ✅
**By:** Lead (consistency check during drain)
**What:** APIM Premium stv2 (~$2,800/mo) was originally proposed in Arbyam's 2026-05-08 directive (paragraph "Evaluate StandardV2, fall back to Premium stv2") and is **already marked SUPERSEDED** in the prior decisions section by the $500/mo cost ceiling. APIM **Developer** is the locked SKU for Phase 2a (T032a). This entry reaffirms that ruling for readers landing here from wave-3 audit memos.
