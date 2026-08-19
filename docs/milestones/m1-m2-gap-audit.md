# M1/M2 Gap Audit

- Audit date: 2026-08-19
- Current gate: M1 kernel frozen; M2 Ledger vertical slice in progress

## Implemented and tested

- UUID identity enforcement and external instrument identifiers
- Decimal-only financial values and canonical string serialization
- UTC-normalized temporal metadata and strict `known_at` as-of filtering
- immutable content-addressed file artifacts and virtual manual artifacts
- versioned import metadata, row-level idempotence, and transactional fact insertion
- append-only SQLite enforcement for artifacts, imports, transactions, legs, corrections, transfers, and reconciliation
- buy, sell, deposit, withdrawal, cash transfer, dividend, interest, fee, and tax CSV normalization
- cash and position replay by account and date
- two-sided internal cash transfers with explicit linkage and fee handling
- append-only correction chains and reconciliation records
- database integrity check, backup, restore, and pre-versioned schema upgrade
- architecture tests for inward dependency direction
- typed Ledger/Core repository ports
- ordered checksummed schema migrations with future-version rejection
- same-transaction SHA-256 audit chain and verification
- complete database/raw/export backup bundles with adversarial restore validation
- stable canonical JSONL export
- executable Capability Registry with schemas, permissions, confirmation, dry-run, provenance, and versions
- CLI and SDK projection from the registry

## M1 residual risks

- Audit hashes are not externally signed; a privileged local attacker can rebuild the chain.
- Backup bundles are integrity-protected but not encrypted.
- SQLite remains a single-user local writer; multi-process write contention policy is not yet specified.
- Migrations are forward-only. Downgrade requires backup restore or an explicit export/import tool.

## Blocking gaps before M2 freeze

- Complete institution/account semantics and historical instrument identifier validity.
- Define lots, cost basis, fee/tax ownership, dividends/distributions, FX, and corporate actions.
- Support two-sided security transfers and cross-currency transfer/conversion contracts.
- Store observed brokerage snapshots as typed reconciliation observations.
- Provide a validated intermediate schema and controlled local ETL for legacy portfolios.
- Rebuild the Ledger deterministically from raw artifacts into an empty database and compare reconciliation outputs.
- Add property tests for conservation, transfer tie-out, correction replay, and arbitrary import order.
- Complete CLI workflows for transaction history, correction, reconciliation, backup, and restore.

## Explicitly deferred

Market data, valuation, performance, Policy, Decision, Research, HTTP, MCP, Web, plugins, Agents, and brokerage actions remain outside this release candidate. `portfolio.get_positions` is only an account-state projection and is not the Phase 3 Portfolio domain.
