# Squad Team

> private-link-solution

## Coordinator

| Name | Role | Notes |
|------|------|-------|
| Squad | Coordinator | Routes work, enforces handoffs and reviewer gates. |

## Members

| Name | Role | Charter | Status |
|------|------|---------|--------|
| Ripley | Lead | [charter](agents/ripley/charter.md) | 🟢 Active |
| Dallas | Infra Specialist (Bicep/AVM) | [charter](agents/dallas/charter.md) | 🟢 Active |
| Kane | Backend Specialist (Python/FastAPI) | [charter](agents/kane/charter.md) | 🟢 Active |
| Lambert | Frontend Specialist (Next.js 15) | [charter](agents/lambert/charter.md) | 🟢 Active |
| Parker | Tester | [charter](agents/parker/charter.md) | 🟢 Active |
| Scribe | Session Logger | [charter](agents/scribe/charter.md) | 🟢 Active |
| Ralph | Work Monitor | [charter](agents/ralph/charter.md) | 🟢 Active |

## Project Context

- **Project:** private-link-solution (Private RAG Accelerator)
- **Created:** 2026-05-09
- **Source of truth for work**: [`specs/001-private-rag-accelerator/tasks.md`](../specs/001-private-rag-accelerator/tasks.md) (135 tasks, 11 phases, US-tagged, parallel-marked)
- **Constitution**: [`.specify/memory/constitution.md`](../.specify/memory/constitution.md) — agents MUST honor every principle, especially I (Security-First / Zero Trust) and II (Idempotent IaC)

## Operating Rules (MUST FOLLOW)

1. **Spec Kit owns the SDD lifecycle.** Squad does not re-plan, re-spec, or re-task. We execute against `tasks.md`.
2. **Architectural decisions go in `docs/decisions/` as ADRs**, not `.squad/decisions.md`. `.squad/decisions.md` is for *team coordination* notes only (who's pairing on what, retro items).
3. **Never edit `infra/` deployable Bicep without explicit human approval in chat.** Customers run `azd up` against this; correctness is non-negotiable (Constitution Principle I & II).
4. **Never weaken zero-trust posture** to "make a test pass": no public endpoints, no shared keys, no `publicNetworkAccess=Enabled`. If a task seems to require it, **escalate to the human** instead.
5. **No `squad watch --execute`** until v1.0 of the accelerator is published. Triage-only mode is fine.
6. **The customer-facing surface is sacred**: `quickstart.md`, `azure.yaml`, `.devcontainer/`, `infra/main.bicep`, and `README.md` deploy section only change via deliberate, reviewed PRs — not by background agents.
7. **All work routes through tasks.md task IDs** (e.g., "T042"). Don't invent work outside the task list without flagging it as scope creep.
8. **Parallel spawn isolation (added 2026-05-09):** Any Dallas, Kane, Lambert, or Parker agent spawned in parallel with other agents MUST work in a disposable git worktree (`git worktree add ..\wt-{slug} -b <branch>`). Sharing the main checkout between parallel agents has caused merge-train races and index pollution (3 documented occurrences during Phase 2a wave-3: PR-C, PR-E, PR-F). Worktree creation + cleanup is part of the standard spawn protocol. After PR merges: `git worktree remove ..\wt-{slug} --force; git worktree prune`.
