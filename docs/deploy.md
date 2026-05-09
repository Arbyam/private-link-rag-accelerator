# Deploying the Private RAG Accelerator (`azd up`)

> Target SLA (SC-001): **≤ 60 minutes total wall-clock**, **≤ 15 minutes
> hands-on** from `azd init` to a printed UI URL.

This document describes the end-to-end `azd up` flow wired by `azure.yaml`
(T055) and the preflight gate that protects it (T056). For architecture and
constitutional guarantees see `specs/001-private-rag-accelerator/spec.md`.

## 1. Prerequisites

Install on the machine that will run `azd up`:

| Tool                  | Min version | Purpose                                  |
| --------------------- | ----------- | ---------------------------------------- |
| Azure CLI (`az`)      | 2.65        | RBAC + ARM control-plane calls           |
| Azure Developer CLI   | 1.13        | Orchestration + service deploy           |
| Bicep                 | 0.30        | `infra/main.bicep` compilation           |
| PowerShell (`pwsh`)   | 7.4         | Hook execution (Windows + posix)         |
| Docker                | 24.x        | Required by `azd` even with `remoteBuild`|
| Node.js               | 20.x        | `apps/web` build context introspection   |
| Python                | 3.12        | `apps/api` and `apps/ingest`             |

`scripts/preflight.{ps1,sh}` validates these on every `azd up` (see §4).

You must hold **Owner** or **Contributor + User Access Administrator** at
the subscription you target (private-DNS-zone link creation requires it).

## 2. One-time setup

```pwsh
git clone https://github.com/Arbyam/private-link-rag-accelerator
cd private-link-rag-accelerator

azd auth login                          # device-code or browser
azd env new <env-name>                  # e.g. rag-prod-eus2
azd env set AZURE_LOCATION eastus2
azd env set AZURE_SUBSCRIPTION_ID <sub-guid>
```

## 3. Run the deployment

```pwsh
azd up
```

That single command runs **four phases**, each gated on the prior:

### Phase 1 — `preprovision` (T056)
Invokes `scripts/preflight.ps1` (Windows) or `scripts/preflight.sh` (posix).
Validates CLI versions, `az` login state, region/SKU availability, AOAI +
AI Search + ACA quota, and caller RBAC. **Any failure aborts `azd up`** with
the script's actionable message; nothing is provisioned.

### Phase 2 — `provision`
`azd` compiles `infra/main.bicep` and submits a subscription-scope
deployment that creates: resource group, hub-spoke VNet + private DNS zones,
managed identities, Log Analytics + App Insights, ACR (private), Key Vault
(private), Storage (private), Cosmos DB (private), Azure OpenAI (private),
AI Search S1 (private), Document Intelligence (private), ACA environment
(internal), Container Apps `web` + `api` and Container Apps Job `ingest`,
and APIM (StandardV2, internal). Expected wall-clock ≈ 35 minutes.

### Phase 3 — `postprovision` (T047)
`scripts/postprovision.ps1` runs idempotently:
1. PUT `kb-index` to AI Search from `infra/search/kb-index.json` (skipped if
   it already exists).
2. Seed up to five blobs from `samples/` into `shared-corpus` (skipped on
   conflict).
3. Print **UI URL** (`https://${webAppFqdn}` — VNet-internal) and **Bastion
   connection** instructions for the jumpbox.

### Phase 4 — `deploy`
For each service in `services:` (web, api, ingest), `azd`:
1. Reads `docker.remoteBuild: true` and uploads the `apps/<svc>` build
   context to ACR Tasks (`az acr build` under the hood).
2. ACR Tasks builds inside the registry's VNet — no public DNS / no public
   network egress is required from your workstation.
3. Pushes the new image tag and updates the matching Container App
   revision. `resourceName` is bound to the Bicep output (`WEB_APP_NAME`,
   `API_APP_NAME`, `INGEST_JOB_NAME`).

## 4. Expected outputs

After `azd up` completes:

```text
SUCCESS: Your application was provisioned and deployed in 47m13s.
You can view the resources created under the resource group rg-rag-prod-eus2.

Outputs:
  uiUrl           https://ca-web-rag-prod-eus2.<region>.azurecontainerapps.io
  apimGatewayUrl  https://apim-…/api
  webAppFqdn      ca-web-…
  apiAppFqdn      ca-api-…
```

**The UI URL is internal-only.** Reach it from the Bastion jumpbox:

```text
1. Open the Azure Portal → Bastion → Connect to vm-jumpbox
2. From the jumpbox browser, navigate to the printed uiUrl
```

## 5. Re-running

`azd up` is idempotent: re-running on a healthy environment is a no-op
(provision converges on `What-If: NoChange`, postprovision logs every step
as `skipped`, deploy uploads a new image only if `apps/<svc>` changed).

`azd deploy <service>` redeploys a single workload without touching infra.

## 6. Troubleshooting

| Symptom                                        | Likely cause                                                | Fix                                                                                                                  |
| ---------------------------------------------- | ----------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `preflight: az not logged in`                  | `az login` token expired                                    | `az login` then re-run `azd up`                                                                                      |
| `preflight: quota` failure                     | Region quota exhausted (AOAI / Search / ACA cores)          | Pick a different region or request quota increase; gate is intentional (T056)                                        |
| `ACR push fails: name resolution`              | Local Docker pushing to private ACR over public DNS         | Confirm `docker.remoteBuild: true` is set in `azure.yaml` (T055). Local push is never used.                          |
| `remoteBuild` not recognized by your `azd`     | `azd` < 1.7                                                 | `winget upgrade microsoft.azd` (or rerun installer); fallback: `az acr build --registry <acrName> ./apps/<svc>`      |
| `postprovision skipped`                        | Hook env-vars missing (`AZURE_SEARCH_ENDPOINT`, …)          | `azd env get-values` to inspect; re-run `azd provision` then `azd hooks run postprovision`                           |
| ACA revision stuck `Provisioning`              | Image tag pushed but ACR pull token not yet propagated      | Wait 60s; re-run `azd deploy <svc>`                                                                                  |
| Cannot reach UI URL from laptop                | Working as intended — `webAppFqdn` is VNet-internal         | Connect via Bastion to the jumpbox VM and browse from there                                                          |

## 7. Tear-down

```pwsh
azd down --purge --force
```

Removes the resource group, soft-deleted Key Vault / OpenAI accounts, and
the deployment history. See also `.github/workflows/teardown.yml` (T013).
