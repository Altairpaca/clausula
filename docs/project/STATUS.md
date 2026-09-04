# Clausula Implementation Status

- Snapshot date: 2026-09-04
- Public branch: `main`
- Stable domain baseline: M1–M5.1 frozen; later work uses forward migrations and additive contracts
- Research/evidence: local text, Markdown, HTML, PDF and web-capture ingestion with provenance/source maps
- Product intelligence: Capital Cockpit, decision workspace, recommendation lifecycle, material attention, evidence pressure and decision lineage are implemented
- Integration boundary: one local daemon owns write/auth/confirmation state; MCP/plugin invocation authority is host-bound and fail-closed
- Release state: no stable tag yet; first release is blocked on the local acceptance items in `docs/project/LOCAL_ACCEPTANCE.md`

## Implemented baseline

### M0 — Legacy archaeology

The legacy ClawAlpha estate was inventoried read-only before migration. Public Git retains only sanitized logical-source summaries and integrity hashes in `ARCHAEOLOGY.md`, `migration_inventory.yaml`, `data_asset_catalog.yaml`, `source_snapshot_manifest.yaml`, and `capability_mapping.yaml`. Per-file local inventory and workstation archaeology tooling remain outside the public repository.

### M1 — Kernel

Implemented contracts include UUID/Decimal/time semantics, typed repository ports, checksummed forward-only migrations, SHA-256 audit chaining, content-addressed raw artifacts, verified backup/restore, canonical JSONL export, the Capability Registry, permission checks, confirmation/dry-run handling, and architecture tests.

Frozen kernel commits include `80ef3e5` and `b8622a3`.

### M2 — Ledger

Frozen ledger baseline commit `9b10390` supports CSV/manual imports, transaction legs, strict as-of replay, multi-currency cash, FIFO lots, realized gain, fees in basis/proceeds, FX conversion, transfers with carried basis, splits, reconciliation, append-only correction, and clean rebuild from raw imports.

The newer accounting surface adds append-only account accounting policies, FIFO/LIFO/HIFO selection, explicit short lots/covering, short realized P&L, and policy-controlled shorting. Historical identifier validity, generalized corporate actions and canonical specific-lot selection remain tracked in #21 because they require a real forward migration.

### M3 — Market, Portfolio and Performance

Implemented contracts include versioned price/FX datasets with provenance and quality states, effective/known cutoffs, append-only portfolio membership, Decimal valuation/allocation/exposure, explicit valuation gaps, TWR, Decimal XIRR/MWR, flow-adjusted drawdown, and point-in-time/fixed-vintage knowledge modes.

Read paths now use batched transaction metadata, instrument/price/FX access and bounded performance reconstruction. `tests/test_read_performance_contracts.py` enforces query-growth invariants, while `scripts/benchmark_reads.py` provides machine-specific smoke/medium/full benchmark evidence without making milliseconds a correctness threshold.

Provider snapshot import, raw-payload capture, dataset provenance, return-index semantics and benchmark comparison contracts are implemented. Selection and validation of real providers and real return semantics remain local acceptance work in #34.

Accepted ADRs: `0001`–`0004` under `docs/adr/`.

### M4 — Policy as Code

Implemented: portfolio-owned versioned policies, fixed-schema Decimal rules, temporal version selection, deterministic evaluation/simulation, fail-closed incomplete valuation, semantic checksums, append-only persistence, rebuild/export/backup, and permission/confirmation/dry-run tests.

Accepted references: `docs/adr/0005-policy-as-code-and-simulation.md` and `docs/reference/policy-rules.md`.

### M4.5 — Planning, Cash Allocation and Execution Constraints

Implemented: immutable plans/scenarios, deterministic cash funding, fee/tax estimates, projected states and constraint gaps, deterministic ranking, append-only persistence, canonical export/backup/rebuild, CLI/SDK/capability projections, typed execution contracts, capital reserve/deployable-cash derivation and risk-headroom output.

Accepted references: `docs/adr/0006-deterministic-planning-and-cash-allocation.md` and `docs/reference/planning.md`.

### M5 / M5.1 — Decision Intelligence and Integrity Remediation

