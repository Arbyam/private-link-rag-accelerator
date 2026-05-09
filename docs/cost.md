# Cost — Default Deployment

**Closes:** SC-009 (published steady-state cost figure), FR-028 (lowest-cost
default SKUs, production-grade as opt-in).
**Region of record:** East US 2.
**Pricing snapshot:** Azure public pricing verified 2026-05-08 (Phase 2a v3
cost validation). All figures rounded **up** conservatively. Figures will
drift over time — re-validate before quoting to a customer.
**Source-of-truth table:** [`.squad/agents/ripley/phase-2-plan.md` §0](../.squad/agents/ripley/phase-2-plan.md).
**SKU deviations from spec.md baseline:** see [`.squad/decisions.md`](../.squad/decisions.md)
(Bastion Standard → Developer; AI Search S1 → Basic; APIM Premium → Developer)
— all permanent, accepted, zero-trust preserved.

---

## 1. Headline numbers

| Mode | Steady-state idle | Notes |
|---|---:|---|
| **Default (as-shipped)** | **~$318/mo** | 36% under the SC-009 ≤ ~$700/mo target; all data-plane services have a Private Endpoint with `publicNetworkAccess=Disabled` (Principle I). |
| Production-grade (all opt-ins on) | ~$3,300/mo | APIM Premium + AI Search S1 + Bastion Standard + Cosmos provisioned; see §3. |

> SC-009 deviation rule: a >20% drift from the published figure triggers a
> constitution-required review of the SKU defaults. The published figure for
> the default deployment is **$318/mo**.

---

## 2. Default deployment — per-resource breakdown

| Resource | SKU | $/mo idle | Why this SKU |
|---|---|---:|---|
| VNet + NSGs + 13 Private DNS zones | — | $7 | VNet/NSG free; 13 zones × $0.50/mo. |
| Azure Bastion | **Developer** | $0 | Shared Microsoft pool, portal-only RDP/SSH. Free. (`docs/decisions/0006`) |
| Jumpbox VM | Standard_B2s (Linux) | $36 | In-VNet shell (`az`, `kubectl`, HTTP probes). Deallocate when idle = $0. |
| Container Registry | **Premium** | $50 | Only ACR tier supporting Private Endpoint (SC-004). |
| AI Search | **Basic** | $74 | Lowest tier supporting PE + semantic ranker. (deviation from S1 — see [`.squad/decisions.md`](../.squad/decisions.md) "T024 SKU deviation") |
| API Management | **Developer** (internal VNet) | $50 | VNet injection, no SLA — adequate for demo. Premium would be +$2,750/mo. |
| Container Apps (web + api + ingest job) | Consumption | $5 | Scale-to-zero; free grants cover light demo. |
| Cosmos DB (NoSQL) | **Serverless** | $3 | Pay-per-RU; suits spiky demo workload. |
| Azure OpenAI (gpt-5 + text-embedding-3-large) | Pay-per-token | $10 | Demo token volume is low. |
| Document Intelligence | **S0** | $3 | F0 does not support PE; S0 is the floor. |
| Storage Account | Standard LRS (blob + queue) | $3 | Two containers; small demo footprint. |
| Key Vault | Standard | $1 | RBAC-auth, no HSM. |
| Log Analytics Workspace | Pay-per-GB | $8 | 30-day retention free tier. |
| Application Insights | Workspace-based | $2 | Inherits LAW pricing. |
| AMPLS | — | $0 | Resource free; PE counted below. |
| Private Endpoints (×9) | — | $66 | 9 × $7.30/mo. |
| **Total idle** | | **$318/mo** | $382 headroom under the SC-009 ≤ ~$700/mo target. |

The 9 Private Endpoints cover: AOAI, AI Search, Cosmos, Blob, Queue, Key
Vault, ACR, Document Intelligence, AMPLS — see
[`.squad/agents/ripley/phase-2-plan.md` §0](../.squad/agents/ripley/phase-2-plan.md)
"Private Endpoint Inventory".

### Cost behaviour at traffic

The figures above are **idle**. Variable-cost lines (will scale with usage):

- **Azure OpenAI** — pay-per-token; the dominant variable cost under load.
- **Document Intelligence** — pay-per-page (≈$0.0015/page custom, ≈$0.01/page
  prebuilt-layout for the first 1M, less above). Bursts on bulk corpus
  ingest.
