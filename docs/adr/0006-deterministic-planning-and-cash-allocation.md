# ADR 0006: Deterministic Planning and Cash Allocation

- Status: Accepted for M4.5 implementation
- Date: 2026-08-19

## Context

Policy evaluation can identify a violation, but a user also needs to compare
possible contributions and rebalances. A plan must explain its assumptions and
constraint tradeoffs without turning a hypothetical into a Ledger fact,
Recommendation, Decision, or Transaction. New capital, fees, and tax estimates
must be explicit and deterministic.

## Decision

`Plan` belongs to a Portfolio and references the PolicyVersion, effective
cutoff, and knowledge cutoff used to build it. A Plan is immutable and has one
or more named `PlanScenario` rows. Each scenario contains candidate actions,
cash made available in the Portfolio base currency, projected state, and
unresolved constraints. Source/import provenance and audit are stored in one
transaction.

M4.5 supports base-currency cash funding only. `cash_available` is added to
cash and total value before candidate actions are applied. Each action contains
`base_value_delta`, non-negative `fee`, and non-negative `tax_estimate` decimal
strings. Fees and tax estimates reduce cash and projected total; they are
estimates, not tax truth or Ledger transactions. Short positions, insufficient
cash, unknown instruments, zero actions, negative fees/taxes, floats, and
incomplete valuation are rejected.

Scenario ranking is deterministic: feasible scenarios first, then fewer hard
constraints, fewer unresolved constraints, lower combined fee/tax estimate,
then stable scenario key. The result records `ledger_mutated: false` and the
selection method. Each scenario exposes:

- `cash_reserve`: projected amount/weight, configured minimums, and both gaps;
- `allocation_gaps`: current weight, target weight, and delta to target for each
  `allocation_band` rule;
- `unresolved_constraints`: rule, severity, status, gap, and explanation;
- projected valuation and policy evaluation with deterministic evidence.

The persisted result is an analytical artifact. Its JSON uses canonical Decimal
strings, while formal tables retain scenario cash, fee, tax, action, projected
total, and constraint columns. A content hash covers each projected valuation;
clean rebuild recomputes scenarios after mapping Portfolio, Policy, Market, and
Instrument IDs and compares semantic output after removing internal UUIDs.

The canonical capabilities are `planning.compare`, `planning.create`,
`planning.list`, and `planning.get`. Compare/get/list are local reads. Create
requires `planning:write`, Policy/Portfolio/Market read permissions, explicit
confirmation, and supports dry-run. No Planning capability writes Ledger.

## Consequences

Users can compare multiple candidate allocations and understand why a scenario
is feasible, violates a rule, or cannot be established. Planning is replayable,
backup-safe, and available without an Agent. M4.5 does not forecast markets,
calculate jurisdiction-specific tax liability, execute orders, or replace the
later Decision and Recommendation lifecycles.
