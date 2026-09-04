# Decision Workspace

The Decision Workspace is the second layer of the Capital Cockpit. It projects existing append-only facts into four decision-oriented queues without creating a second truth system.

## Surfaces

- **Material attention** — persisted derived attention events, ordered by recorded time.
- **Recommendation inbox** — recommendation lifecycle state, emphasizing drafts/reviewed items that still require a human decision.
- **Evidence pressure** — age of known evidence plus explicit contradicting links/claim contradictions. Clausula does not invent a universal freshness threshold; the surface exposes facts so policies or users can define one explicitly later.
- **Review queue** — decision review schedules reconciled against completed reviews, with due/upcoming/completed status at the requested cutoff.

## Lineage

Recommendation → Decision lineage is explicit. A linkage is stored as a tamper-evident audit event; the UI never infers lineage from matching titles or recommendation subjects.

The downstream chain remains:

`recommendation → decision → transaction → review`

Each step is independently auditable. Missing links remain visible as missing rather than being synthesized by an agent.

## Temporal semantics

Every workspace snapshot is evaluated under explicit `as_of` and `known_as_of` cutoffs. Evidence age is measured from the evidence `known_at` timestamp to the requested knowledge cutoff. Review status is evaluated against the requested effective cutoff.

## Non-goals

- no autonomous order placement;
- no LLM-generated canonical financial state;
- no arbitrary evidence-expiry threshold;
- no title/subject heuristics for lineage;
- no mutation from the read workspace itself.
