# ADR-0006: Azure Bastion (Developer) **with** in-VNet Jumpbox for SE access

- Status: Accepted
- Date: 2026-05-09
- Decider(s): Squad team (Lead, Dallas/Infra)

> **Title note:** the originating task (T058) listed this as
> "0006-bastion-over-jumpbox". The accelerator actually deploys **both**
> Bastion *and* a jumpbox VM (they cover complementary needs); this ADR is
> filed under the more accurate name.

## Context

The whole environment is private — every workload sits behind
`internal=true` ACA / VNet injection / Private Endpoints with
`publicNetworkAccess=Disabled`. The Solution Engineer (and, later, the
customer's admin) still need:

- **Browser access** to the chat UI on its `internal=true` ingress URL.
- **Shell context** in the VNet: `az` CLI, `kubectl`-style probes, `curl`
  against private endpoints, ad-hoc DNS resolution checks (quickstart §8).
- **No public ingress** anywhere — RDP/SSH ports MUST NOT be exposed.

Constraints:

- Idle cost ≤ ~$700/mo (SC-009); Bastion Standard alone is +$140/mo.
- $500/mo hard cost ceiling from the project sponsor
  ([`.squad/decisions.md`](../../.squad/decisions.md)).
- ≤30 min security-architect review (SC-010).

## Decision

Deploy **both**:

- **Azure Bastion — Developer SKU** (free, shared Microsoft pool,
  portal-mediated RDP/SSH only, single concurrent session). Resource is
  not actually deployed in the customer subscription — Microsoft's pool
  brokers the session.
- **Linux jumpbox VM — Standard_B2s** in `snet-pe` (managed-identity
  workload, no public IP, no inbound NSG rule from the internet). The SE
  reaches it via Bastion; once on the jumpbox they have full in-VNet shell
  context.

Parameters:

- `deployBastion=true` by default; customers with existing Bastion / VPN /
  ExpressRoute set `false` and reuse their hub.
- `deployJumpbox=true` by default; can be turned off for cost when admin
  shell context is already available via the customer's existing tooling.

## Consequences

### Positive

- **Zero public ingress.** Bastion brokers RDP/SSH at the Microsoft edge;
  the jumpbox itself has no public IP and no inbound NSG allow rule from
  Internet.
- Bastion **Developer is free**, saving $140/mo vs Standard
  ([`.squad/decisions.md`](../../.squad/decisions.md) — "T028 SKU deviation:
  Bastion Standard → Developer — ACCEPTED PERMANENT").
- The jumpbox gives the SE full shell context (`az`, in-VNet `curl`,
  private DNS lookups) — enables the SC-010 30-minute security verification
  walkthrough without leaving the VNet.
- Stopping the jumpbox when idle drops its line item to $0 — see
  [`docs/cost.md`](../cost.md) §4 cost levers.
- Jumpbox has a system-assigned managed identity scoped to the bare
  minimum — no sprawling secrets on the box.

### Negative

- **+$36/mo** for the B2s VM at idle (allocated). Mitigation: deallocate
  when not in use.
- Bastion Developer has **a single concurrent session, no native client,
  no shareable links** — the production-grade `Bastion Standard` upgrade
  (+$140/mo) restores those.
- **Two access paths** (Bastion → portal RDP, Bastion → SSH-to-jumpbox)
  is mildly more complex to document than a single one.

### Neutral

- The jumpbox lives in `snet-pe` rather than a dedicated `snet-jumpbox` to
  conserve subnet IP space (D9 — only four subnets total). It does NOT
  use a Private Endpoint of its own.

## Alternatives considered

- **Jumpbox alone (no Bastion)** — would require either a public IP on the
  VM (violates Principle I) or a customer-supplied VPN/ExpressRoute hop.
  Bastion solves the entry-point problem cleanly.
- **Bastion Standard alone (no jumpbox)** — gives portal RDP/SSH but no
  shell context inside the VNet. SC-010 walkthroughs need `az` and
  in-network `curl` — a portal-only Bastion session is insufficient.
- **Dev Box / Azure Virtual Desktop** — premium cost for what is
  fundamentally an admin shell.
- **Cloud Shell** — runs from the Azure-managed network, not the
  customer VNet — cannot resolve private endpoints or hit `internal=true`
  ingress.

## References

- [`specs/001-private-rag-accelerator/research.md`](../../specs/001-private-rag-accelerator/research.md) — D9 (network), D12 (Bastion).
- [`specs/001-private-rag-accelerator/quickstart.md`](../../specs/001-private-rag-accelerator/quickstart.md) §6, §8.
- [`specs/001-private-rag-accelerator/spec.md`](../../specs/001-private-rag-accelerator/spec.md) — SC-001, SC-010.
- [`.squad/decisions.md`](../../.squad/decisions.md) — "T028 SKU deviation: Bastion Standard → Developer".
- [`docs/cost.md`](../cost.md) §2, §4.
