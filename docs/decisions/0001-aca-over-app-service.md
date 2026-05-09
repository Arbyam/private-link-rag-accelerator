# ADR-0001: Azure Container Apps over App Service

- Status: Accepted
- Date: 2026-05-09
- Decider(s): Squad team (Lead, Dallas/Infra, Kane/Backend, Lambert/Frontend)

## Context

The accelerator runs three workloads:

- a Next.js 15 web app (`apps/web`) with SSE streaming for chat,
- a FastAPI orchestrator (`apps/api`) with long-lived response streams,
- an event-triggered ingest worker (`apps/ingest`) that runs to completion
  per blob upload.

Constraints from the spec and constitution:

- **No public ingress** for any workload (FR-004, Principle I).
- **No shared keys** — managed identity everywhere (FR-003).
- **Idle cost ≤ ~$700/mo** (SC-009) — scale-to-zero strongly preferred for
  the demo loop.
- **≤15 min hands-on deploy** (SC-001) — minimal cluster ops.
- A first-class **batch / event-triggered job** primitive for ingest, not a
  long-lived consumer process.

## Decision

Use **Azure Container Apps** with a single Container Apps Environment
(`vnetConfiguration.internal=true`, dedicated infrastructure subnet
`snet-aca`):

- `web` and `api` as Container Apps (KEDA HTTP scaler, system-assigned MI).
- `ingest` as a Container Apps **Job** (event-triggered via Azure Storage
  Queue, scale-to-zero, per-execution timeout).

## Consequences

### Positive

- `internal=true` gives a private static ingress IP — directly satisfies
  Principle I without an extra App Gateway / Front Door tier.
- Container Apps Jobs are the natural shape for the ingest worker: per-event
  execution, exit-on-completion, no idle compute.
- KEDA scale-to-zero on `web`/`api` keeps the Consumption-plan line near $5/mo
  at idle (`docs/cost.md` §2).
- Single environment shares VNet, Log Analytics, and (future) Dapr — fewer
  resources to wire to private endpoints.
- Built-in revision-based rolling deploys; `azd deploy` slots straight in.

### Negative

- Smaller ecosystem and fewer "click-ops" affordances than App Service
  (deployment slots, hybrid connections, built-in auth) — we hand-roll auth
  in code (D8).
- Diagnostic surface is younger; some failure modes (cold start, ingress
  timeouts) require digging in Log Analytics rather than a portal blade.
- Private-link / customer-DNS story for ACA itself is newer than App
  Service's; teams new to ACA need to learn the `internal=true` + private
  DNS zone pattern.

### Neutral

- Container images live in our private ACR Premium (ADR-0007 / D6); ACA
  pulls via managed identity. Same model App Service would have used.

## Alternatives considered

- **App Service Premium V3 + Private Endpoint** — works, but no first-class
  Jobs primitive (we'd need a separate Functions/WebJob pipeline), and
  Premium V3 idle is materially more expensive than ACA Consumption for the
  three-service shape.
- **AKS** — adds cluster operations (upgrades, node pools, KEDA install)
  that contradict SC-001's "≤15 min hands-on" target. Reserved for a future
  enterprise variant if customers demand pod-level controls.
- **Azure Functions on Flex Consumption** — strong fit for ingest, but the
  FastAPI orchestrator benefits from long-lived SSE streaming connections
  that ACA handles more cleanly than Functions.

## References

- [`specs/001-private-rag-accelerator/spec.md`](../../specs/001-private-rag-accelerator/spec.md) — FR-003, FR-004, SC-001.
- [`specs/001-private-rag-accelerator/research.md`](../../specs/001-private-rag-accelerator/research.md) — D1 (Compute platform).
- [`specs/001-private-rag-accelerator/plan.md`](../../specs/001-private-rag-accelerator/plan.md).
