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
