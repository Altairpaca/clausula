import csv
from decimal import Decimal
from pathlib import Path
import sqlite3

import pytest

from clausula import LedgerService, Store
from clausula.application import ImportValidationError
from clausula.domain import TransactionLeg


def write_csv(path: Path, rows: list[dict], fieldnames: list[str] | None = None) -> None:
    names = fieldnames or list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=names)
        writer.writeheader()
        writer.writerows(rows)


def test_raw_artifact_is_content_addressed_and_immutable(tmp_path):
    store = Store(tmp_path / "home")
    source = tmp_path / "broker.csv"
    source.write_text("id,amount\n1,10\n", encoding="utf-8")

    first_id, digest = store.artifact(source)
    second_id, second_digest = store.artifact(source)
    row = store.db.execute("SELECT path FROM artifacts WHERE id=?", (first_id,)).fetchone()

    assert first_id == second_id
    assert digest == second_digest
    assert row["path"] == f"raw/{digest}"
    assert (store.raw_root / digest).read_bytes() == source.read_bytes()
    assert (store.raw_root / digest).stat().st_mode & 0o222 == 0


def test_invalid_csv_does_not_commit_an_import_or_transactions(tmp_path):
    store = Store(tmp_path / "home")
    service = LedgerService(store)
    account_id = service.create_account("broker", "main")
    source = tmp_path / "invalid.csv"
    write_csv(
        source,
        [
            {"id": "1", "date": "2025-01-01", "type": "buy", "ticker": "ABC", "quantity": "1", "amount": "10"},
            {"id": "2", "date": "not-a-date", "type": "buy", "ticker": "ABC", "quantity": "1", "amount": "10"},
        ],
    )

    with pytest.raises(ImportValidationError, match="row 3"):
        service.import_csv(account_id, source)

    assert store.db.execute("SELECT count(*) FROM imports").fetchone()[0] == 0
    assert store.db.execute("SELECT count(*) FROM transactions").fetchone()[0] == 0


def test_imported_transactions_conserve_amounts_and_carry_provenance(tmp_path):
    store = Store(tmp_path / "home")
    service = LedgerService(store)
    account_id = service.create_account("broker", "main")
    source = tmp_path / "trades.csv"
    write_csv(
        source,
        [{"id": "1", "date": "2025-01-01", "type": "buy", "ticker": "ABC", "quantity": "2", "amount": "100", "fee": "1"}],
    )

    result = service.import_csv(account_id, source)
    transaction = service.transactions(account_id)[0]
    amounts = [Decimal(leg["amount"]) for leg in transaction["legs"]]

    assert sum(amounts) == 0
    assert transaction["artifact_id"] == result["artifact_id"]
    assert transaction["import_id"] == result["import_batch_id"]
    assert transaction["effective_at"]
    assert transaction["known_at"]
    assert transaction["recorded_at"]


def test_append_only_financial_tables_reject_update_and_delete(tmp_path):
    store = Store(tmp_path / "home")
    service = LedgerService(store)
    account_id = service.create_account("broker", "main")
    source = tmp_path / "cash.csv"
    write_csv(source, [{"id": "1", "date": "2025-01-01", "type": "deposit", "ticker": "CASH", "quantity": "0", "amount": "10"}])
    service.import_csv(account_id, source)
    transaction_id = service.transactions(account_id)[0]["id"]

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store.db.execute("UPDATE transactions SET description='changed' WHERE id=?", (transaction_id,))
    store.db.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store.db.execute("DELETE FROM transactions WHERE id=?", (transaction_id,))
    store.db.rollback()


def test_correction_has_real_provenance_and_links_to_original(tmp_path):
    store = Store(tmp_path / "home")
    service = LedgerService(store)
    account_id = service.create_account("broker", "main")
    source = tmp_path / "cash.csv"
    write_csv(source, [{"id": "1", "date": "2025-01-01", "type": "deposit", "ticker": "CASH", "quantity": "0", "amount": "10"}])
    service.import_csv(account_id, source)
    original_id = service.transactions(account_id)[0]["id"]

    correction_id = service.record_correction(
        account_id,
        [
            TransactionLeg(account_id, None, Decimal("0"), Decimal("-1"), "USD", "cash"),
            TransactionLeg(account_id, None, Decimal("0"), Decimal("1"), "USD", "external"),
        ],
        "2025-01-02",
        "broker statement correction",
        corrects_transaction_id=original_id,
    )

    correction = store.transaction(correction_id)
    link = store.db.execute(
        "SELECT corrected_transaction_id FROM corrections WHERE correction_transaction_id=?",
        (correction_id,),
    ).fetchone()
    assert correction["artifact_id"] != "manual"
    assert correction["import_id"] != "manual"
    assert link["corrected_transaction_id"] == original_id
    assert service.state(account_id)["cash"] == "9"


def test_reconciliation_is_an_append_only_record_not_a_state_mutation(tmp_path):
    store = Store(tmp_path / "home")
    service = LedgerService(store)
    account_id = service.create_account("broker", "main")

    result = service.reconcile(account_id, {"cash": "5", "positions": {}}, "2025-01-01")

    assert result.record_id is not None
    assert result.differences[0]["kind"] == "cash"
    assert service.state(account_id, "2025-01-01")["cash"] == "0"
    assert store.db.execute("SELECT count(*) FROM reconciliation_records").fetchone()[0] == 1


