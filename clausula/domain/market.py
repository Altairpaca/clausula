from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import hashlib
from typing import Any

from .common import canonical_decimal, canonical_timestamp, dec, new_id, require_uuid


def _text(value: str, field: str) -> str:
    result = str(value).strip()
    if not result:
        raise ValueError(f"{field} cannot be empty")
    return result


@dataclass(frozen=True)
class DatasetVersion:
    id: str
    dataset_name: str
    version: str
    provider: str
    adapter_name: str
    adapter_version: str
    schema_version: str
    source_artifact_id: str
    import_batch_id: str
    manifest_sha256: str
    manifest_json: str
    recorded_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", require_uuid(self.id, "dataset id"))
        object.__setattr__(self, "dataset_name", _text(self.dataset_name, "dataset_name"))
        object.__setattr__(self, "version", _text(self.version, "dataset version"))
        object.__setattr__(self, "provider", _text(self.provider, "provider"))
        object.__setattr__(self, "adapter_name", _text(self.adapter_name, "adapter_name"))
        object.__setattr__(self, "adapter_version", _text(self.adapter_version, "adapter_version"))
        object.__setattr__(self, "schema_version", _text(self.schema_version, "schema_version"))
        object.__setattr__(self, "source_artifact_id", require_uuid(self.source_artifact_id, "source_artifact_id"))
        object.__setattr__(self, "import_batch_id", require_uuid(self.import_batch_id, "import_batch_id"))
        digest = self.manifest_sha256.lower()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("manifest_sha256 must be a lowercase hexadecimal digest")
        object.__setattr__(self, "manifest_sha256", digest)
        if hashlib.sha256(self.manifest_json.encode("utf-8")).hexdigest() != digest:
            raise ValueError("manifest content does not match manifest_sha256")
        object.__setattr__(self, "recorded_at", canonical_timestamp(self.recorded_at))


@dataclass(frozen=True)
class MarketPrice:
    id: str
    dataset_id: str
    instrument_id: str
    observed_at: str
    known_at: str
    recorded_at: str
    close: Decimal
    currency: str
    quality: str = "accepted"

    def __post_init__(self) -> None:
        for field in ("id", "dataset_id", "instrument_id"):
            object.__setattr__(self, field, require_uuid(getattr(self, field), field))
        object.__setattr__(self, "observed_at", canonical_timestamp(self.observed_at))
        object.__setattr__(self, "known_at", canonical_timestamp(self.known_at))
        object.__setattr__(self, "recorded_at", canonical_timestamp(self.recorded_at))
        if self.known_at > self.recorded_at:
            raise ValueError("known_at cannot be after recorded_at")
        if self.known_at < self.observed_at:
            raise ValueError("known_at cannot be before observed_at")
        object.__setattr__(self, "close", dec(self.close))
        if self.close <= 0:
            raise ValueError("market close must be positive")
        object.__setattr__(self, "currency", _text(self.currency, "currency").upper())
        object.__setattr__(self, "quality", _text(self.quality, "quality").lower())
        if self.quality not in {"accepted", "suspect", "rejected"}:
            raise ValueError("quality must be accepted, suspect, or rejected")


@dataclass(frozen=True)
class FxRate:
    id: str
    dataset_id: str
    observed_at: str
    known_at: str
    recorded_at: str
    from_currency: str
    to_currency: str
    rate: Decimal
    quality: str = "accepted"

    def __post_init__(self) -> None:
        for field in ("id", "dataset_id"):
            object.__setattr__(self, field, require_uuid(getattr(self, field), field))
        object.__setattr__(self, "observed_at", canonical_timestamp(self.observed_at))
        object.__setattr__(self, "known_at", canonical_timestamp(self.known_at))
        object.__setattr__(self, "recorded_at", canonical_timestamp(self.recorded_at))
        if self.known_at > self.recorded_at:
            raise ValueError("known_at cannot be after recorded_at")
        if self.known_at < self.observed_at:
            raise ValueError("known_at cannot be before observed_at")
        object.__setattr__(self, "from_currency", _text(self.from_currency, "from_currency").upper())
        object.__setattr__(self, "to_currency", _text(self.to_currency, "to_currency").upper())
        if self.from_currency == self.to_currency:
            raise ValueError("FX currencies must be distinct")
        object.__setattr__(self, "rate", dec(self.rate))
        if self.rate <= 0:
            raise ValueError("FX rate must be positive")
        object.__setattr__(self, "quality", _text(self.quality, "quality").lower())
        if self.quality not in {"accepted", "suspect", "rejected"}:
            raise ValueError("quality must be accepted, suspect, or rejected")


@dataclass(frozen=True)
class ValuationGap:
    kind: str
    identifier: str
    reason: str

    def as_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "identifier": self.identifier, "reason": self.reason}
