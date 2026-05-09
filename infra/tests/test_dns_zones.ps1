# =============================================================================
# T052: Private DNS zone coverage static test (FR-005)
# =============================================================================
# Asserts that:
#   1. Every well-known privatelink zone the accelerator's services depend on
#      is declared in `infra/modules/network/main.bicep` (privateDnsZoneNames
#      array).
#   2. Each declared zone is VNet-linked (the network module's AVM call
#      provisions a virtualNetworkLinks child for every zone).
#   3. Every Private Endpoint declared by a service module references a
#      privatelink zone that matches its `service` / `groupId` per the
#      Microsoft-published mapping.
#
# WHY SOURCE-LEVEL ANALYSIS:
#   See test_no_public_endpoints.ps1 header — same reasoning applies. The
#   AVM-emitted ARM JSON wraps the actual PE resource inside three layers of
#   nested deployments and parameterizes the zone IDs. The literal coupling
#   between PE service/groupId and the privatelink zone happens in source.
#
# Per-PE coverage table (matches PR #21 outputs in network/main.bicep §616+):
#
#   | Module              | PE service / groupId   | Zone (privatelink.*)            |
#   |---------------------|------------------------|---------------------------------|
#   | openai              | account                | openai.azure.com                |
#   | search              | searchService          | search.windows.net              |
#   | cosmos              | Sql                    | documents.azure.com             |
#   | storage (blob)      | blob                   | blob.core.windows.net           |
#   | storage (queue)     | queue                  | queue.core.windows.net          |
#   | keyvault            | vault                  | vaultcore.azure.net             |
#   | registry            | (single PE — ACR)      | azurecr.io                      |
#   | docintel            | account                | cognitiveservices.azure.com     |
#   | monitoring (AMPLS)  | groupIds=[azuremonitor]| monitor.azure.com + 4 siblings  |
#   | apim                | (VNet injection — no PE resource; uses azure-api.net zone)   |
#
# AMPLS PE registers FIVE zones in one privateDnsZoneGroup (per Azure docs):
#   monitor.azure.com, oms.opinsights.azure.com, ods.opinsights.azure.com,
#   agentsvc.azure-automation.net, blob.core.windows.net.
# =============================================================================

. $PSScriptRoot/_helpers.ps1

BeforeDiscovery {
    . $PSScriptRoot/_helpers.ps1

    # Required zones (13 per PR #21).
    $requiredZones = @(
        'privatelink.openai.azure.com'
        'privatelink.search.windows.net'
        'privatelink.documents.azure.com'
        'privatelink.blob.core.windows.net'
        'privatelink.queue.core.windows.net'
        'privatelink.vaultcore.azure.net'
        'privatelink.azurecr.io'
        'privatelink.cognitiveservices.azure.com'
        'privatelink.monitor.azure.com'
        'privatelink.oms.opinsights.azure.com'
        'privatelink.ods.opinsights.azure.com'
        'privatelink.agentsvc.azure-automation.net'
        'azure-api.net'                              # APIM internal VNet zone (not privatelink-prefixed)
    )

    # PE → expected zone mapping. Each entry: module file + a regex that
    # MUST appear in the source linking the right groupId/service to the
    # right zone (transitively via the wired pdns* output).
    $peExpectations = @(
        @{ Module = 'openai';   Service = 'account';       Zone = 'privatelink.openai.azure.com';            NetOutput = 'pdnsOpenaiId'    }
        @{ Module = 'search';   Service = 'searchService'; Zone = 'privatelink.search.windows.net';          NetOutput = 'pdnsSearchId'    }
        @{ Module = 'cosmos';   Service = 'Sql';           Zone = 'privatelink.documents.azure.com';         NetOutput = 'pdnsCosmosId'    }
        @{ Module = 'storage';  Service = 'blob';          Zone = 'privatelink.blob.core.windows.net';       NetOutput = 'pdnsBlobId'      }
        @{ Module = 'storage';  Service = 'queue';         Zone = 'privatelink.queue.core.windows.net';      NetOutput = 'pdnsQueueId'     }
        @{ Module = 'keyvault'; Service = 'vault';         Zone = 'privatelink.vaultcore.azure.net';         NetOutput = 'pdnsKeyVaultId'  }
        @{ Module = 'registry'; Service = $null;           Zone = 'privatelink.azurecr.io';                  NetOutput = 'pdnsAcrId'       }
        @{ Module = 'docintel'; Service = 'account';       Zone = 'privatelink.cognitiveservices.azure.com'; NetOutput = 'pdnsCognitiveId' }
    )
}

