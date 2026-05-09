# Infra tests

Tests for the `infra/` Bicep templates and `azd` deployment orchestration.

## Test categories

| Category        | When it runs                              | Cost     |
|-----------------|-------------------------------------------|----------|
| **Unit / lint** | Every PR (bicep build, PSScriptAnalyzer)  | $0       |
| **Runtime**     | Deliberate "infra-runtime-tests" workflow | ~$5–10/run |

Runtime tests provision **real** Azure resources against an ephemeral
resource group (`rg-pl-rag-it-{8-char-hex}`) and tear them down at the end.
They are **gated** — do **NOT** run them on every PR.

---

## Runtime tests

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
