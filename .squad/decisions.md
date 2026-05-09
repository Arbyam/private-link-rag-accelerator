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
