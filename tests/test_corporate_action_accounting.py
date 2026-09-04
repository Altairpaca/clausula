from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from clausula import LedgerService, Store
from clausula.adapters.accounting import AccountingPolicyProjection
from clausula.application.accounting import AccountingService
from clausula.domain import canonical_decimal, dec


def _accounting(store: Store, account_id: str, *, allow_short: bool = False) -> AccountingService:
    service = AccountingService(AccountingPolicyProjection(store))
    if not service.list_policies(account_id=account_id):
        service.create_policy(
            account_id,
            "2020-01-01",
            lot_method="fifo",
            allow_short=allow_short,
            known_at="2020-01-01",
            recorded_at="2020-01-01",
        )
    return service


def _buy(ledger: LedgerService, account_id: str, ticker: str, qty: str, amount: str, date: str) -> None:
    path = Path("/tmp/clausula-ca-" + __import__("uuid").uuid4().hex + ".csv")
    path.write_text(
        "id,date,known_at,type,ticker,quantity,amount,fee,currency\n"
        f"b-{date},{date},{date},buy,{ticker},{qty},{amount},0,USD\n",
        encoding="utf-8",
    )
    ledger.import_csv(account_id, path)
    path.unlink()


def _sell(ledger: LedgerService, account_id: str, ticker: str, qty: str, amount: str, date: str) -> None:
    path = Path("/tmp/clausula-ca-" + __import__("uuid").uuid4().hex + ".csv")
    path.write_text(
        "id,date,known_at,type,ticker,quantity,amount,fee,currency\n"
        f"s-{date},{date},{date},sell,{ticker},{qty},{amount},0,USD\n",
        encoding="utf-8",
    )
    ledger.import_csv(account_id, path)
    path.unlink()


@pytest.fixture()
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "home")


def test_merger_transforms_source_lots_conserving_quantity_and_basis(store: Store) -> None:
    ledger = LedgerService(store)
    account = ledger.create_account("broker", "main")
    src = ledger.resolve_instrument("SRC", scheme="ticker", currency="USD")
    dst = ledger.resolve_instrument("DST", scheme="ticker", currency="USD")
    _buy(ledger, account, "SRC", "10", "100", "2024-01-01")
    _accounting(store, account)

    result = ledger.record_corporate_action(
        account,
        "merger",
        "2024-06-01",
        instruments=[
            {"role": "source", "instrument_id": src, "sequence": 1},
            {"role": "destination", "instrument_id": dst, "sequence": 2, "ratio_numerator": "1", "ratio_denominator": "2"},
        ],
        considerations=[
            {"kind": "security", "instrument_id": dst, "quantity": "5", "sequence": 1},
            {"kind": "cash", "currency": "USD", "amount": "10", "sequence": 2},
        ],
        basis_allocations=[
            {
                "source_instrument_id": src,
                "destination_instrument_id": dst,
                "source_quantity": "10",
                "destination_quantity": "5",
                "source_basis": "100",
                "destination_basis": "90",
                "currency": "USD",
            }
        ],
        known_at="2024-06-01",
        description="SRC merges into DST",
    )
    assert result["action_id"]

    report = _accounting(store, account).cost_basis(account, "2024-07-01", known_as_of="2024-07-01")
    assert report["open_lots"][0]["instrument_id"] == dst
    assert report["open_lots"][0]["quantity"] == "5"
    assert report["open_lots"][0]["cost_basis"] == "90"
    assert report["realized_gain_by_currency"] == {"USD": "0"}


def test_spin_off_conserves_parent_plus_child_basis(store: Store) -> None:
    ledger = LedgerService(store)
    account = ledger.create_account("broker", "main")
    parent = ledger.resolve_instrument("PAR", scheme="ticker", currency="USD")
    child = ledger.resolve_instrument("CHD", scheme="ticker", currency="USD")
    _buy(ledger, account, "PAR", "10", "200", "2024-01-01")
    _accounting(store, account)

    ledger.record_corporate_action(
        account,
        "spin_off",
        "2024-06-01",
        instruments=[
            {"role": "source", "instrument_id": parent, "sequence": 1},
            {"role": "destination", "instrument_id": child, "sequence": 2},
        ],
        considerations=[
            {"kind": "security", "instrument_id": child, "quantity": "2", "sequence": 1},
        ],
        basis_allocations=[
            {
                "source_instrument_id": parent,
                "destination_instrument_id": child,
                "source_quantity": "2",
                "destination_quantity": "2",
                "source_basis": "40",
                "destination_basis": "40",
                "currency": "USD",
            }
        ],
        known_at="2024-06-01",
    )

    report = _accounting(store, account).cost_basis(account, "2024-07-01", known_as_of="2024-07-01")
    by_instrument = {lot["instrument_id"]: lot for lot in report["open_lots"]}
    assert by_instrument[parent]["quantity"] == "10"
    assert by_instrument[parent]["cost_basis"] == "160"
    assert by_instrument[child]["quantity"] == "2"
    assert by_instrument[child]["cost_basis"] == "40"
    assert dec(by_instrument[parent]["cost_basis"]) + dec(by_instrument[child]["cost_basis"]) == Decimal("200")


