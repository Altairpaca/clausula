# Market Query Fabric

Status: proposed subproject  
Tracking epic: #69  
Work packages: #70 #71 #72 #73 #74

## Mission

Market Query Fabric (MQF) gives Clausula one robust live-market query contract across fragmented CN/HK public/open-source data channels.

The primary user experience is a reliable query CLI with stable machine-readable output. Python/service, capability, MCP and agent Skill surfaces project the same service and schemas. No agent adapter owns unique market logic.

The first target is A-share and Hong Kong equities/ETFs, with particular emphasis on no-broker-account A-share ETF quote, five-level depth and recent trades, plus clearly qualified best-effort HK quotes.

## Why this is a Clausula subproject

Clausula already owns deterministic investment state, point-in-time market provenance, capability permissions, CLI projection and MCP adaptation. MQF fills the concrete live-provider gap without creating another truth system.

The boundary is intentional:

- MQF is a **live query plane**.
- Existing Clausula market datasets remain the **canonical persisted history plane**.
- Quote/depth/trade responses are ephemeral by default.
- Persisting a provider observation requires an explicit existing/new ingestion use case; a live query never becomes canonical history automatically.
- High-frequency/L2 data remains outside the core market store.
- v0.1 is read-only and has no brokerage/order capability.

This separation keeps the subsystem extractable later if its CLI/MCP contract gains independent users.

## Architecture

```text
mootdx / stock-api / Tencent / Sina / Eastmoney / Xueqiu / AKShare
                              │
                              ▼
                    provider adapters
                              │
                              ▼
                 canonical live schemas
                              │
                              ▼
          MarketQueryService + resilient router
              │          │            │
              │          │            └─ provider health / consensus
              │          └─ freshness / attempts / diagnostics
              └─ symbol normalization
                              │
             ┌────────────────┼────────────────┐
             ▼                ▼                ▼
          Python/SDK          CLI        capabilities
                                                │
                                                ▼
                                              MCP
                                                │
                                                ▼
                                              Skill
```

Dependency direction follows `AGENTS.md`: provider/network parsing belongs in adapters; canonical query contracts and routing behavior must not depend on MCP or an Agent SDK.

## Canonical contract

The initial public model family is:

- `InstrumentRef`
- `QuoteSnapshot`
- `OrderBookSnapshot`
- `TradePrint`
- `Bar`
- `ETFSnapshot`
- `ProviderAttempt`
- `ProviderHealth`
- `QueryMetadata`
- `ProviderConsensus`

Common rules:

1. Canonical symbols are provider-independent (`563360.SH`, `159905.SZ`, `02800.HK`).
2. Provider/raw symbols are retained as provenance, not used as public identity.
3. Money/price/quantity values follow Clausula deterministic decimal serialization.
4. Provider-observed, locally received and query timestamps are distinct when known.
5. Unsupported data is explicit; adapters do not invent missing depth/trade/timestamp fields.
6. Every successful fallback states the provider actually used.
7. Cross-provider disagreement is an output condition, not something the router silently erases.
8. Provider-native payload fragments may appear only in explicit diagnostics/raw namespaces and never become required stable public fields.

## Provider policy

Initial candidates:

| Provider/project | Primary role | Boundary |
| --- | --- | --- |
| `mootdx` | CN quote/depth/trades | preferred MIT candidate for no-account CN path |
| `stock-api` | A/HK quote/K-line and public-source fallback | MIT; normalize its own Tencent/Sina/Eastmoney fallback into MQF provenance |
| Tencent/Sina/Eastmoney | direct quote/K-line adapters when useful | public-web/best-effort; no SLA claim |
| Xueqiu | enrichment / independent cross-check | optional; best-effort |
| AKShare | breadth/research fallback | optional; not low-latency authority |
| `eltdx` | advanced CN research adapter | optional research-only; never vendored into MIT core |