Implemented: immutable trade/non-trade decisions, alternatives, assumptions, expected outcomes, invalidation conditions, review schedules, links to policy/evidence/transactions, and separate process/outcome reviews. Integrity remediation covers ledger knowledge time, failed-import atomicity, portfolio ownership checks, backup verification, rebuild semantics, zero-action simulation, and strict alternative selection.

Accepted reference: `docs/adr/0007-decision-memory-and-review.md`.

### M6 — Research and Evidence Graph

Implemented: immutable research ingestion, source artifact provenance, source-spanned claims/evidence, contradictions, append-only thesis revisions, typed graph links, deterministic temporal search, canonical export/backup/rebuild, CLI/SDK/Capability Registry integration, Markdown/HTML/PDF extraction, explicit page/section source locators, span tracing, and stateless web capture with captured response metadata.

Optional vector/semantic retrieval remains a disposable derived index rather than canonical truth and is intentionally deferred to real-corpus evaluation under #34.

### Recommendation, Attention and Decision Workspace

Recommendation lifecycle records, alternatives and lifecycle transitions are append-only and remain distinct from canonical ledger facts. Version 0.x does not autonomously place brokerage orders.

Material attention is a derived local notification surface with semantic fingerprint deduplication and tamper-evident audit recording. The decision workspace composes attention, recommendation inbox, evidence pressure, review queue and recommendation-to-decision lineage at explicit `as_of` / `known_as_of` cutoffs.

### Local daemon, MCP and plugins

PR #30 established `clausula-daemon` as the single local service owner for Store access, loopback HTTP capability execution, daemon-issued principals and request-bound confirmation challenges. A per-`CLAUSULA_HOME` OS lease rejects a second daemon writer. Local bootstrap credentials are ephemeral runtime state rather than canonical financial state.

PR #32 removed invocation self-assertion: MCP invocation profile/actor identity are bound when an adapter/session is constructed; plugin permissions are fixed by the manifest; neither MCP nor plugin callers can self-assert confirmation. Confirmation-required writes fail closed until trusted host approval is supplied.

PR #33 added import-free plugin entry-point discovery plus explicit manifest loading and host-policy preflight for declared network hosts, filesystem scopes, secrets, capability permissions and side effects. This is an authorization contract, not an OS sandbox.

The remaining daemon/plugin/MCP work in #23 is specifically host-level: real independent processes, concrete transport identity binding, OS ACL/socket behavior, crash recovery and subprocess isolation/failure containment.

## Remaining release blockers

Only the following open workstreams are release blockers after the GitHub-testable implementation pass:

- **#6 — repository protection:** require PR + CI on `main`, block force push/deletion and verify the rule actually rejects bypasses.
- **#21 — accounting forward migration:** historical identifier validity, generalized corporate actions, specific-lot facts when enabled, plus reviewed jurisdiction/broker tax profiles.
- **#23 — host/runtime isolation:** multi-process daemon clients, concrete MCP transport, OS ACL/socket/pipe behavior, crash recovery and real plugin sandbox/failure containment.
- **#34 — real-data acceptance:** live providers, private research corpus, optional semantic retrieval evaluation and target-machine performance evidence.

See `docs/project/LOCAL_ACCEPTANCE.md` for the executable handoff.

## Known cross-cutting risks

- Audit hashes are tamper-evident but not externally signed; a privileged local attacker with full storage control can rebuild a chain.
- Backup bundles are integrity-protected but not encrypted by Clausula.
- Migration downgrade relies on backup restore or export/import; frozen migrations must not be edited in place.
- Historical identifier validity and generalized corporate-action accounting are incomplete until #21 lands.
- Jurisdiction-specific tax interpretation is configuration/review work, not a generic-engine default.
- Provider adapters are contractual until real local providers are selected and validated under #34.
- Plugin host policy authorizes scopes but does not itself enforce an OS sandbox; that enforcement is part of #23 local acceptance.
- Loopback bearer authentication is a local boundary, not an internet-facing TLS/multi-tenant deployment contract.

## Verification

Run from the repository root:

```bash
python -m pip install -e ".[research]"
python -m pytest -q
python -m compileall -q clausula tests
python -m build
git diff --check
```

For read-path evidence on a target machine:

```bash
python scripts/benchmark_reads.py --profile full
```

Do not edit frozen migration SQL or checksum-frozen historical migration definitions. Schema changes require a new forward migration.
