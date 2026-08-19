from __future__ import annotations

from dataclasses import dataclass

from .common import canonical_timestamp, require_uuid


def _text(value: str, field: str) -> str:
    result = str(value).strip()
    if not result:
        raise ValueError(f"{field} cannot be empty")
    return result


@dataclass(frozen=True)
class Portfolio:
    id: str
    name: str
    base_currency: str
    created_at: str
    source_artifact_id: str
    import_batch_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", require_uuid(self.id, "portfolio id"))
        object.__setattr__(self, "name", _text(self.name, "portfolio name"))
        object.__setattr__(self, "base_currency", _text(self.base_currency, "base_currency").upper())
        object.__setattr__(self, "created_at", canonical_timestamp(self.created_at))
        object.__setattr__(
            self,
            "source_artifact_id",
            require_uuid(self.source_artifact_id, "source_artifact_id"),
        )
        object.__setattr__(
            self,
            "import_batch_id",
            require_uuid(self.import_batch_id, "import_batch_id"),
        )


@dataclass(frozen=True)
class PortfolioMembershipEvent:
    id: str
    portfolio_id: str
    account_id: str
    action: str
    effective_at: str
    known_at: str
    recorded_at: str
    source_artifact_id: str
    import_batch_id: str

    def __post_init__(self) -> None:
        for field in ("id", "portfolio_id", "account_id"):
            object.__setattr__(self, field, require_uuid(getattr(self, field), field))
        object.__setattr__(self, "action", _text(self.action, "action").lower())
        if self.action not in {"add", "remove"}:
            raise ValueError("membership action must be add or remove")
        object.__setattr__(self, "effective_at", canonical_timestamp(self.effective_at))
        object.__setattr__(self, "known_at", canonical_timestamp(self.known_at))
        object.__setattr__(self, "recorded_at", canonical_timestamp(self.recorded_at))
        if self.known_at > self.recorded_at:
            raise ValueError("known_at cannot be after recorded_at")
        object.__setattr__(
            self,
            "source_artifact_id",
            require_uuid(self.source_artifact_id, "source_artifact_id"),
        )
        object.__setattr__(
            self,
            "import_batch_id",
            require_uuid(self.import_batch_id, "import_batch_id"),
        )
