# Clausula

Clausula is a local-first, deterministic investment decision system. It
provides versioned ledgers, portfolios, market data, investment policies,
planning, decision memory, and research evidence without making an LLM the
system of record.

## Principles

- Financial calculations use deterministic Python services and `Decimal`.
- Historical facts are append-only and retain source provenance.
- As-of queries distinguish `effective_at`, `known_at`, and `recorded_at`.
- Agent and MCP integrations are adapters, not domain layers.
- Version 0.x does not place brokerage orders autonomously.

## Status

The current implementation includes the kernel, ledger, market and portfolio
analytics, policy-as-code, deterministic planning, decision memory, and a
local research evidence graph. See
[`docs/project/STATUS.md`](docs/project/STATUS.md) for frozen milestones,
verification evidence, and known risks.

## Development

Requires Python 3.12 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
pytest -q
python -m compileall -q clausula tests scripts
git diff --check
```

The command-line entry point is `clausula`. Data and networked services are
local-first by design; do not place private financial data in this repository.

## License

MIT. See [`LICENSE`](LICENSE).
