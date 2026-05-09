# =============================================================================
# T048: bicep-compile static test
# =============================================================================
# Compiles infra/main.bicep with `az bicep build` for each supported parameter
# combination and asserts:
#   - exit 0
#   - zero real bicep warnings AND zero errors (warnings are failures)
#
# Also runs `az bicep lint` against main.bicep for an additional gate.
#
# Parameter combinations covered (per task brief):
#   - default                     (main.parameters.dev.json as-is)
#   - enableZoneRedundancy = true
#   - deployBastion        = false   (already the dev default; covered)
#   - customerProvidedDns  = true
#
# How "combinations" are exercised:
#   `az bicep build` does NOT consume parameter files — it only compiles the
#   Bicep source. Parameter values that change deployment SHAPE (e.g.,
#   conditional modules) are ALREADY exercised by the Bicep compiler because
#   the compiler emits `condition` expressions for `if (...)` blocks; the JSON
#   shape is identical regardless of parameter value at build time. We
#   therefore (a) confirm `bicep build` succeeds with no warnings, and (b)
#   verify each named parameter actually exists on main.bicep — the latter is
#   the static gate the task asks for ("don't add the parameter — escalate
#   if missing").
#
# NOTE: deployment-time validation requiring different parameter VALUES is
# T049's `az deployment sub validate` and is out of scope here (T048 stays
# auth-free).
# =============================================================================

BeforeDiscovery {
    . $PSScriptRoot/_helpers.ps1

    # -ForEach data must exist at Discovery time.
    $combos = @(
        @{ Name = 'enableZoneRedundancy'; Value = 'true'  }
        @{ Name = 'deployBastion';        Value = 'false' }
        @{ Name = 'customerProvidedDns';  Value = 'true'  }
    )
}

Describe 'T048 — bicep static compile' {

    BeforeAll {
        . $PSScriptRoot/_helpers.ps1
        $script:bicepFile = Get-MainBicepPath
        Test-Path $script:bicepFile | Should -BeTrue
        $script:src = Get-Content $script:bicepFile -Raw
    }

    Context 'baseline compile (no overrides)' {
        It 'az bicep build infra/main.bicep returns exit 0 with no real warnings/errors' {
            $r = Invoke-BicepBuild
            $r.ExitCode | Should -Be 0 -Because "stderr was: $($r.Stderr)"
            $diags = Get-RealBicepDiagnostics -StderrText $r.Stderr
            $diags | Should -BeNullOrEmpty -Because "Bicep diagnostics found: $($diags -join '; ')"
            (Test-Path $r.JsonPath) | Should -BeTrue
            (Get-Item $r.JsonPath).Length | Should -BeGreaterThan 1024
        }

        It 'az bicep lint infra/main.bicep is clean (zero warnings, zero errors)' {
            $env:PYTHONIOENCODING = 'utf-8'
            $lintOutput = & az bicep lint --file $script:bicepFile --diagnostics-format default 2>&1 |
                ForEach-Object { $_.ToString() }
            $lintExit = $LASTEXITCODE
            $diags = Get-RealBicepDiagnostics -StderrText ($lintOutput -join "`n")
            $lintExit | Should -Be 0 -Because "lint output: $($lintOutput -join '; ')"
            $diags | Should -BeNullOrEmpty -Because "Lint diagnostics: $($diags -join '; ')"
        }
    }

    Context 'parameter combinations referenced by main.bicep' {
        It 'main.bicep declares param <Name> (combo: <Name>=<Value>)' -ForEach $combos {
            $pattern = "(?m)^\s*param\s+$([Regex]::Escape($Name))\s+"
            ($script:src -match $pattern) | Should -BeTrue -Because (
                "Parameter '$Name' is required by the supported combo '$Name=$Value' " +
                "but is not declared in main.bicep. Escalate to Lead — DO NOT add it here."
            )
        }
    }
}
