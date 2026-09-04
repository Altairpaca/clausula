from __future__ import annotations

from pathlib import Path

import pytest

from clausula import LedgerService, Store
from clausula.adapters.accounting import AccountingPolicyProjection
from clausula.application.accounting import AccountingService


def _setup(store: Store, rows: list[dict]) -> tuple[str, str, str, AccountingService]:
    ledger = LedgerService(store)
    account = ledger.create_account("broker", "main")
    src = ledger.resolve_instrument("SRC", scheme="ticker", currency="USD")
    dst = ledger.resolve_instrument("DST", scheme="ticker", currency="USD")
    path = Path("/tmp/f1-" + __import__("uuid").uuid4().hex + ".csv")
    path.write_text(
        "id,date,known_at,type,ticker,quantity,amount,fee,currency\n"
        + "".join(
            f"{row['id']},{row['date']},{row['date']},{row['type']},{row['ticker']},"
            f"{row['quantity']},{row['amount']},0,USD\n"
            for row in rows
        ),
        encoding="utf-8",
    )
    ledger.import_csv(account, path)
    path.unlink()
    svc = AccountingService(AccountingPolicyProjection(store))
    svc.create_policy(
        account, "2020-01-01", lot_method="fifo", allow_short=False,
        known_at="2020-01-01", recorded_at="2020-01-01",
    )
    return account, src, dst, svc


def test_state_and_replay_agree_on_partial_allocation_merger(tmp_path: Path) -> None:
    store = Store(tmp_path / "home")
    account, src, dst, svc = _setup(store, [{"id": "b1", "date": "2024-01-01", "type": "buy", "ticker": "SRC", "quantity": "10", "amount": "100"}])

    ledger = LedgerService(store)
    with pytest.raises((ValueError, RuntimeError)):
        ledger.record_corporate_action(
            account, "merger", "2024-06-01",
            instruments=[
                {"role": "source", "instrument_id": src, "sequence": 1},
                {"role": "destination", "instrument_id": dst, "sequence": 2},
            ],
            considerations=[
                {"kind": "security", "instrument_id": dst, "quantity": "5", "sequence": 1},
                {"kind": "cash", "currency": "USD", "amount": "10", "sequence": 2},
            ],
            basis_allocations=[
                {
                    "source_instrument_id": src, "destination_instrument_id": dst,
                    "source_quantity": "5", "destination_quantity": "5",
                    "source_basis": "50", "destination_basis": "45", "currency": "USD",
                }
            ],
            known_at="2024-06-01",
        )
    assert svc.cost_basis(account, "2024-07-01", known_as_of="2024-07-01")["status"] == "available"


def test_full_merger_state_matches_replay(tmp_path: Path) -> None:
    store = Store(tmp_path / "home")
    account, src, dst, svc = _setup(store, [{"id": "b1", "date": "2024-01-01", "type": "buy", "ticker": "SRC", "quantity": "10", "amount": "100"}])
    ledger = LedgerService(store)

    ledger.record_corporate_action(
        account, "merger", "2024-06-01",
        instruments=[
            {"role": "source", "instrument_id": src, "sequence": 1},
            {"role": "destination", "instrument_id": dst, "sequence": 2},
        ],
        considerations=[
            {"kind": "security", "instrument_id": dst, "quantity": "10", "sequence": 1},
            {"kind": "cash", "currency": "USD", "amount": "10", "sequence": 2},
        ],
        basis_allocations=[
            {
                "source_instrument_id": src, "destination_instrument_id": dst,
                "source_quantity": "10", "destination_quantity": "10",
                "source_basis": "100", "destination_basis": "90", "currency": "USD",
            }
        ],
        known_at="2024-06-01",
    )
    state = ledger.state(account, "2024-07-01", known_as_of="2024-07-01")
    report = svc.cost_basis(account, "2024-07-01", known_as_of="2024-07-01")
    assert src not in state["positions"], "source must be fully consumed in state"
    assert state["positions"][dst] == "10"
    assert report["open_lots"][0]["instrument_id"] == dst
    assert report["open_lots"][0]["quantity"] == "10"
    assert report["open_lots"][0]["cost_basis"] == "90"
    assert report["realized_gain_by_currency"] == {"USD": "0"}


def test_cash_consideration_gain_is_not_capped_by_cash_basis(tmp_path: Path) -> None:
    store = Store(tmp_path / "home")
    account, src, dst, svc = _setup(store, [{"id": "b1", "date": "2024-01-01", "type": "buy", "ticker": "SRC", "quantity": "10", "amount": "100"}])
    ledger = LedgerService(store)

    ledger.record_corporate_action(
        account, "merger", "2024-06-01",
        instruments=[
            {"role": "source", "instrument_id": src, "sequence": 1},
            {"role": "destination", "instrument_id": dst, "sequence": 2},
        ],
        considerations=[
            {"kind": "security", "instrument_id": dst, "quantity": "10", "sequence": 1},
            {"kind": "cash", "currency": "USD", "amount": "20", "sequence": 2},
        ],
        basis_allocations=[
            {
                "source_instrument_id": src, "destination_instrument_id": dst,
                "source_quantity": "10", "destination_quantity": "10",
                "source_basis": "100", "destination_basis": "90", "currency": "USD",
            }
        ],
        known_at="2024-06-01",
    )
    report = svc.cost_basis(account, "2024-07-01", known_as_of="2024-07-01")
    assert report["realized_gain_by_currency"] == {"USD": "10"}
    assert report["open_lots"][0]["cost_basis"] == "90"


def test_cash_in_lieu_state_removes_source_and_matches_replay(tmp_path: Path) -> None:
    store = Store(tmp_path / "home")
    account, src, _dst, svc = _setup(store, [{"id": "b1", "date": "2024-01-01", "type": "buy", "ticker": "SRC", "quantity": "10", "amount": "100"}])
    ledger = LedgerService(store)

    ledger.record_corporate_action(
        account, "cash_in_lieu", "2024-06-01",
        instruments=[{"role": "source", "instrument_id": src, "sequence": 1}],
        considerations=[{"kind": "cash", "currency": "USD", "amount": "12.50", "sequence": 1}],
        basis_allocations=[],
        known_at="2024-06-01",
    )
    state = ledger.state(account, "2024-07-01", known_as_of="2024-07-01")
    report = svc.cost_basis(account, "2024-07-01", known_as_of="2024-07-01")
    assert src not in state["positions"], "cash-in-lieu must remove the source position in state"
    assert report["open_lots"] == []
