from __future__ import annotations

from dataclasses import dataclass

from .common import canonical_timestamp, require_uuid


def _text(value: str, field: str) -> str:
    result = str(value).strip()
    if not result:
        raise ValueError(f"{field} cannot be empty")
    return result


@dataclass(frozen=True)
class Decision:
    id: str
    portfolio_id: str
    title: str
    intent: str
    rationale: str
    as_of: str
    known_as_of: str
    created_at: str
    policy_version_id: str | None
    plan_id: str | None
    source_artifact_id: str
    import_batch_id: str

    def __post_init__(self) -> None:
        for field in ("id", "portfolio_id", "source_artifact_id", "import_batch_id"):
            object.__setattr__(self, field, require_uuid(getattr(self, field), field))
        for field in ("policy_version_id", "plan_id"):
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(self, field, require_uuid(value, field))
        object.__setattr__(self, "title", _text(self.title, "decision title"))
        object.__setattr__(self, "intent", _text(self.intent, "decision intent").lower())
        if self.intent not in {"trade", "non_trade"}:
            raise ValueError("decision intent must be trade or non_trade")
        object.__setattr__(self, "rationale", str(self.rationale).strip())
        for field in ("as_of", "known_as_of", "created_at"):
            object.__setattr__(self, field, canonical_timestamp(getattr(self, field)))


@dataclass(frozen=True)
class DecisionAlternative:
    id: str
    decision_id: str
    alternative_key: str
    description: str
    selected: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", require_uuid(self.id, "alternative id"))
        object.__setattr__(self, "decision_id", require_uuid(self.decision_id, "decision_id"))
        object.__setattr__(self, "alternative_key", _text(self.alternative_key, "alternative key"))
        object.__setattr__(self, "description", _text(self.description, "alternative description"))
        if not isinstance(self.selected, bool):
            raise ValueError("alternative selected must be boolean")


@dataclass(frozen=True)
class DecisionPolicyLink:
    id: str
    decision_id: str
    policy_version_id: str
    link_type: str

    def __post_init__(self) -> None:
        for field in ("id", "decision_id", "policy_version_id"):
            object.__setattr__(self, field, require_uuid(getattr(self, field), field))
        object.__setattr__(self, "link_type", _text(self.link_type, "policy link type"))


@dataclass(frozen=True)
class DecisionEvidenceLink:
    id: str
    decision_id: str
    evidence_id: str
    evidence_kind: str
    relation: str

    def __post_init__(self) -> None:
        for field in ("id", "decision_id", "evidence_id"):
            object.__setattr__(self, field, require_uuid(getattr(self, field), field))
        object.__setattr__(self, "evidence_kind", _text(self.evidence_kind, "evidence kind"))
        object.__setattr__(self, "relation", _text(self.relation, "evidence relation").lower())
        if self.relation not in {"supports", "contradicts", "context"}:
            raise ValueError("evidence relation is invalid")


@dataclass(frozen=True)
class DecisionTransactionLink:
    id: str
    decision_id: str
    transaction_id: str
    relation: str
    linked_at: str

    def __post_init__(self) -> None:
        for field in ("id", "decision_id", "transaction_id"):
            object.__setattr__(self, field, require_uuid(getattr(self, field), field))
        object.__setattr__(self, "relation", _text(self.relation, "transaction relation"))
        object.__setattr__(self, "linked_at", canonical_timestamp(self.linked_at))


@dataclass(frozen=True)
class DecisionReview:
    id: str
    decision_id: str
    review_type: str
    score: int | None
    notes: str
    reviewed_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", require_uuid(self.id, "review id"))
        object.__setattr__(self, "decision_id", require_uuid(self.decision_id, "decision_id"))
        object.__setattr__(self, "review_type", _text(self.review_type, "review type").lower())
        if self.review_type not in {"process", "outcome"}:
            raise ValueError("review type must be process or outcome")
        if self.score is not None and (
            isinstance(self.score, bool) or not isinstance(self.score, int) or not 1 <= self.score <= 5
        ):
            raise ValueError("review score must be an integer from 1 to 5")
        object.__setattr__(self, "notes", str(self.notes).strip())
        object.__setattr__(self, "reviewed_at", canonical_timestamp(self.reviewed_at))


@dataclass(frozen=True)
class DecisionStatement:
    id: str
    decision_id: str
    kind: str
    statement_key: str
    text: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", require_uuid(self.id, "statement id"))
        object.__setattr__(self, "decision_id", require_uuid(self.decision_id, "decision_id"))
        object.__setattr__(self, "kind", _text(self.kind, "statement kind").lower())
        if self.kind not in {"assumption", "expected_outcome", "invalidation_condition"}:
            raise ValueError("decision statement kind is invalid")
        object.__setattr__(self, "statement_key", _text(self.statement_key, "statement key"))
        object.__setattr__(self, "text", _text(self.text, "statement text"))


@dataclass(frozen=True)
class DecisionReviewSchedule:
    id: str
    decision_id: str
    review_type: str
    due_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", require_uuid(self.id, "review schedule id"))
        object.__setattr__(self, "decision_id", require_uuid(self.decision_id, "decision_id"))
        object.__setattr__(self, "review_type", _text(self.review_type, "review type").lower())
        if self.review_type not in {"process", "outcome"}:
            raise ValueError("review schedule type is invalid")
        object.__setattr__(self, "due_at", canonical_timestamp(self.due_at))