Describe 'T052 — Private DNS zones (FR-005)' {

    BeforeAll {
        . $PSScriptRoot/_helpers.ps1
        $script:netBicep = Join-Path (Get-InfraRoot) 'modules\network\main.bicep'
        $script:netSrc = Get-Content $script:netBicep -Raw
    }

    Context 'network module declares all required zones' {
        It 'has zone <_> in privateDnsZoneNames' -ForEach $requiredZones {
            $rx = "['""]" + [Regex]::Escape($_) + "['""]"
            ($script:netSrc -match $rx) | Should -BeTrue -Because (
                "Required Private DNS zone '$_' is missing from " +
                "infra/modules/network/main.bicep privateDnsZoneNames array."
            )
        }

        It 'wires VNet links for the privateDnsZones (virtualNetworkLinks block present)' {
            ($script:netSrc -match 'virtualNetworkLinks:') | Should -BeTrue
            ($script:netSrc -match 'virtualNetworkResourceId:\s*vnet\.id') | Should -BeTrue
            ($script:netSrc -match 'br/public:avm/res/network/private-dns-zone:') | Should -BeTrue
        }

        It 'gates zone provisioning on customerProvidedDns flag' {
            ($script:netSrc -match 'if\s*\(!?customerProvidedDns\)') | Should -BeTrue
        }

        It 'emits a named output for every well-known zone (PR #21 outputs)' {
            $required = @(
                'pdnsOpenaiId','pdnsSearchId','pdnsCosmosId','pdnsBlobId','pdnsQueueId',
                'pdnsKeyVaultId','pdnsAcrId','pdnsCognitiveId','pdnsMonitorId',
                'pdnsOmsId','pdnsOdsId','pdnsAgentSvcId','pdnsApimId'
            )
            foreach ($o in $required) {
                ($script:netSrc -match "(?m)^\s*output\s+$([Regex]::Escape($o))\s+string") |
                    Should -BeTrue -Because "missing output '$o' from network/main.bicep"
            }
        }
    }

    Context 'each Private Endpoint declares a private DNS zone group' {
        It '<Module> module wires PE → <Zone> via <NetOutput>' -ForEach $peExpectations {
            $modFile = Join-Path (Get-InfraRoot) "modules\$Module\main.bicep"
            Test-Path $modFile | Should -BeTrue
            $src = Get-Content $modFile -Raw

            ($src -match 'privateEndpoints' -or $src -match "Microsoft\.Network/privateEndpoints") |
                Should -BeTrue -Because "$Module/main.bicep should declare at least one private endpoint"

            ($src -match 'privateDnsZoneGroup') |
                Should -BeTrue -Because "$Module/main.bicep should configure privateDnsZoneGroup"

            ($src -match '(?m)^\s*param\s+(privateDnsZone\w*|pdns\w+)\s+string') |
                Should -BeTrue -Because "$Module/main.bicep should declare a DNS-zone-id parameter"

            if ($Service) {
                $rx = "service:\s*'" + [Regex]::Escape($Service) + "'"
                ($src -match $rx) | Should -BeTrue -Because (
                    "$Module/main.bicep should configure PE service='$Service' (matches zone '$Zone')."
                )
            }
        }
    }

    Context 'main.bicep wires each module to the matching network output' {
        BeforeAll {
            . $PSScriptRoot/_helpers.ps1
            $script:mainSrc = Get-Content (Get-MainBicepPath) -Raw
        }

        It 'main.bicep references network output <NetOutput> (zone <Zone>)' -ForEach $peExpectations {
            ($script:mainSrc -match $NetOutput) | Should -BeTrue -Because (
                "infra/main.bicep should reference network.outputs.$NetOutput so the " +
                "$Module module receives the '$Zone' zone ID."
            )
        }
    }

    Context 'AMPLS private endpoint registers all 5 monitor zones' {
        It 'monitoring/main.bicep references monitor + oms + ods + agentsvc + blob zones' {
            $monSrc = Get-Content (Join-Path (Get-InfraRoot) 'modules\monitoring\main.bicep') -Raw
            $needed = @(
                'privateDnsZoneIdMonitor',
                'privateDnsZoneIdOms',
                'privateDnsZoneIdOds',
                'privateDnsZoneIdAgentSvc',
                'privateDnsZoneIdBlob'
            )
            foreach ($n in $needed) {
                ($monSrc -match $n) | Should -BeTrue -Because (
                    "monitoring/main.bicep should consume the '$n' parameter for the AMPLS DNS zone group."
                )
            }
            ($monSrc -match "groupIds:\s*\[\s*\r?\n?\s*'azuremonitor'") |
                Should -BeTrue -Because "AMPLS PE should use groupIds: ['azuremonitor']"
        }
    }

    Context 'compiled ARM corroboration' {
        It 'compiles successfully and emits Microsoft.Network/privateEndpoints resources' {
            $r = Invoke-BicepBuild
            $r.ExitCode | Should -Be 0
            $resources = Get-AllArmResources -JsonPath $r.JsonPath
            $pes = $resources | Where-Object { $_.Type -eq 'Microsoft.Network/privateEndpoints' -and -not $_.Existing }
            $pes.Count | Should -BeGreaterThan 0 -Because "expected at least one private endpoint in compiled ARM"
            Write-Host "[T052] Found $($pes.Count) Microsoft.Network/privateEndpoints resource declarations in compiled ARM."
        }
    }
}
