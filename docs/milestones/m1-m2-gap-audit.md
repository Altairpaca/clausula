# M1/M2 Gap Audit

- Audit date: 2026-08-19
- Current gate: M1 kernel frozen; M2 Ledger vertical slice frozen

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
- FIFO lot replay with realized gain and open basis provenance
- deterministic same-day source ordering for imported transactions
- explicit FX conversion, security transfer lot lineage, and split corporate action records
- typed reconciliation observations
- raw CSV and manual-event rebuild into an empty database with ID mapping and state comparison

## M1 residual risks

- Audit hashes are not externally signed; a privileged local attacker can rebuild the chain.
- Backup bundles are integrity-protected but not encrypted.
- SQLite remains a single-user local writer; multi-process write contention policy is not yet specified.
- Migrations are forward-only. Downgrade requires backup restore or an explicit export/import tool.

## M2 residual risks before M3 valuation freeze

- Historical instrument identifier validity and richer institution/account semantics remain to be modeled.
- Jurisdiction tax lots, short sales, cash-in-lieu, mergers, spin-offs, return of capital, and fund distributions need explicit later contracts.
- Unknown legacy basis is surfaced as a warning/error rather than guessed.
- Rebuild supports versioned CSV and manual event envelopes; legacy adapters require validated intermediate ETL.
- Portfolio valuation requires versioned market snapshots and explicit FX valuation policy.
- Complete CLI workflows for correction, reconciliation, FX, security transfer, and corporate action remain pending.

## M3 completion gate

M3 is accepted when the following are true:

- versioned daily price and FX imports are immutable, content-addressed, and
  fail closed on provider conflicts;
- market queries enforce both observed/effective and known-time cutoffs;
- portfolio membership is separate from accounts and is replayable from raw
  event envelopes;
- valuation returns Decimal-string totals, allocation, concentration, currency
  exposure, and explicit completeness gaps;
- TWR, XIRR/MWR, and drawdown have deterministic tests and declare flow timing;
- backup/export/rebuild cover market datasets and portfolio membership;
- capability, CLI, and SDK projections exercise the same service contracts.

The M3 gate is met by the current 65-test suite, compile and diff checks, and
the M3 ADR in `docs/adr/0004-market-portfolio-temporal-analytics.md`.

## Explicitly deferred

Policy, Decision, Research, HTTP, MCP, Web, plugins, Agents, and brokerage
actions remain outside this release candidate. High-frequency market data,
look-through exposure, short positions, and provider network adapters remain
outside M3. `portfolio.get_positions` is superseded by the M3 Portfolio
valuation/performance capabilities.
