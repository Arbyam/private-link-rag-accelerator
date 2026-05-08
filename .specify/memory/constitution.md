<!--
SYNC IMPACT REPORT
==================
Version change: (template) → 1.0.0
Bump rationale: Initial ratification. Template placeholders replaced with concrete
principles and governance for the Azure End-to-End Private Link RAG Accelerator.
This is a MAJOR (1.0.0) baseline — no prior numbered version existed.

Modified principles:
  - [PRINCIPLE_1_NAME] → I. Security-First / Zero Trust (NON-NEGOTIABLE)
  - [PRINCIPLE_2_NAME] → II. Idempotent & Reproducible Infrastructure-as-Code
  - [PRINCIPLE_3_NAME] → III. Documentation Parity
  - [PRINCIPLE_4_NAME] → IV. Cost Discipline for Demos & POCs
  - [PRINCIPLE_5_NAME] → V. Well-Architected Framework Alignment

Added sections:
  - Solution Accelerator Constraints (audience, compliance posture, target verticals)
  - Development & Contribution Workflow

Removed sections: none.

Templates requiring updates:
  ✅ .specify/templates/plan-template.md — generic "Constitution Check" gate aligns
     with new principles; no edits required.
  ✅ .specify/templates/spec-template.md — no principle-specific references; OK.
  ✅ .specify/templates/tasks-template.md — no principle-specific references; OK.
  ✅ .github/prompts/speckit.*.prompt.md — generic command files; no edits required.
  ⚠ README.md — does not yet exist; create when the accelerator's public-facing
     overview is authored (tracked as follow-up, not a blocker for this amendment).

Follow-up TODOs: none. Ratification date set to today (2026-05-08).
-->

# Private Link RAG Accelerator Constitution

This constitution governs the **Azure End-to-End Private Link RAG Accelerator**, a
reusable solution accelerator deployed by Microsoft field teams (Solution Engineers)
into customer Azure environments for proof-of-concept and demo purposes. The target
audience is regulated **SLED** (State, Local, Education, Healthcare) enterprises that
require zero public-internet exposure for AI/RAG workloads. All design and delivery
decisions MUST align with the **Microsoft Azure Well-Architected Framework (WAF)**.

## Core Principles

### I. Security-First / Zero Trust (NON-NEGOTIABLE)

No customer data plane traffic traverses the public internet. The accelerator MUST
enforce the following defaults, with no opt-out path in templates or scripts:

- All PaaS dependencies (Storage, Key Vault, Azure OpenAI / AI Foundry, AI Search,
  Cosmos DB, SQL, Container Apps / App Service, Container Registry, Monitor) are
  reached exclusively via **Private Endpoints**; their `publicNetworkAccess` MUST
  be set to `Disabled` (or `SecuredByPerimeter` where applicable).
- **Managed Identity** (system- or user-assigned) is the ONLY supported
  authentication mechanism between Azure resources. Connection strings, account
  keys, and embedded secrets are PROHIBITED in IaC, scripts, and application code.
- **Least-privilege RBAC** — role assignments MUST use the most-restrictive
  built-in role that satisfies the workload's documented needs; custom roles
  require written justification in the spec.
- **Private DNS Zones** are deployed and linked for every Private Endpoint;
  resolution MUST work end-to-end without public DNS leakage.
- All inbound administrative access is via **Azure Bastion**, **Entra ID**
  Privileged Identity Management, or equivalent; public RDP/SSH and public
  jumpboxes are PROHIBITED.

Rationale: SLED customers operate under HIPAA, FERPA, CJIS, IRS Pub. 1075, and
similar regimes. A single public endpoint or shared key invalidates the demo's
credibility and may breach customer policy on first deployment.

### II. Idempotent & Reproducible Infrastructure-as-Code

The accelerator is defined entirely in **Bicep**. Every deployable resource MUST
be expressed as code; manual portal configuration is PROHIBITED in the supported
deployment path.

- Bicep is the sanctioned IaC tool for this repository. Other tools (Terraform,
  ARM JSON, Pulumi) MUST NOT be added without a constitution amendment.
- Deployments MUST be **idempotent**: re-running the same template against the
  same parameters produces no drift and no errors.
- Every change MUST be validated with `az deployment ... what-if` (or the Bicep
  equivalent) before apply; deployment scripts MUST surface what-if output.
- A clean **teardown path** (script or `az deployment group delete --mode Complete`
  workflow) MUST be provided and tested for every deployable module.
- Resource names MUST be parameterized and follow a documented naming convention;
  hard-coded names are PROHIBITED outside example parameter files.

Rationale: Field teams deploy this dozens of times per quarter into customer
subscriptions where they have limited tenure. Drift, half-deployed state, or
orphaned resources damage trust and inflate customer costs.

### III. Documentation Parity

Documentation is a first-class deliverable on equal footing with code.

- Every Bicep module MUST ship with a README explaining its purpose, the
  resources it creates, and the security/networking rationale for each choice.
- Every architectural decision (SKU, region pairing, replication mode, identity
  model) MUST be captured in an Architecture Decision Record (ADR) or an
  equivalent decisions section before the related code is merged.
- Every customer-facing feature MUST include a learning-oriented walkthrough
  (the existing `azure-private-link-learning-summary.md` is the canonical
  reference for tone and depth).
