# Clausula

Clausula is a local-first, deterministic investment decision system. It combines versioned ledgers, market and portfolio state, policy-as-code, planning, decision memory, research evidence, recommendations and material-attention tracking without making an LLM the system of record.

<p align="center">
  <img src="docs/assets/system-map.svg" alt="Clausula deterministic investment decision system map" width="96%">
</p>

## Why Clausula

- Financial calculations use deterministic Python services and `Decimal`.
- Historical facts are append-only and retain source provenance.
- As-of queries distinguish `effective_at`, `known_at`, and `recorded_at` so look-ahead is explicit.
- Capital state, policy boundaries, evidence, recommendations, decisions, execution constraints and reviews remain distinct concepts.
- CLI, workspace, HTTP, MCP, plugin and agent surfaces project the same deterministic application state rather than owning financial truth.
- Version 0.x does not place brokerage orders autonomously.

## Quick start

Requires Python 3.12 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[research]"

clausula capability list
clausula system check
clausula account create DemoInstitution "Paper Account"

# Preferred local owner: starts the loopback daemon and Capital Cockpit.
clausula-daemon
```

`clausula-workspace` remains a compatibility entry point and routes through the same daemon path. The daemon owns local write serialization, server-side principal permissions and request-bound confirmation state. Its generated `daemon-auth.json` is sensitive ephemeral runtime state and must not be committed.

The Capital Cockpit is decision-first: `as_of` and `known_as_of` remain visible, and the read model composes valuation completeness, allocation/concentration, reserve/deployable cash, policy headroom, execution constraints, plans, attention, evidence pressure, recommendations, decisions and review lineage. Anonymous workspace projection is read-only; capability invocation requires a daemon-issued local bearer principal.

## Architecture

| Layer | Responsibility |
| --- | --- |
| `clausula/domain` | immutable domain types and temporal contracts |
| `clausula/application` | deterministic use cases and repository ports |
| `clausula/analytics` | portfolio, policy, planning, performance and accounting calculations |
| `clausula/adapters` | SQLite, backup, audit, migrations, market/accounting projections and MCP |
| `clausula/capabilities` | permissioned capability registry shared by integration surfaces |
| `clausula/plugins` | plugin manifest, discovery and host-policy authorization contracts |
| `clausula/api`, `clausula/ui`, `cli.py`, `sdk.py` | daemon, local HTTP/workspace, CLI and Python projections |

Research ingestion supports local text/Markdown/HTML/PDF plus stateless web capture with source maps and provenance. Market provider snapshot and benchmark-return contracts are implemented, while real provider/corpus acceptance remains deliberately outside synthetic CI.

See [`docs/project/STATUS.md`](docs/project/STATUS.md) for implementation status and [`docs/project/LOCAL_ACCEPTANCE.md`](docs/project/LOCAL_ACCEPTANCE.md) for the remaining release gates.

## Verification

```bash
python -m pytest -q
python -m compileall -q clausula tests
python -m build
git diff --check
```

## Security and release boundary

Clausula is local-first. Runtime financial data, databases, backups, raw private research, agent state, tool configuration and credentials do not belong in this repository. Loopback bearer authentication is a local integration boundary, not an internet-facing TLS or multi-tenant security contract. Plugin host policy is authorization preflight, not an OS sandbox. See [`SECURITY.md`](SECURITY.md).

There is intentionally no stable release tag yet. The first tagged release is gated on repository protection plus the forward-migration, host-runtime and real-data acceptance work tracked in #6, #21, #23 and #34.

## License

MIT. See [`LICENSE`](LICENSE).
