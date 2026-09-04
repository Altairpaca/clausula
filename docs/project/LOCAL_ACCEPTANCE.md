# Clausula Local Acceptance and First-Release Gate

This document starts where GitHub-testable implementation ends. Do not mark an item complete from synthetic CI alone when the acceptance criterion depends on repository settings, the target operating system, a real multi-process runtime, private/local data, external providers or a new forward migration.

The first tagged release is blocked until #6, #21, #23 and #34 are either completed or deliberately removed from the release scope with an explicit rationale.

## 0. Baseline before local work

Use a fresh checkout of protected/current `main` and preserve a clean baseline:

```bash
git fetch --all --prune
git switch main
git pull --ff-only
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e ".[research]"
python -m pip install pytest build
python -m pytest -q
python -m compileall -q clausula tests
python -m build
git diff --check
git status --short
```

Required evidence: baseline commit SHA, Python version, OS, test result and build result. Do not commit local credentials, databases, private corpus files or provider payloads containing confidential information.

## 1. #6 — Protect `main` and require CI

This is a GitHub repository-setting task, not application code.

Required configuration:

- require pull requests before merge;
- require the current CI checks before merge;
- require an up-to-date branch where practical;
- block force pushes and branch deletion;
- avoid routine maintainer bypass;
- keep GitHub Actions permissions least-privilege.

Acceptance must test the rule rather than only inspect the UI:

1. create a disposable branch/PR and confirm a green PR can merge through the normal path;
2. attempt a direct push to `main` and confirm rejection;
3. attempt a non-fast-forward/force update to `main` and confirm rejection;
4. verify branch deletion protection;
5. record the active ruleset/protection JSON or screenshots in a sanitized engineering note.

Do not weaken the rule merely to make the acceptance test pass.

## 2. #21 — Forward migration for durable accounting identity/actions

This item requires local source editing because the existing migration ledger is checksum-frozen and the remaining work is schema-dependent.

Implementation rules:

- never edit frozen historical migrations/checksums in place;
- add one or more forward migrations through the existing migration mechanism;
- preserve rebuild/export/backup semantics;
- preserve effective-time and knowledge-time semantics;
- do not encode HK/CN/US tax law as global defaults.

Required scope before closing #21:

- historical instrument identifier validity ranges;
- point-in-time identifier resolution;
- generalized corporate actions needed by the release scope: merger, spin-off, exchange/election, symbol/security change and cash-in-lieu;
- explicit basis allocation and generated fee/tax facts where applicable;
- canonical specific-lot selection facts if specific identification is enabled;
- reviewed local jurisdiction/broker tax-profile configuration rather than inferred tax behavior.

Required tests:

- migrate an existing pre-migration database forward without rewriting old facts;
- clean database migration reaches the same schema;
- old identifier resolves before a change and new identifier resolves only when valid/known;
- corporate actions preserve quantity/value/basis invariants for representative long and short positions where supported;
- rebuild/export/backup round trip preserves new facts;
- audit chain remains valid.

After implementation, push a normal PR and let GitHub CI review the resulting forward migration and regression suite.

## 3. #23 — Real daemon/MCP/plugin host-runtime acceptance

Synthetic unit tests already cover server-side permission binding, replay-resistant confirmation, daemon lease behavior, audit continuity, MCP/plugin self-assertion denial, package discovery and host-policy preflight. Local acceptance must test what CI cannot represent faithfully.

### Multi-process daemon ownership

Use one disposable `CLAUSULA_HOME` and launch `clausula-daemon` as an independent process. From separate processes:

- read through the workspace/HTTP surface;
- invoke read-only capability clients with a read principal;
- invoke confirmed writes with the intended Admin path;
- attempt to start a second daemon against the same home and confirm rejection;
- run concurrent independent client writes and verify serialization plus a valid final audit chain;
- verify no client opens a second writable Store path around the daemon contract.

### Concrete MCP transport

Connect the actual MCP client/runtime intended for use, not an in-process adapter fixture.

Verify:

- transport/configuration binds one authenticated daemon principal/profile;
- protocol payload cannot replace profile/actor identity;
- read profile cannot invoke a write capability;
- Admin still cannot bypass server-issued confirmation;
- disconnect/reconnect creates the expected session identity behavior and audit attribution.

