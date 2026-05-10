<#
.SYNOPSIS
    azd `preprovision` hook — Windows parity for scripts/preflight.sh (T014/T056).

.DESCRIPTION
    Validates local toolchain + Azure auth state BEFORE `azd up` touches Azure.
    Exits non-zero on any failed check; azd treats this as an abort signal
    (continueOnError: false in azure.yaml).

    Checks:
      1. Azure CLI installed + signed in
      2. azd installed
      3. Docker installed + daemon running (skipped if SKIP_DOCKER_CHECK=1)
      4. Node.js >= 20
      5. Python >= 3.12
      6. PowerShell 7+ (already required to run this script)

.PARAMETER SkipDocker
    Skip the Docker daemon check. Use for CI hosts that build via ACR Tasks
    only (no local docker build).

.NOTES
    Mirrors scripts/preflight.sh check-for-check. Keep in lockstep.
#>

[CmdletBinding()]
param(
    [switch]$SkipDocker
)

$ErrorActionPreference = 'Continue'

$errors  = 0
$warnings = 0

function Write-OK   { param($m) Write-Host "[preflight] ✓ $m" -ForegroundColor Green }
function Write-Warn { param($m) Write-Host "[preflight] ⚠ $m" -ForegroundColor Yellow; $script:warnings++ }
function Write-Bad  { param($m) Write-Host "[preflight] ✗ $m" -ForegroundColor Red;    $script:errors++ }
function Write-Step { param($m) Write-Host "[preflight] $m" }

Write-Step "starting preflight checks (Windows / pwsh)"
Write-Step ""

# ---------------------------------------------------------------------------
# 1. Azure CLI
# ---------------------------------------------------------------------------
Write-Step "Azure CLI..."
$az = Get-Command az -ErrorAction SilentlyContinue
if (-not $az) {
    Write-Bad "Azure CLI not found. Install from https://aka.ms/installazurecli"
} else {
    $azVersion = (az version --output json 2>$null | ConvertFrom-Json)."azure-cli"
    Write-OK "Installed (v$azVersion)"

    $account = az account show --query name -o tsv 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $account) {
        Write-Bad "Not logged in. Run 'az login' to authenticate."
    } else {
        Write-OK "Logged in ($account)"
    }
}

# ---------------------------------------------------------------------------
# 2. azd
# ---------------------------------------------------------------------------
Write-Step ""
Write-Step "Azure Developer CLI..."
$azd = Get-Command azd -ErrorAction SilentlyContinue
if (-not $azd) {
    Write-Bad "azd not found. Install from https://aka.ms/azure-dev/install"
} else {
    $azdVersionRaw = (azd version 2>$null) -join ' '
    if ($azdVersionRaw -match '(\d+\.\d+\.\d+)') { $azdVersion = $matches[1] } else { $azdVersion = 'unknown' }
    Write-OK "Installed ($azdVersion)"
}

# ---------------------------------------------------------------------------
# 3. Docker (optional — skip via -SkipDocker or env SKIP_DOCKER_CHECK=1)
# ---------------------------------------------------------------------------
Write-Step ""
Write-Step "Docker..."
if ($SkipDocker -or $env:SKIP_DOCKER_CHECK -eq '1') {
    Write-OK "Skipped (SKIP_DOCKER_CHECK=1 or -SkipDocker)"
} else {
    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if (-not $docker) {
        Write-Bad "Docker not found. Install from https://docs.docker.com/get-docker/"
    } else {
        $dockerVersion = (docker version --format '{{.Client.Version}}' 2>$null)
        Write-OK "Installed (v$dockerVersion)"

        # Probe daemon with a short timeout so the script doesn't hang on a
        # stopped Docker Desktop. Non-zero exit means daemon not reachable.
        $job = Start-Job -ScriptBlock { docker info --format '{{.ServerVersion}}' 2>&1 | Out-Null; $LASTEXITCODE }
        if (Wait-Job $job -Timeout 5) {
            $rc = Receive-Job $job
            if ($rc -eq 0) {
                Write-OK "Daemon running"
            } else {
                Write-Bad "Docker daemon not running. Start Docker Desktop or set SKIP_DOCKER_CHECK=1 if relying on ACR Tasks."
            }
        } else {
            Stop-Job $job -ErrorAction SilentlyContinue
            Write-Bad "Docker daemon probe timed out (>5s). Start Docker Desktop or set SKIP_DOCKER_CHECK=1."
        }
        Remove-Job $job -Force -ErrorAction SilentlyContinue
    }
}

# ---------------------------------------------------------------------------
# 4. Node.js >= 20
# ---------------------------------------------------------------------------
Write-Step ""
Write-Step "Node.js..."
$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) {
    Write-Bad "Node.js not found. Install v20+ from https://nodejs.org/"
} else {
    $nodeVersion = (node --version 2>$null) -replace '^v', ''
    $nodeMajor = [int]($nodeVersion.Split('.')[0])
    if ($nodeMajor -lt 20) {
        Write-Warn "Node.js v$nodeVersion found, but v20+ is required."
    } else {
        Write-OK "Installed (v$nodeVersion)"
    }
}

# ---------------------------------------------------------------------------
# 5. Python >= 3.12 (try `python` then `python3` — skip `py` launcher to avoid
#    Microsoft Store stub that hangs the script when no real Python is found)
# ---------------------------------------------------------------------------
Write-Step ""
Write-Step "Python..."
$pythonCmd = $null
foreach ($cand in @('python', 'python3')) {
    $p = Get-Command $cand -ErrorAction SilentlyContinue
    if ($p -and $p.Source -notmatch 'WindowsApps') { $pythonCmd = $cand; break }
}
if (-not $pythonCmd) {
    Write-Bad "Python not found (real interpreter, not the Microsoft Store stub). Install v3.12+ from https://www.python.org/"
} else {
    $pyVerLine = & $pythonCmd --version 2>&1
    if ($pyVerLine -match '(\d+)\.(\d+)\.(\d+)') {
        $pyMajor = [int]$matches[1]; $pyMinor = [int]$matches[2]
        $pyVersion = "$pyMajor.$pyMinor.$($matches[3])"
        if ($pyMajor -lt 3 -or ($pyMajor -eq 3 -and $pyMinor -lt 12)) {
            Write-Warn "Python v$pyVersion found, but v3.12+ is required."
        } else {
            Write-OK "Installed (v$pyVersion via $pythonCmd)"
        }
    } else {
        Write-Warn "Could not parse Python version from: $pyVerLine"
    }
}

# ---------------------------------------------------------------------------
# 6. PowerShell version
# ---------------------------------------------------------------------------
Write-Step ""
Write-Step "PowerShell..."
if ($PSVersionTable.PSVersion.Major -ge 7) {
    Write-OK "PowerShell $($PSVersionTable.PSVersion) (>= 7 required)"
} else {
    Write-Warn "PowerShell $($PSVersionTable.PSVersion) — recommend 7+ for postprovision.ps1 reliability."
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
Write-Step ""
if ($errors -eq 0) {
    Write-Host "[preflight] All preflight checks passed!" -ForegroundColor Green
    if ($warnings -gt 0) {
        Write-Host "[preflight] ($warnings warning(s) — review above)" -ForegroundColor Yellow
    }
    exit 0
} else {
    Write-Host "[preflight] $errors check(s) failed." -ForegroundColor Red
    exit 1
}
