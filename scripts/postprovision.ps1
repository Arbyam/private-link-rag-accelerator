<#
.SYNOPSIS
    azd `postprovision` hook for the Private RAG Accelerator (T047).

.DESCRIPTION
    Runs after `azd provision` completes. Idempotent — re-running on a healthy
    deployment produces a no-op (every step is logged as skipped).

    Steps:
      1. Create the AI Search `kb-index` from `infra/search/kb-index.json` if
         it doesn't already exist (GET-before-PUT).
      2. Seed up to five sample documents from `samples/` into the
         `shared-corpus` blob container (uploads with `--overwrite false`,
         skipping blobs that already exist).
      3. Print the UI URL + Bastion connection instructions.

.PARAMETER DryRun
    Skip every Azure call. Used by CI / lint to syntax-check the script
    without touching a subscription.

.NOTES
    - Requires PowerShell 7+, az CLI 2.65+, azd 1.13+.
    - The operator running `azd up` must hold:
        * `Search Service Contributor` on the AI Search service (for index PUT)
        * `Storage Blob Data Contributor` on the storage account (for blob upload)
      The script does NOT grant RBAC; it consumes whatever the caller has.
    - Reads outputs from the active azd environment via `azd env get-values`.
#>

[CmdletBinding()]
param(
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$started = Get-Date
$summary = [ordered]@{
    'kb-index'       = 'pending'
    'sample-seeding' = 'pending'
    'ui-url'         = 'pending'
}

function Write-Step  { param($msg) Write-Host "[postprovision] ✔ $msg" }
function Write-Warn  { param($msg) Write-Host "[postprovision] ⚠ $msg" -ForegroundColor Yellow }
function Write-Fail  { param($msg) Write-Host "[postprovision] ✖ $msg" -ForegroundColor Red }
function Write-Info  { param($msg) Write-Host "[postprovision]   $msg" }

# ---------------------------------------------------------------------------
# 0. Resolve repo root (script lives at <repo>/scripts/postprovision.ps1)
# ---------------------------------------------------------------------------
$repoRoot       = Split-Path -Parent $PSScriptRoot
$indexFile      = Join-Path $repoRoot 'infra/search/kb-index.json'
$samplesDir     = Join-Path $repoRoot 'samples'

Write-Step "starting (repo root: $repoRoot, dry-run: $($DryRun.IsPresent))"

# ---------------------------------------------------------------------------
# 1. Load azd env outputs
# ---------------------------------------------------------------------------
function Get-AzdEnv {
    if ($DryRun) {
        return @{
            SEARCH_ENDPOINT             = 'https://dryrun.search.windows.net'
            STORAGE_ACCOUNT_NAME        = 'dryrunstorage'
            AZURE_STORAGE_CORPUS_CONTAINER = 'shared-corpus'
            WEB_APP_FQDN                = 'web.dryrun.azurecontainerapps.io'
            BASTION_NAME                = 'bas-dryrun'
            AOAI_ENDPOINT               = 'https://dryrun.openai.azure.com'
            OPENAI_EMBED_DEPLOYMENT     = 'text-embedding-3-large'
        }
    }

    $raw = & azd env get-values 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $raw) {
        throw "Unable to read azd environment via 'azd env get-values'. Is an azd env selected?"
    }

    $map = @{}
    foreach ($line in $raw) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*"?(.*?)"?\s*$') {
            $map[$Matches[1]] = $Matches[2]
        }
    }
    return $map
}

$envValues = Get-AzdEnv
Write-Step "loaded $($envValues.Count) azd env values"

# Output names — keep aligned with infra/main.bicep outputs.
# azd uppercases bicep output names when materializing them into the env file.
function Get-EnvValue {
    param([string[]]$Names, [string]$Default = $null)
    foreach ($n in $Names) {
        if ($envValues.ContainsKey($n) -and $envValues[$n]) { return $envValues[$n] }
    }
    return $Default
}

