# Clausula Implementation Plan

- Planning horizon: current M4 worktree through M12 Public Beta
- Method: contract-first vertical slices with milestone freeze gates
- Source of truth for current state: `docs/project/STATUS.md`

## Standard Milestone Loop

Every milestone follows the same loop:

```text
Scope and semantic contracts
-> domain objects and state transitions
-> pure deterministic logic
-> repository ports and migrations
-> application services and provenance
-> capability registry
-> CLI / SDK / HTTP / MCP projections as applicable
-> unit / temporal / property / contract / migration / E2E tests
-> semantic and architecture audit
-> remediation and full regression
-> wheel/client smoke
-> ADR and reference docs
-> one clean milestone commit
```

A milestone is not frozen because tables or classes exist. Freeze requires:

- acceptance stories pass end to end;
- no known violation of AGENTS.md invariants;
- all canonical writes have provenance and permission boundaries;
- as-of semantics have adversarial tests;
- backup/export/rebuild implications are covered;
- full test suite, compile, diff check and package smoke pass;
- residual risks and non-goals are documented;
- work is committed independently from the next milestone.

## Immediate Plan: Finish M4 Policy

### 1. Restore Green Baseline

Update only the stale migration expectations for v6, then run full regression. Do not treat this as M4
completion; it only restores accurate infrastructure tests.

### 2. Semantic Audit

Lock the following decisions before widening interfaces:

- Policy belongs to exactly one Portfolio; Account is not Policy ownership.
- Policy is stable identity; PolicyVersion is append-only and immutable.
- Version selection uses `effective_from <= as_of` and `known_at <= known_as_of`.
- A backdated version learned later changes fixed-vintage analysis only after its knowledge time.
- `hard` and `soft` affect severity/reporting, not whether arithmetic is deterministic.
- Incomplete valuation makes the whole evaluation `unavailable`; it never implies compliance.
- Weight thresholds are Decimal values in `[0, 1]`; amount thresholds use portfolio base currency.
- Simulation is an analytical artifact, never a Ledger mutation or Recommendation.
- Initial simulation supports base-currency cash funding only and states that limitation in output.
- Rule definitions use a fixed versioned schema, not an open-ended DSL or executable expressions.

Audit current `_rules` implementation for duplicate object construction and define whether rule IDs must be
preserved in raw envelopes. Preferred outcome: one normalization pass creates rule IDs, the event envelope
records those IDs, and clean rebuild preserves semantic mapping while allowing target UUID remapping.

### 3. Persistence and Provenance

Complete migration v6 and repository contracts for:

```text
InvestmentPolicy
PolicyVersion
PolicyRule
```

Add read queries for list/history/as-of. Preserve formal columns for stable fields; do not move thresholds
into generic JSON. Raw event envelopes record operation, source IDs, all three times, normalized rules,
schema version and checksum.

Decide unit-of-work behavior. At minimum, validation errors must occur before raw/import writes. Prefer a
repository operation that atomically stores artifact metadata, import metadata and canonical policy rows,
while the content-addressed file can safely pre-exist.

### 4. Evaluation and Simulator Tests

Required tests:

- each initial rule type at boundary, just inside and just outside threshold;
- Decimal canonical output and float rejection;
- hard/soft structured violations;
- missing subject is interpreted as zero exposure only when valuation is complete;
- incomplete valuation produces unavailable;
- multi-account portfolio aggregation;
- knowledge-time anti-lookahead for PolicyVersion and market/ledger inputs;
- deterministic evaluation ID for identical facts and versions;
- simulation buy, sell, fee, insufficient cash, oversell, unknown instrument and zero-total edge cases;
- simulation never changes transaction count, state or audit chain;
- provider conflict propagates rather than selecting data silently.

### 5. Capability and Clients

Add canonical capabilities:

```text
policy.create
policy.add_version
policy.list
policy.evaluate
policy.simulate
```

Writes require `policy:write` and confirmation; reads/simulation require `policy:read` plus portfolio/market
read permissions as appropriate. `policy.simulate` is a deterministic local read despite returning a
hypothetical artifact. CLI reads rules/actions from JSON files or JSON text without duplicating business
logic. SDK methods invoke the same registry.

### 6. Rebuild, Backup and Audit

