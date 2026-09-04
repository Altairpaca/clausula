from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import date, timedelta
import json
from pathlib import Path
import tempfile
import time
from typing import Callable

from clausula import LedgerService, Store
from clausula.application import MarketService, PortfolioService


@dataclass(frozen=True)
class Profile:
    accounts: int
    transactions: int
    positions: int
    dates: int


PROFILES = {
    "smoke": Profile(accounts=1, transactions=1_000, positions=20, dates=30),
    "medium": Profile(accounts=3, transactions=10_000, positions=60, dates=365),
    "full": Profile(accounts=5, transactions=25_000, positions=100, dates=1_826),
}


def _write_csv(path: Path, fieldnames: list[str], rows) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _measure(store: Store, operation: Callable[[], object]) -> dict[str, object]:
    statements: list[str] = []
    store.db.set_trace_callback(statements.append)
    started = time.perf_counter()
    try:
        result = operation()
    finally:
        elapsed = time.perf_counter() - started
        store.db.set_trace_callback(None)
    selects = [sql for sql in statements if sql.lstrip().upper().startswith("SELECT")]
    return {
        "seconds": round(elapsed, 6),
        "sql_statements": len(statements),
        "select_statements": len(selects),
        "result_type": type(result).__name__,
    }


def _fixture(root: Path, profile: Profile) -> tuple[Store, str, list[str]]:
    store = Store(root / "home")
    ledger = LedgerService(store)
    market = MarketService(store)
    portfolios = PortfolioService(store)

    start = date(2021, 1, 1)
    tickers = [f"S{index:03d}" for index in range(profile.positions)]
    accounts: list[str] = []
    per_account = max(profile.transactions // profile.accounts, 1)

    for account_index in range(profile.accounts):
        account_id = ledger.create_account("synthetic", f"account-{account_index + 1}")
        accounts.append(account_id)
        path = root / f"ledger-{account_index}.csv"

        def rows():
            yield {
                "id": f"a{account_index}-deposit",
                "date": start.isoformat(),
                "known_at": start.isoformat(),
                "type": "deposit",
                "ticker": "CASH",
                "quantity": "0",
                "amount": str(max(per_account * 20, 100_000)),
                "fee": "0",
                "currency": "USD",
                "asset_type": "cash",
            }
            for index in range(max(per_account - 1, 0)):
                trade_day = start + timedelta(days=index % max(profile.dates, 1))
                yield {
                    "id": f"a{account_index}-t{index}",
                    "date": trade_day.isoformat(),
                    "known_at": trade_day.isoformat(),
                    "type": "buy",
                    "ticker": tickers[index % len(tickers)],
                    "quantity": "1",
                    "amount": "10",
                    "fee": "0",
                    "currency": "USD",
                    "asset_type": "stock",
                }

        _write_csv(
            path,
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
            rows(),
        )
        ledger.import_csv(account_id, path)

    price_path = root / "prices.csv"
    _write_csv(
        price_path,
        ["date", "known_at", "ticker", "close", "currency", "asset_type"],
        (
            {
                "date": start.isoformat(),
                "known_at": start.isoformat(),
                "ticker": ticker,
                "close": "10",
                "currency": "USD",
                "asset_type": "stock",
            }
            for ticker in tickers
        ),
    )
    market.import_prices_csv(
        price_path,
        dataset_name="synthetic-benchmark",
        version="v1",
        provider="local-benchmark",
    )

    portfolio_id = portfolios.create("Synthetic benchmark", "USD")
    for account_id in accounts:
        portfolios.set_membership(
            portfolio_id,
            account_id,
            "add",
            start.isoformat(),
            known_at=start.isoformat(),
        )

    dates = [
        (start + timedelta(days=index)).isoformat()
        for index in range(max(profile.dates, 2))
    ]
    return store, portfolio_id, dates


def run(profile_name: str) -> dict[str, object]:
    profile = PROFILES[profile_name]
    with tempfile.TemporaryDirectory(prefix="clausula-bench-") as directory:
        root = Path(directory)
        setup_started = time.perf_counter()
        store, portfolio_id, dates = _fixture(root, profile)
        setup_seconds = time.perf_counter() - setup_started
        try:
            portfolios = PortfolioService(store)
            account_id = store.portfolio_accounts(
                portfolio_id, dates[-1], dates[-1]
            )[0]
            ledger = LedgerService(store)
            state = _measure(
                store,
                lambda: ledger.state(account_id, dates[-1], known_as_of=dates[-1]),
            )
            valuation = _measure(
                store,
                lambda: portfolios.portfolio_valuation(
                    portfolio_id,
                    dates[-1],
                    known_as_of=dates[-1],
                    price_dataset_name="synthetic-benchmark",
                    price_dataset_version="v1",
                ),
            )
            performance = _measure(
                store,
                lambda: portfolios.performance(
                    portfolio_id,
                    dates,
                    price_dataset_name="synthetic-benchmark",
                    price_dataset_version="v1",
                ),
            )
            return {
                "format": "clausula-read-benchmark-v1",
                "profile": profile_name,
                "shape": {
                    "accounts": profile.accounts,
                    "transactions": profile.transactions,
                    "positions": profile.positions,
                    "performance_dates": len(dates),
                },
                "setup_seconds": round(setup_seconds, 6),
                "state": state,
                "valuation": valuation,
                "performance": performance,
                "note": "Wall-clock numbers are descriptive; SQL/query-growth contracts live in tests/test_read_performance_contracts.py.",
            }
        finally:
            store.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run reproducible synthetic read-path benchmarks for Clausula."
    )
    parser.add_argument(
        "--profile",
        choices=sorted(PROFILES),
        default="smoke",
        help="smoke=1k/20/30, medium=10k/60/365, full=25k/100/1826",
    )
    args = parser.parse_args()
    print(json.dumps(run(args.profile), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
