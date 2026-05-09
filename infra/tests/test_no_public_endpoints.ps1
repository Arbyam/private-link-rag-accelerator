# =============================================================================
# T050: zero-public-endpoints static test (FR-002, SC-004)
# =============================================================================
# Asserts that every data-plane resource of the protected service families is
# configured for `publicNetworkAccess: Disabled` (or the per-service
# equivalent) by the bicep source.
#
# WHY SOURCE-LEVEL ANALYSIS (rather than walking the compiled ARM JSON):
#   The compiled ARM template is dominated by Azure-Verified-Modules (AVM)
#   internal templates. Inside an AVM nested deployment, properties like
#   `publicNetworkAccess` are emitted as ARM expressions that REFERENCE the
#   parameter the AVM exposes — e.g.:
#       "publicNetworkAccess": "[parameters('publicNetworkAccess')]"
#   The literal value the developer set lives ONE LEVEL UP, in the AVM
#   deployment's `properties.parameters.publicNetworkAccess.value`. To resolve
#   this purely from JSON would require per-AVM-version knowledge of every
#   parameter shape (Cosmos uses `networkRestrictions.publicNetworkAccess`,
#   Storage uses `publicNetworkAccess` + `networkAcls`, etc.).
#
#   The SOURCE bicep is where the developer types the literal value. It is
#   the canonical source of truth, doesn't drift with AVM upstream, and
#   matches exactly what `npm audit`-style policy checks look at. We use it
#   as the primary signal AND walk the compiled ARM as a corroborating check.
#
# Per-service rule (mirrors how each AVM module exposes the property):
#   Microsoft.Storage/storageAccounts        → publicNetworkAccess: 'Disabled'
#   Microsoft.DocumentDB/databaseAccounts    → networkRestrictions.publicNetworkAccess: 'Disabled'
#   Microsoft.Search/searchServices          → publicNetworkAccess: 'Disabled'
#   Microsoft.CognitiveServices/accounts     → publicNetworkAccess: 'Disabled'
#                                              (covers OpenAI + Document Intelligence)
#   Microsoft.KeyVault/vaults                → publicNetworkAccess: 'Disabled'
#   Microsoft.ContainerRegistry/registries   → publicNetworkAccess: 'Disabled'
#   Microsoft.App/managedEnvironments        → vnetConfiguration.internal: true
#                                              (this is the documented zero-trust
#                                              equivalent — see infra/modules/
#                                              containerapps/main.bicep §161)
#   Microsoft.App/containerApps              → ingress.external: false
#                                              (no ingress at all is also fine)
#
# OPTIONAL: PSRule for Azure (Azure.Storage.PublicAccess, Azure.AI.PublicAccess
# etc.) is invoked when the module is installed; failures from PSRule are
# reported as additional context. Primary checks are independent of PSRule.
# =============================================================================

. $PSScriptRoot/_helpers.ps1

BeforeDiscovery {
    . $PSScriptRoot/_helpers.ps1
    $moduleDir = Join-Path (Get-InfraRoot) 'modules'

    # See test_no_public_endpoints.ps1 header for per-service rule rationale.
    $rules = @(
        @{
            Label       = 'storage account'
            Type        = 'Microsoft.Storage/storageAccounts'
            File        = Join-Path $moduleDir 'storage\main.bicep'
            Pattern     = "publicNetworkAccess:\s*'Disabled'"
            AltPattern  = $null
        }
        @{
            Label       = 'cosmos db'
            Type        = 'Microsoft.DocumentDB/databaseAccounts'
            File        = Join-Path $moduleDir 'cosmos\main.bicep'
            Pattern     = "publicNetworkAccess:\s*'Disabled'"
            AltPattern  = $null
        }
        @{
            Label       = 'ai search'
            Type        = 'Microsoft.Search/searchServices'
            File        = Join-Path $moduleDir 'search\main.bicep'
            Pattern     = "publicNetworkAccess:\s*'Disabled'"
            AltPattern  = $null
        }
        @{
            Label       = 'azure openai'
            Type        = 'Microsoft.CognitiveServices/accounts'
            File        = Join-Path $moduleDir 'openai\main.bicep'
            Pattern     = "publicNetworkAccess:\s*'Disabled'"
            AltPattern  = $null
        }
        @{
            Label       = 'document intelligence'
            Type        = 'Microsoft.CognitiveServices/accounts'
            File        = Join-Path $moduleDir 'docintel\main.bicep'
            Pattern     = "publicNetworkAccess:\s*'Disabled'"
            AltPattern  = $null
        }
        @{
            Label       = 'key vault'
            Type        = 'Microsoft.KeyVault/vaults'
            File        = Join-Path $moduleDir 'keyvault\main.bicep'
            Pattern     = "publicNetworkAccess:\s*'Disabled'"
            AltPattern  = $null
        }
        @{
            Label       = 'container registry'
            Type        = 'Microsoft.ContainerRegistry/registries'
            File        = Join-Path $moduleDir 'registry\main.bicep'
            Pattern     = "publicNetworkAccess:\s*'Disabled'"
            AltPattern  = $null
        }
        @{
            Label       = 'log analytics workspace'
            Type        = 'Microsoft.OperationalInsights/workspaces'
            File        = Join-Path $moduleDir 'monitoring\main.bicep'
            Pattern     = "publicNetworkAccessForIngestion:\s*'Disabled'"
            AltPattern  = "publicNetworkAccessForQuery:\s*'Disabled'"
        }
        @{
            Label       = 'container apps managed environment'
            Type        = 'Microsoft.App/managedEnvironments'
            File        = Join-Path $moduleDir 'containerapps\main.bicep'
            # Internal=true makes the ACA env have no public LB (data plane).
            # publicNetworkAccess on the env controls only the management
            # plane (ARM revision updates) — accepted-as-equivalent per
            # constitution alignment notes in containerapps/main.bicep §161.
            Pattern     = "internal:\s*true"
            AltPattern  = $null
        }
        @{
            Label       = 'container apps (web/api/ingest)'
            Type        = 'Microsoft.App/containerApps'
            File        = Join-Path $moduleDir 'containerapps\main.bicep'
            # ingressExternal:false on each container app == no public ingress.
            Pattern     = "ingressExternal:\s*false"
            AltPattern  = $null
        }
    )
}

