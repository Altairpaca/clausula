from __future__ import annotations

from typing import Any


class CockpitIntelligenceProjection:
    """Bounded local reads used only by the decision workspace.

    These projections expose existing canonical/derived records without creating
    a second source of financial truth. They intentionally stay out of the core
    repository protocol until the product read model stabilizes.
    """

    def __init__(self, repository):
        if not hasattr(repository, "db"):
            raise TypeError("cockpit intelligence projection requires local SQLite storage")
        self.repository = repository
        self.db = repository.db

    def recommendations(self, portfolio_id: str) -> list[dict[str, Any]]:
        rows = self.db.execute(
            """SELECT r.*,
               COALESCE((
                 SELECT status FROM recommendation_transitions t
                 WHERE t.recommendation_id=r.id
                 ORDER BY t.transitioned_at DESC,t.id DESC LIMIT 1
               ), 'draft') AS status
               FROM recommendations r
               WHERE r.portfolio_id=?
               ORDER BY r.created_at,r.id""",
            (portfolio_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def research_summary(self) -> dict[str, Any]:
        counts = {}
        for key, table in (
            ("documents", "research_documents"),
            ("claims", "research_claims"),
            ("evidence", "research_evidence"),
            ("contradictions", "research_contradictions"),
            ("theses", "research_theses"),
        ):
            counts[key] = self.db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        latest_evidence = self.db.execute(
            """SELECT known_at,recorded_at,document_id,kind,relation
               FROM research_evidence
               ORDER BY known_at DESC,recorded_at DESC,id DESC LIMIT 1"""
        ).fetchone()
        latest_claim = self.db.execute(
            """SELECT known_at,recorded_at,document_id,claim_key
               FROM research_claims
               ORDER BY known_at DESC,recorded_at DESC,id DESC LIMIT 1"""
        ).fetchone()
        latest_revision = self.db.execute(
            """SELECT r.*,t.title
               FROM thesis_revisions r
               JOIN research_theses t ON t.id=r.thesis_id
               ORDER BY r.known_at DESC,r.recorded_at DESC,r.revision_number DESC,r.id DESC
               LIMIT 1"""
        ).fetchone()
        return {
            **counts,
            "latest_evidence": None if latest_evidence is None else dict(latest_evidence),
            "latest_claim": None if latest_claim is None else dict(latest_claim),
            "latest_thesis_revision": None if latest_revision is None else dict(latest_revision),
        }
