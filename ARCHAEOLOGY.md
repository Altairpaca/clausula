# Clausula Capability Archaeology

Generated: `2026-08-19T05:27:45+00:00`

## Scope and method

M0 performed a metadata-only, read-only scan of approved legacy code, data, state, artifacts, archives, and migration bundles. The scan was used to decide what could be migrated as-is, what required semantic rewrites, and what had to remain reference-only or archived.

The complete per-file inventory, local filesystem locations, private Git refs, worktree names, and raw legacy metadata are intentionally retained outside the public repository. Public Git contains only logical source names, aggregate counts/sizes, and integrity hashes needed to explain the migration boundary.

## Public source snapshots

| Source | Files | Size | Tree SHA-256 |
| --- | ---: | ---: | --- |
| `clawalpha_repository` | 1,782 | 711.4 MiB | `848edb81882eccc9…` |
| `clawalpha_data` | 493 | 1883.9 MiB | `2562b47e6a8a3578…` |
| `clawalpha_state` | 9 | 4.1 MiB | `ef12187f4dca420d…` |
| `clawalpha_artifacts` | 133 | 58.1 MiB | `ebce32383dd35069…` |
| `clawalpha_archive` | 8,042 | 545.4 MiB | `4f90fbb076a2c3f8…` |
| `migration` | 415 | 2883.6 MiB | `045fa7e3bed131cf…` |

## Binding findings

1. Legacy code, worktree state, and history bundles were treated as separate evidence sources; none is a canonical Clausula dependency.
2. Legacy portfolio snapshots and research state contain private material and remain local-only.
3. Existing canonical market datasets can be useful as versioned legacy artifacts after hash/schema validation, but they do not prove reconstructability from raw sources.
4. Reconciliation, immutable decision hashes, anti-lookahead tests, source spans, and evidence links are useful contracts; their implementations require domain-level rewrites before entering Clausula.
5. Strategy, execution, Agent/MCP, scheduler, cache, and generated-output code do not enter the Clausula core dependency graph.

## Migration gate

No legacy implementation may be copied solely because it exists. A component moves only after its Clausula contract, temporal semantics, provenance behavior, and acceptance tests are defined. The public summaries are:

- `migration_inventory.yaml` — logical source/classification contract only;
- `data_asset_catalog.yaml` — public asset classes and migration decisions only;
- `source_snapshot_manifest.yaml` — aggregate counts, sizes, and integrity hashes only;
- `capability_mapping.yaml` — mapping between legacy responsibilities and Clausula capabilities.

The local scanner that produced the original detailed inventory is deliberately excluded from the public tree because its configuration and output encode private workstation and legacy-repository metadata.
