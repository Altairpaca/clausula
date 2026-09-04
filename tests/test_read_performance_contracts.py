from __future__ import annotations

import csv
from pathlib import Path

from clausula import LedgerService, Store
from clausula.application import MarketService, PortfolioService


def _write(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _selects(store: Store, operation):
    statements: list[str] = []
    store.db.set_trace_callback(
        lambda sql: statements.append(" ".join(sql.lower().split()))
        if sql.lstrip().lower().startswith("select")
        else None
    )
    try:
        result = operation()
    finally:
        store.db.set_trace_callback(None)
    return result, statements


def test_ledger_state_materializes_transaction_legs_in_one_query(tmp_path) -> None:
    store = Store(tmp_path / "home")
    ledger = LedgerService(store)
    account = ledger.create_account("broker", "main")
    source = tmp_path / "ledger.csv"
    rows = [
        {
            "id": str(index),
            "date": f"2025-01-{(index % 20) + 1:02d}",
            "known_at": f"2025-01-{(index % 20) + 1:02d}",
            "type": "deposit",
            "ticker": "CASH",
            "quantity": "0",
            "amount": "1",
            "fee": "0",
            "currency": "USD",
        }
        for index in range(200)
    ]
    _write(
        source,
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
        ],
        rows,
    )
    ledger.import_csv(account, source)

    state, statements = _selects(
        store,
        lambda: ledger.state(account, "2025-02-01", known_as_of="2025-02-01"),
    )

    assert state["cash"] == "200"
    joined_reads = [
        sql for sql in statements if "from transactions t" in sql and "join legs l" in sql
    ]
    scalar_leg_reads = [sql for sql in statements if "from legs where transaction_id" in sql]
    assert len(joined_reads) == 1
    assert scalar_leg_reads == []


def test_portfolio_valuation_batches_instruments_and_prices(tmp_path) -> None:
    store = Store(tmp_path / "home")
    ledger = LedgerService(store)
    market = MarketService(store)
    account = ledger.create_account("broker", "main")
    source = tmp_path / "ledger.csv"
    rows = []
    prices = []
    for index in range(30):
        ticker = f"S{index:02d}"
        rows.append(
            {
                "id": str(index),
                "date": "2025-01-01",
                "known_at": "2025-01-01",
                "type": "buy",
                "ticker": ticker,
                "quantity": "1",
                "amount": "1",
                "fee": "0",
                "currency": "USD",
            }
        )
        prices.append(
            {
                "date": "2025-01-02",
                "known_at": "2025-01-02",
                "ticker": ticker,
                "close": "2",
                "currency": "USD",
            }
        )
    _write(
        source,
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
        ],
        rows,
    )
    ledger.import_csv(account, source)
    price_file = tmp_path / "prices.csv"
    _write(
        price_file,
        ["date", "known_at", "ticker", "close", "currency"],
        prices,
    )
    market.import_prices_csv(price_file, dataset_name="daily", version="v1")

    valuation, statements = _selects(
        store,
        lambda: PortfolioService(store).valuation(
            account,
            "2025-01-02",
            known_as_of="2025-01-02",
        ),
    )

    assert valuation["complete"] is True
    assert valuation["total_value"] == "30"
    instrument_batches = [
        sql for sql in statements if "from instruments where id in" in sql
    ]
    price_batches = [
        sql for sql in statements if "from market_prices p join market_datasets" in sql
    ]
    scalar_instruments = [
        sql for sql in statements if "select * from instruments where id=" in sql
    ]
    assert len(instrument_batches) == 1
    assert len(price_batches) == 1
    assert scalar_instruments == []


def test_multi_date_performance_sweeps_each_account_stream_once_per_projection(tmp_path) -> None:
    store = Store(tmp_path / "home")
    ledger = LedgerService(store)
    account = ledger.create_account("bank", "cash")
    source = tmp_path / "ledger.csv"
    rows = [
        {
            "id": str(index),
            "date": f"2025-01-{index + 1:02d}",
            "known_at": f"2025-01-{index + 1:02d}",
            "type": "deposit",
            "ticker": "CASH",
            "quantity": "0",
            "amount": "10",
            "fee": "0",
            "currency": "USD",
        }
        for index in range(10)
    ]
    _write(
        source,
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
        ],
        rows,
    )
    ledger.import_csv(account, source)
    portfolios = PortfolioService(store)
    portfolio_id = portfolios.create("Cash", "USD")
    portfolios.set_membership(
        portfolio_id,
        account,
        "add",
        "2025-01-01",
        known_at="2025-01-01",
    )
    dates = [f"2025-01-{day:02d}" for day in range(1, 11)]

    result, statements = _selects(
        store,
        lambda: portfolios.performance(portfolio_id, dates),
    )

    joined_reads = [
        sql for sql in statements if "from transactions t" in sql and "join legs l" in sql
    ]
    assert len(result["valuations"]) == len(dates)
    # One stream for states + one stream for external-flow projection, independent of D.
    assert len(joined_reads) == 2
