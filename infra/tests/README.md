# `infra/tests/` — static analysis suite (Pester v5)

> Tasks: **T048 + T050 + T051 + T052**
>
> Implements **FR-002** (no public endpoints), **FR-003** (no shared keys),
> **FR-005** (Private DNS zones), and **SC-004** (zero-trust posture) as
> machine-checked gates. **Auth-free, offline-friendly, < 60 s on a clean
> machine.**

## What it covers

| File                              | Task | Asserts                                                                                                                       |
| --------------------------------- | ---- | ----------------------------------------------------------------------------------------------------------------------------- |
| `test_compile.ps1`                | T048 | `az bicep build` exits 0 with zero warnings/errors; `az bicep lint` is clean; required parameters are declared on `main.bicep` |
| `test_no_public_endpoints.ps1`    | T050 | Each module sets `publicNetworkAccess: 'Disabled'` (or the documented per-service equivalent — e.g., `internal: true` for ACA) |
| `test_no_shared_keys.ps1`         | T051 | No `listKeys` / `connectionString` / `accountKey` / `primaryKey` references in bicep source outside the AMPLS allowlist        |
| `test_dns_zones.ps1`              | T052 | Every well-known privatelink zone is declared & VNet-linked in the network module; every PE resolves to the matching zone     |

The corresponding runtime tests (T049 deployment validation, T053 PSRule baseline run with auth) live under their own task IDs and **do** require Azure credentials.

## Prerequisites

```powershell
# PowerShell 7+ (5.1 also works for the tests, but azd / az auth ergonomics are better in 7+)
Install-Module -Name Pester              -MinimumVersion 5.5  -Scope CurrentUser -Force
Install-Module -Name PSRule.Rules.Azure                       -Scope CurrentUser -Force   # OPTIONAL, used by T050

# Azure CLI with the bicep extension (already required by the repo).
az bicep version
```

The suite makes **no Azure-management calls**: it never logs in, never validates against a subscription, never reads parameters at deployment scope. Everything is static analysis on `infra/main.bicep` plus the JSON ARM template emitted by `az bicep build`.

## How to run

```powershell
# All four tests at once:
./infra/tests/run-all.ps1

# CI mode with a NUnit result file:
./infra/tests/run-all.ps1 -ResultPath ./infra/tests/.cache/results.xml

# A single test:
Invoke-Pester -Path ./infra/tests/test_compile.ps1
```

`run-all.ps1` exits **0** on full pass and **1** on any failure (or 2 on missing prerequisites).

### Expected runtime

| Phase                                                          | Cost     |
| -------------------------------------------------------------- | -------- |
| First run (compiles `main.bicep`, ≈3.6 MB ARM JSON)            | 10–25 s  |
| Subsequent runs in same shell (cached compile under `.cache/`) | 3–8 s    |
| Full suite end-to-end on cold cache                            | < 60 s   |

The `.cache/` subdirectory is emitted next to the test scripts and re-used by all four tests in one `run-all` invocation; it is git-ignored.

## Design notes — why source-level checks?

The compiled ARM template is dominated by **Azure Verified Modules** (AVM) internal templates. Inside an AVM nested deployment, properties such as `publicNetworkAccess` show up as ARM expressions that *reference* the AVM's own parameter:

```jsonc
"publicNetworkAccess": "[parameters('publicNetworkAccess')]"
```

The literal value the developer typed lives one level up, in the AVM deployment’s `properties.parameters.publicNetworkAccess.value`, and the parameter shape varies per AVM (e.g., Cosmos uses `networkRestrictions.publicNetworkAccess`, Storage uses `publicNetworkAccess` + `networkAcls`). Resolving these purely from the JSON would require per-AVM-version knowledge, drift with upstream releases, and produce false positives whenever AVM ships a new gated feature.

For T050, T051 and T052 we therefore:
- **Primary signal:** regex assertions against `infra/modules/*/main.bicep` — the file the developer types and reviews. This is canonical and stable.
- **Corroboration:** every test still runs `az bicep build` to detect missing zones, missing PE declarations, broken parameter wiring, etc. — anything where the *shape* of the compiled ARM matters.

T048 is purely about compile success (no module-level introspection needed) so it operates only on the compiled output.

## Allowlist for T051 (FR-003 shared-keys)

Allowed exceptions (each documented in `test_no_shared_keys.ps1`):

1. **Application Insights connection string** referenced via the AMPLS-protected ingestion path. Required by AppInsights SDKs to know which AI resource to target; not a data-plane shared key. Routed through Key Vault `SecureString` to APIM (PR-W).

Anything else (e.g., a new `listKeys()` call) **fails the test** and must be either removed or escalated to Lead with a documented rationale before the allowlist is widened.

## Scope guard

These tests **never** modify `infra/main.bicep` or any module. If a test surfaces a real issue (e.g., a resource missing `publicNetworkAccess: 'Disabled'`), the test fails loudly and the finding is escalated via `.squad/decisions/inbox/`. **Do not relax a test to make it pass** — that defeats the entire point of the gate.