Teach clean rebuild to replay policy create/version envelopes after Portfolio mappings are known. Return
policy and version ID maps and compare version numbers, times, checksums and normalized rules. Add verified
backup round-trip tests. Ensure canonical export includes all v6 tables and audit events cover writes.

### 7. M4 Freeze

Write ADR 0005 covering Policy ownership, temporal versioning, fail-closed evaluation, rule schema,
hard/soft semantics and simulator non-mutation. Update capability mapping and status. Run:

```bash
pytest -q
python -m compileall -q clausula tests scripts
git diff --check
python -m pip wheel . --no-deps -w /tmp/clausula-wheel-m4
```

Install the wheel into a temporary venv and smoke `policy.create/evaluate/simulate` through the installed
CLI. Commit M4 separately.

## M4.5 Planning and Cash Allocation

Build deterministic Planning after Policy freezes. Planning does not predict markets.

Scope:

- cash reserve calculation;
- new capital allocator;
- allocation/rebalance gaps;
- target contribution plan;
- scenario comparison;
- explicit fee/tax estimates and unresolved violations.

Entities/artifacts: `Plan`, `PlanScenario`, `CandidateAction`, `ProjectedState`, `UnresolvedConstraint`.
Plan is not Recommendation, Decision or Transaction. Acceptance: given cash and a PolicyVersion, multiple
candidate allocations can be compared without writing Ledger and each output explains constraint tradeoffs.

## M5 Decision Intelligence

Implement ontology before UI:

```text
Decision
DecisionIntent
Alternative
Assumption
ExpectedOutcome
InvalidationCondition
DecisionEvidenceLink
DecisionPolicyLink
DecisionTransactionLink
DecisionReview
```

State and ownership rules:

- “do nothing” is a valid Decision;
- Decision references the PortfolioSnapshot and PolicyVersion known at decision time;
- linking a later Transaction appends a link and never rewrites Decision rationale;
- Review separates process quality from outcome quality;
- scheduled 30d/90d/custom reviews are explicit records;
- Agent may draft rationale/review but may not create canonical Transaction.

Acceptance story: create a non-trade and a trade-related Decision, link evidence/policy, later link an actual
transaction, then review process and outcome separately through capability and CLI.

## M6 Research and Evidence Graph

### Ingestion

Filesystem/PDF/text/web snapshot becomes immutable `ResearchDocument` plus source metadata and searchable
text. Original bytes remain. Parsing is an adapter artifact, not replacement for source.

### Structured Knowledge

Implement `ResearchSource`, `Claim`, `Evidence`, `Contradiction`, `ResearchLink`, `Thesis`, and
`ThesisRevision`. Claim stores exact source span, generated_by metadata and confidence when machine
generated. Thesis changes append revision proposals.

### Retrieval

Start with deterministic metadata/full-text search. Vector search is an optional retrieval implementation,
not a domain entity. Support bidirectional queries across Document, Thesis, Recommendation, Decision and
Transaction.

Acceptance: ingest one document, preserve bytes/hash, add supporting and contradicting claims with spans,
revise a thesis without overwriting history, and trace both directions to a Decision.

## M7 Platform: Registry, CLI, SDK and HTTP

Expand Capability Registry metadata to all namespaces and add invocation audit context. Generate or share
typed request/response contracts across Python, CLI and HTTP. FastAPI/Pydantic may exist at transport edge
but cannot become domain ownership.

Every write distinguishes dry-run, commit and confirmation. Contract tests compare semantic output through
Python, CLI and HTTP. Add system diagnostics, data provenance inspection and export workflows.

## M8 Capital Cockpit

Build the actual local-first product, not a landing page. Initial pages:

```text
Overview      capital state, attention, pending reviews
Accounts      cash, history, reconciliation
Portfolio     positions, returns, concentration, benchmark
Allocation    current/target/gap and simulator
Policy        editor, versions, evaluations, violations
Decisions     table, detail, links, review
Research      documents, claims, theses, graph
Recommendations drafts and lifecycle
Data          imports, datasets, quality, provenance
Plugins       manifests, permissions, health
Settings      storage, backup, security, agents
```

Use dense, work-focused layouts. Decision and Research need table/filter/group workflows. No Agent chat as
primary navigation. Run browser E2E and screenshots at desktop/mobile sizes before freeze.

## M9 Plugin SDK

