# `infra/tests/` — Bicep / azd test suite

Tests for the `infra/` Bicep templates and `azd` deployment orchestration.

## Test categories

| Category        | When it runs                              | Cost          | Tasks                  |
|-----------------|-------------------------------------------|---------------|------------------------|
| **Static**      | Every PR (Pester v5, no Azure auth)        | $0            | T048, T050, T051, T052 |
| **Runtime**     | Deliberate "infra-runtime-tests" workflow | ~$5–$10/run   | T049, T053             |

Static tests are pure-analysis on the Bicep source plus the JSON ARM template
emitted by `az bicep build` — no subscription, no `az login`, no money spent.
Runtime tests provision **real** Azure resources against an ephemeral
resource group (`rg-pl-rag-it-{8-char-hex}`) and tear them down at the end;
they are **gated** — do **NOT** run them on every PR.

---

## Static tests (T048 + T050 + T051 + T052)

> Implements **FR-002** (no public endpoints), **FR-003** (no shared keys),
> **FR-005** (Private DNS zones), and **SC-004** (zero-trust posture) as
> machine-checked gates. **Auth-free, offline-friendly, < 60 s.**

### What the static suite covers

| File                              | Task | Asserts                                                                                                                       |
| --------------------------------- | ---- | ----------------------------------------------------------------------------------------------------------------------------- |
| `test_compile.ps1`                | T048 | `az bicep build` exits 0 with zero warnings/errors; `az bicep lint` is clean; required parameters are declared on `main.bicep` |
| `test_no_public_endpoints.ps1`    | T050 | Each module sets `publicNetworkAccess: 'Disabled'` (or the documented per-service equivalent — e.g., `internal: true` for ACA) |
| `test_no_shared_keys.ps1`         | T051 | No `listKeys` / `connectionString` / `accountKey` / `primaryKey` references in bicep source outside the AMPLS allowlist        |
| `test_dns_zones.ps1`              | T052 | Every well-known privatelink zone is declared & VNet-linked in the network module; every PE resolves to the matching zone     |

The runner `run-all.ps1` wraps all four under a single Pester invocation
with a CI-friendly exit code.

### Prerequisites

```powershell
# PowerShell 7+ (5.1 also works for the static tests)
Install-Module -Name Pester              -MinimumVersion 5.5  -Scope CurrentUser -Force
Install-Module -Name PSRule.Rules.Azure                       -Scope CurrentUser -Force   # OPTIONAL, used by T050

# Azure CLI with the bicep extension (already required by the repo).
az bicep version
```

### How to run

```powershell
# All four tests at once:
./infra/tests/run-all.ps1

# CI mode with a NUnit result file:
./infra/tests/run-all.ps1 -ResultPath ./infra/tests/.cache/results.xml

# A single test:
Invoke-Pester -Path ./infra/tests/test_compile.ps1
```

`run-all.ps1` exits **0** on full pass and **1** on any failure (or 2 on
missing prerequisites).

### Expected runtime

| Phase                                                          | Cost     |
| -------------------------------------------------------------- | -------- |
| First run (compiles `main.bicep`, ≈3.6 MB ARM JSON)            | 10–25 s  |
| Subsequent runs in same shell (cached compile under `.cache/`) | 3–8 s    |
| Full suite end-to-end on cold cache                            | < 60 s   |

The `.cache/` subdirectory is emitted next to the test scripts and re-used
by all four tests in one `run-all` invocation; it is git-ignored.

### Design notes — why source-level checks?

The compiled ARM template is dominated by **Azure Verified Modules** (AVM)
internal templates. Inside an AVM nested deployment, properties such as
`publicNetworkAccess` show up as ARM expressions that *reference* the AVM's
own parameter:

```jsonc
"publicNetworkAccess": "[parameters('publicNetworkAccess')]"
```

The literal value the developer typed lives one level up, in the AVM
deployment’s `properties.parameters.publicNetworkAccess.value`, and the
parameter shape varies per AVM (e.g., Cosmos uses
`networkRestrictions.publicNetworkAccess`, Storage uses `publicNetworkAccess`
+ `networkAcls`). Resolving these purely from the JSON would require
per-AVM-version knowledge, drift with upstream releases, and produce false
positives whenever AVM ships a new gated feature.

For T050, T051 and T052 we therefore:
- **Primary signal:** regex assertions against `infra/modules/*/main.bicep`
  — the file the developer types and reviews. This is canonical and stable.
- **Corroboration:** every test still runs `az bicep build` to detect
  missing zones, missing PE declarations, broken parameter wiring, etc. —
  anything where the *shape* of the compiled ARM matters.

T048 is purely about compile success (no module-level introspection needed)
so it operates only on the compiled output.

### Allowlist for T051 (FR-003 shared-keys)

Allowed exceptions (each documented in `test_no_shared_keys.ps1`):

1. **Application Insights connection string** referenced via the
   AMPLS-protected ingestion path. Required by AppInsights SDKs to know
   which AI resource to target; not a data-plane shared key. Routed through
   Key Vault `SecureString` to APIM (PR-W).

