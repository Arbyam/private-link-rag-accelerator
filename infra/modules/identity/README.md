# `infra/modules/identity` — User-Assigned Managed Identities

> **Task:** T018 (Phase 2a / PR-C)
> **AVM module:** [`avm/res/managed-identity/user-assigned-identity`](https://github.com/Azure/bicep-registry-modules/tree/main/avm/res/managed-identity/user-assigned-identity) `0.4.1`
> **Owner:** Dallas (Infra)

## Purpose

Provisions the workload **user-assigned managed identities (UAMIs)** consumed by
every compute principal in the Private RAG Accelerator. UAMIs replace shared
keys throughout the architecture per **Constitution Principle I — zero-trust /
managed identity everywhere**.

This module only **creates** the identities. **Role assignments** and
`main.bicep` wiring are deliberately deferred to **PR-O (T029/T030)** so that
the data-plane modules (Cosmos, Search, AOAI, Storage, Doc Intel, ACR) can
finish landing first.

## Identities Created

| Symbolic name | Resource name (default)            | Consumer                                    | Notes |
|---------------|------------------------------------|---------------------------------------------|-------|
| `mi-api`      | `mi-api-{prefix}-{env}-{regionShort}`    | FastAPI backend Container App (`aca-api`)   | Talks to all PaaS data-plane services |
| `mi-ingest`   | `mi-ingest-{prefix}-{env}-{regionShort}` | Ingest worker Container App (`aca-ingest`)  | Same surface as `mi-api`, write-scoped roles |
| `mi-web`      | `mi-web-{prefix}-{env}-{regionShort}`    | Next.js frontend Container App (`aca-web`)  | `AcrPull` only — web calls APIM, never PaaS direct |

### Why no APIM / deploy identity here?

- **APIM** is provisioned with a **system-assigned** identity in PR-N
  (`infra/modules/apim/main.bicep`). That identity is intrinsic to the APIM
  resource and cannot be created in advance from this module.
- **GitHub Actions / `azd` deploys** use a **subscription-scoped service
  principal with OIDC federated credentials** — not a workload UAMI inside the
  RG. There is therefore no `id-deploy` to provision here.

## Inputs

| Name                  | Type   | Required | Default                       | Description |
|-----------------------|--------|----------|-------------------------------|-------------|
| `location`            | string | no       | `resourceGroup().location`    | Azure region for the UAMIs. |
| `tags`                | object | no       | `{}`                          | Tags applied to every identity (propagated from `main.bicep`). |
| `identityApiName`     | string | **yes**  | —                             | Name of the `mi-api` UAMI. Supplied as `names.identityApi` from `main.bicep`. |
| `identityIngestName`  | string | **yes**  | —                             | Name of the `mi-ingest` UAMI. Supplied as `names.identityIngest`. |
| `identityWebName`     | string | **yes**  | —                             | Name of the `mi-web` UAMI. Supplied as `names.identityWeb`. |

## Outputs

Per-identity outputs match the contract already pre-wired in `infra/main.bicep`
(T015) — the consumer can simply uncomment the existing module block.

| Output                          | Type   | Description |
|---------------------------------|--------|-------------|
| `identityApiId`                 | string | Resource ID of `mi-api`. |
| `identityApiPrincipalId`        | string | Object ID for role assignments. |
| `identityApiClientId`           | string | Client ID for token requests / federated credentials. |
| `identityIngestId`              | string | Resource ID of `mi-ingest`. |
| `identityIngestPrincipalId`     | string | Object ID for role assignments. |
| `identityIngestClientId`        | string | Client ID. |
| `identityWebId`                 | string | Resource ID of `mi-web`. |
| `identityWebPrincipalId`        | string | Object ID for role assignments. |
| `identityWebClientId`           | string | Client ID. |
| `identities`                    | object | Aggregate map `{ api, ingest, web } → { resourceId, principalId, clientId, name }` — convenience for PR-O role-assignment loops. |

## Identity → Role Mapping (informational; assignments live in PR-O)

This is the source-of-truth role matrix from
`.squad/agents/ripley/phase-2-plan.md` §F (Principle I). PR-O implements these
as `Microsoft.Authorization/roleAssignments` against each target resource.

| Identity      | Target service     | Role |
|---------------|--------------------|------|
| `mi-api`      | Cosmos DB          | Cosmos DB Built-in Data Contributor |
| `mi-api`      | AI Search          | Search Index Data Reader |
| `mi-api`      | Azure OpenAI       | Cognitive Services OpenAI User |
| `mi-api`      | Storage (Blob)     | Storage Blob Data Reader |
| `mi-api`      | Document Intel.    | Cognitive Services User |
| `mi-api`      | ACR                | AcrPull |
| `mi-ingest`   | Cosmos DB          | Cosmos DB Built-in Data Contributor |
| `mi-ingest`   | AI Search          | Search Index Data Contributor |
| `mi-ingest`   | Azure OpenAI       | Cognitive Services OpenAI User |
| `mi-ingest`   | Storage (Blob)     | Storage Blob Data Contributor |
| `mi-ingest`   | Document Intel.    | Cognitive Services User |
| `mi-ingest`   | ACR                | AcrPull |
| `mi-web`      | ACR                | AcrPull |

`mi-web` intentionally has **no PaaS data-plane roles** — the Next.js frontend
calls APIM only. APIM's own system-assigned identity (provisioned in PR-N)
holds `Cognitive Services OpenAI User` on AOAI and `Key Vault Secrets User`
on Key Vault.

## Consuming this module from `main.bicep`

The shell in `infra/main.bicep` (T015) already includes the call site,
commented out. PR-O simply uncomments it:

```bicep
module identity 'modules/identity/main.bicep' = {
  name: 'identity'
  scope: rg
  params: {
    location:           location
    tags:               tags
    identityApiName:    names.identityApi
    identityIngestName: names.identityIngest
    identityWebName:    names.identityWeb
  }
}
```

Downstream modules then reference, for example:

```bicep
identityApiPrincipalId:    identity.outputs.identityApiPrincipalId
identityIngestPrincipalId: identity.outputs.identityIngestPrincipalId
```

…or iterate over `identity.outputs.identities` for symmetric role-assignment
loops.

## Validation

```powershell
az bicep build --file infra/modules/identity/main.bicep --outdir $env:TEMP
```

Must exit `0` with no errors. Warnings about unused outputs are acceptable
while downstream modules are still placeholder-commented.

## Constitutional Compliance

| Principle | Compliance |
|-----------|------------|
| **I — Zero public endpoints / managed identity everywhere** | UAMIs are the *enabling* primitive. No shared keys are issued or stored anywhere in the codebase as a result. |
| **II — Idempotent IaC** | Deterministic naming (`mi-{role}-{prefix}-{env}-{regionShort}`), no `uniqueString()` randomness, declarative AVM-only resources — re-running `azd up` is a no-op. |
