from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path

import pytest

from clausula import LedgerService, Store
from clausula.analytics import replay_fifo


def _load(service: LedgerService, account: str, path: Path, rows: list[dict]) -> None:
    fields = ["id", "date", "type", "ticker", "quantity", "amount", "fee", "currency"]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    service.import_csv(account, path)


@pytest.mark.parametrize("buy_quantity,sell_quantity", [(1, 1), (2, 1), (10, 7), (100, 33)])
def test_fifo_quantity_conservation(buy_quantity: int, sell_quantity: int):
    transaction = {
        "id": "buy",
        "type": "buy",
        "effective_at": "2025-01-01T00:00:00+00:00",
        "legs": [
            {"leg_type": "position", "instrument_id": "instrument", "quantity": str(buy_quantity), "amount": str(buy_quantity * 10), "currency": "USD"}
        ],
    }
    sale = {
        "id": "sell",
        "type": "sell",
        "effective_at": "2025-01-02T00:00:00+00:00",
        "legs": [
            {"leg_type": "position", "instrument_id": "instrument", "quantity": str(-sell_quantity), "amount": str(-sell_quantity * 12), "currency": "USD"},
            {"leg_type": "fee", "amount": "0", "currency": "USD"},
        ],
    }
    report = replay_fifo([transaction, sale])
    assert sum(Decimal(lot["quantity"]) for lot in report["open_lots"]) == Decimal(buy_quantity - sell_quantity)
    assert Decimal(report["realized"][0]["quantity"]) == Decimal(sell_quantity)


def test_same_day_fifo_uses_source_row_order(tmp_path):
    service = LedgerService(Store(tmp_path / "home"))
    account_id = service.create_account("broker", "main")
    _load(
        service,
        account_id,
        tmp_path / "same-day.csv",
        [
            {"id": "b1", "date": "2025-01-01", "type": "buy", "ticker": "ABC", "quantity": "1", "amount": "10", "fee": "0", "currency": "USD"},
            {"id": "b2", "date": "2025-01-01", "type": "buy", "ticker": "ABC", "quantity": "1", "amount": "20", "fee": "0", "currency": "USD"},
            {"id": "s1", "date": "2025-01-02", "type": "sell", "ticker": "ABC", "quantity": "1", "amount": "15", "fee": "0", "currency": "USD"},
        ],
    )
    report = service.cost_basis(account_id)
    assert report["realized"][0]["matches"][0]["source_transaction_id"] == service.transactions(account_id)[0]["id"]


def test_v3_tables_are_append_only(tmp_path):
    store = Store(tmp_path / "home")
    service = LedgerService(store)
    account_id = service.create_account("broker", "main")
    _load(
        service,
        account_id,
        tmp_path / "cash.csv",
        [{"id": "d1", "date": "2025-01-01", "type": "deposit", "ticker": "CASH", "quantity": "0", "amount": "10", "fee": "0", "currency": "USD"}],
    )
    service.record_fx_conversion(account_id, "USD", "TWD", "1", "32", "2025-01-02")
    with pytest.raises(Exception, match="append-only"):
        store.db.execute("DELETE FROM fx_conversions")
    store.db.rollback()
    assert store.verify_audit_chain()["valid"] is True
