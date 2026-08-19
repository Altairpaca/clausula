from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .common import canonical_timestamp, dec, require_uuid


POLICY_RULE_TYPES = {
    "allocation_band",
    "max_single_instrument_weight",
    "max_asset_type_weight",
    "min_cash_weight",
    "min_cash_amount",
    "max_currency_weight",
}


def _text(value: str, field: str) -> str:
    result = str(value).strip()
    if not result:
        raise ValueError(f"{field} cannot be empty")
    return result


def _optional_decimal(value: Decimal | str | int | None) -> Decimal | None:
    return None if value is None else dec(value)


@dataclass(frozen=True)
class InvestmentPolicy:
    id: str
    portfolio_id: str
    name: str
    created_at: str
    source_artifact_id: str
    import_batch_id: str

    def __post_init__(self) -> None:
        for field in (
            "id",
            "portfolio_id",
            "source_artifact_id",
            "import_batch_id",
        ):
            object.__setattr__(self, field, require_uuid(getattr(self, field), field))
        object.__setattr__(self, "name", _text(self.name, "policy name"))
        object.__setattr__(self, "created_at", canonical_timestamp(self.created_at))


@dataclass(frozen=True)
class PolicyVersion:
    id: str
    policy_id: str
    version_number: int
    effective_from: str
    known_at: str
    recorded_at: str
    rules_sha256: str
    source_artifact_id: str
    import_batch_id: str

    def __post_init__(self) -> None:
        for field in (
            "id",
            "policy_id",
            "source_artifact_id",
            "import_batch_id",
        ):
            object.__setattr__(self, field, require_uuid(getattr(self, field), field))
        if (
            isinstance(self.version_number, bool)
            or not isinstance(self.version_number, int)
            or self.version_number < 1
        ):
            raise ValueError("policy version_number must be a positive integer")
        object.__setattr__(self, "effective_from", canonical_timestamp(self.effective_from))
        object.__setattr__(self, "known_at", canonical_timestamp(self.known_at))
        object.__setattr__(self, "recorded_at", canonical_timestamp(self.recorded_at))
        if self.known_at > self.recorded_at:
            raise ValueError("known_at cannot be after recorded_at")
        digest = self.rules_sha256.lower()
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError("rules_sha256 must be a lowercase hexadecimal digest")
        object.__setattr__(self, "rules_sha256", digest)


@dataclass(frozen=True)
class PolicyRule:
    id: str
    policy_version_id: str
    rule_key: str
    rule_type: str
    severity: str
    description: str = ""
    subject: str | None = None
    target: Decimal | None = None
    lower_bound: Decimal | None = None
    upper_bound: Decimal | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", require_uuid(self.id, "rule id"))
        object.__setattr__(
            self,
            "policy_version_id",
            require_uuid(self.policy_version_id, "policy_version_id"),
        )
        object.__setattr__(self, "rule_key", _text(self.rule_key, "rule_key"))
        rule_type = _text(self.rule_type, "rule_type").lower()
        if rule_type not in POLICY_RULE_TYPES:
            raise ValueError(f"unsupported policy rule type: {rule_type}")
        object.__setattr__(self, "rule_type", rule_type)
        severity = _text(self.severity, "severity").lower()
        if severity not in {"hard", "soft"}:
            raise ValueError("policy rule severity must be hard or soft")
        object.__setattr__(self, "severity", severity)
        object.__setattr__(self, "description", str(self.description).strip())
        subject = None if self.subject is None else _text(self.subject, "subject")
        if rule_type == "max_currency_weight" and subject is not None:
            subject = subject.upper()
        elif rule_type in {"allocation_band", "max_asset_type_weight"} and subject is not None:
            subject = subject.lower()
        object.__setattr__(self, "subject", subject)
        for field in ("target", "lower_bound", "upper_bound"):
            object.__setattr__(self, field, _optional_decimal(getattr(self, field)))
        self._validate_semantics()

    def _validate_semantics(self) -> None:
        percentage_fields = (self.target, self.lower_bound, self.upper_bound)
        if self.rule_type != "min_cash_amount":
            for value in percentage_fields:
                if value is not None and not Decimal(0) <= value <= Decimal(1):
                    raise ValueError("policy weight thresholds must be between 0 and 1")
        elif self.lower_bound is not None and self.lower_bound < 0:
            raise ValueError("minimum cash amount cannot be negative")

        if self.rule_type == "allocation_band":
            if self.subject is None or None in (
                self.target,
                self.lower_bound,
                self.upper_bound,
            ):
                raise ValueError("allocation_band requires subject, target, lower, and upper")
            if not self.lower_bound <= self.target <= self.upper_bound:
                raise ValueError("allocation band must satisfy lower <= target <= upper")
            return
        if self.rule_type in {"max_asset_type_weight", "max_currency_weight"}:
            if self.subject is None or self.upper_bound is None:
                raise ValueError(f"{self.rule_type} requires subject and upper")
            if self.target is not None or self.lower_bound is not None:
                raise ValueError(f"{self.rule_type} only accepts subject and upper")
            return
        if self.rule_type == "max_single_instrument_weight":
            if self.upper_bound is None:
                raise ValueError("max_single_instrument_weight requires upper")
            if (
                self.subject is not None
                or self.target is not None
                or self.lower_bound is not None
            ):
                raise ValueError("max_single_instrument_weight only accepts upper")
            return
        if self.rule_type in {"min_cash_weight", "min_cash_amount"}:
            if self.lower_bound is None:
                raise ValueError(f"{self.rule_type} requires lower")
            if (
                self.subject is not None
                or self.target is not None
                or self.upper_bound is not None
            ):
                raise ValueError(f"{self.rule_type} only accepts lower")


@dataclass(frozen=True)
class PolicyEvidence:
    kind: str
    subject: str
    observed_value: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _text(self.kind, "evidence kind"))
        object.__setattr__(self, "subject", _text(self.subject, "evidence subject"))
        object.__setattr__(self, "observed_value", dec(self.observed_value))


@dataclass(frozen=True)
class PolicyRuleResult:
    rule_id: str
    rule_key: str
    rule_type: str
    severity: str
    status: str
    current_value: Decimal | None
    target: Decimal | None
    lower_bound: Decimal | None
    upper_bound: Decimal | None
    evidence: tuple[PolicyEvidence, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "rule_id", require_uuid(self.rule_id, "rule_id"))
        if self.status not in {"compliant", "violation", "unavailable"}:
            raise ValueError("rule result status is invalid")
        for field in ("current_value", "target", "lower_bound", "upper_bound"):
            object.__setattr__(self, field, _optional_decimal(getattr(self, field)))


@dataclass(frozen=True)
class PolicyEvaluation:
    id: str
    policy_version_id: str
    portfolio_id: str
    as_of: str
    known_as_of: str
    status: str
    results: tuple[PolicyRuleResult, ...]

    def __post_init__(self) -> None:
        for field in ("id", "policy_version_id", "portfolio_id"):
            object.__setattr__(self, field, require_uuid(getattr(self, field), field))
        object.__setattr__(self, "as_of", canonical_timestamp(self.as_of))
        object.__setattr__(self, "known_as_of", canonical_timestamp(self.known_as_of))
        if self.status not in {"compliant", "violation", "unavailable"}:
            raise ValueError("policy evaluation status is invalid")
