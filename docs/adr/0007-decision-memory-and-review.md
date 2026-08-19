# ADR 0007: Decision Memory and Review

- Status: Accepted for M5 implementation
- Date: 2026-08-19

## Context

Transactions do not explain why capital was or was not moved. Clausula needs an
immutable decision record that preserves what was known, considered, expected,
and capable of invalidating the choice. Later execution and outcome must not
rewrite the original rationale.

## Decision

`Decision` belongs to a Portfolio, has trade or non-trade intent, and records
effective/knowledge cutoffs. “Do nothing” is a valid selected Alternative.
Decision may reference the PolicyVersion and Plan used at creation; a
PolicyVersion must have been effective and knowable at the Decision cutoff.

Alternatives, Assumptions, ExpectedOutcomes, InvalidationConditions, and
process/outcome review schedules are immutable child records. Policy, evidence,
and later Transaction relationships are append-only links. Evidence links may
support, contradict, or provide context and do not turn research into financial
truth. Transaction linking never creates or mutates a Transaction.

DecisionReview separates `process` from `outcome`, uses an optional 1-5 score,
and appends rather than revises. Scheduled review dates are explicit records.
All create/link/review operations have immutable raw event envelopes, import
metadata, audit events, backup/export coverage, and clean rebuild mappings.

Capabilities are `decision.create`, `decision.list`, `decision.get`,
`decision.link_policy`, `decision.link_evidence`,
`decision.link_transaction`, and `decision.review`. Writes require explicit
confirmation and scoped permissions. No Decision capability writes Ledger.

## Consequences

Clausula can reconstruct a trade or non-trade choice, its alternatives and
assumptions, later execution, and process/outcome reviews. M5 does not create a
Recommendation lifecycle or schedule background jobs; those remain M11 and M7
platform concerns respectively.
