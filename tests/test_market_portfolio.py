from __future__ import annotations

import csv
from pathlib import Path

import pytest

from clausula import LedgerService, Store
from clausula.application import LedgerRebuilder, MarketService, PortfolioService


def write_rows(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_market_import_is_versioned_idempotent_and_as_of_safe(tmp_path):
    store = Store(tmp_path / "home")
    market = MarketService(store)
    source = tmp_path / "prices.csv"
    write_rows(
        source,
        ["date", "known_at", "ticker", "close", "currency", "quality"],
        [
            {"date": "2025-01-01", "known_at": "2025-02-01", "ticker": "ABC", "close": "10", "currency": "USD", "quality": "accepted"},
            {"date": "2025-01-02", "known_at": "2025-02-02", "ticker": "ABC", "close": "99", "currency": "USD", "quality": "rejected"},
        ],
    )

    first = market.import_prices_csv(source, dataset_name="daily", version="v1", provider="fixture")
    second = market.import_prices_csv(source, dataset_name="daily", version="v1", provider="fixture")
    instrument_id = store.db.execute("SELECT id FROM instruments WHERE identifier='ABC'").fetchone()[0]

    assert first == second
    assert first["prices"] == 2
    assert store.db.execute("SELECT count(*) FROM market_datasets").fetchone()[0] == 1
    assert market.price(instrument_id, "2025-01-03", known_as_of="2025-02-15")["close"] == "10"
    with pytest.raises(KeyError, match="no accepted"):
        market.price(instrument_id, "2025-01-03", known_as_of="2025-01-15")


def test_market_dataset_version_conflict_and_provider_conflict_are_explicit(tmp_path):
    store = Store(tmp_path / "home")
    market = MarketService(store)
    fields = ["date", "known_at", "ticker", "close", "currency"]
    first = tmp_path / "first.csv"
    second = tmp_path / "second.csv"
    write_rows(first, fields, [{"date": "2025-01-01", "known_at": "2025-01-02", "ticker": "ABC", "close": "10", "currency": "USD"}])
    write_rows(second, fields, [{"date": "2025-01-01", "known_at": "2025-01-02", "ticker": "ABC", "close": "11", "currency": "USD"}])
    market.import_prices_csv(first, dataset_name="primary", version="v1", provider="one")
    with pytest.raises(ValueError, match="version conflict"):
        market.import_prices_csv(second, dataset_name="primary", version="v1", provider="one")
    market.import_prices_csv(second, dataset_name="secondary", version="v1", provider="two")
    instrument_id = store.db.execute("SELECT id FROM instruments WHERE identifier='ABC'").fetchone()[0]

    with pytest.raises(ValueError, match="conflicting accepted"):
        market.price(instrument_id, "2025-01-02", known_as_of="2025-01-02")
    assert market.price(
        instrument_id,
        "2025-01-02",
        known_as_of="2025-01-02",
        dataset_name="primary",
        dataset_version="v1",
    )["close"] == "10"


def test_market_import_requires_explicit_non_hindsight_knowledge_time(tmp_path):
    store = Store(tmp_path / "home")
    source = tmp_path / "prices.csv"
    write_rows(
        source,
        ["date", "known_at", "ticker", "close", "currency"],
        [{"date": "2025-01-02", "known_at": "2025-01-01", "ticker": "ABC", "close": "10", "currency": "USD"}],
    )
    with pytest.raises(ValueError, match="before observed_at"):
        MarketService(store).import_prices_csv(source)

    write_rows(
        source,
        ["date", "ticker", "close", "currency"],
        [{"date": "2025-01-02", "ticker": "ABC", "close": "10", "currency": "USD"}],
    )
    with pytest.raises(ValueError, match="known_at is required"):
        MarketService(store).import_prices_csv(source)


def test_market_dataset_version_must_be_selected_with_dataset_name(tmp_path):
    store, _ = _portfolio_fixture(tmp_path)
    instrument_id = store.db.execute(
        "SELECT id FROM instruments WHERE identifier='ABC'"
    ).fetchone()[0]
    with pytest.raises(ValueError, match="requires dataset_name"):
        MarketService(store).price(
            instrument_id,
            "2025-01-02",
            known_as_of="2025-01-02",
            dataset_version="v1",
        )


def _portfolio_fixture(tmp_path: Path):
    store = Store(tmp_path / "home")
    ledger = LedgerService(store)
    market = MarketService(store)
    account = ledger.create_account("broker", "main")
    ledger_file = tmp_path / "ledger.csv"
    write_rows(
        ledger_file,
        ["id", "date", "type", "ticker", "quantity", "amount", "fee", "currency", "asset_type"],
        [
            {"id": "d1", "date": "2025-01-01", "type": "deposit", "ticker": "CASH", "quantity": "0", "amount": "200", "fee": "0", "currency": "USD", "asset_type": "cash"},
            {"id": "b1", "date": "2025-01-01", "type": "buy", "ticker": "ABC", "quantity": "2", "amount": "100", "fee": "0", "currency": "USD", "asset_type": "stock"},
            {"id": "d2", "date": "2025-01-01", "type": "deposit", "ticker": "CASH", "quantity": "0", "amount": "3200", "fee": "0", "currency": "TWD", "asset_type": "cash"},
        ],
    )
    ledger.import_csv(account, ledger_file)
    prices = tmp_path / "prices.csv"
    write_rows(
        prices,
        ["date", "known_at", "ticker", "close", "currency", "asset_type"],
        [{"date": "2025-01-02", "known_at": "2025-01-02", "ticker": "ABC", "close": "60", "currency": "USD", "asset_type": "stock"}],
    )
    market.import_prices_csv(prices, dataset_name="daily", version="v1")
    fx = tmp_path / "fx.csv"
    write_rows(
        fx,
        ["date", "known_at", "from_currency", "to_currency", "rate"],
        [{"date": "2025-01-02", "known_at": "2025-01-02", "from_currency": "TWD", "to_currency": "USD", "rate": "0.03125"}],
    )
    market.import_fx_csv(fx, dataset_name="daily-fx", version="v1")
    return store, account


def test_portfolio_valuation_allocation_concentration_and_currency_exposure(tmp_path):
    store, account = _portfolio_fixture(tmp_path)
    result = PortfolioService(store).valuation(
        account,
        "2025-01-02",
        known_as_of="2025-01-02",
        base_currency="USD",
    )

    assert result["complete"] is True
    assert result["total_value"] == "320"
    assert result["allocation"] == [
        {"asset_type": "cash", "base_value": "200", "weight": "0.625"},
        {"asset_type": "stock", "base_value": "120", "weight": "0.375"},
    ]
    assert result["currency_exposure"] == [
        {"currency": "TWD", "base_value": "100"},
        {"currency": "USD", "base_value": "220"},
    ]
    assert result["concentration"][0]["weight"] == "0.375"
    assert result["gaps"] == []


def test_portfolio_missing_market_fact_is_explicit_not_zero_filled(tmp_path):
    store = Store(tmp_path / "home")
    ledger = LedgerService(store)
    account = ledger.create_account("broker", "main")
    source = tmp_path / "ledger.csv"
    write_rows(
        source,
        ["id", "date", "type", "ticker", "quantity", "amount", "fee", "currency"],
        [{"id": "b1", "date": "2025-01-01", "type": "buy", "ticker": "ABC", "quantity": "1", "amount": "10", "fee": "0", "currency": "USD"}],
    )
    ledger.import_csv(account, source)

    result = PortfolioService(store).valuation(account, "2025-01-02", known_as_of="2025-01-02")

    assert result["complete"] is False
    assert result["total_value"] is None
    assert result["gaps"][0]["kind"] == "price"


def test_market_raw_datasets_rebuild_with_same_manifest(tmp_path):
    source_store, account = _portfolio_fixture(tmp_path)
    target_store = Store(tmp_path / "target")

    result = LedgerRebuilder(source_store, target_store).rebuild()

    assert result["consistent"] is True
    assert result["warnings"] == []
    target_account = result["account_mapping"][account]
    valuation = PortfolioService(target_store).valuation(
        target_account, "2025-01-02", known_as_of="2025-01-02"
    )
    assert valuation["total_value"] == "320"
    assert len(target_store.market_datasets()) == 2


def test_portfolio_aggregates_accounts_and_recomputes_weights(tmp_path):
    store, first_account = _portfolio_fixture(tmp_path)
    ledger = LedgerService(store)
    second_account = ledger.create_account("bank", "cash")
    cash = tmp_path / "second.csv"
    write_rows(
        cash,
        ["id", "date", "type", "ticker", "quantity", "amount", "fee", "currency"],
        [{"id": "d1", "date": "2025-01-01", "type": "deposit", "ticker": "CASH", "quantity": "0", "amount": "80", "fee": "0", "currency": "USD"}],
    )
    ledger.import_csv(second_account, cash)
    portfolios = PortfolioService(store)
    portfolio_id = portfolios.create("Household", "USD")
    portfolios.set_membership(portfolio_id, first_account, "add", "2025-01-01", known_at="2025-01-01")
    portfolios.set_membership(portfolio_id, second_account, "add", "2025-01-01", known_at="2025-01-01")

    result = portfolios.portfolio_valuation(
        portfolio_id, "2025-01-02", known_as_of="2025-01-02"
    )

    assert result["total_value"] == "400"
    assert len(result["accounts"]) == 2
    assert result["allocation"] == [
        {"asset_type": "cash", "base_value": "280", "weight": "0.7"},
        {"asset_type": "stock", "base_value": "120", "weight": "0.3"},
    ]
    assert result["concentration"][0]["base_value"] == "120"
    assert result["concentration"][0]["weight"] == "0.3"


def test_portfolio_membership_respects_effective_and_known_time(tmp_path):
    store = Store(tmp_path / "home")
    ledger = LedgerService(store)
    account = ledger.create_account("broker", "main")
    portfolios = PortfolioService(store)
    portfolio_id = portfolios.create("Temporal", "USD")
    portfolios.set_membership(portfolio_id, account, "add", "2025-01-01", known_at="2025-01-01")
    portfolios.set_membership(portfolio_id, account, "remove", "2025-02-01", known_at="2025-03-01")

    assert portfolios.accounts(
        portfolio_id, "2025-02-15", known_as_of="2025-02-15"
    ) == [account]
    assert portfolios.accounts(
        portfolio_id, "2025-02-15", known_as_of="2025-03-15"
    ) == []


def test_dataset_manifest_content_matches_hash(tmp_path):
    store = Store(tmp_path / "home")
    source = tmp_path / "prices.csv"
    write_rows(
        source,
        ["date", "known_at", "ticker", "close", "currency"],
        [{"date": "2025-01-01", "known_at": "2025-01-01", "ticker": "ABC", "close": "10", "currency": "USD"}],
    )
    result = MarketService(store).import_prices_csv(source, dataset_name="daily", version="v1")
    row = store.db.execute(
        "SELECT manifest_sha256,manifest_json FROM market_datasets WHERE id=?",
        (result["dataset_id"],),
    ).fetchone()
    import hashlib

    assert hashlib.sha256(row["manifest_json"].encode("utf-8")).hexdigest() == row["manifest_sha256"]


def test_portfolio_events_have_raw_provenance_and_rebuild_temporal_membership(tmp_path):
    source_store, first_account = _portfolio_fixture(tmp_path)
    ledger = LedgerService(source_store)
    second_account = ledger.create_account("bank", "reserve")
    portfolios = PortfolioService(source_store)
    portfolio_id = portfolios.create("Household", "USD")
    portfolios.set_membership(
        portfolio_id, first_account, "add", "2025-01-01", known_at="2025-01-01"
    )
    portfolios.set_membership(
        portfolio_id, second_account, "add", "2025-02-01", known_at="2025-03-01"
    )

    portfolio_row = source_store.db.execute(
        "SELECT source_artifact_id,import_batch_id FROM portfolios WHERE id=?",
        (portfolio_id,),
    ).fetchone()
    membership_rows = source_store.db.execute(
        """SELECT source_artifact_id,import_batch_id
           FROM portfolio_membership_events WHERE portfolio_id=? ORDER BY effective_at""",
        (portfolio_id,),
    ).fetchall()
    assert portfolio_row["source_artifact_id"] and portfolio_row["import_batch_id"]
    assert all(row["source_artifact_id"] and row["import_batch_id"] for row in membership_rows)
    assert all(
        (source_store.raw_root / row[0]).is_file()
        for row in source_store.db.execute(
            """SELECT a.sha256 FROM artifacts a
               WHERE a.id IN (?,?,?)""",
            (
                portfolio_row["source_artifact_id"],
                membership_rows[0]["source_artifact_id"],
                membership_rows[1]["source_artifact_id"],
            ),
        )
    )

    target_store = Store(tmp_path / "target")
    rebuilt = LedgerRebuilder(source_store, target_store).rebuild()

    assert rebuilt["consistent"] is True
    assert rebuilt["warnings"] == []
    assert rebuilt["portfolio_comparisons"][0]["matches"] is True
    target_portfolio = rebuilt["portfolio_mapping"][portfolio_id]
    assert target_store.portfolio(target_portfolio)["created_at"] == source_store.portfolio(
        portfolio_id
    )["created_at"]
    assert [
        row[0]
        for row in target_store.db.execute(
            """SELECT recorded_at FROM portfolio_membership_events
               WHERE portfolio_id=? ORDER BY effective_at""",
            (target_portfolio,),
        )
    ] == [
        row[0]
        for row in source_store.db.execute(
            """SELECT recorded_at FROM portfolio_membership_events
               WHERE portfolio_id=? ORDER BY effective_at""",
            (portfolio_id,),
        )
    ]
    assert target_store.portfolio_accounts(
        target_portfolio, "2025-02-15", "2025-02-15"
    ) == [rebuilt["account_mapping"][first_account]]
    assert target_store.portfolio_accounts(
        target_portfolio, "2025-02-15", "2025-03-15"
    ) == sorted(
        [
            rebuilt["account_mapping"][first_account],
            rebuilt["account_mapping"][second_account],
        ]
    )
    assert sorted(
        target_store.portfolio_accounts(target_portfolio, "2025-03-15", "2025-03-15")
    ) == sorted(
        [
            rebuilt["account_mapping"][first_account],
            rebuilt["account_mapping"][second_account],
        ]
    )


def test_rejected_membership_write_does_not_leave_provenance_or_import_rows(tmp_path):
    store = Store(tmp_path / "home")
    ledger = LedgerService(store)
    account = ledger.create_account("broker", "main")
    portfolios = PortfolioService(store)
    portfolio_id = portfolios.create("Household")
    portfolios.set_membership(
        portfolio_id, account, "add", "2025-01-01", known_at="2025-01-01"
    )
    before = store.db.execute("SELECT count(*) FROM imports").fetchone()[0]

    with pytest.raises(ValueError, match="does not change state"):
        portfolios.set_membership(
            portfolio_id, account, "add", "2025-01-02", known_at="2025-01-02"
        )

    assert store.db.execute("SELECT count(*) FROM imports").fetchone()[0] == before

    with pytest.raises(KeyError, match="unknown account"):
        portfolios.set_membership(
            portfolio_id,
            "00000000-0000-4000-8000-000000000000",
            "add",
            "2025-01-02",
            known_at="2025-01-02",
        )
    assert store.db.execute("SELECT count(*) FROM imports").fetchone()[0] == before


def test_market_and_portfolio_survive_verified_backup_round_trip(tmp_path):
    store, account = _portfolio_fixture(tmp_path)
    portfolios = PortfolioService(store)
    portfolio_id = portfolios.create("Household", "USD")
    portfolios.set_membership(
        portfolio_id, account, "add", "2025-01-01", known_at="2025-01-01"
    )
    expected = portfolios.portfolio_valuation(
        portfolio_id, "2025-01-02", known_as_of="2025-01-02"
    )
    bundle = tmp_path / "m3.clausula.zip"
    store.backup_bundle(bundle)

    restored = Store(tmp_path / "restored")
    restored.restore_bundle(bundle)

    assert PortfolioService(restored).portfolio_valuation(
        portfolio_id, "2025-01-02", known_as_of="2025-01-02"
    ) == expected
    assert len(restored.market_datasets()) == 2
