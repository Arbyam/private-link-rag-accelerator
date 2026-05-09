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