- **Cosmos DB serverless** — $0.25 per 1M RUs + storage. A demo session is
  pennies.
- **Container Apps** — Consumption: vCPU-second + memory-GiB-second; KEDA
  scale-to-zero keeps idle at the $5 platform floor.
- **Log Analytics / App Insights** — pay-per-GB ingested. Verbose tracing
  (e.g., per-request bodies) can spike this.

A **budget alert** is deployed by default at 80% / 100% of the
`budgetMonthly` parameter (default $1,000) so unexpected spikes page the SE
without manual setup (per D13).

---

## 3. Production-mode cost delta

These are **opt-in** parameters — defaults stay at §2. Toggle in
`azd env set` (see `quickstart.md` §3) or in `main.parameters.prod.json`.

| Toggle | Default | Production-mode | Δ vs default | Why opt in |
|---|---|---|---:|---|
| `apimSku` | Developer | **Premium stv2** (zone-redundant, multi-region capable) | **+$2,750/mo** | 99.95% SLA, autoscale, capacity units; mandatory for any tenanted prod gateway. |
| `aiSearchSku` | basic | **standard (S1)** | **+$176/mo** ($74 → $250) | High-availability replicas, larger index size, partition scale-out. |
| `deployBastion` / Bastion SKU | Developer (free) | **Standard** with always-on host | **+$140/mo** | Native client, shareable links, multi-session for SE/customer support. |
| Cosmos `cosmosCapacityMode` | Serverless | **Provisioned + autoscale** | variable (~$25–$200+/mo at low RU/s ceilings; grows with RU/s) | Predictable spend at sustained QPS; serverless is best for spiky demos. |
| `enableZoneRedundancy` | false | true (multi-AZ on AI Search, Cosmos, Storage) | +5–25% on those lines | Zonal HA inside the region. |
| `enableCustomerManagedKey` | false | true (CMK on Storage / Cosmos / KV / AOAI where supported) | +$1/mo per key + ops | Customer-managed encryption-at-rest. |
| `enablePtu` (AOAI Provisioned Throughput Units) | false | true | minimum ~$2k–$5k/mo per PTU pack | Latency- and rate-deterministic AOAI for prod tenants. |

**Net "all opt-ins on" production-grade target:** approximately **$3,300/mo**
(APIM Premium + Search S1 + Bastion Standard + Cosmos provisioned at modest
RU/s + CMK + zone redundancy; AOAI PTUs **excluded** — those are bought to
fit a specific load profile and dwarf everything else).

---

## 4. Cost levers (what to flip first)

If the customer wants to push lower:

1. **Stop the jumpbox when idle** — saves the full $36/mo VM line; restart
   from the portal in <2 min (`az vm start`).
2. **Set `deployBastion=false`** if they have existing Bastion / VPN /
   ExpressRoute — saves nothing under the Developer SKU but avoids future
   drift if they later upgrade.
3. **Trim DNS zones** (`customerProvidedDns=true`) if they own DNS — saves $7/mo
   and aligns with their hub/spoke landing zone (D9).
4. **Reduce LAW retention** below 30 days if telemetry is the largest line at
   load — only meaningful at sustained traffic.

If the customer wants to push higher (production):

1. APIM Premium first — that's the SLA gate.
2. AI Search S1 second — search availability is the user-visible failure
   mode under load.
3. Provisioned Cosmos third — only once RU/s consumption is measured and
   stable.

---

## 5. References

- [`specs/001-private-rag-accelerator/spec.md`](../specs/001-private-rag-accelerator/spec.md) — SC-009, FR-028.
- [`specs/001-private-rag-accelerator/research.md`](../specs/001-private-rag-accelerator/research.md) — D13 (cost guardrails), D12 (Bastion).
- [`.squad/agents/ripley/phase-2-plan.md`](../.squad/agents/ripley/phase-2-plan.md) §0 — canonical cost table.
- [`.squad/decisions.md`](../.squad/decisions.md) — accepted SKU deviations (Bastion Developer, AI Search Basic, APIM Developer).
- [`docs/decisions/0006-bastion-with-jumpbox-for-vnet-access.md`](decisions/0006-bastion-with-jumpbox-for-vnet-access.md).
- [`docs/decisions/0007-avm-where-possible.md`](decisions/0007-avm-where-possible.md).
