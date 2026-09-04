# Clausula Implementation Status

- Snapshot date: 2026-09-04
- Public branch: `main`
- Stable domain baseline: M1–M5.1 frozen, M6 research/evidence graph implemented
- Integration slices: M7 HTTP, M9 plugin bridge, and M10 MCP projection are local/partial and are not remote-security boundaries
- Next product work: recommendation/attention and higher-level user surfaces

## Implemented baseline

### M0 — Legacy archaeology

The legacy ClawAlpha estate was inventoried read-only before migration. Public Git now retains only sanitized logical-source summaries and integrity hashes in `ARCHAEOLOGY.md`, `migration_inventory.yaml`, `data_asset_catalog.yaml`, `source_snapshot_manifest.yaml`, and `capability_mapping.yaml`. The complete per-file inventory and local scanner remain outside the public repository.

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

PDF parsing, network fetching, and vector search are outside the current slice.

## Partial integration surfaces

- **M7 HTTP**: local-only capability discovery/execution in `clausula/api/http.py`. No remote authentication or deployment contract exists yet.
- **M9 Plugins**: manifest validation and an in-process capability bridge. Isolation, package discovery, secret/network scopes, and crash containment remain deferred.
- **M10 MCP**: protocol-neutral profile projection in `clausula/adapters/mcp.py`. Concrete transport identity/token binding and invocation security remain deferred.

These surfaces must not be exposed as authenticated remote services merely because they carry permission/profile fields.

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
python -m pytest -q tests/test_policy.py tests/test_policy_analytics.py
python -m compileall -q clausula tests
git diff --check
```

Do not edit frozen v1-v5 migration SQL. Changes after the M4 freeze require a forward migration.
