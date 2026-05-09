# =============================================================================
# Shared helpers for infra/tests/*.ps1 (Pester v5)
# =============================================================================
# These helpers are dot-sourced from each test_*.ps1.
# They have NO Azure dependency — purely static analysis on the bicep source
# and the JSON ARM template emitted by `az bicep build`.
# =============================================================================

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Repository root (the worktree / clone root). _helpers.ps1 lives in
# <root>/infra/tests, so two `..` jumps land us at the root.
$script:RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$script:InfraRoot = Join-Path $script:RepoRoot 'infra'
$script:MainBicep = Join-Path $script:InfraRoot 'main.bicep'

function Get-RepoRoot { $script:RepoRoot }
function Get-InfraRoot { $script:InfraRoot }
function Get-MainBicepPath { $script:MainBicep }

# Build infra/main.bicep to ARM JSON. Returns the path to the JSON file.
# Caches output under infra/tests/.cache so multiple tests in run-all don't
# recompile (each compile takes 5–15 s on a clean machine).
#
# Notes on stderr / warnings:
#   - The Azure CLI prints an upgrade advisory on stderr ("A new Bicep release
#     is available: vX.Y.Z"). That is an Azure CLI advisory, NOT a bicep
#     warning. We strip it before returning stderr to callers.
#   - Real bicep warnings/errors look like:
#       <file>(<line>,<col>) : Warning <code>: <message>
#       <file>(<line>,<col>) : Error <code>: <message>
function Invoke-BicepBuild {
    [CmdletBinding()]
    param(
        [string] $BicepFile = (Get-MainBicepPath),
        [hashtable] $ParameterOverrides = $null,
        [switch] $Force
    )

    $cacheDir = Join-Path $PSScriptRoot '.cache'
    if (-not (Test-Path $cacheDir)) { New-Item -ItemType Directory -Force -Path $cacheDir | Out-Null }

    # Cache key: bicep file path + sorted overrides
    $keyParts = @($BicepFile)
    if ($ParameterOverrides) {
        foreach ($k in ($ParameterOverrides.Keys | Sort-Object)) {
            $keyParts += "$k=$($ParameterOverrides[$k])"
        }
    }
    $hash = [BitConverter]::ToString(
        [System.Security.Cryptography.SHA1]::Create().ComputeHash(
            [System.Text.Encoding]::UTF8.GetBytes(($keyParts -join '|'))
        )
    ).Replace('-', '').Substring(0, 12).ToLowerInvariant()

    $outFile = Join-Path $cacheDir "main.$hash.json"
    $errFile = Join-Path $cacheDir "main.$hash.err.txt"

    if (-not $Force -and (Test-Path $outFile) -and ((Get-Item $outFile).Length -gt 0)) {
        return [pscustomobject]@{
            JsonPath = $outFile
            Stderr   = if (Test-Path $errFile) { Get-Content $errFile -Raw } else { '' }
            ExitCode = 0
            Cached   = $true
        }
    }

    # We do NOT support parameter overrides via az bicep build (Bicep is the
    # source — overrides apply at deployment). For T048 the caller writes a
    # transient .bicep that imports main.bicep with different defaults; for
    # other tests we always use the unmodified main.bicep.
    $env:PYTHONIOENCODING = 'utf-8'

    $stderr = & az bicep build --file $BicepFile --outfile $outFile 2>&1 |
        Where-Object { $_ -is [System.Management.Automation.ErrorRecord] -or $_ -match '\S' } |
        ForEach-Object { $_.ToString() }
    $exit = $LASTEXITCODE

    $stderrText = ($stderr -join "`n")
    Set-Content -Path $errFile -Value $stderrText -NoNewline

    return [pscustomobject]@{
        JsonPath = if (Test-Path $outFile) { $outFile } else { $null }
        Stderr   = $stderrText
        ExitCode = $exit
        Cached   = $false
    }
}

# Filter Azure CLI noise from stderr to leave only real bicep diagnostics.
function Get-RealBicepDiagnostics {
    param([string] $StderrText)
    if ([string]::IsNullOrWhiteSpace($StderrText)) { return @() }
    $lines = $StderrText -split "`r?`n" | Where-Object { $_ -match '\S' }
    $noise = @(
        '^WARNING: A new Bicep release is available',
        '^WARNING: .*Upgrade now by running',
        '^Run ''az bicep upgrade''',
        '^WARNING: This command group is in preview'
    )
    return $lines | Where-Object {
        $line = $_
        -not ($noise | Where-Object { $line -match $_ })
    }
}

