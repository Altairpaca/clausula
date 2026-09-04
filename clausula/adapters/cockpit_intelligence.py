from __future__ import annotations

from typing import Any

from clausula.domain import canonical_timestamp


class CockpitIntelligenceProjection:
    """Bounded local reads used only by the decision workspace.

    These projections expose existing canonical/derived records without creating
    a second source of financial truth. Temporal cutoffs are explicit so the
    workspace cannot accidentally mix future recommendations/research into a
    historical snapshot.
    """

    def __init__(self, repository):
        if not hasattr(repository, "db"):
            raise TypeError("cockpit intelligence projection requires local SQLite storage")
        self.repository = repository
        self.db = repository.db

    def recommendations(
        self,
        portfolio_id: str,
        as_of: str,
        known_as_of: str | None = None,
    ) -> list[dict[str, Any]]:
        effective_cutoff = canonical_timestamp(as_of)
        knowledge_cutoff = canonical_timestamp(known_as_of or as_of)
        rows = self.db.execute(
            """SELECT r.*,
               COALESCE((
                 SELECT status FROM recommendation_transitions t
                 WHERE t.recommendation_id=r.id AND t.transitioned_at<=?
                 ORDER BY t.transitioned_at DESC,t.id DESC LIMIT 1
               ), 'draft') AS status
               FROM recommendations r
               WHERE r.portfolio_id=? AND r.as_of<=? AND r.known_as_of<=?
               ORDER BY r.created_at,r.id""",
            (knowledge_cutoff, portfolio_id, effective_cutoff, knowledge_cutoff),
        ).fetchall()
        return [dict(row) for row in rows]

    def research_summary(
        self, as_of: str, known_as_of: str | None = None
    ) -> dict[str, Any]:
        effective_cutoff = canonical_timestamp(as_of)
        knowledge_cutoff = canonical_timestamp(known_as_of or as_of)
        counts = {
            "documents": self.db.execute(
                """SELECT count(*) FROM research_documents
                   WHERE effective_at<=? AND known_at<=?""",
                (effective_cutoff, knowledge_cutoff),
            ).fetchone()[0],
            "claims": self.db.execute(
                """SELECT count(*) FROM research_claims
                   WHERE effective_at<=? AND known_at<=?""",
                (effective_cutoff, knowledge_cutoff),
            ).fetchone()[0],
            "evidence": self.db.execute(
                """SELECT count(*) FROM research_evidence
                   WHERE effective_at<=? AND known_at<=?""",
                (effective_cutoff, knowledge_cutoff),
            ).fetchone()[0],
            "contradictions": self.db.execute(
                """SELECT count(*) FROM research_contradictions
                   WHERE known_at<=?""",
                (knowledge_cutoff,),
            ).fetchone()[0],
            "theses": self.db.execute(
                """SELECT count(DISTINCT t.id)
                   FROM research_theses t JOIN thesis_revisions r ON r.thesis_id=t.id
                   WHERE r.known_at<=?""",
                (knowledge_cutoff,),
            ).fetchone()[0],
        }
        latest_evidence = self.db.execute(
            """SELECT known_at,recorded_at,document_id,kind,relation
               FROM research_evidence
               WHERE effective_at<=? AND known_at<=?
               ORDER BY known_at DESC,recorded_at DESC,id DESC LIMIT 1""",
            (effective_cutoff, knowledge_cutoff),
        ).fetchone()
        latest_claim = self.db.execute(
            """SELECT known_at,recorded_at,document_id,claim_key
               FROM research_claims
               WHERE effective_at<=? AND known_at<=?
               ORDER BY known_at DESC,recorded_at DESC,id DESC LIMIT 1""",
            (effective_cutoff, knowledge_cutoff),
        ).fetchone()
        latest_revision = self.db.execute(
            """SELECT r.*,t.title
               FROM thesis_revisions r
               JOIN research_theses t ON t.id=r.thesis_id
               WHERE r.known_at<=?
               ORDER BY r.known_at DESC,r.recorded_at DESC,r.revision_number DESC,r.id DESC
               LIMIT 1""",
            (knowledge_cutoff,),
        ).fetchone()
        return {
            **counts,
            "latest_evidence": None if latest_evidence is None else dict(latest_evidence),
            "latest_claim": None if latest_claim is None else dict(latest_claim),
            "latest_thesis_revision": None if latest_revision is None else dict(latest_revision),
        }
