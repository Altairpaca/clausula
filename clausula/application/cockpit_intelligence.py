from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping, Sequence

from clausula.domain import canonical_decimal, canonical_timestamp


def _instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _age_days(known_as_of: str, item_known_at: str | None) -> int | None:
    if item_known_at is None:
        return None
    seconds = (_instant(known_as_of) - _instant(item_known_at)).total_seconds()
    return max(0, int(seconds // 86400))


def build_cockpit_intelligence(
    repository,
    projection,
    *,
    portfolio_id: str,
    as_of: str,
    known_as_of: str,
    decisions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    effective_cutoff = canonical_timestamp(as_of)
    knowledge_cutoff = canonical_timestamp(known_as_of)

    attention_rows = []
    if hasattr(repository, "attention_events"):
        attention_rows = [
            dict(row)
            for row in repository.attention_events()
            if canonical_timestamp(row["occurred_at"]) <= knowledge_cutoff
        ]
    attention_rows.sort(
        key=lambda row: (row.get("occurred_at", ""), row.get("recorded_at", "")),
        reverse=True,
    )

    recommendations = projection.recommendations(
        portfolio_id, effective_cutoff, knowledge_cutoff
    )
    open_recommendations = [
        row for row in recommendations if row.get("status") in {"draft", "reviewed"}
    ]
    terminal_recommendations = [
        row for row in recommendations if row.get("status") not in {"draft", "reviewed"}
    ]

    research = projection.research_summary(effective_cutoff, knowledge_cutoff)
    claims = int(research["claims"])
    contradictions = int(research["contradictions"])
    contradiction_ratio = (
        None
        if claims == 0
        else canonical_decimal(Decimal(contradictions) / Decimal(claims))
    )
    freshest_known_at = None
    for key in ("latest_evidence", "latest_claim", "latest_thesis_revision"):
        row = research.get(key)
        if row and (
            freshest_known_at is None or row["known_at"] > freshest_known_at
        ):
            freshest_known_at = row["known_at"]
    evidence_pressure = {
        **research,
        "contradiction_ratio": contradiction_ratio,
        "latest_research_known_at": freshest_known_at,
        "freshness_age_days": _age_days(knowledge_cutoff, freshest_known_at),
    }

    lineage = []
    review_queue = []
    for decision in decisions:
        decision_id = decision["id"]
        links = repository.decision_links(decision_id)
        policy_links = [dict(row) for row in links.get("policy", ())]
        evidence_links = [dict(row) for row in links.get("evidence", ())]
        transaction_links = [dict(row) for row in links.get("transaction", ())]
        reviews = [dict(row) for row in links.get("reviews", ())]
        schedules = [dict(row) for row in links.get("review_schedules", ())]
        completed_by_type: dict[str, str] = {}
        for review in reviews:
            review_type = str(review["review_type"])
            completed_by_type[review_type] = max(
                completed_by_type.get(review_type, ""), review["reviewed_at"]
            )
        for schedule in schedules:
            due_at = canonical_timestamp(schedule["due_at"])
            review_type = str(schedule["review_type"])
            completed = completed_by_type.get(review_type)
            if completed is not None and canonical_timestamp(completed) >= due_at:
                status = "completed"
            elif due_at <= knowledge_cutoff:
                status = "due"
            else:
                status = "upcoming"
            if status != "completed":
                review_queue.append(
                    {
                        "decision_id": decision_id,
                        "title": decision.get("title"),
                        "review_type": review_type,
                        "due_at": due_at,
                        "status": status,
                    }
                )
        missing = []
        if decision.get("plan_id") is None:
            missing.append("plan")
        if not policy_links:
            missing.append("policy")
        if not evidence_links:
            missing.append("evidence")
        if not transaction_links:
            missing.append("execution")
        if not reviews:
            missing.append("review")
        lineage.append(
            {
                "decision_id": decision_id,
                "title": decision.get("title"),
                "intent": decision.get("intent"),
                "as_of": decision.get("as_of"),
                "plan_id": decision.get("plan_id"),
                "policy_links": len(policy_links),
                "evidence_links": len(evidence_links),
                "transaction_links": len(transaction_links),
                "reviews": len(reviews),
                "missing_stages": missing,
                "complete": not missing,
            }
        )

    review_queue.sort(
        key=lambda row: (row["status"] != "due", row["due_at"], row["decision_id"])
    )
    lineage.sort(
        key=lambda row: (row.get("as_of") or "", row["decision_id"]), reverse=True
    )
    return {
        "attention": attention_rows,
        "recommendations": {
            "open": open_recommendations,
            "terminal": terminal_recommendations,
            "open_count": len(open_recommendations),
        },
        "evidence_pressure": evidence_pressure,
        "review_queue": review_queue,
        "decision_lineage": lineage,
        "lineage_note": (
            "Recommendation-to-decision association is not yet a canonical link; "
            "the lineage therefore starts at persisted Decision until that relationship is versioned."
        ),
    }