# Recursively collect every resource emitted by the compiled ARM template.
# Walks nested deployments (Microsoft.Resources/deployments) by drilling into
# their inline `properties.template.resources`.
#
# Returns a flat array of [pscustomobject] with shape:
#   { Type, Name, Path, Existing, Condition, Resource (raw object) }
# Path is a `/`-separated symbolic-name path (e.g.,
#   "storage/storage/storageAccount") for diagnostics.
function Get-AllArmResources {
    param([Parameter(Mandatory)] [string] $JsonPath)
    $json = Get-Content $JsonPath -Raw | ConvertFrom-Json -Depth 100
    $out = New-Object System.Collections.ArrayList

    function _walk {
        param($node, [string] $prefix)
        if (-not $node) { return }
        if (-not ($node.PSObject.Properties.Name -contains 'resources')) { return }
        $res = $node.resources
        if ($null -eq $res) { return }

        # Symbolic-name (object) form is current; positional (array) form is
        # supported as a fallback.
        if ($res -is [System.Collections.IList]) {
            $i = 0
            foreach ($r in $res) {
                _emit $r ("$prefix/[$i]")
                $i++
            }
        } else {
            foreach ($p in $res.PSObject.Properties) {
                _emit $p.Value ("$prefix/$($p.Name)")
            }
        }
    }

    function _emit {
        param($r, [string] $path)
        $existing = $false
        if ($r.PSObject.Properties.Name -contains 'existing') {
            $existing = [bool]$r.existing
        }
        $cond = $null
        if ($r.PSObject.Properties.Name -contains 'condition') {
            $cond = $r.condition
        }
        $name = $null
        if ($r.PSObject.Properties.Name -contains 'name') { $name = $r.name }

        [void]$out.Add([pscustomobject]@{
            Type      = $r.type
            Name      = $name
            Path      = $path
            Existing  = $existing
            Condition = $cond
            Resource  = $r
        })

        if ($r.type -eq 'Microsoft.Resources/deployments' -and
            $r.PSObject.Properties.Name -contains 'properties' -and
            $r.properties -and
            $r.properties.PSObject.Properties.Name -contains 'template') {
            _walk $r.properties.template $path
        }
    }

    _walk $json '(root)'
    return $out.ToArray()
}

# Recursively collect every Microsoft.Resources/deployments node so callers can
# inspect `properties.parameters` (which contain the literal values bicep
# resolved at compile time — e.g., publicNetworkAccess: 'Disabled').
function Get-AllArmDeployments {
    param([Parameter(Mandatory)] [string] $JsonPath)
    Get-AllArmResources -JsonPath $JsonPath |
        Where-Object { $_.Type -eq 'Microsoft.Resources/deployments' }
}

# Resolve a literal parameter value passed to a deployment, if any. Returns
# $null when the parameter is missing OR when its `.value` is an ARM
# expression (like "[parameters('foo')]") rather than a literal.
function Get-DeploymentLiteralParam {
    param(
        [Parameter(Mandatory)] $Deployment,
        [Parameter(Mandatory)] [string] $ParamName
    )
    if (-not $Deployment.Resource.properties) { return $null }
    if (-not ($Deployment.Resource.properties.PSObject.Properties.Name -contains 'parameters')) { return $null }
    $params = $Deployment.Resource.properties.parameters
    if (-not $params) { return $null }
    if (-not ($params.PSObject.Properties.Name -contains $ParamName)) { return $null }
    $entry = $params.$ParamName
    if (-not $entry) { return $null }
    if (-not ($entry.PSObject.Properties.Name -contains 'value')) { return $null }
    return $entry.value
}

# Return the path (relative to the repo root) of every *.bicep file under
# infra/, used by the source-level grep checks.
function Get-AllInfraBicepFiles {
    Get-ChildItem -Path (Get-InfraRoot) -Recurse -Filter '*.bicep' -File |
        Sort-Object FullName
}