- A high-level architecture diagram (Mermaid or PNG) MUST exist and MUST be
  updated in the same change that alters topology.

Rationale: The accelerator's secondary purpose is enablement. SEs hand the repo
to customer architects, who must be able to reason about every choice without
asking the original author.

### IV. Cost Discipline for Demos & POCs

The default deployment is optimized for **demo and POC** cost, not production
scale. Cost discipline is enforced at the IaC layer.

- Default SKUs MUST be the cheapest tier that demonstrates the capability
  (e.g., Standard_LRS storage, Basic/Free App Service plans where Private Link
  permits, Cosmos DB serverless, AI Search Basic, Azure OpenAI S0). Production
  SKUs MUST be opt-in via parameters with documented cost impact.
- Every deployable scenario MUST publish an **estimated monthly cost** in its
  README, broken down by resource family, with the date and region of the estimate.
- A **scheduled or one-shot teardown** mechanism MUST be available; long-running
  demo environments MUST emit cost alerts via Azure Monitor budget rules.
- Resources that incur cost while idle (provisioned-throughput Cosmos, premium
  AI Search replicas, dedicated SQL) MUST NOT be defaults.

Rationale: Customer subscriptions are not unlimited sandboxes. A POC that costs
$3k/month before the customer says "yes" kills the deal.

### V. Well-Architected Framework Alignment

Every spec, plan, and module MUST be evaluated against the five WAF pillars:
**Security**, **Reliability**, **Cost Optimization**, **Operational Excellence**,
and **Performance Efficiency**.

- Spec and plan documents MUST include an explicit WAF section that records
  trade-offs taken and the pillar(s) each trade-off favors.
- Where a principle in this constitution conflicts with a WAF recommendation
  (e.g., cost discipline vs. multi-region reliability), the spec MUST document
  the deviation, the rationale, and the upgrade path for production customers.
- Reliability features that materially affect topology (zone redundancy,
  paired-region failover, geo-replicated Private DNS) are opt-in parameters,
  not removed capabilities — the accelerator MUST show customers how to enable
  them.

Rationale: WAF is the customer-facing yardstick. SEs and customer architects
both expect the accelerator to "show its work" against the framework.

## Solution Accelerator Constraints

The following constraints scope the accelerator and bound what amendments may
loosen without major-version impact:

- **Audience**: Microsoft field Solution Engineers and the customer architects
  they collaborate with. Not aimed at end users.
- **Deployment surface**: A single Azure subscription per deployment instance.
  Multi-subscription / hub-and-spoke variants are explicit extensions, not the
  default path.
- **Compliance posture**: Designed to be deployable into environments aligned
  with HIPAA, FERPA, CJIS, IRS Pub. 1075, and FedRAMP Moderate. The accelerator
  itself is NOT certified; it is a starting point that does not introduce
  obvious blockers to those frameworks.
- **Target verticals**: State & Local Government, Education, Healthcare.
  Vertical-specific guidance (e.g., HIPAA BAA notes) lives in module READMEs.
- **Region defaults**: A US public-cloud region pair is the default; Sovereign
  cloud (Gov, China) variants are explicit, parameterized opt-ins.

## Development & Contribution Workflow

- All work follows the Spec-Driven Development cycle defined in this repository:
  `/speckit.constitution` → `/speckit.specify` → (`/speckit.clarify`) →
  `/speckit.plan` → `/speckit.tasks` → (`/speckit.analyze`) → `/speckit.implement`.
- Pull requests MUST link the spec, plan, and tasks artifacts they implement.
- The plan template's **Constitution Check** gate MUST pass before tasks are
  generated; any violation MUST be recorded with explicit justification in the
  plan's Complexity Tracking section.
- Before merge, every PR MUST verify: (a) Bicep `what-if` is clean,
  (b) no public endpoints introduced, (c) no secrets or keys in code,
  (d) docs and diagrams updated, (e) cost impact noted if SKUs changed.
- Breaking changes to module interfaces (parameter renames, output removals)
  require a MINOR or MAJOR constitution-version-aligned bump in the affected
  module's own version and a migration note.

## Governance

This constitution supersedes ad-hoc conventions, individual preferences, and
historical patterns elsewhere in this repository. In any conflict, the
constitution wins.

- **Amendment procedure**: Open a PR that updates `.specify/memory/constitution.md`,
  bumps the version per the policy below, updates the Sync Impact Report, and
  propagates required changes to dependent templates and docs. Amendments
  require approval from at least one maintainer and a successful run of
  `/speckit.analyze` against any in-flight feature.
- **Versioning policy** (semantic):
  - **MAJOR**: Backward-incompatible governance change — a principle removed,
    redefined, or downgraded from NON-NEGOTIABLE.
  - **MINOR**: New principle or section added, or material expansion of an
    existing principle's scope.
  - **PATCH**: Clarifications, wording fixes, non-semantic refinements.
- **Compliance review**: Every PR description MUST include a "Constitution
  compliance" line stating which principles the change touches and confirming
  no violations (or referencing the Complexity Tracking justification).
- **Runtime guidance**: Agent-specific runtime guidance lives in `AGENTS.md`
  and the `.github/prompts/` slash-command files. Those files MUST defer to
  this constitution when guidance conflicts.

**Version**: 1.0.0 | **Ratified**: 2026-05-08 | **Last Amended**: 2026-05-08
