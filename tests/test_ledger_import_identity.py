from __future__ import annotations

import json

import pytest

from clausula import LedgerService, Store
from clausula.adapters.sqlite import Store as LegacySQLiteStore
from clausula.application.ledger import ImportValidationError
from clausula.application.ledger_import import commit_csv_import


HEADER = "id,date,known_at,type,ticker,quantity,amount,fee,currency,description\n"


def write_csv(path, *rows: str) -> None:
    path.write_text(HEADER + "".join(rows), encoding="utf-8")


def row(
    external_id: str,
    *,
    date: str = "2025-01-01",
    kind: str = "buy",
    ticker: str = "ABC",
    quantity: str = "2",
    amount: str = "100",
    fee: str = "1",
    currency: str = "USD",
    description: str = "broker event",
) -> str:
    return (
        f"{external_id},{date},{date},{kind},{ticker},{quantity},"
        f"{amount},{fee},{currency},{description}\n"
    )


def counts(store: Store) -> dict[str, int]:
    return {
        table: store.db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in ("artifacts", "instruments", "imports", "transactions", "legs")
    }


def test_changed_export_classifies_exact_duplicate_and_inserts_only_new_row(tmp_path):
    store = Store(tmp_path / "home")
    service = LedgerService(store)
    account_id = service.create_account("broker", "main")

    first = tmp_path / "first.csv"
    write_csv(first, row("trade-1"))
    first_result = service.import_csv(account_id, first)
    assert first_result["transactions"] == 1

    changed = tmp_path / "changed.csv"
    write_csv(
        changed,
        row("trade-1", description="same event from a later export"),
        row(
            "cash-2",
            date="2025-01-02",
            kind="deposit",
            ticker="CASH",
            quantity="0",
            amount="50",
            fee="0",
            description="new cash",
        ),
    )

    preview = service.preview_csv(account_id, changed)
    assert preview["ok"] is True
    assert preview["reconciliation"] == {
        "account_id": account_id,
        "new": 1,
        "duplicate_exact": 1,
        "conflict_external_id": 0,
    }
    assert [item["import_status"] for item in preview["transactions"]] == [
        "duplicate_exact",
        "new",
    ]
    existing_id = preview["transactions"][0]["existing_transaction_ids"][0]

    result = service.import_csv(account_id, changed)
    assert result["transactions"] == 1
    assert store.db.execute("SELECT count(*) FROM transactions").fetchone()[0] == 2
    assert store.db.execute(
        "SELECT count(DISTINCT transaction_id) FROM imported_rows WHERE account_id=? AND external_id='trade-1'",
        (account_id,),
    ).fetchone()[0] == 1
    assert store.db.execute(
        "SELECT count(*) FROM imported_rows WHERE account_id=? AND external_id='trade-1'",
        (account_id,),
    ).fetchone()[0] == 2
    assert store.db.execute(
        "SELECT transaction_id FROM imported_rows WHERE account_id=? AND external_id='trade-1' LIMIT 1",
        (account_id,),
    ).fetchone()[0] == existing_id

    latest = store.db.execute(
        """SELECT d.input_rows,d.inserted_rows
           FROM import_details d JOIN imports i ON i.id=d.import_id
           ORDER BY i.created_at DESC,i.id DESC LIMIT 1"""
    ).fetchone()
    assert dict(latest) == {"input_rows": 2, "inserted_rows": 1}

    external_ids = {
        row[0]
        for row in store.db.execute(
            "SELECT external_id FROM transactions WHERE account_id=?",
            (account_id,),
        )
    }
    assert external_ids == {"trade-1", "cash-2"}

    state = service.state(account_id, "2025-01-03")
    assert list(state["positions"].values()) == ["2"]
    assert state["cash_by_currency"] == {"USD": "-51"}


