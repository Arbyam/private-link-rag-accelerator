// =============================================================================
// Module: containerapps
// Task:   T027 (Phase 2a / PR-M)
// Purpose: Azure Container Apps Environment (Consumption-only, internal VNet)
//          + two Container Apps (`web` Next.js 15, `api` FastAPI) + one
//          Container App Job (`ingest` Python). All workloads bound to per-app
//          User-Assigned Managed Identities (UAMIs) from PR-C/identity, pull
//          images from ACR via UAMI (no admin user), have NO public ingress,
//          and emit logs/metrics to the LAW provisioned in PR-D/monitoring.
//
// Wiring contract:
//   Inputs:
//     - peSubnetId (= snet-aca from network module; infra subnet for ACA)
//     - lawId, appInsightsConnectionString (from monitoring module)
//     - acrLoginServer (from registry module; image registry)
//     - miWebId / miApiId / miIngestId (from identity module; UAMI resourceIds)
//     - appEnvVars (object map of common env vars; per-app overrides via
//       webExtraEnvVars / apiExtraEnvVars / ingestExtraEnvVars)
//     - ingestionStorageAccountName / ingestionQueueName (KEDA scale source)
//   Outputs:
//     - resourceId (managed environment)
//     - webAppFqdn / apiAppFqdn (internal FQDNs — NOT publicly resolvable)
//     - webAppName / apiAppName / ingestJobName
//     - {web,api,ingest}PrincipalId (passthrough convenience)
//
// Constitution (zero-trust, Principle I):
//   - vnetConfiguration.internal=true (LOCKED — no public ingress)
//   - All apps ingressExternal=false (LOCKED)
//   - All ACR pulls via UAMI; no registry admin user
//   - peerTrafficEncryption=true (mTLS between revisions)
//   - Diagnostics → LAW
//
// Cost (Phase 2 plan row 9):
//   - Consumption profile only (LOCKED — no D-series workload profiles)
//   - zoneRedundant=false
//   - web: minReplicas=0 (scale-to-zero); api: minReplicas=1 (chat cold-start
//     unacceptable); ingest: scale-to-zero on KEDA queue depth
//   - Estimated ~$5/mo light demo usage
//
// Image deployment:
//   - Image tags here are placeholders ("placeholder"). `azd deploy` rewrites
//     them at deploy time. The env vars and registry config persist.
// =============================================================================

targetScope = 'resourceGroup'

// -------------------------------------------------------------------------
// Identity / placement
// -------------------------------------------------------------------------

@description('Container Apps Environment name. App and job names are derived: ca-web-<env>, ca-api-<env>, cj-ingest-<env>.')
@minLength(2)
@maxLength(32)
param name string

@description('Azure region. Should match the resource group region.')
param location string

@description('Resource tags applied to the environment, apps, and job.')
param tags object = {}

@description('Resource ID of the snet-aca subnet (infrastructure subnet for the Container Apps Environment).')
param peSubnetId string

// -------------------------------------------------------------------------
// Observability
// -------------------------------------------------------------------------

@description('Resource ID of the Log Analytics workspace. Receives container console logs and per-app diagnostic metrics.')
param lawId string

@description('Application Insights connection string. Plumbed into all three workloads as APPLICATIONINSIGHTS_CONNECTION_STRING.')
@secure()
param appInsightsConnectionString string

// -------------------------------------------------------------------------
// Registry + identity wiring
// -------------------------------------------------------------------------

@description('ACR login server (e.g., myacr.azurecr.io). Used to construct image references and to authorize pulls via UAMI.')
param acrLoginServer string

@description('Resource ID of the web app User-Assigned Managed Identity (mi-web). Must already have AcrPull on the registry.')
param miWebId string

@description('Resource ID of the api app User-Assigned Managed Identity (mi-api). Must already have AcrPull on the registry.')
param miApiId string

@description('Resource ID of the ingest job User-Assigned Managed Identity (mi-ingest). Must already have AcrPull on the registry and Storage Queue Data Reader on the ingestion storage account (for KEDA workload-identity auth).')
param miIngestId string

