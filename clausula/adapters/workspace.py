from __future__ import annotations

from datetime import datetime
import json
from typing import Any, Mapping

from clausula.domain import canonical_timestamp, new_id, now

from .audit import append_audit_event


LINEAGE_RELATIONS = {"accepted_into", "considered_in", "rejected_by"}


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _age_days(known_as_of: str, evidence_known_at: str | None) -> int | None:
    if not evidence_known_at:
        return None
    return max((_parse_time(known_as_of) - _parse_time(evidence_known_at)).days, 0)


class DecisionWorkspaceProjection:
    """SQLite-backed derived projection for the decision-first local workspace.

    This projection composes existing append-only facts. It does not introduce a
    second financial truth store. The only write is an explicit recommendation →
    decision relationship recorded as a tamper-evident audit event.
    """

    def __init__(self, repository):
        if not hasattr(repository, "db"):
            raise TypeError("decision workspace requires a local SQLite repository")
        self.repository = repository
        self.db = repository.db

    def __getattr__(self, name: str):
        return getattr(self.repository, name)

    def attentions(
        self,
        *,
        portfolio_id: str,
        known_as_of: str,
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        self.repository.portfolio(portfolio_id)
        cutoff = canonical_timestamp(known_as_of)
        rows = self.db.execute(
            """SELECT * FROM audit_events
               WHERE object_type='attention_event' AND occurred_at<=?
               ORDER BY sequence DESC LIMIT ?""",
            (cutoff, max(int(limit) * 4, int(limit))),
        ).fetchall()
        output: list[dict[str, Any]] = []
        for row in rows:
            payload = json.loads(row["payload_json"])
            scoped_portfolio = payload.get("portfolio_id")
            if scoped_portfolio not in (None, portfolio_id):
                continue
            output.append(
                {
                    "id": row["id"],
                    "fingerprint": row["object_id"],
                    "recorded_at": row["occurred_at"],
                    "scope": "portfolio" if scoped_portfolio == portfolio_id else "global",
                    **payload,
                }
            )
            if len(output) >= int(limit):
                break
        return output

    def recommendations(
        self,
        *,
        portfolio_id: str,
        as_of: str,
        known_as_of: str,
    ) -> list[dict[str, Any]]:
        self.repository.portfolio(portfolio_id)
        effective_cutoff = canonical_timestamp(as_of)
        knowledge_cutoff = canonical_timestamp(known_as_of)
        rows = self.db.execute(
            """SELECT r.*,
               COALESCE((
                 SELECT status FROM recommendation_transitions t
                 WHERE t.recommendation_id=r.id AND t.transitioned_at<=?
                 ORDER BY t.transitioned_at DESC,t.id DESC LIMIT 1
               ), 'draft') AS status
               FROM recommendations r
               WHERE r.portfolio_id=? AND r.as_of<=? AND r.known_as_of<=?
               ORDER BY r.created_at DESC,r.id DESC""",
            (knowledge_cutoff, portfolio_id, effective_cutoff, knowledge_cutoff),
        ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            try:
                item["payload"] = json.loads(item.pop("payload_json"))
            except (KeyError, json.JSONDecodeError):
                item["payload"] = {}
            output.append(item)
        return output

    def evidence_pressure(
        self,
        *,
        portfolio_id: str,
        as_of: str,
        known_as_of: str,
    ) -> dict[str, Any]:
        self.repository.portfolio(portfolio_id)
        effective_cutoff = canonical_timestamp(as_of)
        knowledge_cutoff = canonical_timestamp(known_as_of)
        rows = self.db.execute(
            """SELECT l.id,l.decision_id,d.title AS decision_title,
                      l.evidence_id,l.evidence_kind,l.relation,
                      COALESCE(e.known_at,c.known_at) AS evidence_known_at,
                      COALESCE(e.recorded_at,c.recorded_at) AS evidence_recorded_at,
                      COALESCE(e.text,c.text) AS evidence_text
               FROM decision_evidence_links l
               JOIN decisions d ON d.id=l.decision_id
               LEFT JOIN research_evidence e ON e.id=l.evidence_id
               LEFT JOIN research_claims c ON c.id=l.evidence_id
               WHERE d.portfolio_id=? AND d.as_of<=? AND d.known_as_of<=?
               ORDER BY d.created_at DESC,l.id""",
            (portfolio_id, effective_cutoff, knowledge_cutoff),
        ).fetchall()
        items: list[dict[str, Any]] = []
        linked_claim_ids: set[str] = set()
        for row in rows:
            evidence_known_at = row["evidence_known_at"]
            if evidence_known_at is not None and canonical_timestamp(evidence_known_at) > knowledge_cutoff:
                continue
            if self.db.execute(
                "SELECT 1 FROM research_claims WHERE id=?", (row["evidence_id"],)
            ).fetchone() is not None:
                linked_claim_ids.add(row["evidence_id"])
            items.append(
                {
                    "link_id": row["id"],
                    "decision_id": row["decision_id"],
                    "decision_title": row["decision_title"],
                    "evidence_id": row["evidence_id"],
                    "evidence_kind": row["evidence_kind"],
                    "relation": row["relation"],
                    "known_at": evidence_known_at,
                    "age_days": _age_days(knowledge_cutoff, evidence_known_at),
                    "text": row["evidence_text"],
                }
            )

        contradictions: list[dict[str, Any]] = []
        if linked_claim_ids:
            placeholders = ",".join("?" for _ in linked_claim_ids)
            ids = sorted(linked_claim_ids)
            contradiction_rows = self.db.execute(
                f"""SELECT * FROM research_contradictions
                     WHERE known_at<=? AND (
                       claim_a_id IN ({placeholders}) OR claim_b_id IN ({placeholders})
                     )
                     ORDER BY known_at DESC,recorded_at DESC,id DESC""",
                (knowledge_cutoff, *ids, *ids),
            ).fetchall()
            contradictions = [dict(row) for row in contradiction_rows]

        ages = [item["age_days"] for item in items if item["age_days"] is not None]
        contradicting_links = sum(1 for item in items if item["relation"] == "contradicts")
        return {
            "status": (
                "unlinked"
                if not items
                else "pressure"
                if contradicting_links or contradictions
                else "clear"
            ),
            "linked_evidence": len(items),
            "contradicting_links": contradicting_links,
            "explicit_contradictions": len(contradictions),
            "oldest_age_days": max(ages) if ages else None,
            "newest_age_days": min(ages) if ages else None,
            "items": sorted(
                items,
                key=lambda item: (
                    0 if item["relation"] == "contradicts" else 1,
                    -(item["age_days"] or -1),
                    item["decision_id"],
                    item["evidence_id"],
                ),
            ),
            "contradictions": contradictions,
        }

    def review_queue(
        self,
        *,
        portfolio_id: str,
        as_of: str,
        known_as_of: str,
    ) -> list[dict[str, Any]]:
        self.repository.portfolio(portfolio_id)
        effective_cutoff = canonical_timestamp(as_of)
        knowledge_cutoff = canonical_timestamp(known_as_of)
        schedules = self.db.execute(
            """SELECT s.*,d.title AS decision_title,d.created_at AS decision_created_at
               FROM decision_review_schedules s
               JOIN decisions d ON d.id=s.decision_id
               WHERE d.portfolio_id=? AND d.as_of<=? AND d.known_as_of<=?
               ORDER BY s.due_at,s.id""",
            (portfolio_id, effective_cutoff, knowledge_cutoff),
        ).fetchall()
        decision_ids = sorted({row["decision_id"] for row in schedules})
        reviews_by_key: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
        if decision_ids:
            placeholders = ",".join("?" for _ in decision_ids)
            reviews = self.db.execute(
                f"""SELECT * FROM decision_reviews
                     WHERE decision_id IN ({placeholders}) AND reviewed_at<=?
                     ORDER BY reviewed_at,id""",
                (*decision_ids, knowledge_cutoff),
            ).fetchall()
            for review in reviews:
                reviews_by_key.setdefault(
                    (review["decision_id"], review["review_type"]), []
                ).append(review)

        output: list[dict[str, Any]] = []
        for schedule in schedules:
            matching = reviews_by_key.get(
                (schedule["decision_id"], schedule["review_type"]), []
            )
            completion = next(
                (
                    review
                    for review in reversed(matching)
                    if canonical_timestamp(review["reviewed_at"])
                    >= canonical_timestamp(schedule["due_at"])
                ),
                None,
            )
            due_at = canonical_timestamp(schedule["due_at"])
            if completion is not None:
                status = "completed"
            elif due_at <= knowledge_cutoff:
                status = "due"
            else:
                status = "upcoming"
            output.append(
                {
                    "schedule_id": schedule["id"],
                    "decision_id": schedule["decision_id"],
                    "decision_title": schedule["decision_title"],
                    "review_type": schedule["review_type"],
                    "due_at": due_at,
                    "status": status,
                    "completed_review_id": None if completion is None else completion["id"],
                }
            )
        order = {"due": 0, "upcoming": 1, "completed": 2}
        return sorted(output, key=lambda row: (order[row["status"]], row["due_at"], row["schedule_id"]))

    def recommendation_decision_links(
        self,
        *,
        portfolio_id: str,
        known_as_of: str,
    ) -> list[dict[str, Any]]:
        self.repository.portfolio(portfolio_id)
        cutoff = canonical_timestamp(known_as_of)
        rows = self.db.execute(
            """SELECT * FROM audit_events
               WHERE object_type='recommendation_decision_link' AND occurred_at<=?
               ORDER BY sequence""",
            (cutoff,),
        ).fetchall()
        output = []
        for row in rows:
            payload = json.loads(row["payload_json"])
            if payload.get("portfolio_id") != portfolio_id:
                continue
            output.append(
                {
                    "id": row["id"],
                    "recorded_at": row["occurred_at"],
                    **payload,
                }
            )
        return output

    def add_recommendation_decision_link(
        self,
        recommendation_id: str,
        decision_id: str,
        *,
        relation: str = "accepted_into",
        linked_at: str | None = None,
    ) -> dict[str, Any]:
        normalized_relation = str(relation).strip().lower()
        if normalized_relation not in LINEAGE_RELATIONS:
            raise ValueError(
                "recommendation-decision relation must be accepted_into, considered_in, or rejected_by"
            )
        recommendation = self.repository.recommendation(recommendation_id)
        decision = self.repository.decision(decision_id)
        if recommendation["portfolio_id"] != decision["portfolio_id"]:
            raise ValueError("recommendation-decision link crosses portfolio boundary")
        linked_time = canonical_timestamp(linked_at or now())
        existing = self.recommendation_decision_links(
            portfolio_id=decision["portfolio_id"], known_as_of=linked_time
        )
        for row in existing:
            if (
                row["recommendation_id"] == recommendation_id
                and row["decision_id"] == decision_id
                and row["relation"] == normalized_relation
            ):
                return row
        payload = {
            "portfolio_id": decision["portfolio_id"],
            "recommendation_id": recommendation_id,
            "decision_id": decision_id,
            "relation": normalized_relation,
            "linked_at": linked_time,
        }
        with self.repository.write_transaction():
            event_id = append_audit_event(
                self.db,
                operation="recommendation.link_decision",
                object_type="recommendation_decision_link",
                object_id=new_id(),
                payload=payload,
            )
        return {"id": event_id, "recorded_at": linked_time, **payload}

    def lineage(
        self,
        *,
        portfolio_id: str,
        as_of: str,
        known_as_of: str,
    ) -> list[dict[str, Any]]:
        effective_cutoff = canonical_timestamp(as_of)
        knowledge_cutoff = canonical_timestamp(known_as_of)
        links = self.recommendation_decision_links(
            portfolio_id=portfolio_id, known_as_of=knowledge_cutoff
        )
        rec_by_decision: dict[str, list[dict[str, Any]]] = {}
        for link in links:
            rec_by_decision.setdefault(link["decision_id"], []).append(link)
        decisions = self.db.execute(
            """SELECT * FROM decisions
               WHERE portfolio_id=? AND as_of<=? AND known_as_of<=?
               ORDER BY created_at DESC,id DESC""",
            (portfolio_id, effective_cutoff, knowledge_cutoff),
        ).fetchall()
        output = []
        for decision in decisions:
            transaction_links = [
                dict(row)
                for row in self.db.execute(
                    """SELECT * FROM decision_transaction_links
                       WHERE decision_id=? AND linked_at<=? ORDER BY linked_at,id""",
                    (decision["id"], knowledge_cutoff),
                ).fetchall()
            ]
            reviews = [
                dict(row)
                for row in self.db.execute(
                    """SELECT * FROM decision_reviews
                       WHERE decision_id=? AND reviewed_at<=? ORDER BY reviewed_at,id""",
                    (decision["id"], knowledge_cutoff),
                ).fetchall()
            ]
            recommendation_links = rec_by_decision.get(decision["id"], [])
            recommendations = []
            for link in recommendation_links:
                try:
                    recommendation = dict(
                        self.repository.recommendation(link["recommendation_id"])
                    )
                except KeyError:
                    recommendation = {"id": link["recommendation_id"], "status": "missing"}
                recommendations.append({"link": link, "recommendation": recommendation})
            output.append(
                {
                    "decision": dict(decision),
                    "recommendations": recommendations,
                    "plan_id": decision["plan_id"],
                    "transactions": transaction_links,
                    "reviews": reviews,
                    "stage": (
                        "reviewed"
                        if reviews
                        else "executed"
                        if transaction_links
                        else "decided"
                    ),
                }
            )
        return output
