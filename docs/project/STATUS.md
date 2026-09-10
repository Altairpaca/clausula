# Clausula Implementation Status

- Snapshot date: 2026-09-10
- Public branch: `main`
- Package version: `0.1.0`
- Product state: deterministic investment kernel and decision workspace implemented; stable release not yet tagged
- Current release blockers: host-runtime acceptance (#23) and real-data/private-corpus/target-machine acceptance (#34)

## Implemented baseline

### M0 — Legacy archaeology
The ClawAlpha estate was inventoried before migration. Public Git retains sanitized logical-source summaries, capability mapping, migration inventory, data-asset catalog and source snapshot hashes; workstation-only archaeology state remains outside the public repository.

### M1 — Kernel and persistence
Implemented: UUID/Decimal/time contracts, checksummed forward-only migrations, append-only canonical facts, SHA-256 audit chaining, content-addressed raw artifacts, verified backup/restore, canonical export, Capability Registry, permission/confirmation/dry-run handling and architecture tests. `AGENTS.md` remains the normative engineering-invariant surface.

### M2 — Ledger and accounting
Implemented: CSV/manual imports, transaction legs, strict point-in-time replay, multi-currency cash, realized gain and cost basis, fees, FX conversion, transfers with carried basis, splits, reconciliation, append-only corrections and clean rebuild. The extended accounting surface adds versioned FIFO/LIFO/HIFO policies, explicit short lots and covering, policy-controlled shorting, historical identifier validity and point-in-time resolution, plus generalized corporate actions through forward migration v12. PR #38 repaired corporate-action state/replay and mixed-cash consideration invariants. Jurisdiction vocabulary is constrained to CN/HK/US with CN as the generic default profile; tax law remains external configuration rather than engine inference.

### M3 — Market, portfolio and performance
Implemented: versioned price/FX datasets with provenance/quality states, effective/known cutoffs, append-only portfolio membership, Decimal valuation/allocation/exposure, valuation gaps, TWR, Decimal XIRR/MWR, flow-adjusted drawdown, benchmark comparison and explicit price-return/total-return semantics. Batched transaction, instrument, price and FX reads plus incremental multi-date replay remove the original N+1/replay amplification; structural query-growth tests and `scripts/benchmark_reads.py` provide acceptance evidence.

Concrete provider adapters now include Eastmoney daily OHLCV with raw capture and explicit adjustment labels, plus Tencent daily OHLCV. Tencent CN-SH/HK has been exercised against live data with raw-body digest, currency mapping and idempotent re-import. Broader real-provider edge cases remain under #34.

### M4 — Policy, planning and execution constraints
Implemented: portfolio-owned versioned policies, fixed-schema Decimal rules, temporal version selection, deterministic evaluation/simulation, fail-closed incomplete valuation, capital reserve/deployable-cash derivation, signed risk headroom, immutable plans/scenarios, cash funding, fee/tax estimates, projected states, deterministic ranking and versioned execution contracts. Execution feasibility can return executable/blocked/conditional but version 0.x does not place orders.

### M5 — Decision Intelligence and Capital Cockpit
Implemented: immutable trade/non-trade decisions, alternatives, assumptions, expected outcomes, invalidation conditions, review schedules, policy/evidence/transaction links and separate process/outcome reviews. Recommendation lifecycle remains separate from decisions and ledger facts. The Decision Workspace composes material attention, recommendation inbox, evidence pressure, review queue and explicit recommendation-to-decision lineage at `as_of` / `known_as_of` cutoffs. Capital Cockpit exposes capital state, completeness, allocation/concentration, reserve/deployable cash, policy headroom, plans, execution feasibility and decision memory through the local workspace.

### M6 — Research and evidence graph
Implemented: immutable research ingestion, content/source provenance, text/Markdown/HTML/PDF extraction, stateless web capture, source maps, page/section locators, source-spanned claims/evidence, contradictions, append-only thesis revisions, graph links, temporal search, traceability, export/backup/rebuild and Capability/CLI/SDK integration.

PR #48 strengthened the canonical research boundary by validating document text SHA-256 digests, removing duplicated provenance declarations, enforcing `known_at <= recorded_at` across research records and failing early on future-known thesis creation. A broader `effective_at` versus `known_at` policy is deliberately not changed incidentally and should be decided as a separate bitemporal design question.

### Integration — daemon, MCP and plugins
`clausula-daemon` is the single local service owner for Store access, loopback HTTP capability execution, daemon-issued principals, request-bound confirmation and per-home writer leasing. MCP actor/profile identity is bound by the host/session rather than caller payload; plugins receive a fixed manifest permission envelope and cannot self-confirm protected writes.

Plugin discovery is import-free until explicit manifest load. Host policy authorizes network, filesystem, secret, capability and side-effect scopes. PR #44 added a host-supervised plugin subprocess runner using Linux `bwrap` containment plus stdio capability relay, fail-closed writes, timeout/crash/malformed-output handling and isolation tests. GitHub-hosted CI skips the actual bwrap spawn tests where bubblewrap is unavailable; therefore real-host evidence remains part of #23.

## Completed release blockers

### #6 — main protection: COMPLETE
The active `protect-main` ruleset requires pull requests and strict Python 3.12/3.13 CI, blocks branch deletion/non-fast-forward updates and requires linear history. A real direct/force-push rejection was recorded, and a green PR was merged through the protected path.

### #21 — accounting forward migration: COMPLETE
Forward migration v12, historical identifier resolution and generalized corporate actions were merged and subsequently hardened. Migration, clean rebuild and backup/restore evidence was recorded. Local jurisdiction/broker tax interpretation remains user configuration, not missing generic-engine code.

## Remaining stable-release blockers

### #23 — real host/runtime acceptance
Required evidence: independent daemon/CLI/MCP processes against one `CLAUSULA_HOME`; concrete MCP transport identity binding; second-writer denial and concurrent-write serialization; adverse kill/restart recovery; execution of the existing bwrap plugin runner on the actual supported Linux host; failure injection proving canonical writes remain atomic. Windows ACL/named-pipe validation should either be completed or explicitly deferred from the first-release support matrix.

### #34 — real data/private corpus/target-machine acceptance
Required evidence: stale/missing/revised/failure behavior on the selected live market provider; representative real identifier/security-change cases; provider-documented benchmark/return semantics where used; representative private PDF/HTML/Markdown extraction and locator fidelity; optional disposable semantic-index benchmark if desired; target-machine `scripts/benchmark_reads.py --profile full` results.

## Deferred post-release roadmap
PR #41 and issues #40/#45/#46 cover reproducible investment/AI research workflows. They remain deliberately deferred until the stable-release acceptance boundary closes. Before merging #41, rebase and re-review its workflow contracts against the final research/source-artifact identities so workflow artifacts do not become a second truth system. Agent/model configuration must remain execution provenance; assistant outputs should enter Clausula as evidence/research artifacts or Recommendation drafts, never canonical accounting/market/policy truth.

## Known cross-cutting risks
- Audit hashes are tamper-evident but not externally signed; a privileged storage owner could rebuild a chain.
- Backup bundles are integrity-protected but not encrypted by Clausula.
- Migration downgrade relies on backup restore or export/import; frozen historical migrations must never be edited in place.
- Jurisdiction-specific tax interpretation is reviewed configuration, not inferred engine behavior.
- Tencent live acceptance currently covers only a useful subset of real market behavior; #34 remains the data release gate.
- Linux bwrap containment exists in code, but CI-host limitations mean target-host execution evidence is still required.
- Loopback bearer authentication is a local boundary, not an internet-facing TLS or multi-tenant deployment contract.

## Verification
Run from the repository root:

```bash
python -m pip install -e ".[research]"
python -m pytest -q
python -m compileall -q clausula tests
python -m build
git diff --check
```

For target-machine read-path evidence:

```bash
python scripts/benchmark_reads.py --profile full
```

Do not edit frozen migration SQL or checksum-frozen historical migration definitions. Schema changes require a new forward migration.
