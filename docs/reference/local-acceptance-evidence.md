# Local acceptance evidence

Clausula local acceptance produces derived engineering evidence for release gates that cannot be proven by synthetic GitHub CI. Evidence files are not canonical financial, market, decision or research state and must never contain secrets or private corpus contents.

## Envelope

Format `clausula-local-acceptance/v1` separates the object being tested from the evidence about the test:

- `subject.repository_commit` binds the report to one exact source revision;
- `subject.artifacts` may bind sanitized outputs such as canonical exports by SHA-256;
- `predicate.gate` and `predicate.profile` identify the release acceptance scope;
- `predicate.environment` records relevant runtime versions;
- `predicate.checks` contains stable check IDs with `pass`, `fail` or `skip` status;
- `predicate.materials` records hashed fixtures/provider captures that are safe to disclose;
- `predicate.limitations` states evidence boundaries;
- `predicate.redactions` records intentionally omitted sensitive data;
- `digest.sha256` covers the canonical document excluding the digest field itself.

The structural separation is inspired by the subject/predicate model used by in-toto attestations, but this format is Clausula-specific and makes no in-toto, SLSA or signing compatibility claim.

## Determinism and verification

Call `build_acceptance_evidence(...)` with explicit environment/time/check inputs. Equivalent normalized inputs produce identical canonical JSON digests. `verify_acceptance_evidence(...)` recomputes normalization and the self-digest, so changing a check result, environment value or subject artifact invalidates the report.

Multiple reports may be combined with `combine_acceptance_evidence(...)`. All reports must verify and must refer to the same repository commit; conflicting source revisions fail closed. The resulting `clausula-local-acceptance-set/v1` contains only report digests and gate/profile identity, so individual sanitized reports remain independently reviewable.

## CLI

```bash
python scripts/acceptance_evidence.py verify evidence/daemon.json evidence/provider.json
python scripts/acceptance_evidence.py combine evidence/daemon.json evidence/provider.json --output evidence/release-set.json
python scripts/acceptance_evidence.py verify evidence/release-set.json
```

## Privacy boundary

Do not include bearer tokens, secrets, raw private research, account identifiers that are not intended for disclosure, absolute private filesystem paths, or confidential provider payload contents. Prefer hashes plus neutral labels. A redaction should be stated in `predicate.redactions` when omission materially affects how a reviewer interprets the evidence.

## Release use

For #23, typical checks include daemon ownership, independent-client authorization, crash/restart integrity and plugin sandbox failure containment. For #34, typical checks include provider preflight/import provenance, stale/revised/failure behavior, private-corpus extraction properties and target-machine benchmark completion. A passing envelope documents evidence; it does not itself make a failed or skipped gate pass.
