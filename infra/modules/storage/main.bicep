// =============================================================================
// Module: storage
// Task:   T022 (Phase 2a / PR-G.1 — supersedes partial close in PR #12)
// Purpose: Azure Storage Account (StorageV2 / Standard_LRS / Hot) configured for
//          zero-trust ingestion:
//          - publicNetworkAccess Disabled, networkAcls defaultAction Deny
//          - allowSharedKeyAccess false (Entra-only) + defaultToOAuthAuthentication
//          - allowBlobPublicAccess false, minimumTlsVersion TLS1_2
//          - 2 private endpoints (blob + queue) into snet-pe — file/table/dfs PEs
//            dropped per Ripley phase-2-plan row 13 (we use neither file shares,
//            table storage, nor hierarchical namespace; cost saving ~$22/mo).
//          - 3 pre-created blob containers:
//              * `shared-corpus`        — admin-curated KB
//              * `user-uploads`         — per-user uploads (30-day lifecycle delete)
//              * `eventgrid-deadletter` — Event Grid undelivered events
//          - 1 pre-created queue `ingestion-events` — target of Event Grid
//            subscription on shared-corpus blob events.
//          - Blob soft-delete (7d) + container soft-delete (7d).
//          - Lifecycle policy: delete blobs under `user-uploads/` prefix older
//            than 30 days (mirrors conversation TTL — FR-005 / SC-012).
//          - Event Grid system topic on the storage account, with a
//            CloudEvents-1.0 subscription on Blob{Created,Deleted} for the
//            `shared-corpus` container only — delivers to the
//            `ingestion-events` storage queue (data-model.md §6).
//          - Diagnostics shipped to a Log Analytics workspace (storage account
//            metrics + blob-service logs + queue-service logs).
//
// RBAC scoping:
//   - Cross-module RBAC (app UAMIs → storage) is wired by PR-O (T029) — out
//     of scope here.
//   - Intra-module RBAC for the Event Grid system topic's system-assigned MI
//     IS included here, because:
//       (a) shared-key access is disabled, so EventGrid cannot fall back to
//           internal key-based delivery; MI delivery is the only path, and
//       (b) the topic, the queue, and the dead-letter container all live in
//           this module — there is no cross-module dependency.
//     Two assignments are emitted at storage-account scope:
//       * Storage Queue Data Message Sender   (deliver to ingestion-events)
//       * Storage Blob Data Contributor       (write to eventgrid-deadletter)
// =============================================================================

metadata name = 'Storage Account module (T022)'
metadata description = '''
StorageV2 (Standard_LRS, Hot) with zero-trust posture, 3 containers, 1 queue,
soft-delete, lifecycle policy on user-uploads, and an Event Grid system topic
that streams shared-corpus blob events to a Storage Queue using CloudEvents 1.0.
Built on AVM `avm/res/storage/storage-account` 0.27.1.
'''

targetScope = 'resourceGroup'

// ─────────────────────────────────────────────────────────────────────────────
// Parameters
// ─────────────────────────────────────────────────────────────────────────────

@description('Globally-unique storage account name. Lowercase alphanumerics only, 3–24 chars.')
@minLength(3)
@maxLength(24)
param name string

@description('Azure region for the storage account.')
param location string

@description('Resource tags applied to the storage account, its private endpoints, and the Event Grid system topic.')
param tags object = {}

@description('Resource ID of the private-endpoint subnet (snet-pe).')
param peSubnetId string

@description('Resource ID of the privatelink.blob.core.windows.net Private DNS Zone.')
param pdnsBlobId string

@description('Resource ID of the privatelink.queue.core.windows.net Private DNS Zone.')
param pdnsQueueId string

@description('Resource ID of the Log Analytics workspace receiving diagnostic logs.')
param lawId string

@description('Principal IDs that receive `Storage Blob Data Contributor` on this account (write to shared-corpus / user-uploads). Wired by PR-O / T029 — typically the ingest UAMI.')
param blobContributorPrincipalIds array = []

@description('Principal IDs that receive `Storage Blob Data Reader` on this account (read corpora). Wired by PR-O / T029 — typically the api UAMI.')
param blobReaderPrincipalIds array = []

@description('Principal IDs that receive `Storage Queue Data Reader` on this account (KEDA scaler queue depth). Wired by PR-O / T029 — typically the ingest UAMI.')
param queueReaderPrincipalIds array = []

// ─────────────────────────────────────────────────────────────────────────────
// Constants
// ─────────────────────────────────────────────────────────────────────────────

var sharedCorpusContainer = 'shared-corpus'
var userUploadsContainer = 'user-uploads'
var deadLetterContainer = 'eventgrid-deadletter'
var ingestionQueue = 'ingestion-events'

// Built-in role definition IDs (subscription-scope)
var roleQueueDataMessageSender = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  'c6a89b2d-59bc-44d0-9896-0f6e12d7b80a'
)
var roleBlobDataContributor = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
)
var roleBlobDataReader = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'
)
var roleQueueDataReader = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '19e7f393-937e-4f77-808e-94535e297925'
)

