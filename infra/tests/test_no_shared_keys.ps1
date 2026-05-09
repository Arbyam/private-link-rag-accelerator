# =============================================================================
# T051: zero-shared-keys static test (FR-003)
# =============================================================================
# Greps the *bicep source* under infra/ for forbidden patterns:
#     listKeys, connectionString, accountKey, primaryKey
# (case-insensitive, identifier-boundary aware)
#
# Asserts: zero matches outside the explicitly-allowed exceptions below.
#
# WHY SOURCE-LEVEL GREP (not the compiled ARM):
#   Azure Verified Modules (AVM) ship template code that *can* emit shared-key
#   helpers when the caller opts in — e.g., the AVM storage module has a
#   `secretsExportConfiguration` block that emits `listKeys(...)` only when
#   the caller passes `secretsExportConfiguration` parameters. The accelerator
#   never passes those, so the gated AVM code is dead code at deployment time
#   but still appears as text inside the compiled JSON. Grepping the compiled
#   ARM therefore produces large numbers of false positives that say nothing
#   about the deployment's actual security posture.
#
#   The bicep source IS what the developer types and reviews; that's the
#   correct surface for FR-003 ("no shared keys posture") enforcement.
#
# Allowlist (each entry MUST cite the rationale and ideally a spec/FR):
#
#   1. AMPLS ingestion-key references
#      Path:    infra/modules/monitoring/main.bicep
#      Token:   `connectionString` on Application Insights output
#      Rationale: Application Insights SDKs require a `connectionString` to
#      know WHICH AI resource to send telemetry to. With AMPLS+PrivateOnly
#      configured (this repo), the connection string carries the ingestion
#      endpoint resolution — it is NOT a shared-key data-plane secret like a
#      Storage account key. APIM consumes it via a Key Vault SecureString
#      (PR-W). This is the AMPLS-ingestion exception called out in the task.
#
#   2. Comments / documentation strings
#      Mentions inside `//` line comments and `/* */` block comments are
#      ignored — they are documentation, not deployable references.
# =============================================================================

. $PSScriptRoot/_helpers.ps1

Describe 'T051 — no shared keys (FR-003)' {

    BeforeAll {
        . $PSScriptRoot/_helpers.ps1
        $script:patterns = @('listKeys', 'connectionString', 'accountKey', 'primaryKey')
        $script:bicepFiles = Get-AllInfraBicepFiles
        $script:bicepFiles.Count | Should -BeGreaterThan 0

        # Allowlist as an ordered list of (file-glob, regex, reason). A finding
        # passes if ANY allowlist entry matches both file and matched line.
        $script:allowlist = @(
            @{
                FileGlob = '*\modules\monitoring\main.bicep'
                LineRx   = 'appInsightsConnectionString|appInsights\.outputs\.connectionString'
                Reason   = 'AMPLS-ingestion exception: AppInsights connection string output (telemetry plane via PrivateOnly AMPLS, not a data-plane shared key). Documented in T051 header.'
            }
            @{
                FileGlob = '*\modules\apim\main.bicep'
                LineRx   = 'connectionString:\s*appInsightsConnectionString'
                Reason   = 'AMPLS-ingestion exception: APIM logger consumes the AppInsights connection string for SDK initialization (telemetry, not data-plane keys).'
            }
            @{
                FileGlob = '*\modules\apim\main.bicep'
                LineRx   = 'param\s+appInsightsConnectionString'
                Reason   = 'AMPLS-ingestion exception (parameter declaration).'
            }
            @{
                FileGlob = '*main.bicep'
                LineRx   = 'appInsightsConnectionString'
                Reason   = 'AMPLS-ingestion exception: top-level orchestrator passes connection string through.'
            }
        )
    }

    It 'finds no shared-key references outside the AMPLS allowlist' {
        $offenders = New-Object System.Collections.ArrayList

        foreach ($file in $script:bicepFiles) {
            $lines = Get-Content $file.FullName
            for ($i = 0; $i -lt $lines.Count; $i++) {
                $raw = $lines[$i]

                # Strip inline `//` comment AFTER preserving full text for
                # quoting (we only test against the non-comment portion).
                $code = $raw
                $cmtIdx = $code.IndexOf('//')
                if ($cmtIdx -ge 0) { $code = $code.Substring(0, $cmtIdx) }

                # Skip pure block-comment lines starting with /* or *
                $trim = $code.TrimStart()
                if ($trim.StartsWith('/*') -or $trim.StartsWith('*')) { continue }

                foreach ($p in $script:patterns) {
                    $rx = "(?i)\b$([Regex]::Escape($p))\b"
                    if ($code -match $rx) {
                        # Check allowlist
                        $allowed = $false
                        $allowReason = ''
                        foreach ($a in $script:allowlist) {
                            if (($file.FullName -like $a.FileGlob) -and ($raw -match $a.LineRx)) {
                                $allowed = $true
                                $allowReason = $a.Reason
                                break
                            }
                        }
                        if (-not $allowed) {
                            [void]$offenders.Add([pscustomobject]@{
                                File    = $file.FullName.Substring((Get-RepoRoot).Length + 1)
                                Line    = $i + 1
                                Pattern = $p
                                Source  = $raw.Trim()
                            })
                        } else {
                            Write-Verbose "[allowlisted] $($file.Name):$($i+1) — $allowReason"
                        }
                    }
                }
            }
        }

        if ($offenders.Count -gt 0) {
            $rendered = ($offenders | Format-Table -AutoSize | Out-String)
            Write-Host "`n[T051] FORBIDDEN shared-key references found:`n$rendered"
        }

        $offenders.Count | Should -Be 0 -Because (
            "Found shared-key references in bicep source. Each finding violates " +
            "FR-003 unless added to the AMPLS allowlist with a documented rationale. " +
            "Do NOT silently widen the allowlist — escalate to Lead."
        )
    }

    It 'allowlist entries actually match (no stale/dead allowlist entries)' {
        # If an allowlist entry never matches anything, that's tech debt and
        # may indicate the security exception was removed but the carve-out
        # was forgotten. Warn (non-fatal) so cleanup happens at PR review.
        foreach ($a in $script:allowlist) {
            $matched = $false
            foreach ($file in $script:bicepFiles) {
                if (-not ($file.FullName -like $a.FileGlob)) { continue }
                $content = Get-Content $file.FullName -Raw
                if ($content -match $a.LineRx) { $matched = $true; break }
            }
            if (-not $matched) {
                Write-Host "[T051] WARN: stale allowlist entry — '$($a.LineRx)' on '$($a.FileGlob)' matched nothing."
            }
        }
        $true | Should -BeTrue
    }
}
