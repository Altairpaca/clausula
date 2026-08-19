# ADR 0004: Market Vintages and Portfolio Analytics

- Status: Accepted for M3 implementation
- Date: 2026-08-19

## Context

Portfolio state is a deterministic projection of the Ledger, but valuation also
depends on external market facts. A price or FX rate can be revised, arrive
after the economic date, or conflict with another provider. Portfolio must not
silently select a convenient value, turn missing data into zero, or allow a
knowledge-after-the-query result into an as-of view.

## Decision

Market observations are immutable facts in a named, versioned dataset. Each
dataset has a content-addressed source artifact, import batch, provider,
adapter/schema version, and manifest hash. A dataset name and version identify
one immutable vintage. A query may omit both selectors only when the accepted
facts agree; otherwise it fails closed. Supplying a version requires its
dataset name. Suspect and rejected observations are never used for valuation.

Market observations carry `observed_at`, `known_at`, and `recorded_at`.
`known_at` must not precede `observed_at` or follow `recorded_at`. Queries
filter both observed/effective time and knowledge time. CSV market imports must
provide `known_at` explicitly; import time is not a substitute for knowledge
time.

Portfolio is distinct from Account. A Portfolio contains append-only,
effective-dated and knowledge-dated account membership events. Portfolio
creation and membership events are represented by immutable raw event envelopes
and import batches, so a clean database can replay them without the original
runtime. A portfolio valuation aggregates account valuations in its declared
base currency and returns structured gaps for missing prices, FX, metadata, or
unsupported short positions. It never treats an incomplete total as complete.

M3 supports long positions, daily prices, daily FX, Decimal valuation, asset
allocation, concentration, currency exposure, TWR, Decimal XIRR/MWR, and
drawdown over the linked TWR wealth index. Date-only external flows are treated
as end-of-day and this assumption is included in performance output.

## Consequences

Valuation is explainable through dataset and observation provenance, and
historical views are protected against hindsight contamination. Missing data is
visible to users and downstream Policy evaluation rather than being hidden in a
plausible number. Dataset selection is an explicit analytical decision.

M3 does not model short sales, intraday prices, dividends-adjusted total-return
series, look-through holdings, tax lots beyond M2 FIFO, or provider network
adapters. Those require later contracts and cannot be inferred from this slice.
