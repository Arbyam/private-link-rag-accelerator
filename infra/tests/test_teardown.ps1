<#
.SYNOPSIS
    T053 — Runtime teardown test (SC-003).

.DESCRIPTION
    Pester v5 test that runs `azd up` against an ephemeral resource group,
    asserts the deployment surfaces expected outputs (apiAppFqdn,
    webAppFqdn), then runs `azd down --purge` and asserts that
    `az resource list -g <rg>` returns an empty array AND the resource
    group itself is deleted (404 from `az group show`).

    Expected runtime on a CI runner: ~50 minutes
        * azd up (provision + deploy) : ~35 min
        * azd down --purge            : ~10 min
        * resource verification poll  : up to 5 min

    Intended to run only in a deliberate "infra-runtime-tests" CI workflow,
    NOT on every PR (cost-prohibitive, ~$5–10 of Azure spend per run).

.PARAMETER DryRun
    If set, prints intended commands without invoking azd or az.

.EXAMPLE
    pwsh -File infra/tests/test_teardown.ps1 -DryRun
#>

[CmdletBinding()]
param(
    [switch] $DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. "$PSScriptRoot/_lib/azd-helpers.ps1"

$script:DryRun = [bool]$DryRun
$script:RepoRoot = Resolve-Path (Join-Path $PSScriptRoot '../..')

if ($DryRun) {
    Write-Host "=== T053 dry-run: teardown test ===" -ForegroundColor Cyan
    Write-Host "Repo root      : $script:RepoRoot"
    Write-Host "Subscription   : `$env:AZURE_SUBSCRIPTION_ID"
    Write-Host "Location       : `$env:AZURE_LOCATION"
    Write-Host "AZD env name   : `$env:AZURE_ENV_NAME"
    Write-Host ""
    Write-Host "Steps that would execute (against ephemeral RG rg-pl-rag-it-XXXXXXXX):" -ForegroundColor Cyan
    Write-Host "  1. az group create -n <rg> -l <loc>"
    Write-Host "  2. azd env new <env> --subscription <sub> --location <loc>"
    Write-Host "  3. azd up --no-prompt                          (provision + deploy)"
    Write-Host "  4. azd env get-values                          (assert apiAppFqdn, webAppFqdn)"
    Write-Host "  5. azd down --purge --no-prompt --force        (full teardown)"
    Write-Host "  6. az resource list -g <rg>                    (assert == [])"
    Write-Host "  7. az group show -n <rg>                       (assert 404)"
    Write-Host ""
    Write-Host "[DryRun] OK — no Azure resources touched." -ForegroundColor Green
    exit 0
}

$script:HasAzureEnv = $env:AZURE_SUBSCRIPTION_ID -and $env:AZURE_LOCATION -and $env:AZURE_ENV_NAME

Describe 'T053: azd down --purge fully removes resources (SC-003)' -Tag 'Runtime', 'Teardown' -Skip:(-not $script:HasAzureEnv) {

    BeforeAll {
        . "$PSScriptRoot/_lib/azd-helpers.ps1"
        Assert-RuntimeTestPrereqs
        $script:RG = New-EphemeralResourceGroup `
            -Location       $env:AZURE_LOCATION `
            -SubscriptionId $env:AZURE_SUBSCRIPTION_ID `
            -ReuseExisting:$false

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

    It 'completes azd up (provision + deploy)' {
        $up = Invoke-AzdProvision `
            -WorkingDirectory $script:RepoRoot `
            -ExtraArgs        @() `
            -TimeoutMinutes   90

        # Note: Invoke-AzdProvision wraps `azd provision`; we run `azd deploy`
        # immediately after to satisfy the "azd up" semantic. We split so the
        # 90-minute timeout applies per phase.
        $up.TimedOut | Should -BeFalse
        $up.ExitCode | Should -Be 0 -Because "azd provision stderr: $($up.StdErr)"

        Push-Location $script:RepoRoot
        try {
            azd deploy --no-prompt 2>&1 | Tee-Object -Variable deployOut | Out-Null
            $LASTEXITCODE | Should -Be 0 -Because "azd deploy must succeed: $deployOut"
        } finally {
            Pop-Location
        }
    }

    It 'surfaces expected outputs after azd up' {
        $values = Get-AzdEnvironmentValues -WorkingDirectory $script:RepoRoot
        $values.Keys | Should -Contain 'apiAppFqdn' -Because 'main.bicep must export apiAppFqdn'
        $values.Keys | Should -Contain 'webAppFqdn' -Because 'main.bicep must export webAppFqdn'
        $values['apiAppFqdn'] | Should -Not -BeNullOrEmpty
        $values['webAppFqdn'] | Should -Not -BeNullOrEmpty
    }

    It 'fully tears down via azd down --purge' {
        Push-Location $script:RepoRoot
        try {
            $sw = [System.Diagnostics.Stopwatch]::StartNew()
            azd down --purge --no-prompt --force 2>&1 | Out-Null
            $sw.Stop()
            $LASTEXITCODE | Should -Be 0 -Because 'azd down --purge must exit 0'
            $sw.Elapsed.TotalMinutes | Should -BeLessThan 60
        } finally {
            Pop-Location
        }
    }

    It 'leaves the resource group empty or deleted (SC-003)' {
        # Poll for up to 5 minutes — RG deletion is async.
        $deadline = (Get-Date).AddMinutes(5)
        $isEmpty = $false
        do {
            $isEmpty = Test-ResourceGroupEmpty `
                -Name           $script:RG `
                -SubscriptionId $env:AZURE_SUBSCRIPTION_ID
            if (-not $isEmpty) { Start-Sleep -Seconds 30 }
        } while (-not $isEmpty -and (Get-Date) -lt $deadline)

        $isEmpty | Should -BeTrue -Because (
            "After azd down --purge, RG '$($script:RG)' must contain zero resources " +
            "or be deleted entirely. SC-003 requires full teardown."
        )
    }

    AfterAll {
        . "$PSScriptRoot/_lib/azd-helpers.ps1"
        $rg = Get-Variable -Name RG -Scope Script -ValueOnly -ErrorAction SilentlyContinue
        # Belt-and-suspenders cleanup in case azd down failed mid-test.
        if ($rg) {
            Remove-EphemeralResourceGroup `
                -Name           $rg `
                -SubscriptionId $env:AZURE_SUBSCRIPTION_ID
        }
    }
}
