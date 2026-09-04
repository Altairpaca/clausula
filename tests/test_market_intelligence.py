from __future__ import annotations

import csv

import pytest

from clausula import LedgerService, Store
from clausula.adapters.market_intelligence import MarketIntelligenceProjection
from clausula.application import (
    BenchmarkService,
    MarketService,
    PortfolioService,
    ProviderPrice,
    ProviderSnapshot,
    ProviderSnapshotImporter,
)
from clausula.capabilities import build_core_registry


def _write(path, fieldnames, rows) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_explicit_return_series_is_point_in_time_and_never_inferred(tmp_path) -> None:
    store = Store(tmp_path / "home")
    prices = tmp_path / "benchmark.csv"
    _write(
        prices,
        [
            "date",
            "known_at",
            "ticker",
            "close",
            "currency",
            "return_index",
            "return_semantics",
        ],
        [
            {
                "date": "2026-01-01",
                "known_at": "2026-01-01",
                "ticker": "BENCH",
                "close": "100",
                "currency": "USD",
                "return_index": "100",
                "return_semantics": "total_return",
            },
            {
                "date": "2026-01-02",
                "known_at": "2026-01-02",
                "ticker": "BENCH",
                "close": "108",
                "currency": "USD",
                "return_index": "110",
                "return_semantics": "total_return",
            },
        ],
    )
    MarketService(store).import_prices_csv(
        prices, dataset_name="benchmark", version="v1", provider="fixture"
    )
    projection = MarketIntelligenceProjection(store)

    historical = projection.dataset_health(
        "benchmark",
        "v1",
        as_of="2026-01-01",
        known_as_of="2026-01-01",
    )
    assert historical["return_series"]["present"] is True
    assert historical["return_series"]["semantics"] == ["total_return"]

    series = projection.return_series(
        "benchmark",
        "v1",
        "BENCH",
        as_of="2026-01-02",
        known_as_of="2026-01-02",
    )
    assert series["semantics"] == "total_return"
    assert series["cumulative_return"] == "0.1"
    assert series["series"][1]["period_return"] == "0.1"

    plain = tmp_path / "plain.csv"
    _write(
        plain,
        ["date", "known_at", "ticker", "close", "currency"],
        [
            {
                "date": "2026-01-01",
                "known_at": "2026-01-01",
                "ticker": "RAW",
                "close": "10",
                "currency": "USD",
            }
        ],
    )
    MarketService(store).import_prices_csv(
        plain, dataset_name="raw", version="v1", provider="fixture"
    )
    raw_series = projection.return_series(
        "raw",
        "v1",
        "RAW",
        as_of="2026-01-01",
        known_as_of="2026-01-01",
    )
    assert raw_series["status"] == "unavailable"
    assert raw_series["semantics"] == "price_return_only"


def test_return_series_requires_explicit_semantics(tmp_path) -> None:
    store = Store(tmp_path / "home")
    source = tmp_path / "bad.csv"
    _write(
        source,
        ["date", "known_at", "ticker", "close", "return_index"],
        [
            {
                "date": "2026-01-01",
                "known_at": "2026-01-01",
                "ticker": "ABC",
                "close": "10",
                "return_index": "100",
            }
        ],
    )
    with pytest.raises(ValueError, match="provided together"):
        MarketService(store).import_prices_csv(source)


def test_dataset_health_reports_quality_lag_coverage_and_cross_dataset_conflict(tmp_path) -> None:
    store = Store(tmp_path / "home")
    first = tmp_path / "first.csv"
    second = tmp_path / "second.csv"
    fields = ["date", "known_at", "ticker", "close", "currency", "quality"]
    _write(
        first,
        fields,
        [
            {
                "date": "2026-01-01",
                "known_at": "2026-01-02",
                "ticker": "ABC",
                "close": "10",
                "currency": "USD",
                "quality": "accepted",
            },
            {
                "date": "2026-01-02",
                "known_at": "2026-01-02",
                "ticker": "XYZ",
                "close": "20",
                "currency": "USD",
                "quality": "suspect",
            },
        ],
    )
    _write(
        second,
        fields,
        [
            {
                "date": "2026-01-01",
                "known_at": "2026-01-02",
                "ticker": "ABC",
                "close": "11",
                "currency": "USD",
                "quality": "accepted",
            }
        ],
    )
    market = MarketService(store)
    market.import_prices_csv(first, dataset_name="primary", version="v1", provider="one")
    market.import_prices_csv(second, dataset_name="secondary", version="v1", provider="two")

    health = MarketIntelligenceProjection(store).dataset_health(
        "primary", "v1", as_of="2026-01-03", known_as_of="2026-01-03"
    )
    assert health["status"] == "degraded"
    assert health["quality_counts"]["accepted"] == 1
    assert health["quality_counts"]["suspect"] == 1
    assert health["instrument_coverage"] == 2
    assert health["observation_age_days"] == 1
    assert health["conflicts"][0]["observed_at"].startswith("2026-01-01")