def test_cash_in_lieu_never_silently_disappears(store: Store) -> None:
    ledger = LedgerService(store)
    account = ledger.create_account("broker", "main")
    src = ledger.resolve_instrument("SRC", scheme="ticker", currency="USD")
    _buy(ledger, account, "SRC", "10", "100", "2024-01-01")
    _accounting(store, account)

    result = ledger.record_corporate_action(
        account,
        "cash_in_lieu",
        "2024-06-01",
        instruments=[{"role": "source", "instrument_id": src, "sequence": 1}],
        considerations=[
            {"kind": "cash", "currency": "USD", "amount": "12.50", "sequence": 1},
        ],
        basis_allocations=[],
        known_at="2024-06-01",
    )
    assert result["cash_in_lieu_amount"] == "12.50"

    report = _accounting(store, account).cost_basis(account, "2024-07-01", known_as_of="2024-07-01")
    state = ledger.state(account, "2024-07-01", known_as_of="2024-07-01")
    assert state["cash_by_currency"].get("USD") == "-87.5"
    assert report["realized_gain_by_currency"]["USD"] == "-87.5"


def test_generalized_action_on_short_fails_closed(store: Store) -> None:
    ledger = LedgerService(store)
    account = ledger.create_account("broker", "short")
    src = ledger.resolve_instrument("SRC", scheme="ticker", currency="USD")
    dst = ledger.resolve_instrument("DST", scheme="ticker", currency="USD")
    _sell(ledger, account, "SRC", "10", "100", "2024-01-01")
    _accounting(store, account, allow_short=True)

    with pytest.raises((ValueError, RuntimeError), match="short"):
        ledger.record_corporate_action(
            account,
            "merger",
            "2024-06-01",
            instruments=[
                {"role": "source", "instrument_id": src, "sequence": 1},
                {"role": "destination", "instrument_id": dst, "sequence": 2},
            ],
            considerations=[
                {"kind": "security", "instrument_id": dst, "quantity": "5", "sequence": 1},
            ],
            known_at="2024-06-01",
        )


def test_corporate_action_event_facts_are_layer_separated(store: Store) -> None:
    ledger = LedgerService(store)
    account = ledger.create_account("broker", "main")
    src = ledger.resolve_instrument("SRC", scheme="ticker", currency="USD")
    dst = ledger.resolve_instrument("DST", scheme="ticker", currency="USD")
    _buy(ledger, account, "SRC", "10", "100", "2024-01-01")
    _accounting(store, account)

    result = ledger.record_corporate_action(
        account,
        "exchange",
        "2024-06-01",
        instruments=[
            {"role": "source", "instrument_id": src, "sequence": 1},
            {"role": "destination", "instrument_id": dst, "sequence": 2},
        ],
        considerations=[
            {"kind": "security", "instrument_id": dst, "quantity": "10", "sequence": 1},
            {"kind": "fee", "currency": "USD", "amount": "1", "sequence": 2},
        ],
        basis_allocations=[
            {
                "source_instrument_id": src,
                "destination_instrument_id": dst,
                "source_quantity": "10",
                "destination_quantity": "10",
                "source_basis": "100",
                "destination_basis": "99",
                "currency": "USD",
            }
        ],
        tax_profile_ref="local://tax/hk-v1",
        tax_interpretation={"capital_gain": "none"},
        known_at="2024-06-01",
    )
    event_id = result["event_id"]

    row = store.db.execute(
        "SELECT action_type,effective_at,known_at,source_artifact_id,import_batch_id FROM corporate_action_events WHERE id=?",
        (event_id,),
    ).fetchone()
    assert row["action_type"] == "exchange"
    assert row["source_artifact_id"]
    assert row["import_batch_id"]

    instruments = store.db.execute(
        "SELECT role,instrument_id FROM corporate_action_event_instruments WHERE event_id=? ORDER BY sequence",
        (event_id,),
    ).fetchall()
    assert {(i["role"], i["instrument_id"]) for i in instruments} == {
        ("source", src),
        ("destination", dst),
    }

    considerations = store.db.execute(
        "SELECT kind,instrument_id,currency,quantity,amount FROM corporate_action_considerations WHERE event_id=? ORDER BY sequence",
        (event_id,),
    ).fetchall()
    assert {(c["kind"], c["quantity"], c["amount"]) for c in considerations} == {
        ("security", "10", None),
        ("fee", None, "1"),
    }

    consequences = store.db.execute(
        "SELECT consequence_type,generated,account_id,transaction_id FROM corporate_action_account_consequences WHERE event_id=?",
        (event_id,),
    ).fetchall()
    assert consequences
    assert all(c["account_id"] == account for c in consequences)

    tax = store.db.execute(
        "SELECT tax_profile_ref,interpretation_json FROM corporate_action_tax_interpretations WHERE consequence_id IN (SELECT id FROM corporate_action_account_consequences WHERE event_id=?)",
        (event_id,),
    ).fetchone()
    assert tax["tax_profile_ref"] == "local://tax/hk-v1"
    assert "capital_gain" in tax["interpretation_json"]
