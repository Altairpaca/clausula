from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from .common import canonical_timestamp, dec, require_uuid


def _required_text(value: str, field: str) -> str:
    result = str(value).strip()
    if not result:
        raise ValueError(f"{field} cannot be empty")
    return result


@dataclass(frozen=True)
class TemporalMetadata:
    effective_at: str
    known_at: str
    recorded_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "effective_at", canonical_timestamp(self.effective_at))
        object.__setattr__(self, "known_at", canonical_timestamp(self.known_at))
        object.__setattr__(self, "recorded_at", canonical_timestamp(self.recorded_at))
        if self.known_at > self.recorded_at:
            raise ValueError("known_at cannot be after recorded_at")


@dataclass(frozen=True)
class SourceArtifactRef:
    artifact_id: str
    sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_id", require_uuid(self.artifact_id, "artifact_id"))
        digest = self.sha256.lower()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("sha256 must be a lowercase hexadecimal digest")
        object.__setattr__(self, "sha256", digest)


@dataclass(frozen=True)
class ImportBatchRef:
    batch_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "batch_id", require_uuid(self.batch_id, "batch_id"))


@dataclass(frozen=True)
class InstrumentIdentifier:
    value: str
    scheme: str = "ticker"

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _required_text(self.value, "identifier value"))
        object.__setattr__(self, "scheme", _required_text(self.scheme, "identifier scheme").lower())


@dataclass(frozen=True)
class Instrument:
    id: str
    identifier: InstrumentIdentifier
    name: str
    asset_type: str
    currency: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", require_uuid(self.id, "instrument id"))
        object.__setattr__(self, "name", _required_text(self.name, "instrument name"))
        object.__setattr__(self, "asset_type", _required_text(self.asset_type, "asset_type").lower())
        object.__setattr__(self, "currency", _required_text(self.currency, "currency").upper())


@dataclass(frozen=True)
class TransactionLeg:
    account_id: str
    instrument_id: str | None
    quantity: Decimal
    amount: Decimal
    currency: str
    leg_type: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "account_id", require_uuid(self.account_id, "leg account_id"))
        if self.instrument_id is not None:
            object.__setattr__(self, "instrument_id", require_uuid(self.instrument_id, "instrument_id"))
        object.__setattr__(self, "quantity", dec(self.quantity))
        object.__setattr__(self, "amount", dec(self.amount))
        object.__setattr__(self, "currency", _required_text(self.currency, "currency").upper())
        object.__setattr__(self, "leg_type", _required_text(self.leg_type, "leg_type").lower())


@dataclass(frozen=True)
class Transaction:
    id: str
    account_id: str
    type: str
    effective_at: str
    known_at: str
    recorded_at: str
    description: str
    source_artifact_id: str
    import_batch_id: str
    legs: tuple[TransactionLeg, ...]
    corrects_transaction_id: str | None = None
    source_sequence: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", require_uuid(self.id, "transaction id"))
        object.__setattr__(self, "account_id", require_uuid(self.account_id, "account_id"))
        object.__setattr__(self, "type", _required_text(self.type, "transaction type").lower())
        object.__setattr__(self, "effective_at", canonical_timestamp(self.effective_at))
        object.__setattr__(self, "known_at", canonical_timestamp(self.known_at))
        object.__setattr__(self, "recorded_at", canonical_timestamp(self.recorded_at))
        if self.known_at > self.recorded_at:
            raise ValueError("known_at cannot be after recorded_at")
        object.__setattr__(self, "description", str(self.description).strip())
        object.__setattr__(self, "source_artifact_id", require_uuid(self.source_artifact_id, "source_artifact_id"))
        object.__setattr__(self, "import_batch_id", require_uuid(self.import_batch_id, "import_batch_id"))
        object.__setattr__(self, "legs", tuple(self.legs))
        if not self.legs:
            raise ValueError("a transaction requires at least one leg")
        if any(leg.account_id != self.account_id for leg in self.legs):
            raise ValueError("all transaction legs must belong to the transaction account")
        if self.corrects_transaction_id is not None:
            object.__setattr__(
                self,
                "corrects_transaction_id",
                require_uuid(self.corrects_transaction_id, "corrects_transaction_id"),
            )
            if self.type != "correction":
                raise ValueError("only correction transactions may reference a corrected transaction")
        if isinstance(self.source_sequence, bool) or not isinstance(self.source_sequence, int):
            raise ValueError("source_sequence must be an integer")
        if self.source_sequence < 0:
            raise ValueError("source_sequence must not be negative")


@dataclass(frozen=True)
class PositionState:
    account_id: str
    instrument_id: str
    quantity: Decimal
    cash: Decimal
    as_of: str