// ─────────────────────────────────────────────────────────────────────────────
// Storage Account (AVM)
// Reference: https://github.com/Azure/bicep-registry-modules/tree/main/avm/res/storage/storage-account
// Pinned to 0.27.1.
// ─────────────────────────────────────────────────────────────────────────────

module storage 'br/public:avm/res/storage/storage-account:0.27.1' = {
  name: 'st-${uniqueString(name)}'
  params: {
    name: name
    location: location
    tags: tags

    skuName: 'Standard_LRS'
    kind: 'StorageV2'
    accessTier: 'Hot'

    // --- Zero-trust posture (Constitution Principle I) ---
    publicNetworkAccess: 'Disabled'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Deny'
      ipRules: []
      virtualNetworkRules: []
    }

    // --- Blob services: 3 private containers + soft-delete (7d) ---
    blobServices: {
      deleteRetentionPolicyEnabled: true
      deleteRetentionPolicyDays: 7
      containerDeleteRetentionPolicyEnabled: true
      containerDeleteRetentionPolicyDays: 7
      diagnosticSettings: [
        {
          name: 'diag-blob-to-law'
          workspaceResourceId: lawId
        }
      ]
      containers: [
        {
          name: sharedCorpusContainer
          publicAccess: 'None'
        }
        {
          name: userUploadsContainer
          publicAccess: 'None'
        }
        {
          name: deadLetterContainer
          publicAccess: 'None'
        }
      ]
    }

    // --- Queue service: ingestion-events queue (Event Grid subscription target) ---
    queueServices: {
      diagnosticSettings: [
        {
          name: 'diag-queue-to-law'
          workspaceResourceId: lawId
        }
      ]
      queues: [
        {
          name: ingestionQueue
          metadata: {}
        }
      ]
    }

    // --- Lifecycle policy: delete blobs under user-uploads/ older than 30 days
    //     (FR-005 / SC-012). Does NOT touch shared-corpus.
    managementPolicyRules: [
      {
        name: 'expire-user-uploads-30d'
        enabled: true
        type: 'Lifecycle'
        definition: {
          actions: {
            baseBlob: {
              delete: {
                daysAfterModificationGreaterThan: 30
              }
            }
          }
          filters: {
            blobTypes: [
              'blockBlob'
            ]
            prefixMatch: [
              '${userUploadsContainer}/'
            ]
          }
        }
      }
    ]

    // --- Two private endpoints into snet-pe (blob + queue) ---
    privateEndpoints: [
      {
        name: 'pe-${name}-blob'
        service: 'blob'
        subnetResourceId: peSubnetId
        privateDnsZoneGroup: {
          privateDnsZoneGroupConfigs: [
            {
              privateDnsZoneResourceId: pdnsBlobId
            }
          ]
        }
        tags: tags
      }
      {
        name: 'pe-${name}-queue'
        service: 'queue'
        subnetResourceId: peSubnetId
        privateDnsZoneGroup: {
          privateDnsZoneGroupConfigs: [
            {
              privateDnsZoneResourceId: pdnsQueueId
            }
          ]
        }
        tags: tags
      }
    ]

