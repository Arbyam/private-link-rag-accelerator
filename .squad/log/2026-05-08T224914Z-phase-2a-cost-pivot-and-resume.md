# Session Log — 2026-05-08 — Phase 2a kickoff, cost pivot, and recovery

## Timeline

1. **PR #3 merged** — Dallas's `phase-2a/pr-a-main-bicep-shell` (T015–T016: main.bicep skeleton + dev/prod parameter files) merged via auto-merge under the new autonomy directive.
2. **Autonomy directive (20:06:07)** — Arbyam: full autonomy mode. PRs open with `gh pr create --fill` and auto-merge with squash. Escalation only for `infra/main.bicep` architecture changes, zero-trust weakening, unfinishable tasks, or scope creep.
3. **Phase 2 architecture sign-off (20:13:37)** — 5 decisions resolved: snet-jobs reserved, queue PE added, openai-before-search ordering, jumpbox in snet-pe, Phase 2a/2b split (T015–T032+T032a vs T033+).
4. **APIM module added (20:13:37)** — New T032a. Internal VNet mode, AI Gateway in front of AOAI, JWT auth at the edge, central observability.
5. **$500/mo cost ceiling — HARD constraint (20:13:37)** — Supersedes prior SKU recommendations. Killed APIM Premium, Bastion Standard, AI Search S1.
6. **Ripley v2 plan locked then immediately superseded** — v2 still carried APIM Premium ($2,800/mo) citing SC-004; cost ceiling forced re-plan.
7. **Ripley v3 plan locked (\$318/mo)** — APIM Developer, Bastion Developer, AI Search Basic, Cosmos Serverless, DocIntel S0. Zero-trust fully preserved (all 11 data-plane services PE or VNet-injected with `publicNetworkAccess: Disabled`). \$182 headroom under ceiling.
8. **Default model = claude-opus-4.7 (22:39:49)** — Arbyam: every spawned agent (including Scribe + Ralph) uses Opus 4.7 by default. Saved to `.squad/config.json` → `defaultModel`.
9. **Dallas PR-A.1 first attempt — interrupted** — Agent state lost mid-flight; WIP left in working tree, no PR opened.
10. **Dallas PR-A.1 recovery (in flight)** — Spawned in parallel with this Scribe pass. Commit `aa8bf7a` (`fix(infra): align SKU defaults to $500/mo budget ceiling`) landed on `phase-2a/pr-a1-sku-budget-defaults`. PR/auto-merge pending at session end.

## Cost Table (Ripley v3 — locked)

| Resource | Tier | PE | $/mo |
|---|---|---|---:|
| VNet + NSGs | — | n/a | $0 |
| Private DNS Zones (×13) | — | n/a | $7 |
| Bastion | Developer (free) | n/a | $0 |
| Jumpbox VM | Standard_B2s | n/a | $36 |
| Container Registry | Premium | ✅ | $50 |
| AI Search | Basic | ✅ | $74 |
| API Management | Developer | ✅ VNet-injected | $50 |
| Container Apps (×3) | Consumption | internal VNet | $5 |
| Cosmos DB | Serverless | ✅ | $3 |
| Azure OpenAI | Pay-per-token | ✅ | $10 |
| Document Intelligence | S0 | ✅ | $3 |
| Storage Account | Standard LRS | ✅ (blob+queue) | $3 |
| Key Vault | Standard | ✅ | $1 |
| Log Analytics + App Insights | Pay-per-GB | via AMPLS | $10 |
| Private Endpoints (×9) | — | — | $66 |
| **TOTAL** | | | **$318** |

## State at session end

- Phase 2a plan: **v3 locked**, parameter defaults updated.
- Active branch: `phase-2a/pr-a1-sku-budget-defaults` (Dallas, in flight).
- Squad config: `defaultModel = claude-opus-4.7`.
- Decisions inbox: drained (7 → 0).
- Next: Dallas merges PR-A.1, then PR-B (network module / `infra/modules/network/`).
