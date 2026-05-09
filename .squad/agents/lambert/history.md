# Lambert — History

## Project Context
- **Project:** Private RAG Accelerator (private-link-solution)
- **User:** Arbyam
- **Stack:** Next.js 15, TypeScript 5.5, Tailwind CSS 4, shadcn/ui, Vercel AI SDK 4, NextAuth
- **Key paths:** `apps/web/`, `apps/web/src/`, `apps/web/playwright/`
- **Auth:** Microsoft Entra ID, group-restricted access

## Learnings
<!-- Append UI patterns, component decisions, auth flow notes below -->

### Phase 1 Completion (2026-05-09)
- T006, T009 completed; Next.js 15 frontend and Dockerfile setup
- Package.json and Docker multi-stage build configured for production
- Commit bea363e merged to PR #2

## Team Update — 2026-05-08T22:49:14-07:00 (Scribe broadcast)

Shared facts effective immediately for all squad members:

- **\/month cost ceiling** — HARD constraint on total demo Azure spend. Supersedes any prior SKU choices. Killed APIM Premium, Bastion Standard, AI Search S1.
- **Default model = `claude-opus-4.7`** for every spawned agent (saved to `.squad/config.json`). Includes Scribe + Ralph.
- **Phase 2a/2b split** — Phase 2a = T015–T032 + T032a (IaC foundation, 17 PRs). Phase 2b = T033+ (app foundations, deferred).
- **Autonomy directive** — Lead opens PRs with `gh pr create --fill` then `gh pr merge <n> --squash --auto --delete-branch`. No "go" approvals. Escalate only for `infra/main.bicep`/`infra/modules/*` architecture changes, zero-trust weakening, unfinishable tasks, or scope creep.
- **Phase 2a v3 plan locked** — total ~\/mo, \ headroom. APIM Developer, Bastion Developer, AI Search Basic, Cosmos Serverless. See `.squad/agents/ripley/phase-2-plan.md`.

See `.squad/decisions.md` for full text.