    // --- Account-level diagnostics (metrics only — log categories live on the
    //     blob/queue sub-services above) ---
    diagnosticSettings: [
      {
        name: 'diag-to-law'
        workspaceResourceId: lawId
        metricCategories: [
          {
            category: 'AllMetrics'
          }
        ]
      }
    ]
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Existing-resource handles (for the Event Grid system topic, RBAC scoping,
// and dead-letter wiring). These reference the resources created by the AVM
// module above, so they implicitly depend on it.
// ─────────────────────────────────────────────────────────────────────────────

resource sa 'Microsoft.Storage/storageAccounts@2024-01-01' existing = {
  name: name
  dependsOn: [
    storage
  ]
}

resource saQueueService 'Microsoft.Storage/storageAccounts/queueServices@2024-01-01' existing = {
  parent: sa
  name: 'default'
}

resource ingestionQueueRes 'Microsoft.Storage/storageAccounts/queueServices/queues@2024-01-01' existing = {
  parent: saQueueService
  name: ingestionQueue
}

// ─────────────────────────────────────────────────────────────────────────────
// Event Grid system topic on the storage account (hand-rolled — no AVM).
// Reference: ripley/phase-2-plan.md §"AVM coverage" row "Event Grid System Topic".
// ─────────────────────────────────────────────────────────────────────────────

resource systemTopic 'Microsoft.EventGrid/systemTopics@2023-12-15-preview' = {
  name: '${name}-evgt'
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    source: sa.id
    topicType: 'Microsoft.Storage.StorageAccounts'
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// RBAC for the system topic's MI (intra-module — see header comment).
//   - Storage Queue Data Message Sender → deliver events to ingestion-events
//   - Storage Blob Data Contributor     → write dead-lettered events to
//                                          eventgrid-deadletter container
// Both scoped to the storage account (queue / container scopes are not
// supported targets for principal-based assignments emitted from Bicep at
// resource-group scope without extra parent indirection; account scope is
// the documented pattern for Event Grid → Storage MI delivery).
// ─────────────────────────────────────────────────────────────────────────────

resource raQueueSender 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: sa
  name: guid(sa.id, systemTopic.id, 'queue-sender')
  properties: {
    principalId: systemTopic.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: roleQueueDataMessageSender
  }
}

resource raDeadLetterWriter 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: sa
  name: guid(sa.id, systemTopic.id, 'dlq-writer')
  properties: {
    principalId: systemTopic.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: roleBlobDataContributor
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Event Grid subscription:
//   - Filter: subjectBeginsWith /blobServices/default/containers/shared-corpus/
//   - Event types: Microsoft.Storage.BlobCreated / BlobDeleted
//   - Destination: StorageQueue → ingestion-events (delivered with system MI)
//   - Schema: CloudEvents 1.0 (matches contracts/ingestion-event.schema.json)
//   - Dead-letter: same storage account, eventgrid-deadletter container
//   - Retry: 30 attempts, TTL 60 minutes (= PT1H)
// ─────────────────────────────────────────────────────────────────────────────

resource sharedCorpusSubscription 'Microsoft.EventGrid/systemTopics/eventSubscriptions@2023-12-15-preview' = {
  parent: systemTopic
  name: 'shared-corpus-to-queue'
  properties: {
    eventDeliverySchema: 'CloudEventSchemaV1_0'
    filter: {
      subjectBeginsWith: '/blobServices/default/containers/${sharedCorpusContainer}/'
      includedEventTypes: [
        'Microsoft.Storage.BlobCreated'
        'Microsoft.Storage.BlobDeleted'
      ]
      enableAdvancedFilteringOnArrays: true
    }
    deliveryWithResourceIdentity: {
      identity: {
        type: 'SystemAssigned'
      }
      destination: {
        endpointType: 'StorageQueue'
        properties: {
          resourceId: sa.id
          queueName: ingestionQueue
          queueMessageTimeToLiveInSeconds: 3600
        }
      }
    }
    deadLetterWithResourceIdentity: {
      identity: {
        type: 'SystemAssigned'
      }
      deadLetterDestination: {
        endpointType: 'StorageBlob'
        properties: {
          resourceId: sa.id
          blobContainerName: deadLetterContainer
        }
      }
    }
    retryPolicy: {
      maxDeliveryAttempts: 30
      eventTimeToLiveInMinutes: 60
    }
  }
  dependsOn: [
    raQueueSender
    raDeadLetterWriter
    ingestionQueueRes
  ]
}

// ─────────────────────────────────────────────────────────────────────────────
// RBAC for app UAMIs (T029 / PR-O) — fan-out to the per-app principal IDs
// supplied by the wiring layer. All assignments scoped to the storage account.
//   - Blob Data Contributor → ingest (write to shared-corpus / user-uploads)
//   - Blob Data Reader      → api    (read corpora when answering)
//   - Queue Data Reader     → ingest (KEDA scaler reads queue depth via MI)
// ─────────────────────────────────────────────────────────────────────────────

resource raAppBlobContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in blobContributorPrincipalIds: {
  scope: sa
  name: guid(sa.id, principalId, 'BlobDataContributor')
  properties: {
    principalId: principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: roleBlobDataContributor
  }
}]

resource raAppBlobReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in blobReaderPrincipalIds: {
  scope: sa
  name: guid(sa.id, principalId, 'BlobDataReader')
  properties: {
    principalId: principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: roleBlobDataReader
  }
}]

resource raAppQueueReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in queueReaderPrincipalIds: {
  scope: sa
  name: guid(sa.id, principalId, 'QueueDataReader')
  properties: {
    principalId: principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: roleQueueDataReader
  }
}]

// ─────────────────────────────────────────────────────────────────────────────
// Outputs — consumed by PR-O wiring layer
// ─────────────────────────────────────────────────────────────────────────────

@description('Resource ID of the storage account.')
output resourceId string = storage.outputs.resourceId

@description('Name of the storage account.')
output name string = storage.outputs.name

@description('Primary blob endpoint (https://<name>.blob.core.windows.net/).')
output primaryBlobEndpoint string = storage.outputs.primaryBlobEndpoint

@description('Name of the admin-curated KB blob container.')
output sharedCorpusContainerName string = sharedCorpusContainer

@description('Name of the per-user upload blob container (subject to 30-day lifecycle delete).')
output userUploadsContainerName string = userUploadsContainer

@description('Name of the storage queue that receives Event Grid blob events for shared-corpus.')
output ingestionQueueName string = ingestionQueue

@description('Resource ID of the Event Grid system topic on the storage account (PR-O may grant additional senders).')
output eventGridSystemTopicId string = systemTopic.id
