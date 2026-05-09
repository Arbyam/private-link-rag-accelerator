# =============================================================================
# infra/tests/run-all.ps1
# =============================================================================
# CI-friendly Pester runner for the static-analysis test suite.
#   - Runs every test_*.ps1 under infra/tests
#   - Exits 0 on full pass, 1 on any failure
#   - Suitable for invocation from GitHub Actions / azd hooks
# =============================================================================

[CmdletBinding()]
param(
    [string] $TestPath = $PSScriptRoot,
    [string] $OutputFormat = 'NUnitXml',
    [string] $ResultPath = $null
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# --- Pre-flight: Pester v5 -----------------------------------------------------
$pester = Get-Module -ListAvailable -Name Pester |
    Where-Object { $_.Version -ge [version]'5.0.0' } |
    Sort-Object Version -Descending |
    Select-Object -First 1

if (-not $pester) {
    Write-Error "Pester v5+ is not installed. Run: Install-Module -Name Pester -MinimumVersion 5.5 -Scope CurrentUser -Force"
    exit 2
}
Import-Module Pester -MinimumVersion 5.0.0 -Force

# --- Pre-flight: az + bicep ----------------------------------------------------
try {
    $null = & az --version 2>&1
} catch {
    Write-Error "Azure CLI ('az') not found in PATH."
    exit 2
}

# --- Run -----------------------------------------------------------------------
$testFiles = Get-ChildItem -Path $TestPath -Filter 'test_*.ps1' -File | Sort-Object Name
if ($testFiles.Count -eq 0) {
    Write-Error "No test_*.ps1 files found in $TestPath"
    exit 2
}

Write-Host "[run-all] Pester version: $($pester.Version)" -ForegroundColor Cyan
Write-Host "[run-all] Discovered $($testFiles.Count) test file(s):" -ForegroundColor Cyan
$testFiles | ForEach-Object { Write-Host "  - $($_.Name)" }

$cfg = New-PesterConfiguration
$cfg.Run.Path = $testFiles.FullName
$cfg.Run.PassThru = $true
$cfg.Run.Exit = $false
$cfg.Output.Verbosity = 'Detailed'

if ($ResultPath) {
    $cfg.TestResult.Enabled = $true
    $cfg.TestResult.OutputFormat = $OutputFormat
    $cfg.TestResult.OutputPath = $ResultPath
}

$sw = [System.Diagnostics.Stopwatch]::StartNew()
$result = Invoke-Pester -Configuration $cfg
$sw.Stop()

Write-Host ""
Write-Host "[run-all] Total: $($result.TotalCount)  Passed: $($result.PassedCount)  Failed: $($result.FailedCount)  Skipped: $($result.SkippedCount)  Duration: $([math]::Round($sw.Elapsed.TotalSeconds, 1))s" -ForegroundColor Cyan

if ($result.FailedCount -gt 0) { exit 1 } else { exit 0 }
