<#
.SYNOPSIS
    Reusable helpers for runtime infra tests (T049, T053).

.DESCRIPTION
    Functions that wrap Azure CLI / Azure Developer CLI (azd) interactions
    for the Pester-based runtime test suite. Designed to be dot-sourced from
    individual test scripts:

        . "$PSScriptRoot/_lib/azd-helpers.ps1"

    All long-running operations honor a -DryRun parameter that prints the
    intended command instead of executing it.

.NOTES
    Required tooling on the CI runner:
        * PowerShell 7+
        * Pester v5+
        * Azure CLI 2.60+ (with bicep extension)
        * Azure Developer CLI (azd) 1.10.0+
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Assert-RuntimeTestPrereqs {
    <#
    .SYNOPSIS
        Validates required env vars and CLI tools. Throws on any missing.
    #>
    [CmdletBinding()]
    param(
        [switch] $DryRun
    )

    $required = @('AZURE_SUBSCRIPTION_ID', 'AZURE_LOCATION', 'AZURE_ENV_NAME')
    $missing = $required | Where-Object { -not (Get-Item "Env:$_" -ErrorAction SilentlyContinue) }
    if ($missing.Count -gt 0) {
        throw "Missing required environment variables: $($missing -join ', '). " +
              "These are needed to scope the ephemeral resource group and azd environment."
    }

    if ($DryRun) {
        Write-Host "[DryRun] Skipping CLI tool checks (az, azd)." -ForegroundColor Yellow
        return
    }

    foreach ($cmd in @('az', 'azd')) {
        if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
            throw "Required CLI tool '$cmd' was not found on PATH."
        }
    }
}

function New-EphemeralResourceGroupName {
    <#
    .SYNOPSIS
        Generates a deterministic-but-unique RG name with an 8-char hex suffix.
    #>
    [CmdletBinding()]
    param(
        [string] $Prefix = 'rg-pl-rag-it'
    )

    $suffix = [guid]::NewGuid().ToString('N').Substring(0, 8)
    return "$Prefix-$suffix"
}

function New-EphemeralResourceGroup {
    <#
    .SYNOPSIS
        Creates an Azure resource group at $Location.
    .DESCRIPTION
        If a name with the same prefix already exists from a previous failed
        run AND -ReuseExisting is set, the most recent matching RG is reused.
        Otherwise a new RG with a fresh hex suffix is created.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $Location,
        [Parameter(Mandatory)] [string] $SubscriptionId,
        [string] $Prefix = 'rg-pl-rag-it',
        [switch] $ReuseExisting,
        [switch] $DryRun
    )

    if ($ReuseExisting) {
        if ($DryRun) {
            Write-Host "[DryRun] Would search for existing RG with prefix '$Prefix' in subscription $SubscriptionId" -ForegroundColor Yellow
        } else {
            $existing = az group list --subscription $SubscriptionId `
                --query "[?starts_with(name, '$Prefix-')].name | [0]" -o tsv 2>$null
            if ($existing) {
                Write-Host "Reusing existing resource group: $existing" -ForegroundColor Cyan
                return $existing
            }
        }
    }

    $name = New-EphemeralResourceGroupName -Prefix $Prefix

    if ($DryRun) {
        Write-Host "[DryRun] az group create -n $name -l $Location --subscription $SubscriptionId" -ForegroundColor Yellow
        return $name
    }

    Write-Host "Creating ephemeral resource group: $name in $Location" -ForegroundColor Cyan
    az group create -n $name -l $Location --subscription $SubscriptionId --tags `
        purpose=runtime-test created=$(Get-Date -Format 'yyyy-MM-ddTHH:mm:ssZ') | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create resource group '$name' (az exit code $LASTEXITCODE)."
    }
    return $name
}

function Remove-EphemeralResourceGroup {
    <#
    .SYNOPSIS
        Best-effort cleanup of a resource group. Retries up to $MaxAttempts.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $Name,
        [Parameter(Mandatory)] [string] $SubscriptionId,
        [int] $MaxAttempts = 3,
        [switch] $DryRun
    )

    if ($DryRun) {
        Write-Host "[DryRun] az group delete -n $Name --yes --no-wait --subscription $SubscriptionId" -ForegroundColor Yellow
        return
    }

    for ($i = 1; $i -le $MaxAttempts; $i++) {
        Write-Host "Cleanup attempt $i/$MaxAttempts for RG '$Name'..." -ForegroundColor Cyan
        az group delete -n $Name --yes --no-wait --subscription $SubscriptionId 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Cleanup of '$Name' initiated successfully." -ForegroundColor Green
            return
        }
        Start-Sleep -Seconds (10 * $i)
    }
    Write-Warning "Failed to delete resource group '$Name' after $MaxAttempts attempts. Manual cleanup required."
}

