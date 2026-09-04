from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import json
from typing import Any

from clausula.domain import canonical_decimal, canonical_timestamp, dec


RETURN_SEMANTICS = {"price_return", "total_return"}


def _timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _age_days(cutoff: str, observed_at: str | None) -> int | None:
    if observed_at is None:
        return None
    return max((_timestamp(cutoff) - _timestamp(observed_at)).days, 0)


class MarketIntelligenceProjection:
    """Derived SQLite projection for data trust and explicit return semantics."""

    def __init__(self, repository):
        if not hasattr(repository, "db"):
            raise TypeError("market intelligence requires a local SQLite repository")
        self.repository = repository
        self.db = repository.db

    def __getattr__(self, name: str):
        return getattr(self.repository, name)

    def _dataset(self, dataset_name: str, dataset_version: str) -> Any:
        row = self.db.execute(
            """SELECT * FROM market_datasets
               WHERE dataset_name=? AND version=?""",
            (dataset_name, dataset_version),
        ).fetchone()
        if row is None:
            raise KeyError(
                f"unknown market dataset version: {dataset_name}/{dataset_version}"
            )
        return row

    def dataset_health(
        self,
        dataset_name: str,
        dataset_version: str,
        *,
        as_of: str,
        known_as_of: str | None = None,
    ) -> dict[str, Any]:
        dataset = self._dataset(dataset_name, dataset_version)
        effective_cutoff = canonical_timestamp(as_of)
        knowledge_cutoff = canonical_timestamp(known_as_of or as_of)
        price_rows = self.db.execute(
            """SELECT p.*,i.scheme,i.identifier
               FROM market_prices p
               JOIN instruments i ON i.id=p.instrument_id
               WHERE p.dataset_id=? AND p.observed_at<=? AND p.known_at<=?
               ORDER BY p.observed_at,p.known_at,p.id""",
            (dataset["id"], effective_cutoff, knowledge_cutoff),
        ).fetchall()
        fx_rows = self.db.execute(
            """SELECT * FROM market_fx_rates
               WHERE dataset_id=? AND observed_at<=? AND known_at<=?
               ORDER BY observed_at,known_at,id""",
            (dataset["id"], effective_cutoff, knowledge_cutoff),
        ).fetchall()
        rows = [*price_rows, *fx_rows]
        quality_counts = {"accepted": 0, "suspect": 0, "rejected": 0}
        for row in rows:
            quality_counts[str(row["quality"])] = quality_counts.get(
                str(row["quality"]), 0
            ) + 1
        latest_observed = max((row["observed_at"] for row in rows), default=None)
        latest_known = max((row["known_at"] for row in rows), default=None)

        conflicts = self._conflicts(
            price_rows,
            effective_cutoff=effective_cutoff,
            knowledge_cutoff=knowledge_cutoff,
        )
        manifest = json.loads(dataset["manifest_json"])
        return_meta = manifest.get("return_series") or {}
        return_semantics = sorted(
            {
                row.get("return_semantics")
                for row in manifest.get("rows", ())
                if row.get("return_index") is not None
                and row.get("return_semantics") in RETURN_SEMANTICS
                and row.get("observed_at", "") <= effective_cutoff
                and row.get("known_at", "") <= knowledge_cutoff
            }
        )

        if not rows:
            status = "absent"
        elif quality_counts.get("suspect", 0) or quality_counts.get("rejected", 0) or conflicts:
            status = "degraded"
        else:
            status = "healthy"
        return {
            "dataset": {
                "id": dataset["id"],
                "dataset_name": dataset["dataset_name"],
                "version": dataset["version"],
                "provider": dataset["provider"],
                "adapter_name": dataset["adapter_name"],
                "adapter_version": dataset["adapter_version"],
                "schema_version": dataset["schema_version"],
                "manifest_sha256": dataset["manifest_sha256"],
                "recorded_at": dataset["recorded_at"],
            },
            "as_of": effective_cutoff,
            "known_as_of": knowledge_cutoff,
            "status": status,
            "quality_counts": quality_counts,
            "observations": len(rows),
            "price_observations": len(price_rows),
            "fx_observations": len(fx_rows),
            "instrument_coverage": len({row["instrument_id"] for row in price_rows}),
            "fx_pair_coverage": len(
                {(row["from_currency"], row["to_currency"]) for row in fx_rows}
            ),
            "latest_observed_at": latest_observed,
            "latest_known_at": latest_known,
            "observation_age_days": _age_days(effective_cutoff, latest_observed),
            "knowledge_lag_days": (
                None
                if latest_observed is None or latest_known is None
                else max((_timestamp(latest_known) - _timestamp(latest_observed)).days, 0)
            ),
            "conflicts": conflicts,
            "return_series": {
                "present": bool(return_semantics or return_meta.get("present") is True),
                "semantics": return_semantics,
                "fallback_semantics": "price_return_only" if not return_semantics else None,
            },
        }

    def _conflicts(
        self,
        price_rows,
        *,
        effective_cutoff: str,
        knowledge_cutoff: str,
    ) -> list[dict[str, Any]]:
        if not price_rows:
            return []
        instrument_ids = sorted({row["instrument_id"] for row in price_rows})
        placeholders = ",".join("?" for _ in instrument_ids)
        rows = self.db.execute(
            f"""SELECT p.instrument_id,p.observed_at,p.close,p.currency,
                       d.dataset_name,d.version,d.provider
                FROM market_prices p
                JOIN market_datasets d ON d.id=p.dataset_id
                WHERE p.instrument_id IN ({placeholders})
                  AND p.observed_at<=? AND p.known_at<=? AND p.quality='accepted'
                ORDER BY p.instrument_id,p.observed_at,d.dataset_name,d.version""",
            (*instrument_ids, effective_cutoff, knowledge_cutoff),
        ).fetchall()
        grouped: dict[tuple[str, str], list[Any]] = {}
        for row in rows:
            grouped.setdefault((row["instrument_id"], row["observed_at"]), []).append(row)
        output: list[dict[str, Any]] = []
        for (instrument_id, observed_at), group in grouped.items():
            values = {(row["close"], row["currency"]) for row in group}
            if len(values) <= 1:
                continue
            output.append(
                {
                    "instrument_id": instrument_id,
                    "observed_at": observed_at,
                    "values": [
                        {
                            "close": row["close"],
                            "currency": row["currency"],
                            "dataset_name": row["dataset_name"],
                            "dataset_version": row["version"],
                            "provider": row["provider"],
                        }
                        for row in group
                    ],
                }
            )
        return output

    def return_series(
        self,
        dataset_name: str,
        dataset_version: str,
        identifier: str,
        *,
        identifier_scheme: str = "ticker",
        as_of: str,
        known_as_of: str,
    ) -> dict[str, Any]:
        dataset = self._dataset(dataset_name, dataset_version)
        effective_cutoff = canonical_timestamp(as_of)
        knowledge_cutoff = canonical_timestamp(known_as_of)
        manifest = json.loads(dataset["manifest_json"])
        visible = [
            row
            for row in manifest.get("rows", ())
            if row.get("identifier") == identifier
            and row.get("identifier_scheme", "ticker") == identifier_scheme
            and row.get("quality", "accepted").lower() == "accepted"
            and row.get("observed_at", "") <= effective_cutoff
            and row.get("known_at", "") <= knowledge_cutoff
            and row.get("return_index") is not None
        ]
        visible.sort(key=lambda row: (row["observed_at"], row["known_at"], row.get("row_number", 0)))
        if not visible:
            return {
                "dataset_name": dataset_name,
                "dataset_version": dataset_version,
                "provider": dataset["provider"],
                "identifier": identifier,
                "identifier_scheme": identifier_scheme,
                "as_of": effective_cutoff,
                "known_as_of": knowledge_cutoff,
                "status": "unavailable",
                "semantics": "price_return_only",
                "reason": "dataset has no explicit return_index for this instrument at the cutoff",
                "series": [],
                "cumulative_return": None,
            }
        semantics = {str(row.get("return_semantics")) for row in visible}
        if not semantics <= RETURN_SEMANTICS or len(semantics) != 1:
            raise ValueError(
                "return series mixes or omits explicit price_return/total_return semantics"
            )
        semantic = next(iter(semantics))
        series = []
        previous: Decimal | None = None
        for row in visible:
            value = dec(row["return_index"])
            period_return = None if previous is None else value / previous - Decimal(1)
            series.append(
                {
                    "observed_at": row["observed_at"],
                    "known_at": row["known_at"],
                    "return_index": canonical_decimal(value),
                    "period_return": (
                        None
                        if period_return is None
                        else canonical_decimal(period_return)
                    ),
                }
            )
            previous = value
        first = dec(series[0]["return_index"])
        last = dec(series[-1]["return_index"])
        return {
            "dataset_name": dataset_name,
            "dataset_version": dataset_version,
            "provider": dataset["provider"],
            "identifier": identifier,
            "identifier_scheme": identifier_scheme,
            "as_of": effective_cutoff,
            "known_as_of": knowledge_cutoff,
            "status": "available",
            "semantics": semantic,
            "series": series,
            "cumulative_return": canonical_decimal(last / first - Decimal(1)),
        }
