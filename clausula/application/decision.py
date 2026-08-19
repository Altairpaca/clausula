from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from clausula.domain import (
    Decision,
    DecisionAlternative,
    DecisionEvidenceLink,
    DecisionPolicyLink,
    DecisionReview,
    DecisionReviewSchedule,
    DecisionStatement,
    DecisionTransactionLink,
    canonical_timestamp,
    new_id,
    now,
)

from .ports import CoreRepository


DECISION_EVENT_FORMAT = "clausula-decision-event-v1"


class DecisionError(ValueError):
    pass


class DecisionService:
    def __init__(self, repository: CoreRepository):
        self.repository = repository

    def create(
        self,
        portfolio_id: str,
        title: str,
        intent: str,
        rationale: str,
        as_of: str,
        *,
        known_as_of: str | None = None,
        policy_version_id: str | None = None,
        plan_id: str | None = None,
        alternatives: Sequence[Mapping[str, Any]] = (),
        assumptions: Sequence[Mapping[str, Any]] = (),
        expected_outcomes: Sequence[Mapping[str, Any]] = (),
        invalidation_conditions: Sequence[Mapping[str, Any]] = (),
        review_schedule: Sequence[Mapping[str, Any]] = (),
        created_at: str | None = None,
        recorded_at: str | None = None,
    ) -> dict[str, Any]:
        portfolio = self.repository.portfolio(portfolio_id)
        effective = canonical_timestamp(as_of)
        knowledge = canonical_timestamp(known_as_of or as_of)
        if policy_version_id is not None:
            version = self.repository.policy_version(policy_version_id)
            if version["effective_from"] > effective or version["known_at"] > knowledge:
                raise DecisionError("policy version was not effective and knowable at decision time")
        if plan_id is not None:
            plan = self.repository.plan(plan_id)
            if plan["portfolio_id"] != portfolio_id:
                raise DecisionError("plan belongs to a different portfolio")
        normalized_alternatives = self._normalize_alternatives(alternatives)
        normalized_statements = self._normalize_statements(assumptions, expected_outcomes, invalidation_conditions)
        normalized_schedule = self._normalize_schedule(review_schedule)
        if not normalized_alternatives:
            normalized_alternatives = [
                {"key": "do_nothing", "description": "No action", "selected": intent == "non_trade"}
            ]
        if sum(item["selected"] for item in normalized_alternatives) > 1:
            raise DecisionError("at most one decision alternative may be selected")
        decision_id = new_id()
        created = canonical_timestamp(created_at or now())
        recorded = canonical_timestamp(recorded_at or created)
        event = {
            "format": DECISION_EVENT_FORMAT,
            "schema_version": "1",
            "operation": "decision.create",
            "decision_id": decision_id,
            "portfolio_id": portfolio_id,
            "title": str(title).strip(),
            "intent": intent,
            "rationale": str(rationale).strip(),
            "as_of": effective,
            "known_as_of": knowledge,
            "created_at": created,
            "recorded_at": recorded,
            "policy_version_id": policy_version_id,
            "plan_id": plan_id,
            "alternatives": normalized_alternatives,
            "statements": normalized_statements,
            "review_schedule": normalized_schedule,
        }
        with self.repository.write_transaction():
            artifact_id, _ = self.repository.virtual_artifact(
                "manual://decision-create", self._event_json(event)
            )
            batch_id = self.repository.import_batch(
                artifact_id,
                adapter_name="manual-decision",
                adapter_version="1",
                schema_version="1",
            )
            decision = Decision(
                decision_id,
                portfolio_id,
                title,
                intent,
                rationale,
                effective,
                knowledge,
                created,
                policy_version_id,
                plan_id,
                artifact_id,
                batch_id,
            )
            rows = tuple(
                DecisionAlternative(
                    new_id(),
                    decision_id,
                    item["key"],
                    item["description"],
                    item["selected"],
                )
                for item in normalized_alternatives
            )
            statements = tuple(DecisionStatement(new_id(), decision_id, item["kind"], item["key"], item["text"]) for item in normalized_statements)
            schedules = tuple(DecisionReviewSchedule(new_id(), decision_id, item["review_type"], item["due_at"]) for item in normalized_schedule)
            self.repository.add_decision(decision, rows, statements, schedules)
        return self.get(decision_id)

    def list(self, portfolio_id: str | None = None) -> list[dict[str, Any]]:
        return [dict(row) for row in self.repository.decisions(portfolio_id)]

    def get(self, decision_id: str) -> dict[str, Any]:
        decision = dict(self.repository.decision(decision_id))
        links = self.repository.decision_links(decision_id)
        return {
            "decision": decision,
            "alternatives": [dict(row) for row in self.repository.decision_alternatives(decision_id)],
            "policy_links": [dict(row) for row in links["policy"]],
            "evidence_links": [dict(row) for row in links["evidence"]],
            "transaction_links": [dict(row) for row in links["transaction"]],
            "reviews": [dict(row) for row in links["reviews"]],
            "statements": [dict(row) for row in links["statements"]],
            "review_schedule": [dict(row) for row in links["review_schedules"]],
        }

    def link_policy(self, decision_id: str, policy_version_id: str, link_type: str = "governs") -> str:
        link = DecisionPolicyLink(new_id(), decision_id, policy_version_id, link_type)
        event = {
            "format": DECISION_EVENT_FORMAT,
            "schema_version": "1",
            "operation": "decision.link_policy",
            "link_id": link.id,
            "decision_id": decision_id,
            "policy_version_id": policy_version_id,
            "link_type": link_type,
        }
        self._write_link(link, event, "manual-decision-policy", self.repository.add_decision_policy_link)
        return link.id

    def link_evidence(
        self,
        decision_id: str,
        evidence_id: str,
        evidence_kind: str = "research",
        relation: str = "supports",
    ) -> str:
        link = DecisionEvidenceLink(new_id(), decision_id, evidence_id, evidence_kind, relation)
        event = {
            "format": DECISION_EVENT_FORMAT,
            "schema_version": "1",
            "operation": "decision.link_evidence",
            "link_id": link.id,
            "decision_id": decision_id,
            "evidence_id": evidence_id,
            "evidence_kind": evidence_kind,
            "relation": relation,
        }
        self._write_link(link, event, "manual-decision-evidence", self.repository.add_decision_evidence_link)
        return link.id

    def link_transaction(
        self,
        decision_id: str,
        transaction_id: str,
        relation: str = "executed",
        linked_at: str | None = None,
    ) -> str:
        link = DecisionTransactionLink(
            new_id(), decision_id, transaction_id, relation, linked_at or now()
        )
        event = {
            "format": DECISION_EVENT_FORMAT,
            "schema_version": "1",
            "operation": "decision.link_transaction",
            "link_id": link.id,
            "decision_id": decision_id,
            "transaction_id": transaction_id,
            "relation": relation,
            "linked_at": link.linked_at,
        }
        self._write_link(link, event, "manual-decision-transaction", self.repository.add_decision_transaction_link)
        return link.id

    def review(
        self,
        decision_id: str,
        review_type: str,
        score: int | None,
        notes: str,
        *,
        reviewed_at: str | None = None,
    ) -> str:
        review = DecisionReview(new_id(), decision_id, review_type, score, notes, reviewed_at or now())
        event = {
            "format": DECISION_EVENT_FORMAT,
            "schema_version": "1",
            "operation": "decision.review",
            "review_id": review.id,
            "decision_id": decision_id,
            "review_type": review_type,
            "score": score,
            "notes": notes,
            "reviewed_at": review.reviewed_at,
        }
        self._write_link(review, event, "manual-decision-review", self.repository.add_decision_review)
        return review.id

    @staticmethod
    def _normalize_alternatives(items: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        normalized = []
        seen = set()
        for index, item in enumerate(items):
            if not isinstance(item, Mapping):
                raise DecisionError(f"alternative {index} must be an object")
            unknown = set(item) - {"key", "description", "selected"}
            if unknown:
                raise DecisionError(f"alternative {index} has unknown fields: {', '.join(sorted(unknown))}")
            key = str(item.get("key", "")).strip()
            if not key or key in seen:
                raise DecisionError("alternative keys must be non-empty and unique")
            seen.add(key)
            normalized.append(
                {
                    "key": key,
                    "description": str(item.get("description", "")).strip(),
                    "selected": bool(item.get("selected", False)),
                }
            )
        return normalized

    @staticmethod
    def _normalize_statements(*groups: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
        kinds = ("assumption", "expected_outcome", "invalidation_condition")
        result = []
        for kind, items in zip(kinds, groups):
            for index, item in enumerate(items):
                if set(item) - {"key", "text"}:
                    raise DecisionError(f"{kind} {index} has unknown fields")
                key, text = str(item.get("key", "")).strip(), str(item.get("text", "")).strip()
                if not key or not text:
                    raise DecisionError(f"{kind} requires key and text")
                result.append({"kind": kind, "key": key, "text": text})
        return result

    @staticmethod
    def _normalize_schedule(items: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
        return [{"review_type": str(item["review_type"]), "due_at": canonical_timestamp(item["due_at"])} for item in items]

    def _write_link(self, object_value: Any, event: Mapping[str, Any], adapter: str, writer: Any) -> None:
        with self.repository.write_transaction():
            artifact_id, _ = self.repository.virtual_artifact(
                f"manual://{adapter}", self._event_json(event)
            )
            self.repository.import_batch(
                artifact_id,
                adapter_name=adapter,
                adapter_version="1",
                schema_version="1",
            )
            writer(object_value)

    @staticmethod
    def _event_json(event: Mapping[str, Any]) -> str:
        return json.dumps(event, sort_keys=True, separators=(",", ":"))
