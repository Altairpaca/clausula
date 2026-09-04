from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping, Protocol, Sequence

from clausula.domain import (
    DatasetVersion,
    InstrumentIdentifier,
    MarketPrice,
    canonical_decimal,
    canonical_timestamp,
    dec,
    new_id,
    now,
)

from .market import MARKET_CSV_ADAPTER_VERSION, MARKET_SCHEMA_VERSION, RETURN_SEMANTICS
from .ports import CoreRepository


@dataclass(frozen=True, slots=True)
class ProviderPrice:
    identifier: str
    observed_at: str
    known_at: str
    close: str
    currency: str = "USD"
    identifier_scheme: str = "ticker"
    instrument_name: str = ""
    asset_type: str = "stock"
    quality: str = "accepted"
    return_index: str | None = None
    return_semantics: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderSnapshot:
    provider: str
    dataset_name: str
    version: str
    observations: Sequence[ProviderPrice]
    raw_payload: Mapping[str, Any]
    adapter_name: str = "provider-snapshot"
    adapter_version: str = "1"
    schema_version: str = "1"


class MarketProvider(Protocol):
    """Network/provider plugins implement this outside the deterministic kernel."""

    def snapshot(self) -> ProviderSnapshot: ...


class ProviderSnapshotImporter:
    """Capture raw provider payload before converting it to canonical market rows."""

    def __init__(self, repository: CoreRepository):
        self.repository = repository

    @staticmethod
    def _text(value: str, field: str) -> str:
        result = str(value).strip()
        if not result:
            raise ValueError(f"{field} cannot be empty")
        return result

    def import_snapshot(self, snapshot: ProviderSnapshot) -> dict[str, Any]:
        provider = self._text(snapshot.provider, "provider")
        dataset_name = self._text(snapshot.dataset_name, "dataset_name")
        version = self._text(snapshot.version, "version")
        if not snapshot.observations:
            raise ValueError("provider snapshot requires at least one observation")
        recorded_at = now()

        raw_json = json.dumps(
            dict(snapshot.raw_payload),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        artifact_id, raw_digest = self.repository.virtual_artifact(
            f"provider://{provider}/{dataset_name}/{version}", raw_json
        )
        batch_id = new_id()
        dataset_id = new_id()
        rows: list[dict[str, Any]] = []
        prices: list[MarketPrice] = []
        seen: set[tuple[str, str, str]] = set()

        for index, observation in enumerate(snapshot.observations, 1):
            identifier = self._text(observation.identifier, "identifier")
            scheme = self._text(observation.identifier_scheme, "identifier_scheme")
            observed_at = canonical_timestamp(observation.observed_at)
            known_at = canonical_timestamp(observation.known_at)
            close = canonical_decimal(observation.close)
            if known_at > recorded_at:
                raise ValueError("provider known_at cannot be after import recorded_at")
            if known_at < observed_at:
                raise ValueError("provider known_at cannot be before observed_at")
            if dec(close) <= 0:
                raise ValueError("provider close must be positive")
            key = (scheme, identifier, observed_at)
            if key in seen:
                raise ValueError("duplicate provider price observation")
            seen.add(key)

            return_index = None
            return_semantics = None
            if observation.return_index is not None or observation.return_semantics is not None:
                if observation.return_index is None or observation.return_semantics is None:
                    raise ValueError(
                        "provider return_index and return_semantics must be provided together"
                    )
                return_semantics = str(observation.return_semantics).strip().lower()
                if return_semantics not in RETURN_SEMANTICS:
                    raise ValueError(
                        "provider return_semantics must be price_return or total_return"
                    )
                return_index = canonical_decimal(observation.return_index)
                if dec(return_index) <= 0:
                    raise ValueError("provider return_index must be positive")

            instrument_id = self.repository.instrument(
                InstrumentIdentifier(identifier, scheme),
                observation.instrument_name,
                observation.asset_type,
                observation.currency,
            )
            quality = str(observation.quality).strip().lower()
            prices.append(
                MarketPrice(
                    new_id(),
                    dataset_id,
                    instrument_id,
                    observed_at,
                    known_at,
                    recorded_at,
                    close,
                    observation.currency,
                    quality,
                )
            )
            rows.append(
                {
                    "row_number": index,
                    "identifier": identifier,
                    "identifier_scheme": scheme,
                    "instrument_name": observation.instrument_name,
                    "asset_type": observation.asset_type,
                    "observed_at": observed_at,
                    "known_at": known_at,
                    "close": close,
                    "currency": str(observation.currency).upper(),
                    "quality": quality,
                    "return_index": return_index,
                    "return_semantics": return_semantics,
                }
            )

        manifest_data = {
            "dataset_name": dataset_name,
            "version": version,
            "provider": provider,
            "adapter": snapshot.adapter_name,
            "adapter_version": snapshot.adapter_version,
            "schema": snapshot.schema_version,
            "raw_payload_sha256": raw_digest,
            "return_series": {
                "present": any(row["return_index"] is not None for row in rows),
                "semantics": sorted(
                    {
                        row["return_semantics"]
                        for row in rows
                        if row["return_semantics"] is not None
                    }
                ),
            },
            "rows": rows,
        }
        manifest_json = json.dumps(
            manifest_data, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        manifest_sha256 = hashlib.sha256(manifest_json.encode("utf-8")).hexdigest()
        dataset = DatasetVersion(
            dataset_id,
            dataset_name,
            version,
            provider,
            snapshot.adapter_name,
            snapshot.adapter_version,
            snapshot.schema_version,
            artifact_id,
            batch_id,
            manifest_sha256,
            manifest_json,
            recorded_at,
        )
        return self.repository.add_market_dataset(dataset, prices, ())

    def import_provider(self, provider: MarketProvider) -> dict[str, Any]:
        return self.import_snapshot(provider.snapshot())