// -------------------------------------------------------------------------
// Application environment variables
// -------------------------------------------------------------------------

@description('Common environment variables applied to all three workloads. Map of name → value. azd deploy may inject additional values from infra outputs.')
param appEnvVars object = {}

@description('Extra env vars for the web app (e.g., NEXT_PUBLIC_API_URL once the api FQDN is known). Merged on top of appEnvVars.')
param webExtraEnvVars object = {}

@description('Extra env vars for the api app (e.g., COSMOS_ENDPOINT, AOAI_ENDPOINT). Merged on top of appEnvVars.')
param apiExtraEnvVars object = {}

@description('Extra env vars for the ingest job. Merged on top of appEnvVars.')
param ingestExtraEnvVars object = {}

// -------------------------------------------------------------------------
// Ingest job KEDA configuration
// -------------------------------------------------------------------------

@description('Storage account name backing the ingestion queue. KEDA uses this with workload-identity auth (mi-ingest) to read queue depth — NO shared key required.')
param ingestionStorageAccountName string

@description('Storage queue name that triggers ingestion runs. Default matches data-model.md §6 (BlobCreated/BlobDeleted Event Grid → queue).')
param ingestionQueueName string = 'ingestion-events'

@description('KEDA scale threshold: spawn one job replica for every N messages in the queue.')
@minValue(1)
@maxValue(100)
param ingestQueueLength int = 5

// =============================================================================
// Helpers — convert object env-var maps to the {name, value} array shape that
// the Container Apps RP expects, then merge common + per-app overrides.
// =============================================================================

var webEnvMerged = union(appEnvVars, webExtraEnvVars, {
  APPLICATIONINSIGHTS_CONNECTION_STRING: appInsightsConnectionString
})
var apiEnvMerged = union(appEnvVars, apiExtraEnvVars, {
  APPLICATIONINSIGHTS_CONNECTION_STRING: appInsightsConnectionString
})
var ingestEnvMerged = union(appEnvVars, ingestExtraEnvVars, {
  APPLICATIONINSIGHTS_CONNECTION_STRING: appInsightsConnectionString
})

var webEnvArray = [for kv in items(webEnvMerged): { name: kv.key, value: kv.value }]
var apiEnvArray = [for kv in items(apiEnvMerged): { name: kv.key, value: kv.value }]
var ingestEnvArray = [for kv in items(ingestEnvMerged): { name: kv.key, value: kv.value }]

// Derived names ----------------------------------------------------------------

var webAppName = 'ca-web-${name}'
var apiAppName = 'ca-api-${name}'
var ingestJobName = 'cj-ingest-${name}'

// =============================================================================
// AVM: Container Apps Managed Environment
// Reference: https://github.com/Azure/bicep-registry-modules/tree/main/avm/res/app/managed-environment
// Version pinned to 0.13.3 (latest stable as of 2026-05-08).
// =============================================================================
module env 'br/public:avm/res/app/managed-environment:0.13.3' = {
  name: 'cae-${name}'
  params: {
    name: name
    location: location
    tags: tags

    // --- Zero-trust posture (Constitution Principle I) ---
    // internal=true → no public load balancer; all ingress is VNet-internal.
    internal: true
    infrastructureSubnetResourceId: peSubnetId
    // publicNetworkAccess controls the management plane to the env. Leave
    // 'Enabled' so `azd deploy` revision updates work via ARM without
    // requiring jumpbox/Bastion. Data-plane ingress is still VNet-only via
    // internal=true.
    publicNetworkAccess: 'Enabled'

    // --- Cost: Consumption profile only (LOCKED — Phase 2 plan row 9) ---
    workloadProfiles: [
      {
        name: 'Consumption'
        workloadProfileType: 'Consumption'
      }
    ]
    zoneRedundant: false

    // --- Defense in depth: encrypt pod-to-pod (mTLS) traffic ---
    peerTrafficEncryption: true

    // --- Observability: console logs to LAW; AVM resolves customerId/sharedKey ---
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsWorkspaceResourceId: lawId
    }

