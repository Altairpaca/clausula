from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from clausula.domain import (
    Recommendation,
    RecommendationAlternative,
    RecommendationOrigin,
    RecommendationStatus,
    canonical_timestamp,
    new_id,
    now,
)

from .ports import CoreRepository


TRANSITIONS: dict[RecommendationStatus, frozenset[RecommendationStatus]] = {
    RecommendationStatus.DRAFT: frozenset({RecommendationStatus.REVIEWED, RecommendationStatus.REJECTED, RecommendationStatus.EXPIRED}),
    RecommendationStatus.REVIEWED: frozenset({RecommendationStatus.ACCEPTED, RecommendationStatus.REJECTED, RecommendationStatus.EXPIRED}),
    RecommendationStatus.ACCEPTED: frozenset(),
    RecommendationStatus.REJECTED: frozenset(),
    RecommendationStatus.EXPIRED: frozenset(),
}


class RecommendationService:
    def __init__(self, repository: CoreRepository):
        self.repository = repository

    def create(
        self,
        *,
        portfolio_id: str,
        subject: str,
        recommendation_type: str,
        rationale: str,
        as_of: str,
        known_as_of: str,
        origin: str = "rule",
        facts: Sequence[Mapping[str, Any]] = (),
        assumptions: Sequence[Mapping[str, Any]] = (),
        risks: Sequence[Mapping[str, Any]] = (),
        confidence: str | None = None,
        alternatives: Sequence[Mapping[str, Any]] = (),
        created_at: str | None = None,
        recorded_at: str | None = None,
    ) -> dict[str, Any]:
        self.repository.portfolio(portfolio_id)
        recommendation_id = new_id()
        created = canonical_timestamp(created_at or known_as_of)
        recorded = canonical_timestamp(recorded_at or now())
        payload = {
            "facts": [dict(item) for item in facts],
            "assumptions": [dict(item) for item in assumptions],
            "risks": [dict(item) for item in risks],
            "confidence": confidence,
        }
        event = {
            "format": "clausula-recommendation-event-v1",
            "schema_version": "1",
            "operation": "recommendation.create",
            "recommendation_id": recommendation_id,
            "portfolio_id": portfolio_id,
            "subject": subject,
            "recommendation_type": recommendation_type,
            "rationale": rationale,
            "origin": origin,
            "as_of": as_of,
            "known_as_of": known_as_of,
            "created_at": created,
            "recorded_at": recorded,
            "payload": payload,
            "alternatives": [dict(item) for item in alternatives],
        }
        with self.repository.write_transaction():
            artifact_id, _ = self.repository.virtual_artifact(
                "manual://recommendation-create", json.dumps(event, sort_keys=True, separators=(",", ":"))
            )
            batch_id = self.repository.import_batch(
                artifact_id, adapter_name="manual-recommendation", adapter_version="1", schema_version="1"
            )
            recommendation = Recommendation(
                recommendation_id,
                portfolio_id,
                subject,
                recommendation_type,
                rationale,
                RecommendationOrigin(origin),
                RecommendationStatus.DRAFT,
                canonical_timestamp(as_of),
                canonical_timestamp(known_as_of),
                created,
                json.dumps(payload, sort_keys=True, separators=(",", ":")),
                artifact_id,
                batch_id,
            )
            rows = tuple(
                RecommendationAlternative(
                    new_id(),
                    recommendation_id,
                    str(item["key"]),
                    str(item["description"]),
                    item.get("selected", False),
                )
                for item in alternatives
            )
            self.repository.add_recommendation(recommendation, rows)
        return self.get(recommendation_id)

    def get(self, recommendation_id: str) -> dict[str, Any]:
        return {
            "recommendation": dict(self.repository.recommendation(recommendation_id)),
            "alternatives": [
                dict(row)
                for row in self.repository.recommendation_alternatives(recommendation_id)
            ],
        }

    def transition(self, recommendation_id: str, status: str) -> dict[str, Any]:
        current = RecommendationStatus(self.repository.recommendation(recommendation_id)["status"])
        target = RecommendationStatus(status)
        if target not in TRANSITIONS[current]:
            raise ValueError("invalid recommendation transition")
        self.repository.transition_recommendation(recommendation_id, target.value)
        return dict(self.repository.recommendation(recommendation_id))
