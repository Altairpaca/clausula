from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Mapping

from clausula.domain import (
    DatasetVersion,
    FxRate,
    InstrumentIdentifier,
    MarketPrice,
    canonical_decimal,
    canonical_timestamp,
    dec,
    new_id,
    now,
)

from .ports import CoreRepository


MARKET_CSV_ADAPTER_VERSION = "1"
MARKET_SCHEMA_VERSION = "1"
RETURN_SEMANTICS = {"price_return", "total_return"}


class MarketImportError(ValueError):
    def __init__(self, row_number: int, message: str):
        super().__init__(f"market CSV row {row_number}: {message}")
        self.row_number = row_number


class MarketService:
    def __init__(self, repository: CoreRepository):
        self.repository = repository

    @staticmethod
    def _return_fields(row: Mapping[str, str | None]) -> dict[str, str | None]:
        """Normalize an optional explicit return index without guessing semantics.

        `close` remains the valuation fact. A provider may additionally include
        a positive `return_index` and must declare whether it represents price
        return or total return. Clausula intentionally does not infer total
        return from an adjusted-close-like field whose provider semantics are
        unknown.
        """

        raw_index = (row.get("return_index") or "").strip()
        raw_semantics = (row.get("return_semantics") or "").strip().lower()
        if not raw_index and not raw_semantics:
            return {"return_index": None, "return_semantics": None}
        if not raw_index or not raw_semantics:
            raise ValueError(
                "return_index and return_semantics must be provided together"
            )
        if raw_semantics not in RETURN_SEMANTICS:
            raise ValueError(
                "return_semantics must be price_return or total_return"
            )
        normalized_index = canonical_decimal(raw_index)
        if dec(normalized_index) <= 0:
            raise ValueError("return_index must be positive")
        return {
            "return_index": normalized_index,
            "return_semantics": raw_semantics,
        }

    def import_prices_csv(
        self,
        path: str | Path,
        *,
        dataset_name: str = "daily_prices",
        version: str | None = None,
        provider: str = "local",
    ) -> dict:
        artifact_id, source_digest = self.repository.artifact(path)
        recorded_at = now()
        rows: list[dict] = []
        seen: set[tuple[str, str, str]] = set()
        with Path(path).open(newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None:
                raise MarketImportError(1, "header row is required")
            for row_number, row in enumerate(reader, 2):
                try:
                    observed_at = canonical_timestamp(
                        row.get("observed_at") or row.get("date") or ""
                    )
                    if not (row.get("known_at") or "").strip():
                        raise ValueError("known_at is required")
                    known_at = canonical_timestamp(row["known_at"])
                    close = canonical_decimal(row.get("close") or row.get("price") or "")
                    currency = (row.get("currency") or "USD").strip().upper()
                    identifier = (
                        row.get("ticker") or row.get("instrument") or ""
                    ).strip()
                    if not identifier:
                        raise ValueError("ticker or instrument is required")
                    if dec(close) <= 0:
                        raise ValueError("close must be positive")
                    if known_at > recorded_at:
                        raise ValueError("known_at cannot be after import recorded_at")
                    if known_at < observed_at:
                        raise ValueError("known_at cannot be before observed_at")
                    identifier_scheme = (
                        row.get("identifier_scheme") or "ticker"
                    ).strip()
                    key = (identifier_scheme, identifier, observed_at)
                    if key in seen:
                        raise ValueError("duplicate instrument observation")
                    seen.add(key)
                    rows.append(
                        {
                            "row_number": row_number,
                            "observed_at": observed_at,
                            "known_at": known_at,
                            "close": close,
                            "currency": currency,
                            "identifier": identifier,
                            "identifier_scheme": identifier_scheme,
                            "instrument_name": (
                                row.get("instrument_name") or ""
                            ).strip(),
                            "asset_type": (row.get("asset_type") or "stock").strip(),
                            "quality": (row.get("quality") or "accepted").strip(),
                            **self._return_fields(row),
                        }
                    )
                except (TypeError, ValueError) as exc:
                    raise MarketImportError(row_number, str(exc)) from exc
        if not rows:
            raise MarketImportError(1, "at least one market price row is required")

        dataset_version = version or source_digest[:16]
        manifest_data = {
            "dataset_name": dataset_name,
            "version": dataset_version,
            "provider": provider,
            "adapter": MARKET_CSV_ADAPTER_VERSION,
            "schema": MARKET_SCHEMA_VERSION,
            "source_sha256": source_digest,
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
            manifest_data, sort_keys=True, separators=(",", ":")
        )
        manifest_sha256 = hashlib.sha256(manifest_json.encode("utf-8")).hexdigest()
        dataset_id = new_id()
        batch_id = new_id()
        prices: list[MarketPrice] = []
        for row in rows:
            instrument_id = self.repository.instrument(
                InstrumentIdentifier(row["identifier"], row["identifier_scheme"]),
                row["instrument_name"],
                row["asset_type"],
                row["currency"],
            )
            prices.append(
                MarketPrice(
                    new_id(),
                    dataset_id,
                    instrument_id,
                    row["observed_at"],
                    row["known_at"],
                    recorded_at,
                    row["close"],
                    row["currency"],
                    row["quality"],
                )
            )
        dataset = DatasetVersion(
            dataset_id,
            dataset_name,
            dataset_version,
            provider,
            "csv-prices",
            MARKET_CSV_ADAPTER_VERSION,
            MARKET_SCHEMA_VERSION,
            artifact_id,
            batch_id,
            manifest_sha256,
            manifest_json,
            recorded_at,
        )
        return self.repository.add_market_dataset(dataset, prices, ())

    def import_fx_csv(
        self,
        path: str | Path,
        *,
        dataset_name: str = "daily_fx",
        version: str | None = None,
        provider: str = "local",
    ) -> dict:
        artifact_id, source_digest = self.repository.artifact(path)
        recorded_at = now()
        rows: list[dict] = []
        seen: set[tuple[str, str, str]] = set()
        with Path(path).open(newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None:
                raise MarketImportError(1, "header row is required")
            for row_number, row in enumerate(reader, 2):
                try:
                    observed_at = canonical_timestamp(
                        row.get("observed_at") or row.get("date") or ""
                    )
                    if not (row.get("known_at") or "").strip():
                        raise ValueError("known_at is required")
                    known_at = canonical_timestamp(row["known_at"])
                    from_currency = (row.get("from_currency") or "").strip().upper()
                    to_currency = (row.get("to_currency") or "").strip().upper()
                    rate = canonical_decimal(row.get("rate") or "")
                    if not from_currency or not to_currency or from_currency == to_currency:
                        raise ValueError(
                            "distinct from_currency and to_currency are required"
                        )
                    if dec(rate) <= 0:
                        raise ValueError("rate must be positive")
                    if known_at > recorded_at:
                        raise ValueError("known_at cannot be after import recorded_at")
                    if known_at < observed_at:
                        raise ValueError("known_at cannot be before observed_at")
                    key = (from_currency, to_currency, observed_at)
                    if key in seen:
                        raise ValueError("duplicate FX observation")
                    seen.add(key)
                    rows.append(
                        {
                            "row_number": row_number,
                            "observed_at": observed_at,
                            "known_at": known_at,
                            "from_currency": from_currency,
                            "to_currency": to_currency,
                            "rate": rate,
                            "quality": (row.get("quality") or "accepted").strip(),
                        }
                    )
                except (TypeError, ValueError) as exc:
                    raise MarketImportError(row_number, str(exc)) from exc
        if not rows:
            raise MarketImportError(1, "at least one FX row is required")
        dataset_version = version or source_digest[:16]
        manifest_data = {
            "dataset_name": dataset_name,
            "version": dataset_version,
            "provider": provider,
            "adapter": MARKET_CSV_ADAPTER_VERSION,
            "schema": MARKET_SCHEMA_VERSION,
            "source_sha256": source_digest,
            "rows": rows,
        }
        manifest_json = json.dumps(
            manifest_data, sort_keys=True, separators=(",", ":")
        )
        manifest_sha256 = hashlib.sha256(manifest_json.encode("utf-8")).hexdigest()
        dataset_id = new_id()
        batch_id = new_id()
        rates = [
            FxRate(
                new_id(),
                dataset_id,
                row["observed_at"],
                row["known_at"],
                recorded_at,
                row["from_currency"],
                row["to_currency"],
                row["rate"],
                row["quality"],
            )
            for row in rows
        ]
        dataset = DatasetVersion(
            dataset_id,
            dataset_name,
            dataset_version,
            provider,
            "csv-fx",
            MARKET_CSV_ADAPTER_VERSION,
            MARKET_SCHEMA_VERSION,
            artifact_id,
            batch_id,
            manifest_sha256,
            manifest_json,
            recorded_at,
        )
        return self.repository.add_market_dataset(dataset, (), rates)

    def price(
        self,
        instrument_id: str,
        as_of: str,
        *,
        known_as_of: str | None = None,
        dataset_name: str | None = None,
        dataset_version: str | None = None,
    ) -> Mapping:
        row = self.repository.market_price(
            instrument_id, as_of, known_as_of, dataset_name, dataset_version
        )
        if row is None:
            raise KeyError(f"no accepted market price for {instrument_id} at {as_of}")
        return row

    def fx_rate(
        self,
        from_currency: str,
        to_currency: str,
        as_of: str,
        *,
        known_as_of: str | None = None,
        dataset_name: str | None = None,
        dataset_version: str | None = None,
    ) -> Mapping:
        row = self.repository.market_fx_rate(
            from_currency,
            to_currency,
            as_of,
            known_as_of,
            dataset_name,
            dataset_version,
        )
        if row is None:
            raise KeyError(
                f"no accepted FX rate for {from_currency}/{to_currency} at {as_of}"
            )
        return row
