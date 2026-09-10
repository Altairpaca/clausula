# Clausula Local Acceptance and First-Release Gate

This document starts where deterministic GitHub CI ends. Do not mark host-, OS-, private-data- or provider-dependent behavior complete from synthetic tests alone.

As of 2026-09-10, repository protection (#6) and the accounting v12 migration/corporate-action work (#21) are complete. The first stable tag is blocked principally on #23 and #34.

## 0. Baseline before local acceptance
Use a fresh checkout of protected `main` and preserve a clean evidence baseline:

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

Record commit SHA, Python version, OS, test result and build result. Never commit credentials, runtime databases, private research files or confidential provider payloads.

## 1. Completed gates retained as evidence

### #6 — protected main
The `protect-main` ruleset has been verified with real direct/force-push rejection. Pull requests and strict Python 3.12/3.13 CI are required; deletion/non-fast-forward updates are blocked. No further application work is required unless repository settings regress.

### #21 — accounting v12
Forward migration v12, historical identifier validity, point-in-time resolution and generalized corporate actions are implemented. Migration/rebuild/backup evidence exists and corporate-action replay received a follow-up correctness repair. Jurisdiction/broker tax interpretation remains explicit local configuration and must not be inferred by the generic engine.

## 2. #23 — real daemon/MCP/plugin host-runtime acceptance
Synthetic tests already cover server-side permission binding, replay-resistant confirmation, daemon lease behavior, audit continuity, MCP/plugin self-assertion denial, package discovery and host-policy authorization. PR #44 also implements a Linux `bwrap` subprocess runner. Local acceptance must prove the real host boundary.

### Multi-process daemon ownership
Use one disposable `CLAUSULA_HOME` and launch `clausula-daemon` independently. From separate processes: read through workspace/HTTP; invoke read-only capabilities with a read principal; perform a confirmed write through the intended Admin path; verify a second daemon is rejected; run concurrent client writes; verify serialization and a valid audit chain; verify clients do not open a second writable Store around the daemon contract.

### Concrete MCP transport
Connect the actual MCP runtime intended for use. Verify one authenticated daemon principal/profile is transport-bound; protocol payload cannot replace profile/actor identity; read profiles cannot write; Admin cannot bypass server-issued confirmation; reconnect behavior has expected identity/audit attribution.

### Crash/recovery
Inject termination after lease acquisition, after auth-manifest creation, during reads, around confirmed writes and during plugin execution. Restart and verify canonical SQLite validity, rollback of incomplete writes, audit continuity and actionable stale-runtime recovery.

### Plugin containment
Run the existing subprocess runner on the actual Linux host with bubblewrap available. Exercise undeclared network/filesystem/secret access, timeout, process crash, malformed output and network failure. Acceptance requires fail-closed behavior without partial canonical writes. HostPolicy authorization alone is not containment evidence.

### Platform support decision
If Windows is part of the first stable support matrix, validate lock/credential ACL and the supported transport boundary there. Otherwise explicitly defer Windows host-isolation guarantees rather than leaving the release gate ambiguous.

## 3. #34 — live provider, private corpus and target-machine evidence

### Market/provider
Use the provider(s) actually intended for the local deployment. Tencent CN-SH/HK live fetch already provides a useful acceptance subset; do not add providers merely for count. Still verify stale/missing/revised observations, provider failure, real identifier/security-change cases, and raw-payload/provenance semantics. Label benchmark/return series `price_return` or `total_return` only where provider documentation supports that interpretation.

### Private research corpus
Use representative local Markdown, HTML and PDFs, including at least one malformed/difficult document. Verify extraction reproducibility, page/section locator fidelity, source-span tracing and fail-closed malformed input. Private material stays outside public Git. If semantic/vector retrieval is evaluated, it remains a disposable index over immutable research nodes; deletion/rebuild must not mutate canonical research facts.

### Target-machine performance
Run:

```bash
python scripts/benchmark_reads.py --profile full
```

Record commit SHA, OS/CPU/Python/SQLite versions, setup/read wall time, SQL statement counts and observed memory if available. Treat these as comparative engineering evidence, not universal CI timing thresholds.

## 4. Final release-candidate gate
After #23 and #34 are complete, repeat the clean baseline and then run one end-to-end disposable-home scenario through the real daemon: import representative accounts and market state; reconstruct portfolio at explicit `as_of`/`known_as_of`; evaluate policy/headroom/capital envelope; ingest evidence; create/review a Recommendation and link a Decision; evaluate an execution-constrained Plan without order placement; restart the daemon and repeat reads; backup/export and restore/rebuild into a separate home; compare semantic state and audit evidence.

Only then finalize version/tag/release workflow. A green GitHub CI run alone is not sufficient evidence for the first stable release.

## 5. Evidence handoff format
For each remaining blockpoint record: issue number and tested commit SHA; OS/runtime/provider versions; commands/configuration with secrets redacted; pass/fail for each acceptance item; minimal relevant failure logs; code/config changes required; sanitized benchmark/result artifacts safe to attach or commit.

Bring only genuine host/data failures back into GitHub development. Do not substitute new AI/research features for closing the release boundary.
