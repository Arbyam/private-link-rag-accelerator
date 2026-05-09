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
