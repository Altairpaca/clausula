# Decision Workspace acceptance

A release candidate is acceptable only when all of the following are true:

1. Workspace reads do not mutate ledger, market, policy, planning, recommendation, decision or research facts.
2. Recommendation-to-decision lineage uses explicit stored links, never text matching.
3. Missing evidence, lineage or review data remains missing; no optimistic synthesis is allowed.
4. Evidence pressure reports objective age/contradiction facts rather than an undocumented subjective freshness score.
5. Review queue status is evaluated at the requested temporal cutoff.
6. Portfolio/advisor MCP profiles may read workspace projections; only explicit write capabilities may create lineage links.
7. UI rendering treats all stored text as text content rather than HTML.
8. Python 3.12 and 3.13 CI, repository-hygiene gates and full tests pass before merge.