def test_external_id_conflict_fails_before_any_artifact_or_instrument_publication(tmp_path):
    store = Store(tmp_path / "home")
    service = LedgerService(store)
    account_id = service.create_account("broker", "main")

    accepted = tmp_path / "accepted.csv"
    write_csv(accepted, row("trade-1"))
    service.import_csv(account_id, accepted)

    conflict = tmp_path / "conflict.csv"
    write_csv(
        conflict,
        row(
            "trade-1",
            ticker="NEW-TICKER",
            quantity="3",
            amount="150",
            description="same source id but different economics",
        ),
    )
    before = counts(store)
    raw_before = sorted(path.name for path in store.raw_root.iterdir())

    preview = service.preview_csv(account_id, conflict)
    assert preview["ok"] is False
    assert preview["reconciliation"]["conflict_external_id"] == 1
    assert preview["transactions"][0]["import_status"] == "conflict_external_id"
    assert preview["errors"][-1]["code"] == "conflict_external_id"

    with pytest.raises(ImportValidationError, match="different canonical transaction semantics"):
        service.import_csv(account_id, conflict)

    assert counts(store) == before
    assert sorted(path.name for path in store.raw_root.iterdir()) == raw_before
    assert store.instrument_id_for_identifier("ticker", "NEW-TICKER") is None


def test_historical_null_transaction_external_id_is_still_reconciled(tmp_path):
    home = tmp_path / "home"
    legacy = LegacySQLiteStore(home)
    account_id = legacy.create_account("broker", "legacy")
    accepted = tmp_path / "legacy.csv"
    write_csv(accepted, row("legacy-1"))

    # The pre-hardening adapter stores the source ID only in imported_rows and
    # leaves transactions.external_id NULL.
    result = commit_csv_import(legacy, account_id, accepted)
    assert result["transactions"] == 1
    assert legacy.db.execute(
        "SELECT external_id FROM transactions"
    ).fetchone()[0] is None
    legacy.close()

    store = Store(home)
    service = LedgerService(store)
    later = tmp_path / "later.csv"
    write_csv(
        later,
        row("legacy-1", description="description changed only"),
        row(
            "cash-new",
            date="2025-01-02",
            kind="deposit",
            ticker="CASH",
            quantity="0",
            amount="25",
            fee="0",
        ),
    )

    preview = service.preview_csv(account_id, later)
    assert preview["reconciliation"]["duplicate_exact"] == 1
    assert preview["reconciliation"]["new"] == 1
    result = service.import_csv(account_id, later)
    assert result["transactions"] == 1
    assert store.db.execute("SELECT count(*) FROM transactions").fetchone()[0] == 2


def test_external_id_identity_is_account_scoped(tmp_path):
    store = Store(tmp_path / "home")
    service = LedgerService(store)
    first_account = service.create_account("broker", "one")
    second_account = service.create_account("broker", "two")

    first = tmp_path / "one.csv"
    write_csv(first, row("shared-id", quantity="2", amount="100"))
    service.import_csv(first_account, first)

    second = tmp_path / "two.csv"
    write_csv(second, row("shared-id", quantity="7", amount="700"))
    preview = service.preview_csv(second_account, second)
    assert preview["ok"] is True
    assert preview["reconciliation"]["new"] == 1
    assert preview["reconciliation"]["conflict_external_id"] == 0
    assert service.import_csv(second_account, second)["transactions"] == 1

    assert store.db.execute(
        "SELECT count(*) FROM transactions WHERE external_id='shared-id'"
    ).fetchone()[0] == 2


def test_exact_same_artifact_remains_idempotent_with_full_input_count(tmp_path):
    store = Store(tmp_path / "home")
    service = LedgerService(store)
    account_id = service.create_account("broker", "main")
    source = tmp_path / "same.csv"
    write_csv(source, row("one"), row("two", date="2025-01-02"))

    assert service.import_csv(account_id, source)["transactions"] == 2
    preview = service.preview_csv(account_id, source)
    assert preview["reconciliation"]["duplicate_exact"] == 2
    assert service.import_csv(account_id, source)["transactions"] == 0
    assert store.db.execute("SELECT count(*) FROM transactions").fetchone()[0] == 2

    latest = store.db.execute(
        """SELECT d.input_rows,d.inserted_rows
           FROM import_details d JOIN imports i ON i.id=d.import_id
           ORDER BY i.created_at DESC,i.id DESC LIMIT 1"""
    ).fetchone()
    assert dict(latest) == {"input_rows": 2, "inserted_rows": 0}
