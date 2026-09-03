from __future__ import annotations

import csv
from pathlib import Path

from clausula import LedgerService, Store
from clausula.analytics import performance_summary, xirr
from clausula.application import MarketService, PortfolioService
from decimal import Decimal


def write_rows(path: Path, fields: list[str], rows: list[dict]) -> None:
    if "known_at" not in fields:
        fields = [*fields[:2], "known_at", *fields[2:]]
        rows = [
            {**row, "known_at": row.get("date") or row.get("effective_at") or "2025-01-01"}
            for row in rows
        ]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_decimal_xirr_and_drawdown_golden_values():
    rate = xirr(
        [("2025-01-01", Decimal("-200")), ("2026-01-01", Decimal("220"))]
    )
    assert rate is not None
    assert abs(rate - Decimal("0.1")) < Decimal("1e-20")

    result = performance_summary(
        [
            {"date": "2025-01-01", "value": "200", "net_external_flow": "0", "complete": True},
            {"date": "2025-06-01", "value": "180", "net_external_flow": "0", "complete": True},
            {"date": "2026-01-01", "value": "220", "net_external_flow": "0", "complete": True},
        ]
    )
    assert result["maximum_drawdown"] == "-0.1"
    assert result["time_weighted_return"] == "0.1"

    with_flow = performance_summary(
        [
            {"date": "2025-01-01", "value": "100", "net_external_flow": "0", "complete": True},
            {"date": "2025-06-01", "value": "200", "net_external_flow": "100", "complete": True},
            {"date": "2026-01-01", "value": "220", "net_external_flow": "0", "complete": True},
        ]
    )
    assert with_flow["time_weighted_return"] == "0.1"
    assert with_flow["maximum_drawdown"] == "0"


def test_portfolio_performance_uses_point_in_time_market_facts(tmp_path):
    store = Store(tmp_path / "home")
    ledger = LedgerService(store)
    market = MarketService(store)
    portfolios = PortfolioService(store)
    account = ledger.create_account("broker", "main")
    ledger_source = tmp_path / "ledger.csv"
    write_rows(
        ledger_source,
        ["id", "date", "type", "ticker", "quantity", "amount", "fee", "currency"],
        [
            {"id": "d1", "date": "2025-01-01", "type": "deposit", "ticker": "CASH", "quantity": "0", "amount": "200", "fee": "0", "currency": "USD"},
            {"id": "b1", "date": "2025-01-01", "type": "buy", "ticker": "ABC", "quantity": "2", "amount": "100", "fee": "0", "currency": "USD"},
        ],
    )
    ledger.import_csv(account, ledger_source)
    prices = tmp_path / "prices.csv"
    write_rows(
        prices,
        ["date", "known_at", "ticker", "close", "currency"],
        [
            {"date": "2025-01-01", "known_at": "2025-01-01", "ticker": "ABC", "close": "50", "currency": "USD"},
            {"date": "2026-01-01", "known_at": "2026-01-01", "ticker": "ABC", "close": "60", "currency": "USD"},
        ],
    )
    market.import_prices_csv(prices, dataset_name="daily", version="v1")
    portfolio_id = portfolios.create("Performance", "USD")
    portfolios.set_membership(
        portfolio_id, account, "add", "2025-01-01", known_at="2025-01-01"
    )

    result = portfolios.performance(
        portfolio_id, ["2025-01-01", "2026-01-01"]
    )

    assert result["knowledge_mode"] == "point_in_time"
    assert result["time_weighted_return"] == "0.1"
    assert abs(Decimal(result["money_weighted_return"]) - Decimal("0.1")) < Decimal("1e-20")
    assert result["maximum_drawdown"] == "0"
    assert [point["value"] for point in result["series"]] == ["200", "220"]
