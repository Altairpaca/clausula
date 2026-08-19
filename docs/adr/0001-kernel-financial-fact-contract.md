# ADR 0001: Kernel Financial Fact Contract

- Status: Accepted for M1/M2 implementation
- Date: 2026-08-19

## Context

Clausula must replay investment facts without floating-point drift, source loss, or hindsight contamination. The initial prototype stored the right three timestamps but did not normalize them, copied no raw artifacts, allowed SQL updates/deletes, and could create transactions with placeholder provenance.

## Decision

Internal IDs use canonical UUID strings. External instrument identifiers are resolved through a separate identifier registry.

Money, quantity, fees, tax, and future FX values enter the domain as `Decimal`. Floats, non-finite values, and non-canonical persistence are rejected. SQLite stores canonical plain decimal strings without exponent notation or insignificant trailing zeros.

All timestamps are offset-aware ISO-8601 values normalized to UTC. Date-only input means UTC midnight. `effective_at` is the economic time, `known_at` is when the fact could be known, and `recorded_at` is when Clausula accepted it. `known_at` may not be later than `recorded_at`. As-of replay applies both `effective_at <= cutoff` and `known_at <= cutoff`.

Every transaction references an existing immutable source artifact and import batch. File artifacts are content-addressed under `raw/`; manual operations create deterministic virtual artifacts. Import batches declare adapter, adapter version, schema version, input count, and inserted count.

Financial tables are append-only at both application and SQLite trigger levels. Corrections are new compensating transactions, optionally linked to the corrected transaction. Reconciliation records observed and derived states but never changes Ledger state.

Transaction amounts conserve to zero per currency. Position quantity and accounting amount remain separate. Cash state replays only cash legs; positions replay only position legs. Currencies are never summed without an FX conversion contract.

## Consequences

CSV imports and manual operations are deterministic and traceable. Raw values from the pre-versioned prototype remain untouched during schema upgrade, so old non-canonical decimal strings may remain until an explicit audited migration is approved.

This ADR does not define lots, realized PnL, corporate actions, taxes, FX conversion transactions, portfolio aggregation, or valuation. Those require additional domain decisions before M2/M3 can freeze.