    // --- Application Insights (native, not Dapr) ---
    appInsightsConnectionString: appInsightsConnectionString
  }
}

// =============================================================================
// AVM: Container App — web (Next.js 15)
// Reference: https://github.com/Azure/bicep-registry-modules/tree/main/avm/res/app/container-app
// Version pinned to 0.22.1 (latest stable as of 2026-05-08).
// =============================================================================
module webApp 'br/public:avm/res/app/container-app:0.22.1' = {
  name: 'ca-web-${name}'
  params: {
    name: webAppName
    location: location
    tags: tags
    environmentResourceId: env.outputs.resourceId
    workloadProfileName: 'Consumption'

    managedIdentities: {
      userAssignedResourceIds: [
        miWebId
      ]
    }

    registries: [
      {
        server: acrLoginServer
        identity: miWebId
      }
    ]

    // Internal ingress only — VNet-resolvable FQDN, no public IP.
    ingressExternal: false
    ingressTargetPort: 3000
    ingressTransport: 'auto'
    ingressAllowInsecure: false

    scaleSettings: {
      minReplicas: 0
      maxReplicas: 2
      rules: [
        {
          name: 'http-concurrency'
          http: {
            metadata: {
              concurrentRequests: '50'
            }
          }
        }
      ]
    }

    containers: [
      {
        name: 'web'
        image: '${acrLoginServer}/web:placeholder'
        resources: {
          cpu: json('0.5')
          memory: '1Gi'
        }
        env: webEnvArray
      }
    ]

    diagnosticSettings: [
      {
        name: '${webAppName}-diag'
        workspaceResourceId: lawId
        metricCategories: [
          { category: 'AllMetrics' }
        ]
      }
    ]
  }
}

// =============================================================================
// AVM: Container App — api (FastAPI)
// Always-on (minReplicas=1) so the chat endpoint never cold-starts.
// =============================================================================
module apiApp 'br/public:avm/res/app/container-app:0.22.1' = {
  name: 'ca-api-${name}'
  params: {
    name: apiAppName
    location: location
    tags: tags
    environmentResourceId: env.outputs.resourceId
    workloadProfileName: 'Consumption'

    managedIdentities: {
      userAssignedResourceIds: [
        miApiId
      ]
    }

    registries: [
      {
        server: acrLoginServer
        identity: miApiId
      }
    ]

    ingressExternal: false
    ingressTargetPort: 8000
    ingressTransport: 'auto'
    ingressAllowInsecure: false

    scaleSettings: {
      minReplicas: 1
      maxReplicas: 3
      rules: [
        {
          name: 'http-concurrency'
          http: {
            metadata: {
              concurrentRequests: '50'
            }
          }
        }
      ]
    }

    containers: [
      {
        name: 'api'
        image: '${acrLoginServer}/api:placeholder'
        resources: {
          cpu: json('0.5')
          memory: '1Gi'
        }
        env: apiEnvArray
        probes: [
          {
            type: 'Liveness'
            httpGet: {
              path: '/healthz'
              port: 8000
              scheme: 'HTTP'
            }
            initialDelaySeconds: 10
            periodSeconds: 30
            timeoutSeconds: 5
            failureThreshold: 3
          }
          {
            type: 'Readiness'
            httpGet: {
              path: '/healthz'
              port: 8000
              scheme: 'HTTP'
            }
            initialDelaySeconds: 5
            periodSeconds: 10
            timeoutSeconds: 5
            failureThreshold: 3
          }
        ]
      }
    ]

    diagnosticSettings: [
      {
        name: '${apiAppName}-diag'
        workspaceResourceId: lawId
        metricCategories: [
          { category: 'AllMetrics' }
        ]
      }
    ]
  }
}