def test_provider_snapshot_captures_raw_payload_before_normalization(tmp_path) -> None:
    store = Store(tmp_path / "home")
    snapshot = ProviderSnapshot(
        provider="fixture-provider",
        dataset_name="provider-prices",
        version="2026-01-02",
        observations=(
            ProviderPrice(
                identifier="ABC",
                observed_at="2026-01-02",
                known_at="2026-01-02",
                close="10",
                return_index="100",
                return_semantics="price_return",
            ),
        ),
        raw_payload={"symbol": "ABC", "close": 10, "source_id": "fixture-1"},
    )
    result = ProviderSnapshotImporter(store).import_snapshot(snapshot)
    dataset = store.db.execute(
        "SELECT * FROM market_datasets WHERE id=?", (result["dataset_id"],)
    ).fetchone()
    artifact = store.db.execute(
        """SELECT a.sha256,d.source_path
           FROM artifacts a JOIN artifact_details d ON d.artifact_id=a.id
           WHERE a.id=?""",
        (dataset["source_artifact_id"],),
    ).fetchone()
    assert artifact["source_path"].startswith("provider://fixture-provider/")
    raw = (store.raw_root / artifact["sha256"]).read_text(encoding="utf-8")
    assert '"source_id":"fixture-1"' in raw
    series = MarketIntelligenceProjection(store).return_series(
        "provider-prices",
        "2026-01-02",
        "ABC",
        as_of="2026-01-02",
        known_as_of="2026-01-02",
    )
    assert series["semantics"] == "price_return"


def test_benchmark_compare_returns_explicit_comparability_semantics(tmp_path) -> None:
    store = Store(tmp_path / "home")
    ledger = LedgerService(store)
    account = ledger.create_account("broker", "main")
    ledger_path = tmp_path / "ledger.csv"
    _write(
        ledger_path,
        [
            "id",
            "date",
            "known_at",
            "type",
            "ticker",
            "quantity",
            "amount",
            "fee",
            "currency",
            "asset_type",
        ],
        [
            {
                "id": "cash",
                "date": "2026-01-01",
                "known_at": "2026-01-01",
                "type": "deposit",
                "ticker": "CASH",
                "quantity": "0",
                "amount": "100",
                "fee": "0",
                "currency": "USD",
                "asset_type": "cash",
            },
            {
                "id": "buy",
                "date": "2026-01-01",
                "known_at": "2026-01-01",
                "type": "buy",
                "ticker": "ABC",
                "quantity": "10",
                "amount": "100",
                "fee": "0",
                "currency": "USD",
                "asset_type": "stock",
            },
        ],
    )
    ledger.import_csv(account, ledger_path)
    portfolio = PortfolioService(store).create("Household", "USD", created_at="2026-01-01")
    PortfolioService(store).set_membership(
        portfolio, account, "add", "2026-01-01", known_at="2026-01-01"
    )

    prices = tmp_path / "prices.csv"
    _write(
        prices,
        [
            "date",
            "known_at",
            "ticker",
            "close",
            "currency",
            "return_index",
            "return_semantics",
        ],
        [
            {
                "date": "2026-01-01",
                "known_at": "2026-01-01",
                "ticker": "ABC",
                "close": "10",
                "currency": "USD",
                "return_index": "100",
                "return_semantics": "price_return",
            },
            {
                "date": "2026-01-02",
                "known_at": "2026-01-02",
                "ticker": "ABC",
                "close": "11",
                "currency": "USD",
                "return_index": "110",
                "return_semantics": "price_return",
            },
            {
                "date": "2026-01-01",
                "known_at": "2026-01-01",
                "ticker": "BENCH",
                "close": "100",
                "currency": "USD",
                "return_index": "100",
                "return_semantics": "total_return",
            },
            {
                "date": "2026-01-02",
                "known_at": "2026-01-02",
                "ticker": "BENCH",
                "close": "105",
                "currency": "USD",
                "return_index": "105",
                "return_semantics": "total_return",
            },
        ],
    )
    MarketService(store).import_prices_csv(
        prices, dataset_name="daily", version="v1", provider="fixture"
    )
    projection = MarketIntelligenceProjection(store)
    result = BenchmarkService(store, projection).compare(
        portfolio,
        benchmark_dataset_name="daily",
        benchmark_dataset_version="v1",
        benchmark_identifier="BENCH",
        as_of="2026-01-02",
        known_as_of="2026-01-02",
        price_dataset_name="daily",
        price_dataset_version="v1",
    )
    assert result["portfolio_return"] == "0.1"
    assert result["benchmark_return"] == "0.05"
    assert result["active_return_difference"] == "0.05"
    assert result["benchmark"]["semantics"] == "total_return"
    assert result["comparability"] == "total_return_comparable_if_ledger_income_is_complete"

    names = {item["name"] for item in build_core_registry(store).describe()}
    assert {"market.dataset_health", "market.return_series", "portfolio.benchmark_compare"} <= names
