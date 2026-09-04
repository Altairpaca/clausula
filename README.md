# Clausula

Clausula is a local-first, deterministic investment decision system. It provides versioned ledgers, portfolios, market data, investment policies, planning, decision memory, and research evidence without making an LLM the system of record.

## Why Clausula

- Financial calculations use deterministic Python services and `Decimal`.
- Historical facts are append-only and retain source provenance.
- As-of queries distinguish `effective_at`, `known_at`, and `recorded_at` to make look-ahead explicit.
- Agent, MCP, HTTP, CLI, and SDK surfaces project the same capability registry instead of owning financial state.
- Version 0.x does not place brokerage orders autonomously.

## Quick start

Requires Python 3.12 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .

# Inspect the capability surface and validate local state.
clausula capability list
clausula system check

# Create a local account; commands return structured JSON.
clausula account create DemoInstitution "Paper Account"
```

Run the verification suite before changing domain or persistence contracts:

```bash
python -m pytest -q
python -m compileall -q clausula tests
git diff --check
```

## Architecture

| Layer | Responsibility |
| --- | --- |
| `clausula/domain` | immutable domain types and contracts |
| `clausula/application` | deterministic use cases and repository ports |
| `clausula/analytics` | portfolio, policy, planning, performance and cost-basis calculations |
| `clausula/adapters` | SQLite, backup, audit, migrations and MCP projections |
| `clausula/capabilities` | permissioned capability registry shared by external surfaces |
| `clausula/api`, `cli.py`, `sdk.py` | HTTP, CLI and Python projections |

The current implementation includes the kernel, ledger, market and portfolio analytics, policy-as-code, deterministic planning, decision memory, and a local research evidence graph. See [`docs/project/STATUS.md`](docs/project/STATUS.md) for frozen milestones, verification evidence, deferred capabilities, and known risks.

## Security and data boundary

Clausula is local-first. Runtime financial data, databases, backups, agent state, tool configuration, and credentials do not belong in this repository. The 0.x HTTP and MCP projections are integration adapters rather than authenticated remote-service boundaries; keep them local or place an authenticated gateway in front of them. See [`SECURITY.md`](SECURITY.md) before exposing any service outside the host.

## License

MIT. See [`LICENSE`](LICENSE).