// =============================================================================
// AVM: Container App Job — ingest (Python doc parsing + embedding)
// Event-driven KEDA azure-queue scaler authenticated via UAMI workload-identity
// (NO shared key — storage account has shared-key auth disabled per T022).
// Reference: https://github.com/Azure/bicep-registry-modules/tree/main/avm/res/app/job
// Version pinned to 0.7.1 (latest stable as of 2026-05-08).
// =============================================================================
module ingestJob 'br/public:avm/res/app/job:0.7.1' = {
  name: 'cj-ingest-${name}'
  params: {
    name: ingestJobName
    location: location
    tags: tags
    environmentResourceId: env.outputs.resourceId
    workloadProfileName: 'Consumption'

    managedIdentities: {
      userAssignedResourceIds: [
        miIngestId
      ]
    }

    registries: [
      {
        server: acrLoginServer
        identity: miIngestId
      }
    ]

    triggerType: 'Event'
    replicaTimeout: 1800
    replicaRetryLimit: 3

    eventTriggerConfig: {
      parallelism: 1
      replicaCompletionCount: 1
      scale: {
        minExecutions: 0
        maxExecutions: 10
        pollingInterval: 30
        rules: [
          {
            name: 'queue-depth'
            type: 'azure-queue'
            // KEDA workload-identity auth: identity = UAMI resourceId. KEDA
            // will use the UAMI's federated credentials to call the Storage
            // Queue API; no account key, no SAS, no connection string.
            identity: miIngestId
            metadata: {
              accountName: ingestionStorageAccountName
              queueName: ingestionQueueName
              queueLength: '${ingestQueueLength}'
            }
          }
        ]
      }
    }

    containers: [
      {
        name: 'ingest'
        image: '${acrLoginServer}/ingest:placeholder'
        resources: {
          cpu: json('1.0')
          memory: '2Gi'
        }
        env: ingestEnvArray
      }
    ]
  }
}

// =============================================================================
// Outputs — consumed by the wiring layer (T030) and azd deploy.
// Internal FQDNs are NOT publicly resolvable; they resolve only inside the
// platform VNet (or via Bastion jumpbox per T028).
// =============================================================================

@description('Resource ID of the Container Apps Managed Environment.')
output resourceId string = env.outputs.resourceId

@description('Name of the Container Apps Managed Environment.')
output name string = env.outputs.name

@description('Default DNS suffix for the environment (e.g., <hash>.<region>.azurecontainerapps.io). For internal envs, the FQDN format is <app>.internal.<defaultDomain>.')
output defaultDomain string = env.outputs.defaultDomain

@description('Internal FQDN of the web Container App. Resolves only inside the platform VNet.')
output webAppFqdn string = webApp.outputs.fqdn

@description('Internal FQDN of the api Container App. Resolves only inside the platform VNet. Plumb this into the web app as NEXT_PUBLIC_API_URL.')
output apiAppFqdn string = apiApp.outputs.fqdn

@description('Resource name of the web Container App.')
output webAppName string = webApp.outputs.name

@description('Resource name of the api Container App.')
output apiAppName string = apiApp.outputs.name

@description('Resource name of the ingest Container App Job.')
output ingestJobName string = ingestJob.outputs.name

@description('Resource ID of the web Container App.')
output webAppResourceId string = webApp.outputs.resourceId

@description('Resource ID of the api Container App.')
output apiAppResourceId string = apiApp.outputs.resourceId

@description('Resource ID of the ingest Container App Job.')
output ingestJobResourceId string = ingestJob.outputs.resourceId

@description('Pass-through: principalId of the web UAMI (for downstream RBAC fan-out in T029).')
output webPrincipalId string = reference(miWebId, '2024-11-30').principalId

@description('Pass-through: principalId of the api UAMI (for downstream RBAC fan-out in T029).')
output apiPrincipalId string = reference(miApiId, '2024-11-30').principalId

@description('Pass-through: principalId of the ingest UAMI (for downstream RBAC fan-out in T029).')
output ingestPrincipalId string = reference(miIngestId, '2024-11-30').principalId