function Test-ResourceGroupEmpty {
    <#
    .SYNOPSIS
        Returns $true if RG has zero resources, or if RG itself is gone.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $Name,
        [Parameter(Mandatory)] [string] $SubscriptionId,
        [switch] $DryRun
    )

    if ($DryRun) {
        Write-Host "[DryRun] az group show -n $Name; az resource list -g $Name" -ForegroundColor Yellow
        return $true
    }

    $exists = az group exists -n $Name --subscription $SubscriptionId 2>$null
    if ($exists -ne 'true') {
        return $true
    }

    $resources = az resource list -g $Name --subscription $SubscriptionId -o json 2>$null | ConvertFrom-Json
    if ($null -eq $resources) { return $true }
    return ($resources.Count -eq 0)
}

function Invoke-AzdProvision {
    <#
    .SYNOPSIS
        Wraps `azd provision` with a hard timeout and stdout/stderr capture.
    .OUTPUTS
        PSCustomObject with: ExitCode, StdOut, StdErr, DurationSeconds, TimedOut
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $WorkingDirectory,
        [string[]] $ExtraArgs = @(),
        [int] $TimeoutMinutes = 90,
        [switch] $DryRun
    )

    $azdArgs = @('provision', '--no-prompt') + $ExtraArgs
    $cmdLine = "azd $($azdArgs -join ' ')"

    if ($DryRun) {
        Write-Host "[DryRun] (cwd=$WorkingDirectory) $cmdLine  (timeout=${TimeoutMinutes}m)" -ForegroundColor Yellow
        return [pscustomobject]@{
            ExitCode        = 0
            StdOut          = '[DryRun] No changes'
            StdErr          = ''
            DurationSeconds = 0
            TimedOut        = $false
        }
    }

    $stdoutFile = New-TemporaryFile
    $stderrFile = New-TemporaryFile
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $proc = Start-Process -FilePath 'azd' -ArgumentList $azdArgs `
        -WorkingDirectory $WorkingDirectory `
        -RedirectStandardOutput $stdoutFile.FullName `
        -RedirectStandardError $stderrFile.FullName `
        -PassThru -NoNewWindow

    $timedOut = $false
    if (-not $proc.WaitForExit($TimeoutMinutes * 60 * 1000)) {
        $timedOut = $true
        try { $proc.Kill($true) } catch { Write-Warning "Failed to kill azd: $_" }
        $proc.WaitForExit()
    }
    $sw.Stop()

    $stdout = Get-Content $stdoutFile.FullName -Raw -ErrorAction SilentlyContinue
    $stderr = Get-Content $stderrFile.FullName -Raw -ErrorAction SilentlyContinue
    Remove-Item $stdoutFile.FullName, $stderrFile.FullName -ErrorAction SilentlyContinue

    return [pscustomobject]@{
        ExitCode        = if ($timedOut) { -1 } else { $proc.ExitCode }
        StdOut          = $stdout
        StdErr          = $stderr
        DurationSeconds = [int]$sw.Elapsed.TotalSeconds
        TimedOut        = $timedOut
    }
}

function Get-AzdEnvironmentValues {
    <#
    .SYNOPSIS
        Reads `azd env get-values` and returns a hashtable.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $WorkingDirectory,
        [switch] $DryRun
    )

    if ($DryRun) {
        Write-Host "[DryRun] azd env get-values (cwd=$WorkingDirectory)" -ForegroundColor Yellow
        return @{}
    }

    Push-Location $WorkingDirectory
    try {
        $raw = azd env get-values 2>$null
        if ($LASTEXITCODE -ne 0) {
            throw "azd env get-values failed (exit code $LASTEXITCODE)."
        }
    } finally {
        Pop-Location
    }

    $result = @{}
    foreach ($line in ($raw -split "`r?`n")) {
        if ($line -match '^\s*([A-Z0-9_]+)\s*=\s*"?(.*?)"?\s*$') {
            $result[$Matches[1]] = $Matches[2]
        }
    }
    return $result
}

function Test-AzdProvisionNoChanges {
    <#
    .SYNOPSIS
        Inspects `azd provision --preview` output and returns $true if it
        reports zero changes.
    .DESCRIPTION
        azd's preview output wording has shifted across versions. We accept
        any of these signals as "no changes":
          * "0 to create, 0 to delete, 0 to modify"
          * "No changes"
          * "Total: 0"
          * "0 changes"
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $PreviewOutput
    )

    if ([string]::IsNullOrWhiteSpace($PreviewOutput)) { return $false }

    $patterns = @(
        '0\s+to\s+create,\s*0\s+to\s+delete,\s*0\s+to\s+modify',
        '\bNo changes\b',
        '\bTotal:\s*0\b',
        '\b0 changes\b'
    )
    foreach ($p in $patterns) {
        if ($PreviewOutput -match $p) { return $true }
    }
    return $false
}
