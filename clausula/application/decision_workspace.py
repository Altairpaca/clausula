from __future__ import annotations

from typing import Any, Protocol

from clausula.domain import canonical_timestamp


class DecisionWorkspaceRepository(Protocol):
    def attentions(self, *, portfolio_id: str, known_as_of: str, limit: int = 12) -> list[dict[str, Any]]: ...

    def recommendations(self, *, portfolio_id: str, as_of: str, known_as_of: str) -> list[dict[str, Any]]: ...

    def evidence_pressure(self, *, portfolio_id: str, as_of: str, known_as_of: str) -> dict[str, Any]: ...

    def review_queue(self, *, portfolio_id: str, as_of: str, known_as_of: str) -> list[dict[str, Any]]: ...

    def lineage(self, *, portfolio_id: str, as_of: str, known_as_of: str) -> list[dict[str, Any]]: ...

    def add_recommendation_decision_link(
        self,
        recommendation_id: str,
        decision_id: str,
        *,
        relation: str = "accepted_into",
        linked_at: str | None = None,
    ) -> dict[str, Any]: ...


class DecisionWorkspaceService:
    """Compose action-relevant, derived decision signals for the local workspace."""

    def __init__(self, repository: DecisionWorkspaceRepository):
        self.repository = repository

    def snapshot(
        self,
        portfolio_id: str,
        as_of: str,
        *,
        known_as_of: str | None = None,
        attention_limit: int = 12,
    ) -> dict[str, Any]:
        effective_cutoff = canonical_timestamp(as_of)
        knowledge_cutoff = canonical_timestamp(known_as_of or as_of)
        recommendations = self.repository.recommendations(
            portfolio_id=portfolio_id,
            as_of=effective_cutoff,
            known_as_of=knowledge_cutoff,
        )
        review_queue = self.repository.review_queue(
            portfolio_id=portfolio_id,
            as_of=effective_cutoff,
            known_as_of=knowledge_cutoff,
        )
        return {
            "as_of": effective_cutoff,
            "known_as_of": knowledge_cutoff,
            "attention": self.repository.attentions(
                portfolio_id=portfolio_id,
                known_as_of=knowledge_cutoff,
                limit=attention_limit,
            ),
            "recommendations": recommendations,
            "recommendation_inbox": [
                row
                for row in recommendations
                if row.get("status") in {"draft", "reviewed"}
            ],
            "evidence": self.repository.evidence_pressure(
                portfolio_id=portfolio_id,
                as_of=effective_cutoff,
                known_as_of=knowledge_cutoff,
            ),
            "review_queue": review_queue,
            "reviews_due": [row for row in review_queue if row["status"] == "due"],
            "lineage": self.repository.lineage(
                portfolio_id=portfolio_id,
                as_of=effective_cutoff,
                known_as_of=knowledge_cutoff,
            ),
        }

    def link_recommendation_decision(
        self,
        recommendation_id: str,
        decision_id: str,
        *,
        relation: str = "accepted_into",
        linked_at: str | None = None,
    ) -> dict[str, Any]:
        return self.repository.add_recommendation_decision_link(
            recommendation_id,
            decision_id,
            relation=relation,
            linked_at=linked_at,
        )
