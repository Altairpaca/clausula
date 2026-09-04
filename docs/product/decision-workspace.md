# Decision Workspace

The Decision Workspace is the second layer of the Capital Cockpit. It projects existing append-only facts into four decision-oriented queues without creating a second truth system.

## Surfaces

- **Material attention** — persisted derived attention events, ordered and bounded by their actual recorded time.
- **Recommendation inbox** — point-in-time recommendation lifecycle state, emphasizing drafts/reviewed items that still require a human decision.
- **Evidence pressure** — age of known evidence plus explicit contradicting links/claim contradictions. Clausula does not invent a universal freshness threshold; the surface exposes objective facts so a policy or user may define one explicitly later.
- **Review queue** — decision review schedules reconciled against reviews that were actually knowable by the requested cutoff, with due/upcoming/completed status.

## Lineage

Recommendation → Decision lineage is explicit. A linkage is stored as a tamper-evident audit event; the UI never infers lineage from matching titles or recommendation subjects.

The downstream chain remains:

`recommendation → decision → plan/execution → transaction → review`

Each step is independently auditable. Missing links remain visible as missing rather than being synthesized by an agent.

## Temporal semantics

Every workspace snapshot is evaluated under explicit `as_of` and `known_as_of` cutoffs. Evidence age is measured from the evidence `known_at` timestamp to the requested knowledge cutoff.

Some legacy relationship rows, including decision-evidence links and decision reviews, have a business timestamp but do not carry a separate `known_at`. For these rows the matching tamper-evident audit event supplies the **knowability boundary**: a relationship or review appended today cannot appear in a historical knowledge snapshot merely because its business date was backdated. Transaction links and explicit recommendation-decision lineage are likewise bounded by both their semantic timestamp and actual append time where available.

This is intentionally stricter than a conventional activity feed. Backfilled records may describe an earlier period, but Clausula does not rewrite what the system could have known at that earlier time.

## Non-goals

- no autonomous order placement;
- no LLM-generated canonical financial state;
- no arbitrary evidence-expiry threshold;
- no title/subject heuristics for lineage;
- no mutation from the read workspace itself.
