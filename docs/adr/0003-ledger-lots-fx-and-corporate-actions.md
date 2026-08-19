# ADR 0003: Ledger Lots, FX, and Corporate Actions

- Status: Accepted for M2 implementation
- Date: 2026-08-19

## Context

Quantity replay alone cannot explain current cost, realized gains, account-to-account security movement, currency conversion, or split-adjusted history. These semantics must be deterministic before Portfolio valuation and performance are built.

## Decision

FIFO is the first canonical cost-basis method. A buy opens a lot whose basis is gross purchase amount plus transaction fees. A sell consumes oldest open lots; net proceeds are gross sale amount minus fees. Partial consumption allocates remaining basis proportionally and assigns the entire residual basis when a lot closes, preserving exact Decimal conservation.

Cost-basis outputs are derived artifacts, not mutable Ledger facts. Every open lot and realized match links to source transaction IDs. Overselling the replayed available quantity is an error, never an implicit short position. Short sales and jurisdiction-specific tax elections are deferred.

A dedicated security transfer creates linked source and destination transactions. It consumes FIFO source lots, records their carried basis, opens destination lots with the same basis, and creates no realized gain. Generic broker rows labeled `transfer_in` or `transfer_out` without a linked carried-basis record remain quantity facts with unknown basis and are explicitly flagged by cost-basis replay.

An FX conversion is one transaction with balanced legs in each currency: source cash and source clearing legs sum to zero; destination cash and destination clearing legs sum to zero. The recorded rate is destination amount divided by source amount. Fees use an explicit currency and never disappear into the rate.

The first corporate action is `split`, including reverse splits through a positive numerator/denominator ratio. A split appends a quantity adjustment transaction and metadata. It multiplies every open lot quantity by the ratio while preserving total basis. Cash in lieu, mergers, spin-offs, and return of capital require later explicit action types.

Reconciliation observations are typed append-only rows for cash or instrument quantity. JSON snapshots remain a presentation envelope, not the only canonical observation representation.

## Consequences

M2 can explain each holding through open lots and each realized result through sale-to-lot matches. Portfolio analytics may consume these derived views but may not redefine cost semantics. Market prices are not part of this ADR, so unrealized gain requires an explicit caller-supplied price and currency match.
