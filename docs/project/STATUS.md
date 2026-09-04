# Clausula Implementation Status

- Snapshot date: 2026-09-04
- Public branch: `main`
- Stable domain baseline: M1–M5.1 frozen, M6 research/evidence graph implemented
- Product intelligence: recommendation lifecycle, material attention, Capital Envelope/Risk Headroom, Execution Contracts, and Decision Workspace v1 are implemented
- Performance baseline: bounded ledger/market reads, incremental multi-date replay, query-growth regression tests, and reproducible synthetic benchmarks are implemented
- Integration slices: M7 HTTP, M9 plugin bridge, and M10 MCP projection are local/partial and are not remote-security boundaries
- Next product work: P2 provider/data semantics and single-daemon integration ownership; the P1 decision-product slice is complete

## Implemented baseline

### M0 — Legacy archaeology

The legacy ClawAlpha estate was inventoried read-only before migration. Public Git retains only sanitized logical-source summaries and integrity hashes in `ARCHAEOLOGY.md`, `migration_inventory.yaml`, `data_asset_catalog.yaml`, `source_snapshot_manifest.yaml`, and `capability_mapping.yaml`. The complete per-file inventory and local scanner remain outside the public repository.

### M1 — Kernel

Frozen commits:

```text
80ef3e5 chore: establish audited Clausula kernel baseline
b8622a3 feat: freeze auditable M1 kernel infrastructure
```

Implemented contracts include UUID/Decimal/time semantics, typed repository ports, checksummed forward-only migrations, SHA-256 audit chaining, content-addressed raw artifacts, verified backup/restore, canonical JSONL export, Capability Registry, permissions, confirmation/dry-run handling, and architecture tests.

### M2 — Ledger

Frozen commit `9b10390`. The ledger supports CSV/manual imports, transaction legs, strict as-of replay, multi-currency cash, FIFO lots, realized gain, fees in basis/proceeds, FX conversion, transfers with carried basis, splits, reconciliation, append-only correction, and clean rebuild from raw imports.

### M3 — Market and Portfolio

Frozen commit `8f48bcf`. Implemented contracts include versioned daily price/FX datasets with provenance and quality states, effective/known cutoffs, append-only portfolio membership, Decimal valuation/allocation/exposure, explicit valuation gaps, TWR, Decimal XIRR/MWR, flow-adjusted drawdown, and point-in-time/fixed-vintage knowledge modes.

Accepted ADRs: `0001`–`0004` under `docs/adr/`.

### M4 — Policy as Code

Implemented: portfolio-owned versioned policies, fixed-schema Decimal rules, temporal version selection, deterministic evaluation and simulation, fail-closed incomplete valuation, semantic checksums, append-only persistence, rebuild/export/backup, and permission/confirmation/dry-run tests.

Accepted references: `docs/adr/0005-policy-as-code-and-simulation.md` and `docs/reference/policy-rules.md`.

### M4.5 — Planning and Cash Allocation

Implemented: immutable plans/scenarios, deterministic cash funding, fee/tax estimates, projected states and constraint gaps, deterministic ranking, append-only persistence, canonical export/backup/rebuild, and CLI/SDK/capability projections.

Accepted references: `docs/adr/0006-deterministic-planning-and-cash-allocation.md` and `docs/reference/planning.md`.

### M5 / M5.1 — Decision Intelligence and Integrity Remediation

Implemented: immutable trade/non-trade decisions, alternatives, assumptions, expected outcomes, invalidation conditions, review schedules, links to policy/evidence/transactions, and separate process/outcome reviews. M5.1 closes integrity findings around ledger knowledge time, failed-import atomicity, portfolio ownership checks, backup verification, rebuild semantics, zero-action simulation, and strict alternative selection.

Accepted reference: `docs/adr/0007-decision-memory-and-review.md`.

### M6 — Research and Evidence Graph

Implemented: immutable text ingestion, source artifact provenance, source-spanned claims/evidence, contradictions, append-only thesis revisions, typed graph links, deterministic temporal substring search, schema migrations, canonical export/backup, clean rebuild, CLI/SDK/Capability Registry integration, and acceptance tests.

PDF parsing, network fetching, and vector search remain outside the deterministic core slice.

## Product layer

### Recommendation and Material Attention

The recommendation lifecycle is persisted through append-only recommendation records, alternatives, and lifecycle transitions. Recommendation state remains distinct from canonical ledger facts and does not autonomously place brokerage orders.

Material attention is a derived local notification surface. `AttentionService` rejects non-material evaluations, canonicalizes semantic event data, computes a stable SHA-256 fingerprint for exact deduplication, and records material changes through the tamper-evident audit ledger. Attention evaluation does not create or mutate ledger, policy, recommendation, or decision facts.