@dataclass(frozen=True)
class ReconciliationResult:
    account_id: str
    as_of: str
    differences: tuple[dict[str, Any], ...]
    record_id: str | None = None


@dataclass(frozen=True)
class FxConversion:
    transaction_id: str
    from_currency: str
    to_currency: str
    from_amount: Decimal
    to_amount: Decimal
    rate: Decimal
    fee: Decimal = Decimal(0)
    fee_currency: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "transaction_id", require_uuid(self.transaction_id, "transaction_id"))
        object.__setattr__(self, "from_currency", _required_text(self.from_currency, "from_currency").upper())
        object.__setattr__(self, "to_currency", _required_text(self.to_currency, "to_currency").upper())
        if self.from_currency == self.to_currency:
            raise ValueError("FX currencies must be distinct")
        object.__setattr__(self, "from_amount", dec(self.from_amount))
        object.__setattr__(self, "to_amount", dec(self.to_amount))
        object.__setattr__(self, "rate", dec(self.rate))
        object.__setattr__(self, "fee", dec(self.fee))
        if self.from_amount <= 0 or self.to_amount <= 0 or self.rate <= 0:
            raise ValueError("FX amounts and rate must be positive")
        if self.fee < 0:
            raise ValueError("FX fee must not be negative")
        if self.rate != self.to_amount / self.from_amount:
            raise ValueError("FX rate must equal to_amount / from_amount")
        if self.fee:
            normalized = _required_text(self.fee_currency or "", "fee_currency").upper()
            if normalized not in {self.from_currency, self.to_currency}:
                raise ValueError("FX fee currency must be one of the converted currencies")
            object.__setattr__(self, "fee_currency", normalized)
        elif self.fee_currency is not None:
            object.__setattr__(self, "fee_currency", self.fee_currency.upper())


@dataclass(frozen=True)
class SecurityTransfer:
    id: str
    source_transaction_id: str
    destination_transaction_id: str
    instrument_id: str
    quantity: Decimal
    carried_basis: Decimal
    currency: str
    allocations: tuple[LotTransferAllocation, ...] = ()

    def __post_init__(self) -> None:
        for field in ("id", "source_transaction_id", "destination_transaction_id", "instrument_id"):
            object.__setattr__(self, field, require_uuid(getattr(self, field), field))
        object.__setattr__(self, "quantity", dec(self.quantity))
        object.__setattr__(self, "carried_basis", dec(self.carried_basis))
        object.__setattr__(self, "currency", _required_text(self.currency, "currency").upper())
        if self.quantity <= 0:
            raise ValueError("security transfer quantity must be positive")
        if self.carried_basis < 0:
            raise ValueError("carried basis must not be negative")
        object.__setattr__(self, "allocations", tuple(self.allocations))
        if self.allocations:
            if sum((item.quantity for item in self.allocations), Decimal(0)) != self.quantity:
                raise ValueError("transfer allocation quantities must equal transferred quantity")
            if sum((item.basis for item in self.allocations), Decimal(0)) != self.carried_basis:
                raise ValueError("transfer allocation basis must equal carried basis")
            if any(item.currency != self.currency for item in self.allocations):
                raise ValueError("transfer allocation currency mismatch")


@dataclass(frozen=True)
class LotTransferAllocation:
    source_transaction_id: str
    acquired_at: str
    quantity: Decimal
    basis: Decimal
    currency: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_transaction_id",
            require_uuid(self.source_transaction_id, "source_transaction_id"),
        )
        object.__setattr__(self, "acquired_at", canonical_timestamp(self.acquired_at))
        object.__setattr__(self, "quantity", dec(self.quantity))
        object.__setattr__(self, "basis", dec(self.basis))
        object.__setattr__(self, "currency", _required_text(self.currency, "currency").upper())
        if self.quantity <= 0 or self.basis < 0:
            raise ValueError("lot transfer quantity must be positive and basis nonnegative")


@dataclass(frozen=True)
class CorporateAction:
    id: str
    transaction_id: str
    instrument_id: str
    action_type: str
    numerator: Decimal
    denominator: Decimal

    def __post_init__(self) -> None:
        for field in ("id", "transaction_id", "instrument_id"):
            object.__setattr__(self, field, require_uuid(getattr(self, field), field))
        object.__setattr__(self, "action_type", _required_text(self.action_type, "action_type").lower())
        object.__setattr__(self, "numerator", dec(self.numerator))
        object.__setattr__(self, "denominator", dec(self.denominator))
        if self.action_type != "split":
            raise ValueError("unsupported corporate action")
        if self.numerator <= 0 or self.denominator <= 0:
            raise ValueError("corporate action ratio must be positive")

    @property
    def ratio(self) -> Decimal:
        return self.numerator / self.denominator


