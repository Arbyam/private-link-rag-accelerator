# Kane — History

## Project Context
- **Project:** Private RAG Accelerator (private-link-solution)
- **User:** Arbyam
- **Stack:** Python 3.12, FastAPI 0.115+, Azure SDKs (Cosmos, Search, OpenAI, Storage, Doc Intelligence)
- **Key paths:** `apps/api/`, `apps/ingest/`, `specs/001-private-rag-accelerator/contracts/`
- **Isolation invariant:** All search queries MUST include scope filter

## Learnings
<!-- Append API patterns, SDK gotchas, auth flows, RAG pipeline decisions below -->

### Phase 1 Completion (2026-05-09)
- T004, T005, T007, T008 completed; backend setup finalized
- Python 3.12 + FastAPI runtime, Docker multi-stage builds for optimization
- Commit bea363e merged to PR #2

## Team Update — 2026-05-08T22:49:14-07:00 (Scribe broadcast)

Shared facts effective immediately for all squad members:

- **\/month cost ceiling** — HARD constraint on total demo Azure spend. Supersedes any prior SKU choices. Killed APIM Premium, Bastion Standard, AI Search S1.
- **Default model = `claude-opus-4.7`** for every spawned agent (saved to `.squad/config.json`). Includes Scribe + Ralph.
- **Phase 2a/2b split** — Phase 2a = T015–T032 + T032a (IaC foundation, 17 PRs). Phase 2b = T033+ (app foundations, deferred).
- **Autonomy directive** — Lead opens PRs with `gh pr create --fill` then `gh pr merge <n> --squash --auto --delete-branch`. No "go" approvals. Escalate only for `infra/main.bicep`/`infra/modules/*` architecture changes, zero-trust weakening, unfinishable tasks, or scope creep.
- **Phase 2a v3 plan locked** — total ~\/mo, \ headroom. APIM Developer, Bastion Developer, AI Search Basic, Cosmos Serverless. See `.squad/agents/ripley/phase-2-plan.md`.

See `.squad/decisions.md` for full text.
