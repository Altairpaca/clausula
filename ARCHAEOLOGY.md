# Clausula Capability Archaeology

Generated: `2026-08-19T05:27:45+00:00`

## Scope and method

This M0 inventory is a metadata-only, read-only scan of every approved legacy root, both migration Git bundles, the active ClawAlpha worktree, external data/state/artifact directories, and migration manifests. It records file hashes without copying source content or personal financial data into Clausula.

The scan catalogued **10,874 files** totaling **5.94 GiB**.

## Source snapshots

| Source | Files | Size | Tree SHA-256 | Git state |
|---|---:|---:|---|---|
| `/home/altair/projects/clawalpha` | 1,782 | 711.4 MiB | `848edb81882eccc9…` | main@04868b303db4, dirty=561 |
| `/home/altair/data/clawalpha` | 493 | 1883.9 MiB | `2562b47e6a8a3578…` | n/a |
| `/home/altair/state/clawalpha` | 9 | 4.1 MiB | `ef12187f4dca420d…` | n/a |
| `/home/altair/artifacts/clawalpha` | 133 | 58.1 MiB | `ebce32383dd35069…` | n/a |
| `/home/altair/archive/clawalpha` | 8,042 | 545.4 MiB | `4f90fbb076a2c3f8…` | n/a |
| `/home/altair/migration` | 415 | 2883.6 MiB | `045fa7e3bed131cf…` | n/a |

## Classification

- `MIGRATE_AS_IS`: 35 files
- `MIGRATE_WITH_REWRITE`: 819 files
- `REFERENCE_ONLY`: 9,057 files
- `ARCHIVE`: 859 files
- `DELETE_CANDIDATE`: 104 files

## Binding findings

1. The active ClawAlpha worktree is heavily modified, so `HEAD`, worktree, and the history bundle are separate evidence sources.
2. The legacy Clausula bundle contains private portfolio snapshots and a script-oriented paper-trading system; it is not a valid new-domain baseline.
3. Existing canonical ETF Parquet is useful, but the observed raw store is insufficient to prove a full rebuild. The dataset must be imported as a versioned legacy artifact until reconstructed.
4. ClawAlpha reconciliation, immutable decision hashes, anti-lookahead tests, source spans, and evidence links are valuable contracts, but their implementations require domain rewrites.
5. Strategy, execution, Agent/MCP, cron, cache, and generated-output code must not enter the Clausula core dependency graph.

## Migration gate

No legacy implementation may be copied solely because it exists. A component may move only after its canonical Clausula contract, temporal semantics, provenance behavior, and acceptance tests are defined. Items marked `DELETE_CANDIDATE` are inventory decisions only; this scan deletes nothing.

Detailed component decisions and the complete file catalog are in `migration_inventory.yaml`; data summaries are in `data_asset_catalog.yaml`; reproducible root and bundle hashes are in `source_snapshot_manifest.yaml`.