### Capital Envelope and Risk Headroom

The Capital Cockpit derives policy-aware decision state from one point-in-time valuation:

- cash in portfolio base currency;
- conservative policy-implied reserve floor;
- deployable cash / reserve shortfall only when required evidence is complete;
- `unconstrained` rather than falsely treating all cash as deployable when no reserve policy exists;
- signed distance to each evaluable policy boundary, with negative headroom representing an existing violation.

These values are deterministic read-model state, not canonical financial facts.

### Versioned Execution Contracts

Execution feasibility is represented as versioned, provenance-aware deterministic constraints rather than agent memory. Current typed constraints include allowed instruments/sides, min/max trade value, max total turnover, settled-cash requirements, minimum lot, price tick, sell-delay/holding-age rules, and trading windows.

Evaluation returns `executable`, `blocked`, or `conditional`. Missing quantity, price, holding age, settled cash, local time, or an active contract never passes optimistically. Persisted Plan scenarios can be evaluated through the same contract surface. No order-placement capability is introduced.

### Capital Cockpit and Decision Workspace v1

The loopback-only read workspace follows the product sequence:

`Capital State → Policy Boundary → Attention → Evidence → Plan / Recommendation → Execution Feasibility → Decision → Review`

Decision Workspace v1 adds:

- material attention feed;
- recommendation inbox;
- evidence pressure using objective evidence age, contradicting links, and explicit claim contradictions;
- decision review queue reconciled against completed process/outcome reviews;
- explicit audit-backed recommendation → decision links;
- visible recommendation → decision → transaction → review lineage.

Point-in-time projections use audit append time when relationship/review rows lack an independent knowledge timestamp. Backdating business time therefore cannot make a later-appended relationship visible in an earlier knowledge snapshot.

Normative product documentation lives under `docs/product/`.

## Performance baseline

The public read path no longer relies on transaction/position-count N+1 behavior for the optimized concrete services:

- ordered transaction + legs materialization replaces per-transaction leg reads;
- FIFO metadata uses bounded batch reads;
- instrument metadata, accepted market prices, and FX pairs resolve in batches at one temporal/dataset cutoff;
- repeated instruments/currencies share reads within a portfolio snapshot;
- multi-date performance advances ordered account state across sorted cutoffs instead of replaying the complete ledger independently for every date.

`tests/test_read_performance_contracts.py` locks structural query-growth invariants in CI. `scripts/benchmark_reads.py` and `docs/product/read-benchmarks.md` provide reproducible smoke/medium/full synthetic profiles for fixed-machine wall-clock comparison; wall-clock thresholds are intentionally not CI gates.

## Partial integration surfaces

- **M7 HTTP**: loopback-only capability discovery/execution and read workspace in `clausula/api/http.py`. No remote authentication or deployment contract exists yet.
- **M9 Plugins**: manifest validation and an in-process capability bridge. Isolation, package discovery, secret/network scopes, and crash containment remain deferred.
- **M10 MCP**: protocol-neutral profile projection in `clausula/adapters/mcp.py`, including read access to execution/workspace projections where appropriate. Concrete transport identity/token binding and invocation security remain deferred.

These surfaces must not be exposed as authenticated remote services merely because they carry permission/profile fields.

## Remaining P2 work

The completed P1 product slice should not be confused with these deferred areas:

- point-in-time network provider adapters with explicit freshness/quality/provenance;
- benchmark comparison and total-return-adjusted semantics where the provider supports them;
- corporate-action completeness, broader lot/tax semantics, richer identifier validity/account metadata;
- research ingestion beyond plain text (PDF/web/vector retrieval outside deterministic truth);
- a single long-running local daemon owning the SQLite writer, authentication/identity binding, confirmation boundary and concurrency policy;
- plugin/widget extensibility only after identity, permissions, secrets/network scopes and failure isolation are explicit.

## Known cross-cutting risks

- Audit hashes are not externally signed; a privileged local attacker could rebuild the chain.
- Backup bundles are integrity-protected but not encrypted.
- SQLite is a single-user local writer; a multi-process contention/daemon ownership policy is not frozen.
- Migration downgrade relies on backup restore or export/import.
- Historical identifier validity ranges and richer account/institution semantics remain incomplete.
- Short positions, jurisdiction-specific tax lots, mergers, spin-offs, and cash-in-lieu remain deferred.
- Market core is CSV/local-provider based; network provider adapters and Parquet scale-out remain future work.
- Performance uses raw daily close and is not guaranteed to use total-return-adjusted prices.

## Verification

Run from the repository root:

```bash
git status --short
python -m pytest -q
python -m compileall -q clausula tests
git diff --check
python -m build
```

Do not edit frozen v1-v5 migration SQL. Changes after the M4 freeze require a forward migration.