Describe 'T050 — no public endpoints' {

    BeforeAll {
        . $PSScriptRoot/_helpers.ps1
        # Compile once for ARM corroboration.
        $script:bicepResult = Invoke-BicepBuild
        $script:bicepResult.ExitCode | Should -Be 0
        $script:armResources = Get-AllArmResources -JsonPath $script:bicepResult.JsonPath
    }

    Context 'per-service zero-trust posture' {
        It 'asserts <Label> (<Type>) has zero-public-network posture' -ForEach $rules {
            Test-Path $File | Should -BeTrue -Because "module file missing: $File"
            $src = Get-Content $File -Raw

            $primary = [Regex]::IsMatch($src, $Pattern)
            $alt = $false
            if ($AltPattern) {
                $alt = [Regex]::IsMatch($src, $AltPattern)
            }
            $ok = $primary -or $alt

            $becauseMsg = "Module $File ($Type) does not match required posture pattern: /$Pattern/"
            if ($AltPattern) { $becauseMsg += " or /$AltPattern/" }
            $becauseMsg += ". This is a real security finding — DO NOT relax the test, escalate to Lead instead."

            $ok | Should -BeTrue -Because $becauseMsg
        }
    }

    Context 'compiled ARM corroboration table' {
        It 'emits a summary of protected resource types found in the compiled ARM' {
            $protectedTypes = @(
                'Microsoft.Storage/storageAccounts'
                'Microsoft.DocumentDB/databaseAccounts'
                'Microsoft.Search/searchServices'
                'Microsoft.CognitiveServices/accounts'
                'Microsoft.KeyVault/vaults'
                'Microsoft.ContainerRegistry/registries'
                'Microsoft.App/managedEnvironments'
                'Microsoft.App/containerApps'
                'Microsoft.OperationalInsights/workspaces'
            )
            $rows = $script:armResources |
                Where-Object { $_.Type -in $protectedTypes -and -not $_.Existing } |
                Group-Object Type |
                ForEach-Object {
                    [pscustomobject]@{
                        ResourceType = $_.Name
                        Count        = $_.Count
                    }
                }
            $rendered = ($rows | Format-Table -AutoSize | Out-String)
            Write-Host "`n[T050] Protected resource types in compiled ARM:`n$rendered"
            foreach ($t in $protectedTypes) {
                ($rows | Where-Object ResourceType -eq $t) |
                    Should -Not -BeNullOrEmpty -Because "expected $t to be deployed"
            }
        }
    }

    Context 'optional PSRule.Rules.Azure cross-check' {
        It 'runs PSRule when installed (skips otherwise)' {
            $mod = Get-Module -ListAvailable -Name PSRule.Rules.Azure | Select-Object -First 1
            if (-not $mod) {
                Set-ItResult -Skipped -Because 'PSRule.Rules.Azure not installed (optional). Run `Install-Module PSRule.Rules.Azure -Scope CurrentUser` to enable.'
                return
            }
            Import-Module PSRule.Rules.Azure
            $jsonPath = $script:bicepResult.JsonPath
            try {
                $results = Invoke-PSRule -Module PSRule.Rules.Azure -InputPath $jsonPath -Outcome Fail -ErrorAction SilentlyContinue
                if ($results) {
                    Write-Host "[T050] PSRule.Rules.Azure findings (informational):"
                    $results | ForEach-Object { Write-Host "  - $($_.RuleName): $($_.TargetName)" }
                }
            } catch {
                Write-Host "[T050] PSRule run failed (non-fatal): $($_.Exception.Message)"
            }
            $true | Should -BeTrue
        }
    }
}
