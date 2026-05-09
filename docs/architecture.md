# Architecture

This document describes the as-deployed architecture of the Private RAG
Accelerator at three levels of zoom:

1. **System context** — the canonical high-level diagram from
   [`quickstart.md` §9](../specs/001-private-rag-accelerator/quickstart.md).
2. **Request flow** — what happens when an authenticated user sends a chat
   turn.
3. **Ingest flow** — what happens when a blob is dropped into the
   `shared-corpus` container.

For decisions and trade-offs that produced this shape, see
[`docs/decisions/`](decisions/). For the resulting cost picture, see
[`docs/cost.md`](cost.md).

---

## 1. System context

Source: [`specs/001-private-rag-accelerator/quickstart.md` §9](../specs/001-private-rag-accelerator/quickstart.md).

```mermaid
flowchart LR
    subgraph Client["Authorized client (Bastion/VPN/ExpressRoute)"]
        U[End user / Admin]
    end

    subgraph VNet["Customer VNet (no public ingress)"]
        subgraph ACAEnv["Container Apps Environment (internal=true)"]
            WEB[Next.js 15 web app]
            API[FastAPI orchestrator]
            JOB[(Ingest Job)]
        end

        subgraph PE["Private Endpoints"]
            PE1[(Storage)]
            PE2[(Cosmos DB)]
            PE3[(AI Search)]
            PE4[(Azure OpenAI)]
            PE5[(Doc Intelligence)]
            PE6[(ACR)]
            PE7[(Key Vault)]
            PE8[(AMPLS / Monitor)]
        end
    end

    subgraph PaaS["Azure PaaS (publicNetworkAccess = Disabled)"]
        STORAGE[Blob Storage<br/>shared-corpus + user-uploads]
        COSMOS[Cosmos DB NoSQL<br/>conversations + documents + ingestion-runs]
        SEARCH[AI Search Basic<br/>kb-index, hybrid + semantic + integrated vec]
        AOAI[Azure OpenAI<br/>gpt-5 + text-embedding-3-large]
        DOCINT[Document Intelligence<br/>prebuilt-layout]
        ACR[Container Registry Premium]
        KV[Key Vault]
        MON[Monitor + Log Analytics + App Insights]
    end

    EVT[Event Grid → Storage Queue]

    U -->|OIDC + Bearer| WEB
    WEB -->|REST + SSE| API

    API -->|MSI| AOAI
    API -->|MSI, scope filter| SEARCH
    API -->|MSI| COSMOS
    API -->|MSI| STORAGE
    API -->|MSI| DOCINT

    STORAGE --> EVT
    EVT --> JOB
    JOB -->|MSI| DOCINT
    JOB -->|MSI| SEARCH
    JOB -->|MSI| COSMOS
    JOB -->|MSI| STORAGE

    SEARCH -.embedding skill.-> AOAI

    API --> PE3
    API --> PE2
    API --> PE1
    API --> PE4
    API --> PE5
    JOB --> PE1
    JOB --> PE2
    JOB --> PE3
    JOB --> PE5
    WEB --> PE6
    API --> PE6
    JOB --> PE6

    PE3 --- SEARCH
    PE4 --- AOAI
    PE2 --- COSMOS
    PE1 --- STORAGE
    PE5 --- DOCINT
    PE6 --- ACR
    PE7 --- KV
    PE8 --- MON
```

> Note: AI Search runs at **Basic** in the default deployment — the lowest
> tier supporting Private Endpoint. The diagram in `quickstart.md` §9
> labels it "S1" against the spec baseline; the as-deployed figure is
> Basic per the Phase 2a v3 cost-validated plan
> ([`.squad/decisions.md`](../.squad/decisions.md), "T024 SKU deviation").

---

## 2. Request flow (chat turn)

What a single user chat turn looks like, end to end. APIM sits between
the client and the ACA web app, providing an internal-VNet AI Gateway
(token-quota, JWT pre-validation, request shaping) before the request
hits Container Apps.

