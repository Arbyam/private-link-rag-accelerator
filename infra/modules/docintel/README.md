# `docintel` module

Deploys an **Azure AI Document Intelligence** account (Cognitive Services
`kind=FormRecognizer`) with zero public surface, fronted by a Private
Endpoint into `snet-pe`.

Implements task **T026** from
[`specs/001-private-rag-accelerator/tasks.md`](../../../specs/001-private-rag-accelerator/tasks.md)
per [research.md](../../../specs/001-private-rag-accelerator/research.md) D4.

## What it deploys

| Resource | Purpose |
|---|---|
| `Microsoft.CognitiveServices/accounts` (`kind=FormRecognizer`, SKU `S0`) | Document Intelligence account |
| `Microsoft.Network/privateEndpoints` (group `account`) | Private endpoint in `snet-pe` |
| Private DNS zone group → `privatelink.cognitiveservices.azure.com` | DNS resolution for the PE |
| `Microsoft.Insights/diagnosticSettings` | All logs + metrics → Log Analytics |

> **Note on the API kind.** Azure renamed the service to *Document
> Intelligence*, but the underlying ARM/Bicep `kind` is still
> `FormRecognizer`. That is intentional and not a typo.

## Constitution checklist

- ✅ **Zero public endpoints** — `publicNetworkAccess: 'Disabled'`,
  `networkAcls.defaultAction: 'Deny'`, ingress only via Private Endpoint.
- ✅ **Local auth disabled** — `disableLocalAuth: true`; Entra ID + managed
  identity only. No account keys in Key Vault, ever.
- ✅ **Diagnostics → LAW** — `allLogs` + `AllMetrics` shipped to the
  workspace passed in via `lawId`.
- ✅ **Idempotent** — purely declarative AVM module; re-running the
  deployment converges to the same state.

## Inputs

| Name | Type | Required | Notes |
|---|---|---|---|
| `name` | `string` | ✅ | 2–64 chars. Also used verbatim as `customSubDomainName` (required for PE). |
| `location` | `string` | ✅ | Region must offer Document Intelligence (e.g. `eastus`, `eastus2`, `westus2`, `westeurope`). |
| `tags` | `object` | — | Defaults to `{}`. |
| `peSubnetId` | `string` | ✅ | Resource ID of `snet-pe` (from `network` module → `snetPeId`). |
| `pdnsCogsvcsId` | `string` | ✅ | Resource ID of the `privatelink.cognitiveservices.azure.com` Private DNS zone. **Wire from `network.outputs.pdnsCognitiveId`** — the network module's name for that zone. |
| `lawId` | `string` | ✅ | Resource ID of the Log Analytics workspace. |
| `sku` | `string` | — | `S0` (default) or `F0`. The accelerator standardizes on `S0`; `F0` is too constrained for the demo flow (~$3/mo per Phase 2a plan). |

## Outputs

| Name | Type | Notes |
|---|---|---|
| `resourceId` | `string` | Account resource ID — pass to the identity module for RBAC. |
| `name` | `string` | Account name. |
| `endpoint` | `string` | `https://<name>.cognitiveservices.azure.com/` — what callers configure as `AZURE_DOCINTEL_ENDPOINT`. |

## DNS zone — important

Document Intelligence and (most) Cognitive Services share the
`privatelink.cognitiveservices.azure.com` zone. **Azure OpenAI is the
exception** — it uses `privatelink.openai.azure.com`. When wiring this
module from `infra/main.bicep`, pass the **`pdnsCognitiveId`** output
from the network module, not `pdnsOpenaiId`.

## RBAC (handled outside this module)

Per the team convention, role assignments live in the identity module /
top-level composition, not here. Grant managed identities the
**Cognitive Services User** role (`a97b65f3-24c7-4388-baec-2e87135dc908`)
on `resourceId` to call the analyze endpoints with Entra auth.

## Validate locally

```pwsh
az bicep build --file infra/modules/docintel/main.bicep
```

Expected: exit 0, zero warnings.
