<#
.SYNOPSIS
    T049 — Runtime idempotency test (SC-002).

.DESCRIPTION
    Pester v5 test that runs `azd provision` against an ephemeral resource
    group, then runs `azd provision --preview` and asserts that the second
    invocation reports ZERO changes — i.e., the bicep templates are
    idempotent under repeat application (Constitution Principle II).

    Expected runtime on a CI runner: ~75 minutes
        * azd provision (cold)        : ~60 min
        * azd provision --preview     : ~5 min
        * azd down --purge cleanup    : ~10 min

    Intended to run only in a deliberate "infra-runtime-tests" CI workflow,
    NOT on every PR (cost-prohibitive).

.PARAMETER DryRun
    If set, prints intended commands without invoking azd or az. Used for
    local sanity checking and for the CI sanity gate.

.EXAMPLE
    pwsh -File infra/tests/test_what_if_idempotent.ps1 -DryRun

.EXAMPLE
    $env:AZURE_SUBSCRIPTION_ID = '...'
    $env:AZURE_LOCATION        = 'eastus2'
    $env:AZURE_ENV_NAME        = 'pl-rag-it'
    Invoke-Pester -Path infra/tests/test_what_if_idempotent.ps1
#>

[CmdletBinding()]
param(
    [switch] $DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. "$PSScriptRoot/_lib/azd-helpers.ps1"

# Surface DryRun to the Pester block via script scope.
$script:DryRun = [bool]$DryRun

# Repository root is two levels up from this file: infra/tests/ -> repo root.
$script:RepoRoot = Resolve-Path (Join-Path $PSScriptRoot '../..')

if ($DryRun) {
    Write-Host "=== T049 dry-run: idempotency test ===" -ForegroundColor Cyan
    Write-Host "Repo root      : $script:RepoRoot"
    Write-Host "Subscription   : `$env:AZURE_SUBSCRIPTION_ID"
    Write-Host "Location       : `$env:AZURE_LOCATION"
    Write-Host "AZD env name   : `$env:AZURE_ENV_NAME"
    Write-Host ""
    Write-Host "Steps that would execute (against ephemeral RG rg-pl-rag-it-XXXXXXXX):" -ForegroundColor Cyan
    Write-Host "  1. az group create -n <rg> -l <loc>"
    Write-Host "  2. azd env new <env> --subscription <sub> --location <loc>"
    Write-Host "  3. azd provision --no-prompt                  (cold deploy)"
    Write-Host "  4. azd provision --no-prompt --preview        (assert 0 changes)"
    Write-Host "  5. azd down --purge --no-prompt --force        (cleanup)"
    Write-Host "  6. az group delete -n <rg> --yes --no-wait    (best effort)"
    Write-Host ""
    Write-Host "[DryRun] OK — no Azure resources touched." -ForegroundColor Green
    exit 0
}

$script:HasAzureEnv = $env:AZURE_SUBSCRIPTION_ID -and $env:AZURE_LOCATION -and $env:AZURE_ENV_NAME

Describe 'T049: azd provision is idempotent (SC-002)' -Tag 'Runtime', 'Idempotency' -Skip:(-not $script:HasAzureEnv) {

    BeforeAll {
        . "$PSScriptRoot/_lib/azd-helpers.ps1"
        Assert-RuntimeTestPrereqs
        $script:RG = New-EphemeralResourceGroup `
            -Location       $env:AZURE_LOCATION `
            -SubscriptionId $env:AZURE_SUBSCRIPTION_ID `
            -ReuseExisting:$false

        # azd env new is idempotent if the env already exists in .azure/<name>.
        Push-Location $script:RepoRoot
        try {
            azd env new $env:AZURE_ENV_NAME `
                --subscription $env:AZURE_SUBSCRIPTION_ID `
                --location     $env:AZURE_LOCATION 2>&1 | Out-Null
            azd env set AZURE_RESOURCE_GROUP $script:RG 2>&1 | Out-Null
        } finally {
            Pop-Location
        }
    }

    It 'completes the first azd provision run successfully' {
        $first = Invoke-AzdProvision -WorkingDirectory $script:RepoRoot -TimeoutMinutes 90
        $first.TimedOut | Should -BeFalse -Because 'azd provision must finish within the 90-minute hard timeout'
        $first.ExitCode | Should -Be 0    -Because "azd provision stderr: $($first.StdErr)"
        $first.StdOut   | Should -Match '(Deployment Succeeded|Your application was provisioned)' `
            -Because 'azd reports a success banner on a clean provision'
    }

    It 'reports zero changes on the second azd provision --preview run (SC-002)' {
        $second = Invoke-AzdProvision `
            -WorkingDirectory $script:RepoRoot `
            -ExtraArgs        @('--preview') `
            -TimeoutMinutes   30

        $second.TimedOut | Should -BeFalse
        $second.ExitCode | Should -Be 0 -Because "azd provision --preview stderr: $($second.StdErr)"

        $hasNoChanges = Test-AzdProvisionNoChanges -PreviewOutput $second.StdOut
        $hasNoChanges | Should -BeTrue -Because (
            "azd provision --preview must report zero changes for idempotency. " +
            "Actual stdout (truncated 2KB):`n" + ($second.StdOut.Substring(0, [Math]::Min(2048, $second.StdOut.Length)))
        )
    }

    AfterAll {
        . "$PSScriptRoot/_lib/azd-helpers.ps1"
        $rg = Get-Variable -Name RG -Scope Script -ValueOnly -ErrorAction SilentlyContinue
        $repoRoot = Get-Variable -Name RepoRoot -Scope Script -ValueOnly -ErrorAction SilentlyContinue
        if ($repoRoot) {
            Push-Location $repoRoot
            try {
                azd down --purge --no-prompt --force 2>&1 | Out-Null
            } catch {
                Write-Warning "azd down failed: $_"
            } finally {
                Pop-Location
            }
        }
        if ($rg) {
            Remove-EphemeralResourceGroup `
                -Name           $rg `
                -SubscriptionId $env:AZURE_SUBSCRIPTION_ID
        }
    }
}
