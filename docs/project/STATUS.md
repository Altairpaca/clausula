# Clausula Implementation Status

- Snapshot date: 2026-08-19, Asia/Taipei
- Repository: `/home/altair/projects/clausula`
- Branch: `main`
- Last frozen implementation commit: `8f48bcf feat: complete market and portfolio analytics vertical slice`
- Documentation checkpoint: committed immediately after M3 while M4 remains uncommitted
- Persistent objective status at checkpoint: paused by user interruption
- Current phase: M4 Policy as Code, uncommitted and not frozen

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

## M4 Policy Work In Progress

M4 当前代码存在于 dirty worktree，不能称为 release candidate。已经实现但尚未完成
semantic audit 的部分：

- `clausula/domain/policy.py`
  - `InvestmentPolicy`、`PolicyVersion`、`PolicyRule`；
  - structured evaluation/result/evidence objects；
  - 初始 rule types：allocation band、single instrument max、asset type max、cash amount/
    weight minimum、currency max；
  - Decimal threshold validation、UUID identity、version temporal fields。
- `clausula/analytics/policy.py`
  - deterministic rule evaluation；
  - incomplete valuation fail closed 为 `unavailable`；
  - deterministic evaluation UUID；
  - base-currency-cash funded what-if simulation；
  - simulation 明确不写 Ledger。
- `clausula/application/policy.py`
  - create policy、append policy version、list/evaluate/simulate；
  - immutable raw policy event envelope、ImportBatch、rules hash；
  - strict effective/known version selection。
- SQLite migration v6 与 repository methods；backup export table coverage；typed ports/exports。
- `tests/test_policy_analytics.py` 与 `tests/test_policy.py`：7 targeted tests passed。

## Exact Test State

Checkpoint 时完整命令：

```text
pytest -q
```

结果：

```text
70 passed, 2 failed
```

失败不是 Policy 行为失败，而是两个既有 migration assertions 仍预期 schema v5：

1. `tests/test_kernel_infrastructure.py::test_migrations_are_ordered_and_checksummed`
   需要加入 `(6, "versioned_investment_policy", 64)`。
2. `tests/test_persistence_contracts.py::test_pre_versioned_database_is_upgraded_without_rewriting_facts`
   需要将 expected user/schema versions 从 5 更新到 6。

定向结果：

```text
pytest -q tests/test_policy.py tests/test_policy_analytics.py
7 passed
```

## Exact Dirty Worktree

Tracked modifications:

```text
clausula/adapters/backup.py
clausula/adapters/migrations.py
clausula/adapters/sqlite.py
clausula/analytics/__init__.py
clausula/application/__init__.py
clausula/application/ports.py
clausula/domain/__init__.py
```

Untracked M4 files:

```text
clausula/analytics/policy.py
clausula/application/policy.py
clausula/domain/policy.py
tests/test_policy.py
tests/test_policy_analytics.py
```

Untracked pre-existing content not created or reviewed as part of M4:

```text
docs/benchmarks/
```

Do not delete, overwrite, stage, or claim ownership of `docs/benchmarks/` until its provenance is
confirmed. The project context documents under `docs/project/` are intentionally created by this
checkpoint task.

## M4 Remaining Gaps

M4 is not ready to commit until all of the following are complete:

1. Update v6 migration assertions and rerun full tests.
2. Audit `_rules` normalization and stable rule IDs/checksum behavior.
3. Add policy capabilities: create, add_version, list, evaluate, simulate.
4. Add Policy CLI and Python SDK convenience projections.
5. Add policy event replay to `LedgerRebuilder`, with policy/version ID mappings and comparison.
6. Add backup/restore round-trip and clean raw rebuild tests for multiple temporal versions.
7. Add permission/confirmation/dry-run capability contract tests.
8. Add temporal tests proving a later-known backdated PolicyVersion is invisible at earlier knowledge cutoff.
9. Add simulation adversarial tests: insufficient cash, oversell/short, float rejection, fee effect,
   unknown instrument, incomplete valuation, dataset conflict.
10. Decide and document whether deterministic evaluations remain ephemeral or become versioned
    analytical artifacts. Current implementation returns them but does not persist them.
11. Write M4 ADR and metric/rule definition documentation.
12. Update `capability_mapping.yaml`, architecture docs and milestone status.
13. Run full suite, compile, diff check, YAML parse, wheel build and installed CLI smoke.
14. Only then commit with a milestone-scoped message such as
    `feat: complete versioned investment policy vertical slice`.

## Known Cross-Cutting Risks

- Audit hashes are not externally signed; a privileged local attacker could rebuild the chain.
- Backup bundles are integrity-protected but not encrypted.
- SQLite is currently a single-user local writer; multi-process contention policy is not frozen.
- Migration downgrade requires backup restore/export-import.
- Historical identifier validity ranges and richer account/institution semantics are incomplete.
- Short positions, jurisdiction-specific tax lots, mergers, spin-offs and cash-in-lieu are deferred.
- Market core is CSV/local-provider based; network provider adapters and Parquet scale-out remain later work.
- Policy raw artifact/import creation and canonical insert are separate repository calls. Expected validation
  failures are prevented before provenance creation, but unexpected storage failure atomicity needs an
  explicit unit-of-work decision.
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

Do not edit frozen v1-v5 migration SQL. Migration v6 is still unfrozen and may be remediated before the
M4 commit.