Anything else (e.g., a new `listKeys()` call) **fails the test** and must
be either removed or escalated to Lead with a documented rationale before
the allowlist is widened.

### Scope guard

These tests **never** modify `infra/main.bicep` or any module. If a test
surfaces a real issue (e.g., a resource missing `publicNetworkAccess:
'Disabled'`), the test fails loudly and the finding is escalated via
`.squad/decisions/inbox/`. **Do not relax a test to make it pass** — that
defeats the entire point of the gate.

---

## Runtime tests (T049 + T053)

### Files

| Test                              | Task | Spec  | Approx. runtime |
|-----------------------------------|------|-------|-----------------|
| `test_what_if_idempotent.ps1`     | T049 | SC-002 | ~75 min        |
| `test_teardown.ps1`               | T053 | SC-003 | ~50 min        |

Shared helpers live in `_lib/azd-helpers.ps1` (dot-sourced by each test).

### Required environment variables

| Var                       | Example          | Purpose                                  |
|---------------------------|------------------|------------------------------------------|
| `AZURE_SUBSCRIPTION_ID`   | `00000000-…`     | Target subscription for the ephemeral RG |
| `AZURE_LOCATION`          | `eastus2`        | Region for all resources                 |
| `AZURE_ENV_NAME`          | `pl-rag-it`      | `azd` environment name                   |

If any of these are missing the test fails fast with a clear message.

### Required Azure permissions

The CI principal (service principal or workload identity) MUST have:

* **Contributor** at the subscription scope (the tests create and delete
  resource groups), **OR**
* **Owner** at a parent management group, **OR**
* **Contributor** + a custom role with `Microsoft.Resources/subscriptions/resourceGroups/write`
  at the subscription scope.

For Private Endpoint creation specifically, the principal also needs
`Microsoft.Network/virtualNetworks/subnets/join/action` on the deployed VNet
— this is satisfied automatically when Contributor is granted at the
subscription scope.

### Required tooling on the CI runner

* PowerShell 7+
* [Pester](https://pester.dev/) v5.0.0+
* [PSScriptAnalyzer](https://learn.microsoft.com/powershell/utility-modules/psscriptanalyzer/overview) (for the lint gate)
* [Azure CLI](https://learn.microsoft.com/cli/azure/) 2.60+ with the `bicep`
  extension installed
* [Azure Developer CLI (`azd`)](https://learn.microsoft.com/azure/developer/azure-developer-cli/) 1.10.0+

### Local sanity check (`-DryRun`)

Both runtime test scripts honor a `-DryRun` switch that prints the commands
they *would* execute without invoking `azd` or `az`. Use this to verify
script wiring without burning Azure credits:

```pwsh
pwsh -File infra/tests/test_what_if_idempotent.ps1 -DryRun
pwsh -File infra/tests/test_teardown.ps1           -DryRun
```

Both must exit 0 with no Azure calls.

### Running the tests for real

```pwsh
$env:AZURE_SUBSCRIPTION_ID = '<sub-id>'
$env:AZURE_LOCATION        = 'eastus2'
$env:AZURE_ENV_NAME        = 'pl-rag-it'

# Logged in via az login + azd auth login first.
Invoke-Pester -Path infra/tests/test_what_if_idempotent.ps1 -PassThru
Invoke-Pester -Path infra/tests/test_teardown.ps1           -PassThru
```

Each test:

1. Creates an ephemeral RG with a random 8-char hex suffix.
2. Provisions / deploys / verifies / tears down.
3. Best-effort cleans the RG in `AfterAll` even on failure (with retries).

If a previous run left a stranded RG, you can clean it manually:

```pwsh
az group list --query "[?starts_with(name, 'rg-pl-rag-it-')].name" -o tsv |
  ForEach-Object { az group delete -n $_ --yes --no-wait }
```

### Cost expectations

A single full run of either test deploys the entire stack: APIM (Std v2),
Azure OpenAI, AI Search, Document Intelligence, Cosmos DB, Container Apps
Environment, Container Registry, Storage, Key Vault, VNet + Bastion, etc.

Approximate spend per run: **$5–$10 USD**, dominated by APIM Std v2 and
Cosmos DB minimum hourly charges. Teardown is asynchronous; some resources
may continue billing for a few minutes after `azd down` returns.

### CI workflow note

These tests are deliberately **not** wired into the default PR workflow.
A future "infra-runtime-tests" workflow (manual `workflow_dispatch` +
nightly schedule against `main`) is the intended trigger. That workflow is
out of scope for the initial implementation tasks T049/T053; they ship as
test scripts the workflow can call.

### Anomaly escalation

If `test_what_if_idempotent.ps1` consistently reports non-zero changes on
the second run, the bicep templates have an idempotency bug (typically a
`utcNow()` default in a parameter, or a non-deterministic name collision).
Do **not** weaken the assertion — file an entry in
`.squad/decisions/inbox/` and escalate to Lead.