```mermaid
flowchart TD
    U[User<br/>via Bastion / VPN / ExpressRoute]
    APIM[APIM Developer<br/>internal VNet]
    WEB[ACA: web<br/>Next.js 15]
    API[ACA: api<br/>FastAPI]
    SEARCH[(AI Search<br/>kb-index)]
    COSMOS[(Cosmos<br/>conversations)]
    AOAI[(Azure OpenAI<br/>gpt-5)]
    STORAGE[(Blob<br/>citation source)]

    U -->|1. HTTPS + Entra Bearer token| APIM
    APIM -->|2. JWT validated| WEB
    WEB -->|3. /chat<br/>SSE upstream| API
    API -->|4. validate JWT,<br/>extract oid| API
    API -->|5. retrieve<br/>filter: scope eq 'shared'<br/>or scope eq user:&lt;oid&gt;| SEARCH
    SEARCH -->|6. top-k passages| API
    API -->|7. read history<br/>partition: /userId| COSMOS
    API -->|8. chat completion<br/>streaming| AOAI
    AOAI -->|9. tokens stream| API
    API -->|10. SSE deltas + citations| WEB
    WEB -->|11. SSE to user| U
    API -->|12. append turn,<br/>touch TTL| COSMOS
    U -.->|13. open citation| WEB
    WEB -.->|/citations/...| API
    API -.->|signed read via MI| STORAGE
```

Steps 5 and 12 carry the SC-011 isolation guarantee: the `scope` filter
in the search query and the `/userId` partition on the Cosmos write are
both derived from the **server-validated** Entra `oid` claim — never from
client input (ADR-0005, [data-model §5](../specs/001-private-rag-accelerator/data-model.md)).

All hops marked with a Private Endpoint icon in §1 traverse private
networking; nothing in this flow leaves the customer VNet.

---

## 3. Ingest flow (shared-corpus blob)

Triggered when an admin (or `azd up` post-provision hook) drops a
document into the `shared-corpus` blob container.

```mermaid
flowchart TD
    BLOB[Blob upload<br/>shared-corpus/...]
    EVT[Event Grid<br/>system topic]
    QUEUE[Storage Queue<br/>ingestion-events]
    JOB[ACA Job: ingest<br/>KEDA queue scaler]
    DOCINT[(Document Intelligence<br/>prebuilt-layout)]
    SKILL[AI Search skillset<br/>SplitSkill + AzureOpenAIEmbedding]
    INDEX[(kb-index<br/>scope=shared)]
    COSMOS_DOCS[(Cosmos: documents<br/>partition: /scope)]
    COSMOS_RUNS[(Cosmos: ingestion-runs)]
    AOAI[(AOAI<br/>text-embedding-3-large)]

    BLOB -->|1. BlobCreated| EVT
    EVT -->|2. enqueue| QUEUE
    QUEUE -->|3. KEDA scales 0 to N| JOB
    JOB -->|4. mark run started| COSMOS_RUNS
    JOB -->|5. crack layout via MI| DOCINT
    DOCINT -->|6. markdown + tables| JOB
    JOB -->|7. push doc to skillset| SKILL
    SKILL -->|8. split + embed via shared private link| AOAI
    SKILL -->|9. write passages<br/>scope=shared| INDEX
    JOB -->|10. write document metadata| COSMOS_DOCS
    JOB -->|11. mark run complete| COSMOS_RUNS
```

Per-user upload flow is the same shape with two differences:

- The blob lands at `user-uploads/{userOid}/{conversationId}/...` instead
  of `shared-corpus/`.
- `scope` on the resulting passages is `user:<oid>` (not `shared`), and
  the `apps/api` orchestrator calls `embeddings.create()` directly rather
  than going through the Search skillset (ADR-0004).

The job's all-or-nothing run record in `ingestion-runs` is the surface
that satisfies FR-013 (admin-visible ingestion status).

---

## 4. Where to read more

- Compute / job topology — [ADR-0001](decisions/0001-aca-over-app-service.md).
- State store — [ADR-0002](decisions/0002-cosmos-nosql-over-postgres.md), [data-model §§2–4](../specs/001-private-rag-accelerator/data-model.md).
- Chat model — [ADR-0003](decisions/0003-gpt5-over-gpt4o.md).
- Embedding pipeline — [ADR-0004](decisions/0004-integrated-vectorization.md), [data-model §5](../specs/001-private-rag-accelerator/data-model.md).
- Cross-user isolation — [ADR-0005](decisions/0005-single-search-index-with-scope-filter.md).
- Admin access — [ADR-0006](decisions/0006-bastion-with-jumpbox-for-vnet-access.md), [quickstart §6](../specs/001-private-rag-accelerator/quickstart.md).
- IaC discipline — [ADR-0007](decisions/0007-avm-where-possible.md), [`infra/AVM-AUDIT.md`](../infra/AVM-AUDIT.md).
- Cost — [`docs/cost.md`](cost.md).
- Networking detail — [research.md D9](../specs/001-private-rag-accelerator/research.md).
