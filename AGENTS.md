# Clausula Engineering Constraints

## Product invariants

- Agent runtimes are never the system of record. Canonical Ledger, Portfolio, Policy, Decision, and Research data belongs to Clausula.
- MCP is an adapter, never a domain layer. No business capability may exist only in an MCP server.
- Every capability must be executable without an Agent through Python/services and projectable to at least one client adapter.
- Financial correctness is deterministic. Ledger, holdings, returns, allocation, and policy evaluation never require an LLM.
- LLM output cannot directly mutate canonical financial truth. It may create drafts and proposals that explicit service operations validate.
- Raw inputs are immutable and traceable through a source artifact, import batch, transformation version, and content hash.
- Temporal semantics are explicit: `effective_at`, `known_at`, and `recorded_at` have distinct meanings. As-of queries exclude facts known after the cutoff.
- Proposal, Recommendation, Decision, and Transaction are distinct entities and lifecycle stages.
- Research is evidence, not canonical financial truth. Contradictory claims are valid when provenance is retained.
- Plugins cannot bypass domain rules or gain arbitrary canonical database access.
- Private data is local-first. Networked or hosted services are optional enhancements.
- Domain models, schemas, and canonical capabilities are Agent-agnostic and contain no runtime-specific concepts.
- v0.x does not autonomously place brokerage orders. Action capabilities and permissions may be reserved but not activated.
- Data resolution follows decision resolution. High-frequency and L2 data stay outside the core market store.
- Correct domain design outranks compatibility with ClawAlpha. Legacy assets migrate only through validated contracts.

## Engineering rules

- Dependencies point inward: `domain <- application/capabilities <- adapters/clients`.
- Domain code imports no web, API, MCP, Agent SDK, storage adapter, or specific provider.
- Financial facts are append-only. Corrections are compensating records and never overwrite source facts.
- Money, quantity, fee, tax, and FX values use `Decimal`; canonical persistence and API serialization use decimal strings. Binary floating point is forbidden.
- Internal identifiers are UUIDs. Tickers, broker codes, and natural keys are external identifiers only.
- Adapters parse external inputs; application services are the only write path to canonical financial truth.

## Working commands

```bash
pytest -q
python -m compileall -q clausula tests scripts
git diff --check
```

Before implementing a milestone, read the current ADRs, domain references, capability mapping, migration inventory, and milestone acceptance criteria. A milestone is complete only after deterministic tests, semantic and architecture audit, remediation, and regression.
