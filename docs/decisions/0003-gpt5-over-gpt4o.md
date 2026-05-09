# ADR-0003: gpt-5 over gpt-4o for the chat deployment

- Status: Accepted
- Date: 2026-05-09
- Decider(s): Squad team (Lead, Kane/Backend)

## Context

The orchestrator (`apps/api`) needs a chat model behind a Private Endpoint
that supports:

- Long-context grounded RAG (system prompt + retrieved passages + multi-turn
  history).
- Tool / function calls for citation rendering and admin actions.
- SSE streaming for the chat UX (FR / latency budget).
- Availability across the regions our SLED customers deploy to (East US 2,
  South Central US, North Central US, West US 3).

The choice is between staying on `gpt-4o` (incumbent default in many
templates) and moving to `gpt-5`.

## Decision

Default chat deployment is **`gpt-5`** on Azure OpenAI, embedded behind a
Private Endpoint with `publicNetworkAccess=Disabled`. The model name is
parameterised (`chatModel`) — customers can swap to a regional fallback or
fine-tuned variant by changing the parameter without IaC structural
changes.

Embedding deployment is **`text-embedding-3-large`** (3072 dims) on the same
AOAI resource — covered separately because it's the obvious current-gen
embedder; not the subject of this ADR.

## Consequences

### Positive

- **`gpt-4o` is on the Azure deprecation track.** Building net-new on a
  deprecated model would force a forced migration during a customer pilot,
  which is exactly the failure mode an accelerator must avoid.
- gpt-5 is current generation, supports the multi-turn + tool-call patterns
  the orchestrator already uses, and is **widely available** in the
  East US 2 / South Central US / North Central US / West US 3 set (D2).
- Better grounding adherence and longer context window improve citation
  accuracy (SC-006: ≥85% correct citation rate on the benchmark set).
- Model name is parameterised — customers can override per environment.

### Negative

- **Higher per-token cost** than gpt-4o; demo workload absorbs this
  (idle/light-traffic is rounding error in `docs/cost.md` §2), but at
  sustained load the AOAI line will be the dominant variable cost.
- **P50 latency for short turns** can be slower than gpt-4o; Vercel AI SDK
  streaming masks this for the user but bench numbers are not strictly
  better on every turn shape.
- **PTU economics** — at high QPS, customers should buy Provisioned
  Throughput Units. The `enablePtu=true` parameter is opt-in (default
  pay-as-you-go S0).

### Neutral

- Same Private Endpoint, same managed-identity auth, same DNS zone
  (`privatelink.openai.azure.com`) regardless of which AOAI model is
  selected — no architecture change to switch.

## Alternatives considered

- **`gpt-4o`** — Deprecated path. Rejected.
- **`gpt-4.1` / `gpt-4-turbo`** — Older generation, no upside over gpt-5
  for this workload, similar or higher cost.
- **Self-hosted open-weights via AML / KAITO** — Significant ops burden
  (GPU pools, scaling, prompt-format quirks), breaks the
  "easy to set up" SC-001 principle. Reserved for a sovereign-cloud
  variant.
- **Anthropic / Google models via partner endpoints** — Out-of-tenant data
  flow; violates the "stay in customer tenant" assumption.

## References

- [`specs/001-private-rag-accelerator/spec.md`](../../specs/001-private-rag-accelerator/spec.md) — SC-006.
- [`specs/001-private-rag-accelerator/research.md`](../../specs/001-private-rag-accelerator/research.md) — D2 (Chat model).
- [`specs/001-private-rag-accelerator/quickstart.md`](../../specs/001-private-rag-accelerator/quickstart.md) §3 — `CHAT_MODEL` parameter.
- `infra/modules/openai/` — Bicep deployment.