$searchEndpoint   = Get-EnvValue 'SEARCH_ENDPOINT','SEARCHENDPOINT'
$storageAccount   = Get-EnvValue 'STORAGE_ACCOUNT_NAME','STORAGEACCOUNTNAME'
$corpusContainer  = Get-EnvValue 'AZURE_STORAGE_CORPUS_CONTAINER','SHARED_CORPUS_CONTAINER' 'shared-corpus'
$webFqdn          = Get-EnvValue 'WEB_APP_FQDN','WEBAPPFQDN','UI_URL','UIURL'
$bastionName      = Get-EnvValue 'BASTION_NAME','BASTIONNAME'
$aoaiEndpoint     = Get-EnvValue 'AOAI_ENDPOINT','OPEN_AI_ENDPOINT','OPENAIENDPOINT'
$embedDeployment  = Get-EnvValue 'OPENAI_EMBED_DEPLOYMENT','OPENAIEMBEDDEPLOYMENT' 'text-embedding-3-large'

# ---------------------------------------------------------------------------
# 2. Step 1 — kb-index
# ---------------------------------------------------------------------------
function Invoke-EnsureSearchIndex {
    if (-not (Test-Path $indexFile)) {
        Write-Warn "kb-index definition not found at '$indexFile' — skipping (T045 may not have landed yet)"
        $script:summary['kb-index'] = 'skipped (no definition file)'
        return
    }
    if (-not $searchEndpoint) {
        Write-Warn "SEARCH_ENDPOINT not set in azd env — skipping kb-index step"
        $script:summary['kb-index'] = 'skipped (no SEARCH_ENDPOINT)'
        return
    }

    $apiVersion = '2024-07-01'
    $url = "$searchEndpoint/indexes/kb-index?api-version=$apiVersion"

    if ($DryRun) {
        Write-Step "DRY-RUN: would GET/PUT $url using $indexFile"
        $script:summary['kb-index'] = 'dry-run'
        return
    }

    Write-Info "acquiring AAD token for AI Search data plane"
    $tokenJson = & az account get-access-token --resource 'https://search.azure.com/' --output json 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $tokenJson) {
        throw "Failed to acquire token for https://search.azure.com/. Run 'az login' and ensure your identity has Search Service Contributor."
    }
    $token = ($tokenJson | ConvertFrom-Json).accessToken
    $headers = @{
        Authorization = "Bearer $token"
        'Content-Type' = 'application/json'
    }

    Write-Info "GET $url"
    $exists = $false
    try {
        Invoke-RestMethod -Method Get -Uri $url -Headers $headers -ErrorAction Stop | Out-Null
        $exists = $true
    } catch {
        $status = $null
        if ($_.Exception.Response) { $status = [int]$_.Exception.Response.StatusCode }
        if ($status -eq 403) {
            Write-Warn "AI Search returned 403 — running outside the VNet, skipping kb-index step (deploy from jumpbox or runner inside VNet to seed the index)"
            $script:summary['kb-index'] = 'skipped (403 — outside VNet)'
            return
        }
        if ($status -ne 404) {
            throw "Unexpected error probing kb-index ($status): $($_.Exception.Message)"
        }
    }

    if ($exists) {
        Write-Step "kb-index already exists — skipping create"
        $script:summary['kb-index'] = 'skipped (exists)'
        return
    }

    Write-Info "kb-index not found — creating from $indexFile"
    $body = Get-Content -Raw -Path $indexFile

    # Substitute placeholder tokens in the index definition (e.g. ${AOAI_ENDPOINT})
    $substitutions = @{
        'AOAI_ENDPOINT'           = $aoaiEndpoint
        'OPENAI_EMBED_DEPLOYMENT' = $embedDeployment
        'SEARCH_ENDPOINT'         = $searchEndpoint
    }
    foreach ($k in $substitutions.Keys) {
        $val = $substitutions[$k]
        if ($null -ne $val) {
            $body = $body.Replace('${' + $k + '}', $val)
        }
    }

    Invoke-RestMethod -Method Put -Uri $url -Headers $headers -Body $body -ErrorAction Stop | Out-Null
    Write-Step "kb-index created"
    $script:summary['kb-index'] = 'created'
}

