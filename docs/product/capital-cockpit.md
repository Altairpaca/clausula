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

Clausula should borrow interaction principles rather than page copies:

- **Wealthfolio**: local-first/private defaults, fast portfolio summary surfaces, explicit data-health feedback, privacy masking, and backend-owned performance semantics.
- **Ghostfolio**: mature portfolio information architecture and clear account/holding/allocation decomposition.
- **Maybe**: aggressive visual simplification; do not expose complexity merely because the model contains it.
- **OpenBB**: analytical surfaces should answer a concrete question and compose into a workspace instead of becoming an undifferentiated dashboard.

Ideas are adopted only when they improve an investment decision or reduce operational friction *and* preserve Clausula's deterministic, point-in-time, provenance-aware truth model.

## Visual language

The default desktop view should be calm, dense, and legible rather than terminal-like or gamified.

- Capital is prominent, but not the only hero metric.
- Policy violations and incomplete valuation outrank decorative performance charts.
- Monetary privacy masking is one click away.
- Missing/stale data is visible rather than silently forward-filled.
- Good/attention/violation colors carry semantic meaning and are used sparingly.
- Charts are introduced only when their semantics are explicit and the backend path is fast enough to support them without hiding expensive recomputation.

## Capital Cockpit v0

The first read-only slice includes:

- canonical / partial portfolio value;
- cash weight and value;
- largest-position concentration;
- oldest accepted position-price date;
- allocation view;
- valuation gaps;
- policy status and non-compliant/unavailable rules;
- persisted plans;
- decision memory timeline;
- explicit `as_of` / `known_as_of` controls;
- local screen-privacy masking.

The v0 intentionally does **not** request a long performance history. The current performance implementation replays valuation and cash-flow history repeatedly per requested date. A chart should be added after the replay/read-model path is made appropriately incremental or batched.

## Next differentiating surfaces

### Capital runway and deployable cash

Separate cash required by reserve policy from cash that is actually deployable. A single cash percentage is insufficient for personal capital allocation.

### Risk-budget drift

Show distance to concentration/allocation/currency boundaries, not only whether the current state is already in violation. The useful question is often "how much room remains?"

### Evidence pressure

For every thesis/exposure, summarize evidence freshness, new supporting evidence, new contradictions, and unreviewed thesis revisions. This is advisory context, never canonical market truth.

### Decision lineage

Render recommendation -> decision -> transaction -> review as one traceable chain. The system should make it difficult to confuse a recommendation with an executed decision or to judge a decision only by its realized outcome.

### Execution constraints

Settlement, market-session, turnover, liquidity, fee/tax and jurisdictional constraints should become typed planning inputs where supported. They should not live only in prose.

## Performance principle

A responsive workspace requires read models whose query growth is bounded by batches rather than entity counts. The known first targets are transaction/leg replay, position/price lookup, FX lookup, and repeated per-date performance reconstruction. Correctness and point-in-time semantics are frozen constraints; optimization must preserve both.
