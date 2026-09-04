# Capital Cockpit product direction

## Product thesis

Clausula is not a portfolio tracker with an AI chat box attached. The primary user surface is a decision workspace over deterministic, provenance-aware financial state.

The canonical loop is:

```text
Capital State -> Policy Boundary -> Attention -> Evidence
      -> Plan / Recommendation -> Decision -> Execution -> Review
```

The UI should help a user answer, in order:

1. What is the capital state at an explicit effective and knowledge cutoff?
2. Is the state complete enough to reason about, and what data is stale or missing?
3. Which policy/risk boundaries are satisfied, close to limits, or violated?
4. What changed materially enough to deserve attention?
5. What evidence supports or contradicts the thesis behind current exposure?
6. Which feasible actions exist under the current constraints?
7. What was actually decided, and why were alternatives rejected?
8. What happened after execution, and was the process good independently of the outcome?

`as_of` and `known_as_of` are product concepts, not implementation details. A polished surface must not hide them when doing so would create hindsight ambiguity.

## What Clausula learns from mature open-source finance products

Clausula borrows interaction principles rather than page copies:

- **Wealthfolio**: local-first/private defaults, fast portfolio summary surfaces, explicit data-health feedback, privacy masking, and backend-owned performance semantics.
- **Ghostfolio**: mature portfolio information architecture and clear account/holding/allocation decomposition.
- **Maybe**: aggressive visual simplification; do not expose complexity merely because the model contains it.
- **OpenBB**: analytical surfaces should answer a concrete question and compose into a workspace instead of becoming an undifferentiated dashboard.

Ideas are adopted only when they improve an investment decision or reduce operational friction *and* preserve Clausula's deterministic, point-in-time, provenance-aware truth model.

## Visual language

The default desktop view should be calm, dense and legible rather than terminal-like or gamified.

- Capital is prominent, but not the only hero metric.
- Policy violations and incomplete valuation outrank decorative performance charts.
- Monetary privacy masking is one click away.
- Missing/stale data is visible rather than silently forward-filled.
- Good/attention/violation colors carry semantic meaning and are used sparingly.
- Charts require explicit backend semantics; a visually attractive chart with ambiguous return or knowledge-time semantics does not belong in the product.

## Implemented Capital Cockpit read model

The current loopback workspace/read model includes:

- canonical or partial portfolio value and valuation completeness;
- allocation/concentration and data gaps;
- cash value, reserve requirement, deployable cash and reserve shortfall;
- policy status plus signed headroom to deterministic boundaries;
- persisted plans and typed execution-contract status;
- material Attention;
- recommendation inbox and recommendation lifecycle state;
- evidence freshness/contradiction pressure;
- decision and review queues;
- recommendation -> decision lineage;
- public-equity case monitoring;
- explicit `as_of` / `known_as_of` controls;
- local screen-privacy masking.

The workspace itself is anonymous read-only. Protected capability invocation is owned by the local daemon and requires a daemon-issued principal; UI presentation does not become an authorization surface merely because the underlying read model contains actions or recommendations.

## Performance state

The original replay bottlenecks are no longer the architectural blocker they were when this document was first written. Transaction metadata, instrument/price/FX access and multi-date performance reads now use batched/bounded query paths, and CI traces SQL to reject N+1-style query growth. `scripts/benchmark_reads.py` remains the machine-specific evidence harness.

A long performance chart should therefore be added only when it answers a product question and its return semantics are explicit. In particular, portfolio wealth returns must not be presented as directly comparable with a benchmark unless the benchmark's `price_return`/`total_return` semantics and portfolio-income completeness support that comparison.

## Implemented differentiators

### Capital runway and deployable cash

The backend derives policy-required reserve, deployable cash and reserve gap from complete portfolio valuation plus active minimum-cash rules. If valuation is incomplete, the envelope fails closed rather than inventing deployable capital.

### Risk-budget drift

Policy results expose signed headroom to deterministic lower/upper boundaries, allowing the workspace to surface distance-to-limit rather than only already-triggered violations.

### Evidence pressure

The decision workspace summarizes evidence state separately from canonical market/ledger truth and can surface supporting/contradicting pressure at explicit temporal cutoffs.

### Decision lineage

Recommendation-to-decision relationships are explicit and the broader workspace keeps recommendation, decision, execution and review states separate. A recommendation is never equivalent to an executed decision.

### Execution constraints

Execution contracts are typed application inputs rather than free-form notes, and plan evaluation can report configured/unconfigured/constraint state without placing brokerage orders.

## Remaining product/release work

The next step is not to add more dashboard chrome. The remaining high-value work is release validation around the existing product surface:

- real provider and benchmark semantics (#34);
- richer historical identifiers/corporate actions/accounting (#21);
- concrete multi-process/MCP/plugin host runtime isolation (#23);
- protected `main` and required CI (#6);
- visual refinement only after representative local data proves which panels deserve prominence.

The first stable release should follow those acceptance gates rather than using feature count as the release criterion.
