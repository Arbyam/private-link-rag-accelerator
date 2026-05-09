# `openai/` — Azure OpenAI (private endpoint + model deployments)

**Task:** T025 — **PR:** PR-I (Phase 2a)
**AVM:** [`avm/res/cognitive-services/account@0.14.2`](https://github.com/Azure/bicep-registry-modules/tree/main/avm/res/cognitive-services/account)

## What this module does

Provisions an Azure OpenAI account (Cognitive Services `kind: OpenAI`) with:

- **Zero public access** — `publicNetworkAccess: 'Disabled'`, `networkAcls.defaultAction: 'Deny'`.
- **Entra-only auth** — `disableLocalAuth: true`. Apps use their managed identity with the `Cognitive Services OpenAI User` role (assigned in PR-O / T029).
- **`customSubDomainName`** set to the resource name (required for token auth + PE resolution).
- **Private endpoint** in `snet-pe` with a zone group bound to `privatelink.openai.azure.com`.
- **Two model deployments**, per [research.md](../../../specs/001-private-rag-accelerator/research.md) **D2**:
  - **Chat:** `gpt-5` (deployment name `gpt-5`), version `2025-08-07`, SKU `Standard`, capacity `10` (10 K TPM).
  - **Embeddings:** `text-embedding-3-large` (3072 dims, deployment name `text-embedding-3-large`), version `1`, SKU `Standard`, capacity `10`.
- **Diagnostics** (`allLogs` + `AllMetrics`) shipped to the platform Log Analytics workspace.

## Why `Standard` (not `GlobalStandard`)

Standard deployments stay region-locked. GlobalStandard load-balances across regions, which conflicts with strict Private Link semantics (the request can hit a region whose PE the customer hasn't approved). Customers can flip the `deploymentSku` parameter for production if they explicitly want that trade-off.

## Why no manual `dependsOn` chain on deployments

Two `Microsoft.CognitiveServices/accounts/deployments` resources deployed in parallel race and one historically returns 409. AVM `0.14.2` already applies `@batchSize(1)` to the `deployments` resource, so the chain is enforced by the AVM module — we don't need to express it in this caller.

## Inputs

| Name                      | Type     | Required | Default                          | Notes |
|---------------------------|----------|----------|----------------------------------|-------|
| `name`                    | `string` | ✅       | —                                | Globally unique (2–64). Also used as `customSubDomainName`. |
| `location`                | `string` | ✅       | —                                | Must support both models (e.g., `eastus2`, `southcentralus`, `northcentralus`, `westus3`). |
| `tags`                    | `object` |          | `{}`                             | |
| `peSubnetId`              | `string` | ✅       | —                                | Resource ID of `snet-pe`. |
| `pdnsOpenaiId`            | `string` | ✅       | —                                | Resource ID of `privatelink.openai.azure.com`. |
| `lawId`                   | `string` | ✅       | —                                | Log Analytics workspace resource ID. |
| `chatModel`               | `string` |          | `gpt-5`                          | |
| `chatModelVersion`        | `string` |          | `2025-08-07`                     | Pinned for reproducibility. |
| `chatDeploymentName`      | `string` |          | `gpt-5`                          | The deployment id apps use. |
| `chatCapacity`            | `int`    |          | `10`                             | TPM × 1000. |
| `embeddingModel`          | `string` |          | `text-embedding-3-large`         | |
| `embeddingModelVersion`   | `string` |          | `1`                              | |
| `embeddingDeploymentName` | `string` |          | `text-embedding-3-large`         | |
| `embeddingCapacity`       | `int`    |          | `10`                             | TPM × 1000. |
| `deploymentSku`           | `string` |          | `Standard`                       | `Standard` or `GlobalStandard`. |

## Outputs

| Name                       | Type     | Notes |
|----------------------------|----------|-------|
| `resourceId`               | `string` | Used by PR-O for role assignments and by PR-J (search) for the AOAI shared private link target. |
| `name`                     | `string` | |
| `endpoint`                 | `string` | e.g., `https://<name>.openai.azure.com/`. |
| `chatDeploymentName`       | `string` | Echoed for downstream env-var wiring. |
| `embeddingDeploymentName`  | `string` | Echoed for downstream env-var wiring. |

## Constitution checklist

- [x] **Zero public endpoints** — `publicNetworkAccess: 'Disabled'` + `defaultAction: 'Deny'`. Only path in is the PE in `snet-pe`.
- [x] **Local auth disabled** — `disableLocalAuth: true`. No API keys.
- [x] **Diagnostics → LAW** — `allLogs` + `AllMetrics` to `lawId`.
- [x] **Idempotent** — re-running `azd up` produces zero diffs (AVM module + parameterised model versions).

## Cost (default config)

Pay-per-token at S0; demo token volume is low. Phase 2 budget envelope allocates **~$10/month** for this module (see `.squad/agents/ripley/phase-2-plan.md` row 11).

## Validation

```pwsh
az bicep build --file infra/modules/openai/main.bicep
```

Expected: exit 0, zero warnings.

## Wiring (consumed by `infra/main.bicep` in PR-O)

```bicep
module openai 'modules/openai/main.bicep' = {
  name: 'openai'
  params: {
    name:         '${namingPrefix}-aoai'
    location:     location
    tags:         tags
    peSubnetId:   network.outputs.peSubnetId
    pdnsOpenaiId: network.outputs.pdnsOpenaiId
    lawId:        monitoring.outputs.lawId
  }
}

// PR-J (search) takes an explicit dependsOn on this module so that the AI
// Search shared private link to AOAI works on first deploy.
```
