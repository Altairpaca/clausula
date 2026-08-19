# Dependency Rules

Clausula uses inward-only dependencies:

```text
domain <- application/services <- capabilities <- CLI / HTTP / MCP / scheduler
                      ^
                      |
              storage and source adapters
```

The current M1-M4 slice has these concrete boundaries:

- `clausula.domain` owns identity, temporal, Decimal, instrument, transaction,
  leg, reconciliation, market observation, portfolio membership, and investment
  policy contracts.
  It uses only the Python standard library.
- `clausula.application` owns canonical Ledger, Market import, Portfolio, and
  Policy operations, typed repository ports, transactional provenance, and
  deterministic replay. It does not construct a concrete adapter.
- `clausula.analytics` owns pure Decimal cost-basis, valuation, aggregation,
  TWR, XIRR, drawdown, Policy evaluation, and non-mutating simulation functions
  over canonical inputs.
- `clausula.capabilities` owns executable client contracts, permission/confirmation gates, and schema validation. It depends on application ports, never on SQLite.
- `clausula.adapters.sqlite` owns SQLite schema, migrations, append-only enforcement, raw filesystem storage, backup, and restore.
- `clausula.cli` and `clausula.sdk` are client projections over the Capability Registry. Direct SDK service methods are temporary convenience wrappers over the same service implementation.
- `clausula.models`, `clausula.services`, and `clausula.store` are temporary compatibility imports, not ownership locations.

Architectural tests parse imports from every module in `clausula.domain` and `clausula.application`. New outer layers must be added to the forbidden import list when introduced.

Canonical writes follow this path:

```text
external input -> adapter parsing -> application validation -> domain object -> storage port
```

Adapters, plugins, Agents, and clients may not issue arbitrary SQL against canonical tables. The concrete SQLite adapter remains public for local lifecycle control and diagnostics, but canonical writes are application/capability operations.
