# ADR 0005: Policy as Code and Deterministic Simulation

- Status: Accepted for M4 implementation
- Date: 2026-08-19

## Context

Clausula needs to explain whether a portfolio complied with the policy that was
effective and knowable at a historical cutoff. Policy cannot be an executable
LLM prompt, an unversioned settings blob, or a rule engine that silently treats
missing valuation as compliance. A what-if must also remain distinct from a
Recommendation, Decision, or Transaction.

## Decision

An `InvestmentPolicy` belongs to exactly one Portfolio and provides stable
identity. Each `PolicyVersion` is append-only, contains a fixed-schema set of
`PolicyRule` rows, and carries `effective_from`, `known_at`, and `recorded_at`.
Selection requires both `effective_from <= as_of` and
`known_at <= known_as_of`; later-known backdated versions are invisible before
their knowledge cutoff.

Rule inputs are normalized in one pass. Rule IDs are deterministic UUIDv5
identities within a PolicyVersion, raw event envelopes record those IDs, and
`rules_sha256` hashes sorted semantic fields without IDs. The hash therefore
survives clean rebuild even though target policy/version/rule UUIDs are mapped
to new internal IDs. Decimal values use canonical strings and binary floats are
rejected before provenance is written.

M4 supports six closed rule types:

| Type | Subject | Thresholds | Compliant when |
| --- | --- | --- | --- |
| `allocation_band` | asset type | target, lower, upper | lower <= weight <= upper |
| `max_single_instrument_weight` | none | upper | largest instrument weight <= upper |
| `max_asset_type_weight` | asset type | upper | asset weight <= upper |
| `min_cash_weight` | none | lower | cash weight >= lower |
| `min_cash_amount` | none | lower | base-currency cash value >= lower |
| `max_currency_weight` | currency | upper | currency exposure weight <= upper |

Weight thresholds are inclusive Decimal values in `[0, 1]`. Amount thresholds
are non-negative and denominated in the Portfolio base currency. A missing
subject is zero exposure only when valuation is complete. If valuation is
incomplete, every rule and the aggregate evaluation are `unavailable`.
`hard` and `soft` are reporting severity; they do not change arithmetic.

Policy evaluation is an ephemeral deterministic analytical result in M4. Its
UUID is derived from the policy version, portfolio, cutoffs, and ordered rule
results. Canonical Policy versions and market/Ledger facts are persisted, while
recomputable evaluations are returned with their input valuation and evidence.
A later requirement for signed or retained evaluations needs a separate
versioned analytical-artifact contract.

Simulation accepts only base-value changes funded by base-currency cash. It
rejects insufficient cash, short positions, unknown instruments, zero actions,
negative fees, floats, and incomplete valuation. Fees reduce both cash and
total value. Simulation returns before/after evaluation and explicitly records
that the Ledger was not mutated.

Policy create/version operations validate first, then store artifact metadata,
import metadata, canonical rows, and audit events in one SQLite transaction.
The immutable content-addressed file may safely pre-exist a rolled-back
database transaction. Clean rebuild replays `clausula-policy-event-v1`, maps
policy/version/rule IDs, and compares times, version numbers, checksums, and
normalized rules.

The canonical capabilities are `policy.create`, `policy.add_version`,
`policy.list`, `policy.evaluate`, and `policy.simulate`. Writes require
`policy:write`, confirmation, and support dry-run. Evaluation and simulation
require policy, portfolio, and market read permissions. CLI and Python SDK call
the same registry handlers.

## Consequences

Policy behavior is deterministic, temporal, rebuildable, and usable without an
Agent. Incomplete or conflicting data cannot create false compliance. M4 does
not provide arbitrary expressions, tax-aware planning, autonomous rebalancing,
persistent evaluation history, Recommendation lifecycle, or brokerage action.
Those require later domain contracts.
