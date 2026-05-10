// =============================================================================
// Sub-module: bastion/jumpbox
// Task:       T028 (Phase 2a / PR-N)
// Purpose:    Linux jumpbox VM (Ubuntu 22.04 LTS, Standard_B2s) with no public
//             IP, SSH-key auth only, system-assigned managed identity, and an
//             18:00 UTC auto-shutdown schedule.
//
// Hand-rolled (not AVM compute/virtual-machine) because:
//   - The AVM VM module is large and forces many parameters that don't map to
//     this minimal break-glass jumpbox (data disks, extensions catalog, etc.).
//   - We need explicit control over the cloud-init payload, NIC, and the
//     DevTestLab auto-shutdown sibling resource.
//
// NSG: relies on snet-pe's NSG (provisioned by the network module). No NSG is
// created here — the constitution requires a single NSG per subnet.
// =============================================================================

targetScope = 'resourceGroup'

// -----------------------------------------------------------------------------
// Parameters
// -----------------------------------------------------------------------------

@description('VM name. Will also be used as computer name (truncated to 15 chars).')
@minLength(2)
@maxLength(64)
param name string

@description('Azure region.')
param location string

@description('Resource tags.')
param tags object = {}

@description('Resource ID of snet-pe (jumpbox lives here, not in AzureBastionSubnet).')
param vmSubnetId string

@description('Resource ID of the Log Analytics workspace for NIC diagnostic settings.')
param lawId string

@description('Linux admin username.')
param adminUsername string

@description('SSH public key for the admin user.')
@secure()
param adminPublicKey string

@description('VM size.')
param vmSize string = 'Standard_B2s'

// -----------------------------------------------------------------------------
// Cloud-init: idempotent install of az CLI, kubectl, docker, jq, git, unzip,
// curl, bicep CLI. Kept under 16 KB and safe to re-run.
// -----------------------------------------------------------------------------
var cloudInit = '''#cloud-config
package_update: true
package_upgrade: false
packages:
  - curl
  - jq
  - git
  - unzip
  - ca-certificates
  - apt-transport-https
  - lsb-release
  - gnupg
  - docker.io
runcmd:
  - [ bash, -lc, "command -v az || curl -sL https://aka.ms/InstallAzureCLIDeb | bash" ]
  - [ bash, -lc, "command -v kubectl || (curl -fsSLo /usr/local/bin/kubectl https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl && chmod +x /usr/local/bin/kubectl)" ]
  - [ bash, -lc, "command -v bicep || (curl -fsSLo /usr/local/bin/bicep https://github.com/Azure/bicep/releases/latest/download/bicep-linux-x64 && chmod +x /usr/local/bin/bicep)" ]
  - [ bash, -lc, "systemctl enable --now docker" ]
'''

// -----------------------------------------------------------------------------
// NIC — single dynamic private IP into snet-pe, no public IP. Accelerated
// networking is OFF: Standard_B2s (the budget-plan default for this jumpbox)
// is a burstable SKU and does NOT support accelerated networking. Bumping to
// Dsv4/Dsv5 would re-enable it but doubles idle cost.
// -----------------------------------------------------------------------------
resource nic 'Microsoft.Network/networkInterfaces@2024-05-01' = {
  name: 'nic-${name}'
  location: location
  tags: tags
  properties: {
    enableAcceleratedNetworking: false
    ipConfigurations: [
      {
        name: 'ipconfig1'
        properties: {
          privateIPAllocationMethod: 'Dynamic'
          subnet: {
            id: vmSubnetId
          }
        }
      }
    ]
  }
}

// -----------------------------------------------------------------------------
// VM — Ubuntu 22.04 LTS gen2, 30 GiB Premium SSD OS disk, system-assigned MI,
// SSH-only, automatic OS patching by platform.
// -----------------------------------------------------------------------------
resource vm 'Microsoft.Compute/virtualMachines@2024-07-01' = {
  name: name
  location: location
  tags: union(tags, {
    AutoShutdown: '18:00 UTC'
  })
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    hardwareProfile: {
      vmSize: vmSize
    }
    storageProfile: {
      imageReference: {
        publisher: 'Canonical'
        offer: '0001-com-ubuntu-server-jammy'
        sku: '22_04-lts-gen2'
        version: 'latest'
      }
      osDisk: {
        name: 'osdisk-${name}'
        caching: 'ReadWrite'
        createOption: 'FromImage'
        diskSizeGB: 30
        managedDisk: {
          storageAccountType: 'Premium_LRS'
        }
      }
    }
    osProfile: {
      computerName: substring(name, 0, min(length(name), 15))
      adminUsername: adminUsername
      customData: base64(cloudInit)
      linuxConfiguration: {
        disablePasswordAuthentication: true
        ssh: {
          publicKeys: [
            {
              path: '/home/${adminUsername}/.ssh/authorized_keys'
              keyData: adminPublicKey
            }
          ]
        }
        provisionVMAgent: true
        patchSettings: {
          patchMode: 'AutomaticByPlatform'
          assessmentMode: 'AutomaticByPlatform'
          automaticByPlatformSettings: {
            rebootSetting: 'IfRequired'
          }
        }
      }
    }
    networkProfile: {
      networkInterfaces: [
        {
          id: nic.id
        }
      ]
    }
    diagnosticsProfile: {
      bootDiagnostics: {
        enabled: true
      }
    }
  }
}

// -----------------------------------------------------------------------------
// Auto-shutdown @ 18:00 UTC via DevTest Lab schedule. Free, native to Azure,
// dramatically reduces idle burn for a break-glass jumpbox.
// Resource name MUST be 'shutdown-computevm-<vmName>' for the portal to wire
// the schedule into the VM's "Auto-shutdown" blade.
// -----------------------------------------------------------------------------
resource autoShutdown 'Microsoft.DevTestLab/schedules@2018-09-15' = {
  name: 'shutdown-computevm-${vm.name}'
  location: location
  tags: tags
  properties: {
    status: 'Enabled'
    taskType: 'ComputeVmShutdownTask'
    dailyRecurrence: {
      time: '1800'
    }
    timeZoneId: 'UTC'
    targetResourceId: vm.id
    notificationSettings: {
      status: 'Disabled'
      timeInMinutes: 30
    }
  }
}

// -----------------------------------------------------------------------------
// NIC diagnostic settings → LAW (constitution Principle II). Only metrics are
// available for NICs; there are no NIC log categories.
// -----------------------------------------------------------------------------
resource nicDiag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'diag-to-law'
  scope: nic
  properties: {
    workspaceId: lawId
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
      }
    ]
  }
}

// -----------------------------------------------------------------------------
// Outputs (consumed by the parent bastion module)
// -----------------------------------------------------------------------------
output vmId string = vm.id
output vmName string = vm.name
output principalId string = vm.identity.principalId
output privateIp string = nic.properties.ipConfigurations[0].properties.privateIPAddress
output nicId string = nic.id
