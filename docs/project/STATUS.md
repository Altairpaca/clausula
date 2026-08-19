# Clausula Implementation Status

- Snapshot date: 2026-08-19, Asia/Taipei
- Repository: `/home/altair/projects/clausula`
- Branch: `main`
- Last frozen implementation: `feat: complete versioned investment policy vertical slice` (current `HEAD`)
- Current phase: M6 Research and Evidence Graph
- M4 Policy as Code, M4.5 Planning/Cash Allocation, and M5 Decision Intelligence are frozen.

## Frozen Milestones

### M0 Archaeology

完成对旧 ClawAlpha 工作区、数据、状态、归档和迁移包的只读盘点。结果在
`ARCHAEOLOGY.md`、`migration_inventory.yaml`、`data_asset_catalog.yaml`、
`source_snapshot_manifest.yaml` 和 `capability_mapping.yaml`。没有把私人财务数据复制进 Git。

### M1 Kernel

Frozen commits:

```text
80ef3e5 chore: establish audited Clausula kernel baseline
b8622a3 feat: freeze auditable M1 kernel infrastructure
```

已具备 UUID/Decimal/temporal contracts、typed repository ports、checksummed forward-only
migrations、SHA-256 audit chain、content-addressed raw artifacts、verified backup/restore、
canonical JSONL export、Capability Registry、permissions、confirmation、dry-run、CLI/SDK
projection 和 architecture tests。

### M2 Ledger

Frozen commit:

```text
9b10390 feat: complete auditable ledger vertical slice
```

已具备 CSV/manual imports、交易和 leg、严格 as-of replay、多币种现金、FIFO lots、realized
gain、费用计入 basis/proceeds、FX conversion、双边现金/证券转账、carried basis、split、
typed reconciliation、append-only correction，以及从 raw imports 重建 clean database。

### M3 Market and Portfolio

Frozen commit:

```text
8f48bcf feat: complete market and portfolio analytics vertical slice
```

冻结前验证：65 tests passed；28 项架构/基础设施/能力定向测试通过；wheel 构建成功；
隔离 virtualenv 安装后的 CLI 能发现 16 个 capabilities。

已具备：

- versioned daily price/FX CSV datasets、manifest JSON/hash、provider provenance；
- accepted/suspect/rejected quality，冲突时禁止 silent fallback；
- observed/effective 与 known cutoff，显式禁止 hindsight；
- Portfolio 与 Account 分离，append-only temporal membership；
- Portfolio create/membership 的 raw event envelope 和 clean rebuild；
- Decimal valuation、allocation、concentration、currency exposure、valuation gaps；
- incomplete valuation 不产生伪造 total/weights；
- TWR、Decimal XIRR/MWR、flow-adjusted drawdown；
- point-in-time 与 fixed-vintage performance knowledge modes；
- market/portfolio capability、CLI、SDK、backup/export/rebuild coverage。

Accepted ADRs:

```text
docs/adr/0001-kernel-financial-fact-contract.md
docs/adr/0002-migrations-audit-backup-and-capabilities.md
docs/adr/0003-ledger-lots-fx-and-corporate-actions.md
docs/adr/0004-market-portfolio-temporal-analytics.md
```

### M4 Policy as Code

M4 release candidate includes:

- Portfolio-owned `InvestmentPolicy`, append-only `PolicyVersion`, and fixed-schema `PolicyRule`;
- six Decimal-only rule types with inclusive boundaries and strict field shapes;
- effective/known/recorded temporal selection with backdated anti-lookahead tests;
- deterministic evaluation/evidence and fail-closed incomplete valuation;
- deterministic base-currency-cash simulation with no Ledger or audit mutation;
- stable semantic rule checksum, deterministic per-version rule IDs, and raw event IDs;
- atomic raw/import/canonical/audit writes for create and append-version operations;
- schema migration v6, append-only triggers, canonical export, backup/restore, and clean rebuild;
- policy/version/rule rebuild ID maps and semantic comparisons;
- `policy.create`, `policy.add_version`, `policy.list`, `policy.evaluate`, and `policy.simulate`;
- permission, confirmation, dry-run, CLI, SDK, temporal, boundary, and adversarial tests.

Policy evaluations remain deterministic ephemeral analytical outputs. They are not canonical facts and
are not persisted in M4. Simulation is not a Plan, Recommendation, Decision, or Transaction.

Accepted M4 references:

```text
docs/adr/0005-policy-as-code-and-simulation.md
docs/reference/policy-rules.md
```

Release verification before freeze: 80 tests passed; Policy targeted tests, compile, diff, and YAML checks
passed. Wheel build succeeded, and an isolated installed CLI discovered 21 capabilities and executed
`policy.create`, `policy.evaluate`, and `policy.simulate` successfully.

### M4.5 Planning and Cash Allocation

M4.5 release candidate includes:

- immutable Portfolio/PolicyVersion-owned `Plan` and named `PlanScenario` rows;
- base-currency cash funding with deterministic fee and explicit tax estimates;
- candidate actions, projected states, cash reserve gaps, target allocation gaps, and unresolved constraints;
- deterministic ranking by feasibility, hard constraints, total constraints, combined costs, and stable key;
- v7 append-only planning tables, canonical export, backup/restore, and clean rebuild semantic comparison;
- `planning.compare`, `planning.create`, `planning.list`, and `planning.get` registry capabilities;
- CLI/SDK projections, confirmation/dry-run/permission tests, and no-Ledger-mutation acceptance stories.

Accepted M4.5 references:

```text
docs/adr/0006-deterministic-planning-and-cash-allocation.md
docs/reference/planning.md
```

M4.5 verification: 85 tests passed; compile, diff, and YAML checks passed. The final wheel built
successfully, and an isolated installed CLI discovered 25 capabilities and executed
`planning.compare`, `planning.create`, and `planning.get` successfully.

### M5 Decision Intelligence

M5 frozen implementation includes immutable trade/non-trade Decisions, Alternatives,
Assumptions, ExpectedOutcomes, InvalidationConditions, review schedules,
Policy/Evidence/Transaction links, and separate process/outcome reviews. Schema
v8, canonical export, backup/restore, clean rebuild, registry, CLI, SDK, and
permission/confirmation/dry-run contracts cover the lifecycle. Transaction
links never create or mutate Ledger facts.

Accepted reference: `docs/adr/0007-decision-memory-and-review.md`.

## Known Cross-Cutting Risks

- Audit hashes are not externally signed; a privileged local attacker could rebuild the chain.
- Backup bundles are integrity-protected but not encrypted.
- SQLite is currently a single-user local writer; multi-process contention policy is not frozen.
- Migration downgrade requires backup restore/export-import.
- Historical identifier validity ranges and richer account/institution semantics are incomplete.
- Short positions, jurisdiction-specific tax lots, mergers, spin-offs and cash-in-lieu are deferred.
- Market core is CSV/local-provider based; network provider adapters and Parquet scale-out remain later work.
- Content-addressed files can remain as harmless unreferenced bytes after an operating-system failure;
  policy database provenance and canonical writes are transactional.
- Performance uses raw daily close, not guaranteed total-return adjusted prices.

## Verification Commands

Run from `/home/altair/projects/clausula`:

```bash
git status --short
pytest -q
pytest -q tests/test_policy.py tests/test_policy_analytics.py
python -m compileall -q clausula tests scripts
git diff --check
```

Do not edit frozen v1-v5 migration SQL. Changes after the M4 freeze require a forward migration.