### OS credential/transport boundary

On POSIX, validate owner-only permissions for `CLAUSULA_HOME` and `daemon-auth.json`; if Unix-domain sockets are adopted, verify socket ownership/mode and denial from an unauthorized local user/context. On Windows, validate the supported lock plus named-pipe/file ACL equivalent if Windows is in release scope.

Loopback HTTP may remain the portable fallback, but do not represent loopback alone as multi-user OS isolation.

### Crash and recovery

Inject termination at adverse points:

- after daemon lease acquisition;
- after auth manifest creation;
- during a read;
- before/inside/after a confirmed write;
- during plugin execution.

Restart and verify:

- canonical SQLite state is valid;
- incomplete writes roll back rather than partially commit;
- audit chain remains continuous/valid;
- stale lock/auth runtime state is recovered or fails with an actionable error;
- a new daemon can eventually become the single owner without manual database surgery.

### Plugin runtime isolation

Run a real disposable plugin subprocess and enforce, at the host layer, the manifest/HostPolicy-approved envelope.

Inject:

- undeclared network destination;
- undeclared filesystem path;
- unavailable/undeclared secret;
- timeout;
- process crash;
- malformed output;
- network failure during a request.

Acceptance requires the plugin to fail without corrupting or partially committing canonical financial state. Record the enforcement mechanism actually used; `HostPolicy.authorize()` by itself is preflight, not sandbox evidence.

## 4. #34 — Live provider, private corpus and target-machine evidence

### Market/provider

Select the actual provider adapter(s) used by the local deployment and verify from provider documentation plus captured data:

- raw payload is captured before canonical conversion;
- `observed_at`, `known_at`, `recorded_at`, dataset version and quality have defensible semantics;
- stale, missing and revised observations behave explicitly;
- provider/network failure fails cleanly;
- real identifiers resolve correctly after #21;
- return index is labelled `price_return` or `total_return` only when the provider's definition supports that label.

Do not infer total-return semantics from a price series name.

### Private research corpus

Use a representative local corpus containing Markdown, HTML and PDFs, including at least one malformed or difficult document. Verify:

- extraction reproducibility;
- page/section locator fidelity;
- span tracing back to the source;
- malformed input fails without creating misleading canonical research state;
- private raw material stays outside public Git.

If semantic/vector retrieval is desired, benchmark candidate engines as disposable derived indexes over immutable research nodes. Index deletion/rebuild must not mutate canonical financial or research facts.

### Target-machine performance

Run:

```bash
python scripts/benchmark_reads.py --profile full
```

Record at minimum:

- commit SHA;
- OS / CPU / Python / SQLite version;
- setup time;
- read wall time;
- SQL statement counts;
- peak/observed memory if available.

Use the result as comparative engineering evidence, not as a universal millisecond CI threshold.

## 5. Final release candidate gate

After #6/#21/#23/#34 are complete:

```bash
git switch main
git pull --ff-only
python -m pytest -q
python -m compileall -q clausula tests
python -m build
git diff --check
git status --short
```

Then perform one end-to-end disposable-home scenario through the real daemon:

1. initialize/import representative accounts and market state;
2. reconstruct portfolio state at explicit `as_of` / `known_as_of` cutoffs;
3. evaluate policy/headroom and capital envelope;
4. ingest representative evidence;
5. create/review a recommendation and link a decision;
6. evaluate an execution-constrained plan without autonomous brokerage execution;
7. close/restart the daemon and repeat read verification;
8. backup/export, restore/rebuild into a separate home and compare semantic state/audit evidence.

Only after the release candidate passes should the version/tag/release workflow be finalized. Do not create a stable tag solely because GitHub CI is green.

## Evidence handoff format

For each local blockpoint, return a compact report containing:

- issue number and tested commit SHA;
- OS/runtime/provider versions;
- exact commands or configuration used, with secrets redacted;
- pass/fail per acceptance item;
- failing logs reduced to the relevant error/context;
- code/config changes required to resolve failures;
- sanitized benchmark/result artifacts that are safe to commit or attach.

The goal is to bring only genuine host/data failures back into GitHub development, rather than repeating work already proven by deterministic CI.
