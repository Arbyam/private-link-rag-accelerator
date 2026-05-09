# AVM Audit — T031 (2026-05-08)

One-shot artifact summarizing the Azure Verified Modules (AVM) baseline for every
infrastructure module under `infra/modules/*`. Generated as part of T031
(AVM refactor + version alignment). PR-Q's `infra/README.md` references this
file as the canonical AVM-pin index.

## Methodology

1. Enumerated every `br/public:avm/*` reference across `infra/modules/*/main.bicep`.
2. Queried [`mcr.microsoft.com`](https://mcr.microsoft.com/v2/bicep/avm/res) for
   the published tag list of each AVM module.
3. For each module behind latest, attempted a version bump and re-ran
   `az bicep build` on the module **and** on `infra/main.bicep`.
4. Held back any bump that broke the module's input contract (PR-O wiring layer
   depends on inputs being stable).
5. Confirmed accelerator-specific glue stays hand-rolled where AVM has no
   equivalent or where the hand-rolled shape is intentionally tighter.

Per [decision 2026-05-09](../.squad/decisions.md) (AVM version pinning policy):
all AVM references are pinned to a specific published version — never `latest`,
never a floating range.

## Per-module AVM version table

| # | Module | AVM ref | Before | After | Notes |
|---|--------|---------|--------|-------|-------|
| 1 | network | `network/private-dns-zone` | 0.7.1 | **0.8.1** | Bumped — clean build. VNet/subnets/NSGs stay hand-rolled (heavily customized; AVM `virtual-network` adds no value). |
| 2 | identity | `managed-identity/user-assigned-identity` | 0.4.1 | **0.5.1** | Bumped — clean build for all three MIs (api/ingest/web). |
| 3 | monitoring | `operational-insights/workspace` | 0.15.1 | 0.15.1 | Already latest. AMPLS bundle stays hand-rolled (no AVM coverage). |
| 3 | monitoring | `insights/component` | 0.7.1 | 0.7.1 | Already latest. |
| 4 | registry | `container-registry/registry` | 0.12.1 | 0.12.1 | Already latest. |
| 5 | keyvault | `key-vault/vault` | 0.13.3 | 0.13.3 | Already latest. |
| 6 | storage | `storage/storage-account` | 0.27.1 | **0.32.0** | Bumped 5 minor versions — clean build. Event Grid system topic + subscription stay hand-rolled (no AVM coverage). |
| 7 | cosmos | `document-db/database-account` | 0.15.1 | **0.16.0** | Bumped one minor — clean. **Held back 0.17.0+**: AVM dropped the `sqlDatabases` parameter (containers must now be authored as standalone resources) and renamed `automaticFailover` → `enableAutomaticFailover`. Both are breaking for the current module shape; deferred to a follow-up refactor. SQL data-plane RBAC stays hand-rolled per [decisions.md](../.squad/decisions.md). |
| 8 | openai | `cognitive-services/account` | 0.13.2 | **0.14.2** | Bumped — clean. AVM still applies `@batchSize(1)` to `deployments` (race-mitigation we depend on). |
| 9 | search | `search/search-service` | 0.12.1 | 0.12.1 | Already latest. |
| 10 | docintel | `cognitive-services/account` | 0.13.0 | **0.14.2** | Bumped + aligned with `openai` module to keep the cognitive-services AVM shape consistent across both consumers. |
| 11 | containerapps | `app/managed-environment` | 0.13.3 | 0.13.3 | Already latest. |
| 11 | containerapps | `app/container-app` | 0.22.1 | 0.22.1 | Already latest (used twice — web + api). |
| 11 | containerapps | `app/job` | 0.7.1 | 0.7.1 | Already latest. |
| 12 | bastion | `network/bastion-host` | 0.8.2 | 0.8.2 | Already latest. Jumpbox VM stays hand-rolled (no AVM equivalent for the cloud-init workflow). |
| 13 | apim | `api-management/service` | 0.14.1 | 0.14.1 | Already latest. |

**Bumps:** 6 modules (`network`, `identity`, `storage`, `cosmos`, `openai`, `docintel`).
**Already-on-latest:** 7 modules (`monitoring`, `registry`, `keyvault`, `search`,
`containerapps`, `bastion`, `apim`).
**Held-back bumps:** 1 (`cosmos` from 0.16.0 → 0.17.0+; documented inline in
`infra/modules/cosmos/main.bicep`).

## Hand-rolled glue (intentional, stays as-is)

These pieces are intentionally not AVM. Each is either accelerator-specific
(no AVM coverage) or deliberately tighter than what AVM offers. PR-O's wiring
layer depends on the current shape — do not refactor without coordinating with
the wiring owner.

| Module | Hand-rolled component | Why it stays hand-rolled |
|--------|-----------------------|--------------------------|
| network | VNet + 6 subnets + 6 NSGs + service-endpoint policies | Heavily customized: APIM management-plane NSG rules, Bastion NSG rules, AzureBastionSubnet name constraint, ACA delegation. AVM `virtual-network` would add a wrapping layer with no shape benefit. |
| monitoring | AMPLS (Azure Monitor Private Link Scope) bundle | No AVM module exists for `Microsoft.Insights/privateLinkScopes`. The bundle composes AMPLS + 5 scoped resources + 1 PE + 1 DNS zone group. |
| cosmos | SQL data-plane role definitions + role assignments | Per [decisions.md](../.squad/decisions.md): emitted by the wiring layer (PR-O / T029) so the same resource graph can fan out role assignments to multiple principals. AVM's `sqlRoleAssignments` parameter cannot express the cross-module fan-out we need. |
| storage | Event Grid system topic + subscription for blob events | No AVM coverage for system-topic-bound subscriptions in the storage module. |
| bastion | Jumpbox VM (Linux + cloud-init) | The cloud-init workflow installs the toolchain (azd, az, gh, docker, etc.) the SE uses for in-VNet runs. AVM `compute/virtual-machine` does not model the cloud-init / customData shape we need without losing the authoring clarity. |
| `infra/main.bicep` | Composition layer | Per task instructions: this layer wires modules together and is owned by PR-O. Not in scope for this audit. |
| (cross-cutting) | Scope-RBAC fan-out (T029) | Hand-rolled module that emits role assignments at multiple scopes (Cosmos data-plane, Storage, Search, ACR, Key Vault) for multiple principals (api MI, ingest MI, web MI, deployer). AVM's per-resource `roleAssignments` parameter cannot express the cross-resource fan-out matrix. |

## Validation

- `az bicep build --file infra/main.bicep` exits 0 with zero warnings.
- Every changed module's `main.bicep` builds clean in isolation.
- No SKU bumps, no input/output contract changes, no `infra/main.bicep` edits.
- Cost lock at $318/mo (per Ripley's Phase 2 plan) is not touched.

## Re-audit cadence

This document was generated on 2026-05-08. Re-audit:

- Before any infra hardening PR that touches an AVM module.
- Quarterly, or when a tracked AVM module ships a release with security-relevant
  changes.
- Whenever the `cosmos` module is opened — the held-back 0.17.0+ migration
  should be considered each time.