# ---------------------------------------------------------------------------
# 3. Step 2 — seed sample documents
# ---------------------------------------------------------------------------
function Invoke-SeedSamples {
    if (-not (Test-Path $samplesDir)) {
        Write-Warn "'samples/' directory missing — skipping seeding (T071/T108 may not have landed yet)"
        $script:summary['sample-seeding'] = 'skipped (no samples dir)'
        return
    }

    $files = Get-ChildItem -Path $samplesDir -File -ErrorAction SilentlyContinue |
             Where-Object { $_.Name -notin @('README.md', '.gitkeep') }
    if (-not $files -or $files.Count -eq 0) {
        Write-Warn "'samples/' has no document files — skipping seeding"
        $script:summary['sample-seeding'] = 'skipped (empty)'
        return
    }

    if (-not $storageAccount) {
        Write-Warn "STORAGE_ACCOUNT_NAME not set in azd env — skipping seeding"
        $script:summary['sample-seeding'] = 'skipped (no STORAGE_ACCOUNT_NAME)'
        return
    }

    if ($DryRun) {
        Write-Step "DRY-RUN: would upload $($files.Count) file(s) → ${storageAccount}/${corpusContainer}/"
        foreach ($f in $files) { Write-Info "  - $($f.Name)" }
        $script:summary['sample-seeding'] = "dry-run ($($files.Count) files)"
        return
    }

    $uploaded = 0
    $skipped  = 0
    foreach ($f in $files) {
        $blobName = $f.Name
        Write-Info "uploading $blobName → $storageAccount/$corpusContainer (skip-if-exists)"

        $stderr = $null
        & az storage blob upload `
            --auth-mode login `
            --account-name $storageAccount `
            --container-name $corpusContainer `
            --name $blobName `
            --file $f.FullName `
            --overwrite false `
            --only-show-errors 2>&1 | Tee-Object -Variable stderr | Out-Null

        if ($LASTEXITCODE -eq 0) {
            $uploaded++
            Write-Step "  uploaded $blobName"
        } else {
            $stderrText = ($stderr | Out-String)
            if ($stderrText -match 'BlobAlreadyExists' -or $stderrText -match 'already exists') {
                $skipped++
                Write-Info "  $blobName already present — skipping"
            } elseif ($stderrText -match 'blocked by network rules' -or $stderrText -match 'AuthorizationFailure' -or $stderrText -match 'PublicAccessNotPermitted') {
                Write-Warn "  Storage blocked by network rules — running outside VNet, skipping sample seeding (run from jumpbox/runner inside VNet to seed)"
                $script:summary['sample-seeding'] = 'skipped (blocked — outside VNet)'
                return
            } else {
                throw "Failed to upload '$blobName' to $storageAccount/$corpusContainer`: $stderrText"
            }
        }
    }
    Write-Step "sample seeding complete (uploaded=$uploaded, skipped=$skipped)"
    $script:summary['sample-seeding'] = "uploaded=$uploaded skipped=$skipped"
}

# ---------------------------------------------------------------------------
# 4. Step 3 — print UI URL + Bastion instructions
# ---------------------------------------------------------------------------
function Show-UiUrl {
    if (-not $webFqdn) {
        Write-Warn "WEB_APP_FQDN not set in azd env — UI URL unavailable"
        $script:summary['ui-url'] = 'skipped (no WEB_APP_FQDN)'
        return
    }

    Write-Host ''
    Write-Host "🌐 UI: https://$webFqdn" -ForegroundColor Cyan
    Write-Host ''
    Write-Host 'The chat UI is internal-only. Reach it from inside the VNet:' -ForegroundColor Cyan
    if ($bastionName) {
        Write-Host "  • Azure Bastion ($bastionName): connect to the seeded jumpbox VM," -ForegroundColor Cyan
        Write-Host '    then browse to the URL above. See quickstart.md §6a.' -ForegroundColor Cyan
    } else {
        Write-Host '  • Azure Bastion: connect to the seeded jumpbox VM, then browse' -ForegroundColor Cyan
        Write-Host '    to the URL above. See quickstart.md §6a.' -ForegroundColor Cyan
    }
    Write-Host '  • Or via your VPN / ExpressRoute peered to the deployed VNet' -ForegroundColor Cyan
    Write-Host '    (DEPLOY_BASTION=false). See quickstart.md §6b.' -ForegroundColor Cyan
    Write-Host ''

    $script:summary['ui-url'] = "https://$webFqdn"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
try {
    Invoke-EnsureSearchIndex
    Invoke-SeedSamples
    Show-UiUrl
} catch {
    Write-Fail $_.Exception.Message
    throw
} finally {
    $elapsed = ((Get-Date) - $started).TotalSeconds
    Write-Host ''
    Write-Host '[postprovision] summary:' -ForegroundColor Cyan
    foreach ($k in $summary.Keys) {
        Write-Host ("  {0,-16} {1}" -f $k, $summary[$k])
    }
    Write-Host ("[postprovision] elapsed: {0:N1}s" -f $elapsed)
}
