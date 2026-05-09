# Parker — History

## Project Context
- **Project:** Private RAG Accelerator (private-link-solution)
- **User:** Arbyam
- **Test stack:** pytest + pytest-asyncio (Python), Vitest (TS), Playwright (E2E)
- **Key paths:** `apps/api/tests/`, `apps/ingest/tests/`, `apps/web/playwright/`
- **Critical SCs:** SC-002 (idempotent IaC), SC-004 (zero public), SC-011 (isolation)

## Learnings
<!-- Append test patterns, fixture strategies, in-VNet test setup notes below -->

### Phase 1 Completion (2026-05-09)
- T010 completed; linting configuration established (ruff, eslint, bicep linting)
- Commit 1d789c9 merged to PR #2

## Team Update — 2026-05-08T22:49:14-07:00 (Scribe broadcast)

Shared facts effective immediately for all squad members:

- **\/month cost ceiling** — HARD constraint on total demo Azure spend. Supersedes any prior SKU choices. Killed APIM Premium, Bastion Standard, AI Search S1.
- **Default model = `claude-opus-4.7`** for every spawned agent (saved to `.squad/config.json`). Includes Scribe + Ralph.
- **Phase 2a/2b split** — Phase 2a = T015–T032 + T032a (IaC foundation, 17 PRs). Phase 2b = T033+ (app foundations, deferred).
- **Autonomy directive** — Lead opens PRs with `gh pr create --fill` then `gh pr merge <n> --squash --auto --delete-branch`. No "go" approvals. Escalate only for `infra/main.bicep`/`infra/modules/*` architecture changes, zero-trust weakening, unfinishable tasks, or scope creep.
- **Phase 2a v3 plan locked** — total ~\/mo, \ headroom. APIM Developer, Bastion Developer, AI Search Basic, Cosmos Serverless. See `.squad/agents/ripley/phase-2-plan.md`.

See `.squad/decisions.md` for full text.
