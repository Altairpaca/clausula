from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .common import canonical_timestamp, dec, require_uuid


def _text(value: str, field: str) -> str:
    result = str(value).strip()
    if not result:
        raise ValueError(f"{field} cannot be empty")
    return result


@dataclass(frozen=True)
class Plan:
    id: str
    portfolio_id: str
    policy_id: str
    policy_version_id: str
    name: str
    as_of: str
    known_as_of: str
    created_at: str
    source_artifact_id: str
    import_batch_id: str

    def __post_init__(self) -> None:
        for field in (
            "id",
            "portfolio_id",
            "policy_id",
            "policy_version_id",
            "source_artifact_id",
            "import_batch_id",
        ):
            object.__setattr__(self, field, require_uuid(getattr(self, field), field))
        object.__setattr__(self, "name", _text(self.name, "plan name"))
        for field in ("as_of", "known_as_of", "created_at"):
            object.__setattr__(self, field, canonical_timestamp(getattr(self, field)))


@dataclass(frozen=True)
class PlanScenario:
    id: str
    plan_id: str
    scenario_key: str
    description: str
    cash_available: Decimal
    total_fees: Decimal
    total_tax_estimate: Decimal
    status: str
    projected_total: Decimal | None
    result_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", require_uuid(self.id, "scenario id"))
        object.__setattr__(self, "plan_id", require_uuid(self.plan_id, "plan_id"))
        object.__setattr__(self, "scenario_key", _text(self.scenario_key, "scenario key"))
        object.__setattr__(self, "description", str(self.description).strip())
        object.__setattr__(self, "cash_available", dec(self.cash_available))
        object.__setattr__(self, "total_fees", dec(self.total_fees))
        object.__setattr__(self, "total_tax_estimate", dec(self.total_tax_estimate))
        if self.cash_available < 0 or self.total_fees < 0 or self.total_tax_estimate < 0:
            raise ValueError("scenario cash, fees, and tax estimates cannot be negative")
        if self.status not in {"feasible", "violates_policy", "unavailable", "rejected"}:
            raise ValueError("scenario status is invalid")
        if self.projected_total is not None:
            object.__setattr__(self, "projected_total", dec(self.projected_total))
            if self.projected_total < 0:
                raise ValueError("scenario projected_total cannot be negative")
        digest = str(self.result_sha256).lower()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("scenario result_sha256 must be a hexadecimal digest")
        object.__setattr__(self, "result_sha256", digest)


@dataclass(frozen=True)
class CandidateAction:
    id: str
    scenario_id: str
    sequence: int
    instrument_id: str
    base_value_delta: Decimal
    fee: Decimal
    tax_estimate: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", require_uuid(self.id, "candidate action id"))
        object.__setattr__(self, "scenario_id", require_uuid(self.scenario_id, "scenario_id"))
        object.__setattr__(self, "instrument_id", require_uuid(self.instrument_id, "instrument_id"))
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 0:
            raise ValueError("candidate action sequence must be a non-negative integer")
        object.__setattr__(self, "base_value_delta", dec(self.base_value_delta))
        object.__setattr__(self, "fee", dec(self.fee))
        object.__setattr__(self, "tax_estimate", dec(self.tax_estimate))
        if self.base_value_delta == 0:
            raise ValueError("candidate action delta cannot be zero")
        if self.fee < 0 or self.tax_estimate < 0:
            raise ValueError("candidate action fee and tax estimate cannot be negative")


@dataclass(frozen=True)
class ProjectedState:
    id: str
    scenario_id: str
    complete: bool
    total_value: Decimal | None
    valuation_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", require_uuid(self.id, "projected state id"))
        object.__setattr__(self, "scenario_id", require_uuid(self.scenario_id, "scenario_id"))
        if not isinstance(self.complete, bool):
            raise ValueError("projected state complete must be boolean")
        if self.total_value is not None:
            object.__setattr__(self, "total_value", dec(self.total_value))
            if self.total_value < 0:
                raise ValueError("projected state total_value cannot be negative")
        if self.complete and self.total_value is None:
            raise ValueError("complete projected state requires total_value")
        digest = str(self.valuation_sha256).lower()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("valuation_sha256 must be a hexadecimal digest")
        object.__setattr__(self, "valuation_sha256", digest)


@dataclass(frozen=True)
class UnresolvedConstraint:
    id: str
    scenario_id: str
    rule_id: str | None
    rule_key: str
    severity: str
    status: str
    kind: str
    gap: Decimal | None
    explanation: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", require_uuid(self.id, "constraint id"))
        object.__setattr__(self, "scenario_id", require_uuid(self.scenario_id, "scenario_id"))
        if self.rule_id is not None:
            object.__setattr__(self, "rule_id", require_uuid(self.rule_id, "rule_id"))
        object.__setattr__(self, "rule_key", _text(self.rule_key, "rule key"))
        object.__setattr__(self, "severity", _text(self.severity, "constraint severity").lower())
        if self.severity not in {"hard", "soft"}:
            raise ValueError("constraint severity must be hard or soft")
        if self.status not in {"violation", "unavailable"}:
            raise ValueError("constraint status is invalid")
        object.__setattr__(self, "kind", _text(self.kind, "constraint kind"))
        if self.gap is not None:
            object.__setattr__(self, "gap", dec(self.gap))
            if self.gap < 0:
                raise ValueError("constraint gap cannot be negative")
        object.__setattr__(self, "explanation", _text(self.explanation, "constraint explanation"))