def test_state_keeps_currencies_separate_and_transfer_direction_is_correct(tmp_path):
    service = LedgerService(Store(tmp_path / "home"))
    account_id = service.create_account("broker", "main")
    source = tmp_path / "cash.csv"
    write_csv(
        source,
        [
            {"id": "1", "date": "2025-01-01", "type": "transfer_in", "ticker": "CASH", "quantity": "0", "amount": "10", "currency": "USD"},
            {"id": "2", "date": "2025-01-01", "type": "transfer_out", "ticker": "CASH", "quantity": "0", "amount": "3", "currency": "USD"},
            {"id": "3", "date": "2025-01-01", "type": "deposit", "ticker": "CASH", "quantity": "0", "amount": "100", "currency": "TWD"},
        ],
    )

    service.import_csv(account_id, source)
    state = service.state(account_id)
    assert state["cash"] is None
    assert state["cash_by_currency"] == {"TWD": "100", "USD": "7"}


def test_internal_cash_transfer_ties_out_both_accounts_and_fee(tmp_path):
    store = Store(tmp_path / "home")
    service = LedgerService(store)
    source = service.create_account("broker", "source")
    destination = service.create_account("bank", "destination")

    result = service.record_cash_transfer(
        source, destination, "100", "USD", "2025-01-01", fee="2"
    )

    assert service.state(source)["cash_by_currency"] == {"USD": "-102"}
    assert service.state(destination)["cash_by_currency"] == {"USD": "100"}
    link = store.db.execute(
        "SELECT * FROM transfer_links WHERE id=?", (result["transfer_id"],)
    ).fetchone()
    assert link["source_transaction_id"] == result["source_transaction_id"]
    assert link["destination_transaction_id"] == result["destination_transaction_id"]
    for transaction_id in (result["source_transaction_id"], result["destination_transaction_id"]):
        assert sum(Decimal(leg["amount"]) for leg in store.legs(transaction_id)) == 0


def test_pre_versioned_database_is_upgraded_without_rewriting_facts(tmp_path):
    root = tmp_path / "home"
    root.mkdir()
    account_id = "11111111-1111-4111-8111-111111111111"
    artifact_id = "22222222-2222-4222-8222-222222222222"
    import_id = "33333333-3333-4333-8333-333333333333"
    transaction_id = "44444444-4444-4444-8444-444444444444"
    with sqlite3.connect(root / "clausula.db") as connection:
        connection.executescript(
            """
            CREATE TABLE accounts(id TEXT PRIMARY KEY, institution TEXT NOT NULL, name TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE instruments(id TEXT PRIMARY KEY, scheme TEXT NOT NULL, identifier TEXT NOT NULL, name TEXT NOT NULL, asset_type TEXT NOT NULL, currency TEXT NOT NULL, UNIQUE(scheme,identifier));
            CREATE TABLE artifacts(id TEXT PRIMARY KEY, path TEXT NOT NULL, sha256 TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE imports(id TEXT PRIMARY KEY, artifact_id TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE transactions(id TEXT PRIMARY KEY, account_id TEXT NOT NULL, type TEXT NOT NULL, effective_at TEXT NOT NULL, known_at TEXT NOT NULL, recorded_at TEXT NOT NULL, description TEXT, artifact_id TEXT NOT NULL, import_id TEXT NOT NULL, external_id TEXT, UNIQUE(account_id, external_id));
            CREATE TABLE legs(id INTEGER PRIMARY KEY, transaction_id TEXT NOT NULL, account_id TEXT NOT NULL, instrument_id TEXT, quantity TEXT NOT NULL, amount TEXT NOT NULL, currency TEXT NOT NULL, leg_type TEXT NOT NULL);
            CREATE TABLE observations(id INTEGER PRIMARY KEY, account_id TEXT NOT NULL, instrument_id TEXT, quantity TEXT NOT NULL, cash TEXT NOT NULL, as_of TEXT NOT NULL);
            """
        )
        connection.execute("INSERT INTO accounts VALUES(?,?,?,?)", (account_id, "broker", "legacy", "2025-01-01"))
        connection.execute("INSERT INTO artifacts VALUES(?,?,?,?)", (artifact_id, "/legacy.csv", "a" * 64, "2025-01-01"))
        connection.execute("INSERT INTO imports VALUES(?,?,?)", (import_id, artifact_id, "2025-01-01"))
        connection.execute(
            "INSERT INTO transactions VALUES(?,?,?,?,?,?,?,?,?,?)",
            (transaction_id, account_id, "deposit", "2025-01-01", "2025-01-01", "2025-01-01", "legacy", artifact_id, import_id, "row-1"),
        )
        connection.execute(
            "INSERT INTO legs(transaction_id,account_id,instrument_id,quantity,amount,currency,leg_type) VALUES(?,?,?,?,?,?,?)",
            (transaction_id, account_id, None, "0", "10.00", "USD", "cash"),
        )

    store = Store(root)

    assert store.integrity_check() == "ok"
    assert store.db.execute("PRAGMA user_version").fetchone()[0] == 7
    assert [row[0] for row in store.db.execute("SELECT version FROM schema_migrations ORDER BY version")] == [1, 2, 3, 4, 5, 6, 7]
    assert store.db.execute("SELECT artifact_kind FROM artifact_details").fetchone()[0] == "legacy"
    assert store.db.execute("SELECT adapter_name FROM import_details").fetchone()[0] == "legacy"
    assert store.db.execute("SELECT transaction_id FROM imported_rows").fetchone()[0] == transaction_id
    assert store.db.execute("SELECT amount FROM legs").fetchone()[0] == "10.00"
