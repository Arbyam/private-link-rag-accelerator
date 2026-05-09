# =============================================================================
# infra/tests/run-all.ps1
# =============================================================================
# CI-friendly Pester runner for the STATIC analysis test suite (auth-free).
#
# Runtime tests (test_what_if_idempotent.ps1, test_teardown.ps1) require Azure
# credentials and a paid subscription; they are NOT invoked here. Run those
# directly via Invoke-Pester from the dedicated infra-runtime-tests workflow.
#
# Usage:
#   ./run-all.ps1                  # static suite only (default)
#   ./run-all.ps1 -IncludeRuntime  # also discover runtime tests (requires az login + envs)
# =============================================================================

[CmdletBinding()]
param(
    [string] $TestPath = $PSScriptRoot,
    [string] $OutputFormat = 'NUnitXml',
    [string] $ResultPath = $null,
    [switch] $IncludeRuntime
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

# --- Discover the static suite -------------------------------------------------
# The static suite is a curated allowlist — we explicitly enumerate the four
# files this runner is responsible for, so adding a new test_*.ps1 (e.g., a
# runtime test) doesn't accidentally enrol it in the PR-blocking suite.
$staticFiles = @(
    'test_compile.ps1'
    'test_no_public_endpoints.ps1'
    'test_no_shared_keys.ps1'
    'test_dns_zones.ps1'
)

$testFiles = @()
foreach ($name in $staticFiles) {
    $f = Join-Path $TestPath $name
    if (Test-Path $f) { $testFiles += (Get-Item $f) }
}

if ($IncludeRuntime) {
    $extra = Get-ChildItem -Path $TestPath -Filter 'test_*.ps1' -File |
        Where-Object { $_.Name -notin $staticFiles }
    $testFiles += $extra
}

if ($testFiles.Count -eq 0) {
    Write-Error "No test files discovered under $TestPath"
    exit 2
}

Write-Host "[run-all] Pester version: $($pester.Version)" -ForegroundColor Cyan
Write-Host "[run-all] Mode: $(if ($IncludeRuntime) {'static + runtime'} else {'static-only'})" -ForegroundColor Cyan
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
