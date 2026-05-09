# `infra/modules/bastion`

> **Task:** T028 (Phase 2a / PR-N) — Azure Bastion + Linux jumpbox VM, gated by `deployBastion`.

Provisions break-glass admin access into the private VNet:

| Resource | SKU / size | Cost (eastus2) | Why |
|---|---|---|---|
| `Microsoft.Network/bastionHosts` (Developer) | Developer | **$0/mo** | Free shared-pool tier; single concurrent session is fine for SE demos. |
| `Microsoft.Network/networkInterfaces` (jumpbox NIC) | — | <$1/mo | No Public IP. Lives in `snet-pe`. Accelerated networking on. |
| `Microsoft.Compute/virtualMachines` (jumpbox) | `Standard_B2s` Linux Ubuntu 22.04 | ~$36/mo | Smallest sensible 2 vCPU / 4 GiB box; auto-shutdown caps the bill. |
| `Microsoft.Compute/disks` (OS disk) | 30 GiB Premium_LRS | ~$5/mo | |
| `Microsoft.DevTestLab/schedules` (auto-shutdown) | 18:00 UTC daily | $0 | Native Azure auto-shutdown. |

The whole module is gated by `deployBastion`. When `false`, **nothing** is deployed and all outputs are empty strings — callers can pipe outputs into `azd env` values without conditional logic.

---

## SKU deviation: Standard → Developer (accepted)

`specs/001-private-rag-accelerator/tasks.md` T028 says "Bastion Standard". Phase 2a v3 plan caps total monthly cost at $500 and locks **Developer SKU**.

The deviation is permanently accepted in [`/.squad/decisions/inbox/copilot-directive-20260509T062045Z-phase2a-wave3-audit.md` §4](../../../.squad/decisions/inbox/copilot-directive-20260509T062045Z-phase2a-wave3-audit.md). Trade-offs:

- **Pros:** $0/mo (saves ~$140/mo against the cap), seconds-to-deploy, no Public IP needed.
- **Cons:** single concurrent session, no IP-based connect, no shareable links, no native-client tunneling, no diagnostic settings (see below).

If a customer fork needs concurrency / tunneling, bump `skuName` to `Standard` and add a `publicIPAddressObject`. The AVM module (`avm/res/network/bastion-host:0.8.2`) handles both code paths.

## AVM vs hand-rolled

| Component | Choice | Reason |
|---|---|---|
| Bastion host | **AVM `avm/res/network/bastion-host:0.8.2`** | Native support for Developer SKU (`skuName: 'Developer'` → `virtualNetwork.id` instead of PIP); verified against the AVM `tests/e2e/developer/main.test.bicep` example. |
| Jumpbox VM + NIC + DevTestLab schedule | **Hand-rolled** (`jumpbox.bicep`) | The AVM `compute/virtual-machine` module is large and forces many parameters that don't map to a minimal break-glass jumpbox. Hand-rolled keeps the cloud-init payload, NIC, and auto-shutdown sibling readable. API versions are pinned to current GA. |

## Public IP

**No public IP is provisioned anywhere in this module.**

- Developer-SKU Bastion does not take an `ipConfigurations[].publicIPAddress` — it uses Microsoft's shared backend keyed off `properties.virtualNetwork.id`. AVM 0.8.2 enforces this internally.
- The jumpbox NIC has no `publicIPAddress` reference; inbound is via Bastion only.

## Diagnostic settings

- **Jumpbox NIC** → LAW (`AllMetrics`). NICs have no log categories.
- **Bastion Developer SKU** → not configured. The Developer tier runs on Microsoft-managed shared infra and does not surface `BastionAuditLogs` (the AVM Developer-SKU e2e test omits `diagnosticSettings` for the same reason). If/when this changes, add `diagnosticSettings: [{ workspaceResourceId: lawId, logCategoriesAndGroups: [{ categoryGroup: 'allLogs' }] }]` to the AVM call in `main.bicep`.

## Cloud-init (jumpbox bootstrap)

`jumpbox.bicep` injects a small (~1 KB) `#cloud-config` payload that idempotently installs:

- `az` CLI (Microsoft repo)
- `kubectl` (latest stable static binary)
- `bicep` CLI (latest GA static binary)
- `docker.io`, `jq`, `git`, `unzip`, `curl`, `ca-certificates`, `apt-transport-https`, `lsb-release`, `gnupg`

Each `runcmd` step uses `command -v <tool> || …` so re-running is a no-op.

## Auto-shutdown

`Microsoft.DevTestLab/schedules` named `shutdown-computevm-<vmName>` (the well-known portal-discoverable name) shuts the VM down at **18:00 UTC** daily. Notifications are disabled. Override via the portal or by editing the schedule resource.

## Module contract

### Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `deployBastion` | bool | `true` | Master gate. When `false`, deploys nothing. |
| `name` | string | — | Base name; resources are `bas-{name}`, `vm-jump-{name}`, `nic-vm-jump-{name}`. |
| `location` | string | — | Azure region. |
| `tags` | object | `{}` | Applied to every child resource. The jumpbox additionally gets `AutoShutdown: '18:00 UTC'`. |
| `bastionSubnetId` | string | — | `AzureBastionSubnet` resource ID. The vnet ID is derived from this; the subnet itself is not directly referenced (Developer SKU). |
| `vmSubnetId` | string | — | `snet-pe` resource ID. The jumpbox NIC lands here — VMs are forbidden in `AzureBastionSubnet`. |
| `lawId` | string | — | Log Analytics workspace for NIC diagnostics. |
| `adminUsername` | string | `azureuser` | Linux admin user. |
| `adminPublicKey` | secure string | — | SSH public key (single-line `ssh-rsa …`). Password auth is **disabled**. |
| `vmSize` | string | `Standard_B2s` | VM SKU. |

### Outputs

| Name | Description |
|---|---|
| `bastionResourceId` | Bastion host resource ID (empty when gated). |
| `bastionName` | Bastion host name (empty when gated). |
| `jumpboxResourceId` | Jumpbox VM resource ID (empty when gated). |
| `jumpboxPrincipalId` | System-assigned MI `principalId` for downstream RBAC (e.g. AcrPull); empty when gated. |
| `jumpboxPrivateIp` | Jumpbox NIC private IP (empty when gated). |

## Constitution checklist

- [x] **Zero public endpoints on the jumpbox** — NIC has no `publicIPAddress`.
- [x] **SSH key auth only** — `disablePasswordAuthentication: true`, no `adminPassword` parameter exists.
- [x] **Diagnostics → LAW** — NIC `AllMetrics`. Bastion Developer SKU diagnostics are not supported by Azure (documented above).
- [x] **Idempotent** — All resources use deterministic names; cloud-init `runcmd` steps are guarded with `command -v`.

## Validate locally

```pwsh
az bicep build --file infra/modules/bastion/main.bicep
```

Expect exit 0 and zero warnings.
