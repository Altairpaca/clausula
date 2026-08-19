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
