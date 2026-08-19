from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path

import pytest

from clausula import LedgerService, Store
from clausula.analytics import CostBasisError


def import_rows(service: LedgerService, account_id: str, path: Path, rows: list[dict]) -> None:
    fields = ["id", "date", "known_at", "type", "ticker", "quantity", "amount", "fee", "currency"]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    service.import_csv(account_id, path)


def test_fifo_cost_basis_and_realized_gain_include_fees(tmp_path):
    service = LedgerService(Store(tmp_path / "home"))
    account_id = service.create_account("broker", "main")
    import_rows(
        service,
        account_id,
        tmp_path / "trades.csv",
        [
            {"id": "b1", "date": "2025-01-01", "type": "buy", "ticker": "ABC", "quantity": "10", "amount": "100", "fee": "1", "currency": "USD"},
            {"id": "b2", "date": "2025-01-02", "type": "buy", "ticker": "ABC", "quantity": "5", "amount": "75", "fee": "1", "currency": "USD"},
            {"id": "s1", "date": "2025-01-03", "type": "sell", "ticker": "ABC", "quantity": "12", "amount": "180", "fee": "2", "currency": "USD"},
        ],
    )

    report = service.cost_basis(account_id, "2025-01-04")

    assert report["open_basis_by_currency"] == {"USD": "45.6"}
    assert report["realized_gain_by_currency"] == {"USD": "46.6"}
    assert report["realized"][0]["proceeds"] == "178"
    assert report["realized"][0]["cost_basis"] == "131.4"
    assert [match["quantity"] for match in report["realized"][0]["matches"]] == ["10", "2"]
    assert report["open_lots"][0]["quantity"] == "3"
    assert report["open_lots"][0]["unit_cost"] == "15.2"


def test_fifo_rejects_oversell(tmp_path):
    service = LedgerService(Store(tmp_path / "home"))
    account_id = service.create_account("broker", "main")
    import_rows(
        service,
        account_id,
        tmp_path / "trades.csv",
        [
            {"id": "b1", "date": "2025-01-01", "type": "buy", "ticker": "ABC", "quantity": "1", "amount": "10", "fee": "0", "currency": "USD"},
            {"id": "s1", "date": "2025-01-02", "type": "sell", "ticker": "ABC", "quantity": "2", "amount": "20", "fee": "0", "currency": "USD"},
        ],
    )
    with pytest.raises(CostBasisError, match="insufficient quantity"):
        service.cost_basis(account_id)


def test_split_preserves_total_basis_and_changes_unit_cost(tmp_path):
    store = Store(tmp_path / "home")
    service = LedgerService(store)
    account_id = service.create_account("broker", "main")
    import_rows(
        service,
        account_id,
        tmp_path / "trades.csv",
        [{"id": "b1", "date": "2025-01-01", "type": "buy", "ticker": "ABC", "quantity": "10", "amount": "100", "fee": "0", "currency": "USD"}],
    )
    instrument_id = next(iter(service.positions(account_id)))

    action_id = service.record_split(account_id, instrument_id, "2", "1", "2025-01-02")
    historical_report = service.cost_basis(account_id, "2025-01-03")
    report = service.cost_basis(account_id)

    assert service.positions(account_id)[instrument_id] == "20"
    assert historical_report["open_lots"][0]["quantity"] == "10"
    assert report["open_lots"][0]["quantity"] == "20"
    assert report["open_lots"][0]["cost_basis"] == "100"
    assert report["open_lots"][0]["unit_cost"] == "5"
    assert store.db.execute("SELECT id FROM corporate_actions").fetchone()[0] == action_id


def test_security_transfer_preserves_fifo_lineage_and_basis(tmp_path):
    store = Store(tmp_path / "home")
    service = LedgerService(store)
    source_account = service.create_account("broker", "source")
    destination_account = service.create_account("broker", "destination")
    import_rows(
        service,
        source_account,
        tmp_path / "trades.csv",
        [
            {"id": "b1", "date": "2025-01-01", "type": "buy", "ticker": "ABC", "quantity": "10", "amount": "100", "fee": "0", "currency": "USD"},
            {"id": "b2", "date": "2025-01-02", "type": "buy", "ticker": "ABC", "quantity": "5", "amount": "75", "fee": "0", "currency": "USD"},
        ],
    )
    instrument_id = next(iter(service.positions(source_account)))
    original_lots = service.cost_basis(source_account)["open_lots"]

    transfer = service.record_security_transfer(
        source_account, destination_account, instrument_id, "12", "2025-01-03"
    )

    source_report = service.cost_basis(source_account)
    destination_report = service.cost_basis(destination_account)
    assert source_report["open_basis_by_currency"] == {"USD": "45"}
    assert destination_report["open_basis_by_currency"] == {"USD": "130"}
    assert [lot["quantity"] for lot in destination_report["open_lots"]] == ["10", "2"]
    assert [lot["source_transaction_id"] for lot in destination_report["open_lots"]] == [
        lot["source_transaction_id"] for lot in original_lots
    ]
    assert source_report["realized"] == destination_report["realized"] == []
    assert store.db.execute(
        "SELECT count(*) FROM security_transfer_allocations WHERE security_transfer_id=?",
        (transfer["transfer_id"],),
    ).fetchone()[0] == 2


def test_fx_conversion_balances_each_currency_and_updates_cash(tmp_path):
    store = Store(tmp_path / "home")
    service = LedgerService(store)
    account_id = service.create_account("broker", "main")

    transaction_id = service.record_fx_conversion(
        account_id,
        "USD",
        "TWD",
        "100",
        "3200",
        "2025-01-01",
        fee="1",
        fee_currency="USD",
    )

    state = service.state(account_id)
    assert state["cash_by_currency"] == {"TWD": "3200", "USD": "-101"}
    totals: dict[str, Decimal] = {}
    for leg in store.legs(transaction_id):
        totals[leg["currency"]] = totals.get(leg["currency"], Decimal(0)) + Decimal(leg["amount"])
    assert totals == {"USD": Decimal(0), "TWD": Decimal(0)}
    assert store.transaction_metadata(transaction_id)["fx_conversion"]["rate"] == "32"


def test_effective_and_knowledge_cutoffs_are_independent(tmp_path):
    service = LedgerService(Store(tmp_path / "home"))
    account_id = service.create_account("broker", "main")
    import_rows(
        service,
        account_id,
        tmp_path / "trades.csv",
        [{"id": "b1", "date": "2025-01-01", "known_at": "2025-02-01", "type": "buy", "ticker": "ABC", "quantity": "1", "amount": "10", "fee": "0", "currency": "USD"}],
    )

    assert service.state(account_id, "2025-01-15", known_as_of="2025-02-15")["positions"]
    assert service.state(account_id, "2025-01-15", known_as_of="2025-01-15")["positions"] == {}


def test_reconciliation_persists_typed_observations(tmp_path):
    store = Store(tmp_path / "home")
    service = LedgerService(store)
    account_id = service.create_account("broker", "main")
    instrument_id = service.resolve_instrument("ABC", currency="USD")

    result = service.reconcile(
        account_id,
        {"cash_by_currency": {"USD": "5"}, "positions": {instrument_id: "2"}},
        "2025-01-01",
    )

    observations = store.db.execute(
        "SELECT kind,instrument_id,currency,value FROM reconciliation_observations WHERE reconciliation_id=? ORDER BY kind",
        (result.record_id,),
    ).fetchall()
    assert [tuple(row) for row in observations] == [
        ("cash", None, "USD", "5"),
        ("position", instrument_id, None, "2"),
    ]