M0/M1 (#70) owns the precise license/ToS and reuse decision before code is copied or vendored.

## Router behavior

The router is capability-aware and market-aware.

Required behavior:

- bounded timeout and retry budgets;
- fallback only to semantically compatible providers;
- explicit attempt trace and winning source;
- freshness/staleness labeling;
- temporary degradation/circuit state where it improves reliability;
- structured unsupported/partial/error results;
- deterministic symbol normalization;
- cross-provider comparison without false consensus;
- provider pinning for diagnostics without changing the result schema.

A provider being reachable does not mean its output is current. Freshness is part of the result contract.

## CLI

The intended first-class interface is:

```text
clausula market search <query>
clausula market quote <symbols...>
clausula market depth <symbol> [--levels 5]
clausula market trades <symbol> [--limit 100]
clausula market bars <symbol> --interval 1m --count 240
clausula market etf <symbol>
clausula market compare <symbol>
clausula market provider-health [provider]
```

Human output should be concise and diagnostic. `--json` emits the canonical contract directly. CLI logic must not diverge from Python/capability/MCP behavior.

## Capability, MCP and Skill exposure

MQF capabilities are read-only:

- `market.search_instrument`
- `market.quote`
- `market.depth`
- `market.trades`
- `market.bars`
- `market.etf_snapshot`
- `market.compare_providers`
- `market.provider_health`

The existing Clausula MCP adapter should discover these from the capability registry. Input/output schema must come from the same shared models used by the CLI/service layer rather than be maintained manually in a second schema definition.

The repository-owned Market Query Skill teaches agent clients when to invoke each capability and how to qualify source/freshness. It must explicitly prevent two common errors:

- presenting best-effort HK public-web data as exchange-licensed HKEX L1;
- treating a read-only query result as evidence that a trade was placed or executed.

## Acceptance universe

Core live acceptance should include:

- `563360.SH` — A500 ETF
- `515450.SH` — dividend ETF
- `159905.SZ` — Shenzhen dividend ETF
- `510300.SH` — CSI 300 ETF
- `02800.HK` — Tracker Fund of Hong Kong
- one liquid CN equity
- one liquid HK equity

CN acceptance targets current quote, five-level depth and recent trades from a no-broker-account path. HK v0.1 targets robust best-effort quote with honest source/freshness/entitlement semantics.

## Test strategy

Deterministic CI and live-provider acceptance are separate evidence classes.

### Deterministic CI

- schema snapshots;
- symbol normalization;
- captured/redistributable provider parser fixtures;
- timeout/retry/fallback state machines;
- disagreement/consensus calculations;
- CLI/MCP semantic equivalence with injected service results;
- permission/read-only checks;
- Skill tool-selection fixtures.

### Live acceptance

- exact commit/provider versions;
- test time/timezone;
- quote/depth/trade/bar sanity and ordering;
- deliberate preferred-provider failure to exercise fallback;
- cross-provider price/timestamp deviation;
- stale/out-of-session behavior;
- deployment `initialize` / `tools/list` / `tools/call` smoke test.

Live measurements are evidence, not permanent SLA guarantees.

## Milestones

- **M0–M1 #70** — source/license audit, canonical schema, provider protocol.
- **M2 #71** — provider adapters, resilient routing, freshness and consensus.
- **M3 #72** — robust query CLI and JSON diagnostics.
- **M4 #73** — capability registry, MCP tools and repository-owned Skill.
- **M5 #74** — real CN/HK acceptance, CI evidence and read-only MCP deployment.

## Extraction criteria

MQF should become a standalone package/repository only if at least one of these becomes true:

1. non-Clausula consumers need the CLI/MCP contract;
2. provider dependency cadence materially differs from Clausula core releases;
3. packaging provider extras inside Clausula creates dependency or licensing friction;
4. the canonical live-query contract becomes useful independently of portfolio/accounting state.

Until then, keeping MQF in Clausula avoids a second project boundary while preserving an explicit extraction seam.

## Non-goals for v0.1

- brokerage execution;
- licensed data redistribution;
- HKEX depth without an entitled source;
- tick-history/HFT storage;
- persistence of every live observation;
- provider-specific schemas exposed to agents;
- claims of real-time/SLA quality that the underlying public sources do not guarantee.
