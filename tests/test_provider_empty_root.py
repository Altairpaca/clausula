"""Empty-root provider acceptance for #34 using a captured raw Eastmoney fixture."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from clausula import Store
from clausula.application.market_provider import ProviderSnapshotImporter
from clausula.application.providers.eastmoney import (
    EastmoneyDailyProvider,
    EastmoneyInstrument,
    EastmoneyProviderError,
    MARKET_CURRENCY,
    MARKET_PREFIX,
    snapshot_for_market,
)

FIXTURE_BODY = json.dumps(
    {
        "rc": 0,
        "data": {
            "code": "AAPL",
            "name": "Apple Inc.",
            "klines": [
                "2025-01-02,10.30,10.13,10.42,10.05,789071,803904040.00,3.60,-1.55,-0.16,0.27",
                "2025-01-03,10.15,10.28,10.33,10.11,640119,653888200.00,2.17,1.48,0.15,0.22",
                "2025-01-06,10.30,10.42,10.51,10.25,701233,726739800.00,2.52,1.36,0.14,0.24",
                "2025-01-07,10.44,10.38,10.52,10.30,662341,686800100.00,2.11,-0.38,-0.04,0.23",
            ],
        },
    }
).encode("utf-8")


def _snapshot_from_fixture(body: bytes):
    name, code, rows = EastmoneyDailyProvider.parse_klines(body)
    from clausula.application.market_provider import ProviderPrice, ProviderSnapshot

    observations = [
        ProviderPrice(
            identifier="AAPL",
            observed_at=row["observed_at"],
            known_at="2025-01-08T00:00:00+00:00",
            close=row["close"],
            instrument_name=name,
            asset_type="stock",
            currency="USD",
        )
        for row in rows
    ]
    return ProviderSnapshot(
        provider="eastmoney",
        dataset_name="daily_prices",
        version=f"eastmoney-US-{code}-fqt0-20250101-20250110",
        observations=observations,
        raw_payload={
            "capture": {
                "source": "eastmoney_http",
                "observed_at": "2025-01-08T00:00:00+00:00",
                "byte_length": len(body),
            },
            "klines": [row["observed_at"] for row in rows],
        },
        adapter_name="eastmoney-http",
        adapter_version="1",
        schema_version="1",
    )


def test_empty_root_import_isolates_canonical_data_and_preserves_raw_provenance() -> None:
    test_root = Path(tempfile.mkdtemp(prefix="clausula-eastmoney-acceptance-"))
    store = Store(test_root / "home")
    importer = ProviderSnapshotImporter(store)

    _, code, rows = EastmoneyDailyProvider.parse_klines(FIXTURE_BODY)
    assert code == "AAPL"
    assert len(rows) == 4
    assert rows[0]["close"] == "10.13"
    assert rows[0]["observed_at"] == "2025-01-02"

    snapshot = _snapshot_from_fixture(FIXTURE_BODY)
    result = importer.import_snapshot(snapshot)

    assert result["dataset_name"] == "daily_prices"
    assert result["provider"] == "eastmoney"
    assert result["manifest_sha256"]
    datasets = store.market_datasets("daily_prices")
    assert len(datasets) == 1
    assert store.db.execute(
        "SELECT count(*) c FROM market_prices WHERE dataset_id=?",
        (datasets[0]["id"],),
    ).fetchone()["c"] == 4

    artifact = store.db.execute(
        "SELECT a.id,a.sha256 FROM artifacts a"
        " JOIN artifact_details d ON d.artifact_id=a.id"
        " WHERE d.source_path LIKE 'provider://%'"
    ).fetchone()
    assert artifact is not None
    assert (test_root / "home" / "raw" / artifact["sha256"]).exists()

    store.close()
    assert (test_root / "home" / "clausula.db").exists()


def test_empty_observation_snapshot_fails_without_partial_publish() -> None:
    test_root = Path(tempfile.mkdtemp(prefix="clausula-eastmoney-fail-"))
    store = Store(test_root / "home")
    importer = ProviderSnapshotImporter(store)
    from clausula.application.market_provider import ProviderSnapshot

    bad = ProviderSnapshot(
        provider="eastmoney",
        dataset_name="daily_prices",
        version="bad",
        observations=[],
        raw_payload={},
    )
    try:
        importer.import_snapshot(bad)
        raise AssertionError("empty snapshot should raise")
    except ValueError:
        pass
    assert store.market_datasets("daily_prices") == []
    store.close()


def test_market_currency_is_never_a_silent_usd_default() -> None:
    assert MARKET_CURRENCY == {
        "CN-SH": "CNY",
        "CN-SZ": "CNY",
        "HK": "HKD",
        "US": "USD",
    }
    assert set(MARKET_CURRENCY) == set(MARKET_PREFIX)
    with pytest.raises(EastmoneyProviderError, match="unsupported market"):
        EastmoneyDailyProvider(
            EastmoneyInstrument(market_code="XX", symbol="X"), market="XX"
        )
    assert snapshot_for_market


def test_parse_klines_rejects_malformed_rows() -> None:
    malformed = json.dumps(
        {"rc": 0, "data": {"code": "X", "name": "X", "klines": ["2025-01-02,10.30"]}}
    ).encode("utf-8")
    try:
        EastmoneyDailyProvider.parse_klines(malformed)
        raise AssertionError("malformed kline should raise")
    except RuntimeError:
        pass
