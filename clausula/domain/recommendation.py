from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .common import canonical_decimal, canonical_timestamp, require_uuid


class RecommendationStatus(StrEnum):
    DRAFT = "draft"
    REVIEWED = "reviewed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"


class RecommendationOrigin(StrEnum):
    RULE = "rule"
    AGENT = "agent"


@dataclass(frozen=True, slots=True)
class Recommendation:
    id: str
    portfolio_id: str
    subject: str
    recommendation_type: str
    rationale: str
    origin: RecommendationOrigin
    status: RecommendationStatus
    as_of: str
    known_as_of: str
    created_at: str
    payload_json: str
    source_artifact_id: str
    import_batch_id: str

    def __post_init__(self) -> None:
        for field in ("id", "portfolio_id", "source_artifact_id", "import_batch_id"):
            object.__setattr__(self, field, require_uuid(getattr(self, field), field))
        for field in ("subject", "recommendation_type", "rationale", "payload_json"):
            value = str(getattr(self, field)).strip()
            if not value:
                raise ValueError(f"recommendation {field} cannot be empty")
            object.__setattr__(self, field, value)
        for field in ("as_of", "known_as_of", "created_at"):
            object.__setattr__(self, field, canonical_timestamp(getattr(self, field)))


@dataclass(frozen=True, slots=True)
class RecommendationAlternative:
    id: str
    recommendation_id: str
    key: str
    description: str
    selected: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", require_uuid(self.id, "alternative id"))
        object.__setattr__(
            self, "recommendation_id", require_uuid(self.recommendation_id, "recommendation_id")
        )
        for field in ("key", "description"):
            value = str(getattr(self, field)).strip()
            if not value:
                raise ValueError(f"recommendation alternative {field} cannot be empty")
            object.__setattr__(self, field, value)
        if not isinstance(self.selected, bool):
            raise ValueError("recommendation alternative selected must be boolean")
