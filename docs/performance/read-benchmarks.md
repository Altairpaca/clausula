# Read-path benchmarks

Clausula treats temporal correctness and bounded query growth as the primary performance contract. Wall-clock time is still useful, but it varies with SQLite version, storage, CPU, filesystem cache, and Python build, so CI does **not** fail on a millisecond threshold.

## Run

```bash
python scripts/benchmark_reads.py --profile smoke
python scripts/benchmark_reads.py --profile medium
python scripts/benchmark_reads.py --profile full
```

The command prints machine-readable JSON with setup time plus read timing and SQL statement counts.

| profile | accounts | transactions | positions | performance dates |
| --- | ---: | ---: | ---: | ---: |
| `smoke` | 1 | 1,000 | 20 | 30 |
| `medium` | 3 | 10,000 | 60 | 365 |
| `full` | 5 | 25,000 | 100 | 1,826 |

The full profile represents roughly five years of daily performance cutoffs. Synthetic market prices are intentionally simple and point-in-time safe so the benchmark measures replay/read-model cost rather than provider/network cost.

## What is enforced in CI

`tests/test_read_performance_contracts.py` traces SQLite and verifies the structural invariants that matter across machines:

- transaction count does not create transaction→legs N+1 queries for one ledger state;
- position count does not create one instrument/price read per position;
- increasing performance dates does not trigger one full ledger replay per date;
- temporal and dataset cutoffs continue to isolate snapshots.

The benchmark harness is therefore descriptive evidence, while query-growth tests are normative acceptance gates.

## Recording before/after evidence

When changing replay, valuation, or performance code, run the same profile on the same machine before and after the change and retain the JSON in the PR description or local engineering notes. Compare:

1. output correctness and completeness;
2. `select_statements` / total SQL statements;
3. wall-clock read time;
4. memory behavior if the change materializes larger batches.

Do not accept a faster implementation that crosses `as_of`, `known_as_of`, dataset-version, or provenance boundaries. A cache that can return the wrong historical knowledge state is a correctness regression, not a performance improvement.
