# Dependency Rules

Clausula uses inward-only dependencies:

```text
domain <- application/services <- capabilities <- CLI / HTTP / MCP / scheduler
                      ^
                      |
              storage and source adapters
```

The current M1/M2 slice has these concrete boundaries:

- `clausula.domain` owns identity, temporal, Decimal, instrument, transaction, leg, and reconciliation contracts. It uses only the Python standard library.
- `clausula.application` owns canonical Ledger write operations and deterministic replay. It accepts a storage port by behavior and does not construct a concrete adapter.
- `clausula.adapters.sqlite` owns SQLite schema, migrations, append-only enforcement, raw filesystem storage, backup, and restore.
- `clausula.cli` and `clausula.sdk` are client projections over application services.
- `clausula.models`, `clausula.services`, and `clausula.store` are temporary compatibility imports, not ownership locations.

Architectural tests parse imports from every module in `clausula.domain` and `clausula.application`. New outer layers must be added to the forbidden import list when introduced.

Canonical writes follow this path:

```text
external input -> adapter parsing -> application validation -> domain object -> storage port
```

Adapters, plugins, Agents, and clients may not issue arbitrary SQL against canonical tables. The concrete SQLite adapter is currently public only because the early SDK and tests still need lifecycle control; narrowing that surface is an M1 follow-up.