Define public manifests and bridges for DataSource, Analytics, Research, Policy and Action plugins. Manifest
declares capabilities, permissions, network, filesystem scope, secrets, side effects and compatibility.
Plugins receive no arbitrary SQL. Include minimal provider and analytics examples plus conformance tests.

## M10 MCP and Agent Adapters

Project Capability Registry into MCP after platform contracts stabilize. Permission profiles include
research-only, portfolio-read-only, advisor and admin. Each invocation records agent identity, capability,
input summary, output reference, duration, side effect and confirmation.

Compatibility tests use a generic MCP client and validate discoverability, schema, permissions and
structured results, not model prose. v0.x allows deterministic reads, assisted extraction and draft
recommendations; autonomous brokerage action remains disabled.

## M11 Intelligence and Attention

### Recommendation

Implement first-class `Recommendation`, alternatives, evidence, policy references and lifecycle:

```text
DRAFT -> REVIEWED -> ACCEPTED | REJECTED | EXPIRED
```

Agent defaults to DRAFT. ACCEPTED may create a Decision draft, never a Transaction. Preserve facts,
assumptions, risks, confidence, invalidation conditions, capability call lineage and origin `RULE|AGENT`.

### Attention Automation

Implement explicit event rules, cooldown, severity and notification behavior. No material change means no
recommendation and no notification. Contextual Agent actions consume explicit page/context objects and
return structured artifacts.

## M12 Public Beta

Public Beta requires:

- complete install/upgrade/uninstall documentation;
- deterministic demo portfolio with no private data;
- verified backup, restore, export and migration rehearsals;
- local secrets isolation and least-privilege tokens;
- append-only/tamper-evident audit coverage for sensitive writes;
- legacy ClawAlpha ETL reports with mappings, warnings, unresolved identifiers and reconciliation;
- example plugins and generic Agent client;
- user manual, Domain Reference, Capability Reference, Plugin SDK and ADR index;
- full end-to-end acceptance story from import through review;
- release candidate from a clean worktree and reproducible wheel.

## Data Pipeline Plan

### Canonical Ingestion

```text
source bytes
-> immutable content-addressed SourceArtifact
-> adapter parser with versioned schema
-> validated intermediate records
-> ImportBatch and transformation metadata
-> canonical append-only facts
-> reconciliation and quality report
-> versioned analytical artifacts
```

No adapter may write arbitrary canonical tables. Duplicate source/version is idempotent; same version with
different manifest is a conflict. Provider disagreements remain visible.

### Storage

- SQLite: transactional canonical domain records and indexes.
- Parquet: larger market series and derived analytical datasets when CSV/SQLite scale is insufficient.
- Filesystem: raw broker exports, PDFs, snapshots, immutable event envelopes and artifacts.
- Cache: disposable and never required to reconstruct truth.

### Legacy ETL

Do not run old runtime as a dependency. Use:

```text
old raw/schema -> validated intermediate -> Clausula objects -> warnings/reconciliation report
```

Migrate the legacy daily ETF canonical dataset first as a hash-pinned legacy dataset. Rewrite identifier
registry around UUID plus historical identifiers. Keep high-frequency/L2/factor/backtest material in
Research Lab or archive and import only evidence/artifacts into Core.

## Security, Observability and Explainability

Cross-cutting work runs every milestone:

- default local storage; OS keychain/secret backend separated from business DB;
- permissions such as `portfolio:read`, `ledger:write`, `policy:write`,
  `recommendation:create`, `decision:create`, `action:*`;
- minimum Agent permissions: read plus draft creation;
- audit every sensitive canonical write and Agent invocation;
- analytical artifacts retain input versions and method version;
- PolicyEvaluation retains PolicyVersion and valuation provenance;
- a transport-neutral TraceContext may be introduced without importing observability SDKs into domain;
- every UI number must be traceable to facts, datasets and calculations.

## Commit Discipline

- Never mix a frozen milestone with initial code from the next milestone.
- Do not amend v1-v5 migration SQL; create forward migration unless the migration is still unfrozen.
- Stage only task-owned files; preserve unrelated/untracked user changes.
- Commit message names the completed vertical slice, not an aspirational phase.
- Before commit, inspect `git diff --check`, `git status --short`, full tests, package smoke and docs.
- After commit, record the hash and acceptance evidence in `STATUS.md` before starting the next phase.
