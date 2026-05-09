# ADR-0007: Use Azure Verified Modules wherever a usable one exists

- Status: Accepted
- Date: 2026-05-09
- Decider(s): Squad team (Lead, Dallas/Infra)

## Context

Every Azure resource in the accelerator can be provisioned in one of three
ways:

- **Hand-rolled Bicep** — `resource ... 'Microsoft.X/...' = { ... }` directly.
- **Azure Verified Modules (AVM)** — `module ... 'br/public:avm/res/...:vX.Y.Z' = { ... }`.
- **Third-party / Bicep registry** modules.

Constraints:

- Constitution Principle II — IaC is idempotent and reproducible.
- Principle I — no public network access; defaults must lean to
  `publicNetworkAccess=Disabled`, diagnostic settings emitted to LAW,
  customer-managed-key opt-in plumbed.
- Terraform is forbidden without a Constitution amendment (D10).
- Solution Engineers should not be responsible for tracking upstream API
  changes on every resource.

## Decision

**Prefer AVM `br/public:avm/res/...` modules everywhere a usable one
exists.** Hand-rolled Bicep is reserved for:

- Composition glue (subscription-scope `main.bicep`, role-assignment
  fan-out).
- Resources where AVM does not yet ship a usable module (or the available
  AVM version is broken — see "negative consequences" below).

Operational rules (codified in
[`.squad/decisions.md`](../../.squad/decisions.md)
Phase 2a wave-3 — "AVM version pinning + module-local SKU allowlists"):

1. **Pin AVM to a specific published version** — never `latest`, never a
   floating range. Recheck MCR tag list at module-implementation time, pick
   the newest stable, document the pin choice in the module's leading
   comment / README. The pin set lives in [`infra/AVM-AUDIT.md`](../../infra/AVM-AUDIT.md).
2. **Constrain SKU parameters with `@allowed([...])`** to the values that
   satisfy zero-trust + cost constitution at the module boundary
   (e.g., ACR `@allowed(['Premium'])`). Turns a runtime/compliance failure
   into a deploy-time error.

## Consequences

### Positive

- AVM modules ship best-practice defaults: Private Endpoint plumbing,
  diagnostic settings, MI-friendly RBAC, `publicNetworkAccess=Disabled`
  parameters — saves us from reinventing the wheel on every resource.
- Faster onboarding for new contributors — the module surface is
  documented upstream.
- Security baseline benefits from upstream fixes when we bump pins.
- Pinned versions + `@allowed` SKU lists make compliance auditable at
  deploy time, not runtime.

### Negative

- **Occasional breaking contract changes** between AVM minor versions.
  Documented case: **Cosmos AVM 0.17.0 dropped `sqlDatabases`** as a
  parameter; the accelerator is **held at 0.16.0** until the upstream
  rework lands ([`infra/AVM-AUDIT.md`](../../infra/AVM-AUDIT.md)).
- Less control over bleeding-edge resource features — if a brand-new
  property isn't surfaced in the AVM module yet, we either wait for an
  AVM release or fall back to hand-rolled Bicep (and document why).
- Slightly higher template-compile time and module-resolution overhead vs
  inline `resource` declarations (negligible in practice).

### Neutral

- The composition layer (`main.bicep`, role fan-out, output stitching)
  stays hand-rolled — AVM has no opinion on cross-module wiring, and
  named outputs (e.g., the network module's 13 named DNS-zone outputs,
  see [`.squad/decisions.md`](../../.squad/decisions.md) Phase 2a wave-3)
  are easier to reason about than module-emitted maps.

## Alternatives considered

- **Hand-rolled Bicep modules everywhere** — more code to maintain,
  slower to pick up upstream security fixes; rejected.
- **Terraform** — forbidden by the Constitution without amendment (D10).
- **Pulumi / CDKTF** — adds a programming-language layer the SE persona
  doesn't necessarily speak; rejected for v1.
- **Use AVM `latest`** — pin drift would silently break customer
  deployments; explicitly disallowed by the version-pinning rule above.

## References

- [`specs/001-private-rag-accelerator/research.md`](../../specs/001-private-rag-accelerator/research.md) — D10 (IaC).
- [`infra/AVM-AUDIT.md`](../../infra/AVM-AUDIT.md) — module pin table, Cosmos 0.16.0 hold.
- [`infra/README.md`](../../infra/README.md) — module catalog.
- [`.squad/decisions.md`](../../.squad/decisions.md) — "AVM version pinning + module-local SKU allowlists".