CORPORATE_ACTION_TYPES = frozenset(
    {
        "symbol_change",
        "security_change",
        "merger",
        "cash_merger",
        "stock_merger",
        "mixed_consideration",
        "spin_off",
        "exchange",
        "election",
        "cash_in_lieu",
    }
)


@dataclass(frozen=True)
class ActionInstrumentFact:
    role: str
    instrument_id: str
    sequence: int
    ratio_numerator: Decimal | None = None
    ratio_denominator: Decimal | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", _required_text(self.role, "role").lower())
        if self.role not in {"source", "destination"}:
            raise ValueError("action instrument role must be source or destination")
        object.__setattr__(self, "instrument_id", require_uuid(self.instrument_id, "instrument_id"))
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence <= 0:
            raise ValueError("action instrument sequence must be a positive integer")
        if (self.ratio_numerator is None) != (self.ratio_denominator is None):
            raise ValueError("action instrument ratio requires both numerator and denominator")
        if self.ratio_numerator is not None:
            numerator = dec(self.ratio_numerator)
            denominator = dec(self.ratio_denominator)
            object.__setattr__(self, "ratio_numerator", numerator)
            object.__setattr__(self, "ratio_denominator", denominator)
            if numerator <= 0 or denominator <= 0:
                raise ValueError("action instrument ratio must be positive")


@dataclass(frozen=True)
class ActionConsiderationFact:
    kind: str
    sequence: int
    instrument_id: str | None = None
    currency: str | None = None
    quantity: Decimal | None = None
    amount: Decimal | None = None
    election_key: str | None = None
    provenance: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _required_text(self.kind, "kind").lower())
        if self.kind not in {"security", "cash", "fee", "tax"}:
            raise ValueError("consideration kind must be security, cash, fee, or tax")
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence <= 0:
            raise ValueError("consideration sequence must be a positive integer")
        if self.kind == "security":
            if self.instrument_id is None:
                raise ValueError("security consideration requires instrument_id")
            object.__setattr__(self, "instrument_id", require_uuid(self.instrument_id, "instrument_id"))
            if self.quantity is None or dec(self.quantity) <= 0:
                raise ValueError("security consideration requires a positive quantity")
            object.__setattr__(self, "quantity", dec(self.quantity))
        else:
            if self.currency is None or self.amount is None or dec(self.amount) < 0:
                raise ValueError("cash/fee/tax consideration requires currency and nonnegative amount")
            object.__setattr__(self, "currency", _required_text(self.currency, "currency").upper())
            object.__setattr__(self, "amount", dec(self.amount))
        if self.election_key is not None:
            object.__setattr__(self, "election_key", _required_text(self.election_key, "election_key"))
        object.__setattr__(self, "provenance", str(self.provenance).strip())


@dataclass(frozen=True)
class ActionBasisAllocation:
    source_instrument_id: str
    destination_instrument_id: str | None
    source_quantity: Decimal
    destination_quantity: Decimal
    source_basis: Decimal
    destination_basis: Decimal
    currency: str
    sequence: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_instrument_id", require_uuid(self.source_instrument_id, "source_instrument_id"))
        if self.destination_instrument_id is not None:
            object.__setattr__(
                self,
                "destination_instrument_id",
                require_uuid(self.destination_instrument_id, "destination_instrument_id"),
            )
        object.__setattr__(self, "source_quantity", dec(self.source_quantity))
        object.__setattr__(self, "destination_quantity", dec(self.destination_quantity))
        object.__setattr__(self, "source_basis", dec(self.source_basis))
        object.__setattr__(self, "destination_basis", dec(self.destination_basis))
        object.__setattr__(self, "currency", _required_text(self.currency, "currency").upper())
        for name in ("source_quantity", "destination_quantity", "source_basis", "destination_basis"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must not be negative")
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence <= 0:
            raise ValueError("basis allocation sequence must be a positive integer")


@dataclass(frozen=True)
class ReconciliationObservation:
    kind: str
    value: Decimal
    currency: str | None = None
    instrument_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _required_text(self.kind, "kind").lower())
        object.__setattr__(self, "value", dec(self.value))
        if self.kind == "cash":
            object.__setattr__(self, "currency", _required_text(self.currency or "", "currency").upper())
            if self.instrument_id is not None:
                raise ValueError("cash observation cannot reference an instrument")
        elif self.kind == "position":
            object.__setattr__(self, "instrument_id", require_uuid(self.instrument_id or "", "instrument_id"))
            if self.currency is not None:
                raise ValueError("position observation cannot reference a currency")
        else:
            raise ValueError("observation kind must be cash or position")
