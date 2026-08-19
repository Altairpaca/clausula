from __future__ import annotations

import csv
import json
from pathlib import Path
import sqlite3
import zipfile

import pytest

from clausula import LedgerService, Store
from clausula.adapters.migrations import MigrationError
from clausula.application import LedgerRepository


def imported_store(tmp_path: Path) -> tuple[Store, LedgerService, str]:
    store = Store(tmp_path / "home")
    service = LedgerService(store)
    account_id = service.create_account("broker", "main")
    source = tmp_path / "trades.csv"
    with source.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=["id", "date", "type", "ticker", "quantity", "amount", "fee"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "id": "trade-1",
                "date": "2025-01-01",
                "type": "buy",
                "ticker": "ABC",
                "quantity": "2",
                "amount": "100",
                "fee": "1",
            }
        )
    service.import_csv(account_id, source)
    return store, service, account_id


def test_sqlite_store_satisfies_typed_ledger_repository(tmp_path):
    assert isinstance(Store(tmp_path / "home"), LedgerRepository)


def test_migrations_are_ordered_and_checksummed(tmp_path):
    store = Store(tmp_path / "home")
    rows = store.db.execute(
        "SELECT version,name,length(checksum) FROM schema_migrations ORDER BY version"
    ).fetchall()
    assert [tuple(row) for row in rows] == [
        (1, "kernel_baseline", 64),
        (2, "tamper_evident_audit_log", 64),
        (3, "ledger_lots_fx_corporate_actions", 64),
    ]

    store.db.execute("DROP TRIGGER schema_migrations_reject_update")
    store.db.execute("UPDATE schema_migrations SET checksum=? WHERE version=1", ("0" * 64,))
    store.db.commit()
    store.close()
    with pytest.raises(MigrationError, match="checksum mismatch"):
        Store(tmp_path / "home")


def test_future_schema_is_rejected(tmp_path):
    root = tmp_path / "future"
    root.mkdir()
    with sqlite3.connect(root / "clausula.db") as connection:
        connection.execute("PRAGMA user_version = 99")
    with pytest.raises(MigrationError, match="newer than supported"):
        Store(root)


def test_audit_chain_covers_canonical_writes_and_detects_tampering(tmp_path):
    store, service, account_id = imported_store(tmp_path)
    check = store.verify_audit_chain()
    operations = {
        row[0] for row in store.db.execute("SELECT operation FROM audit_events ORDER BY sequence")
    }

    assert check["valid"] is True
    assert check["events"] >= 5
    assert {"account.create", "artifact.capture", "instrument.resolve", "ledger.buy", "import.create"} <= operations
    assert service.state(account_id)["cash"] == "-101"

    store.db.execute("DROP TRIGGER audit_events_reject_update")
    store.db.execute("UPDATE audit_events SET payload_json='{}' WHERE sequence=1")
    store.db.commit()
    assert store.verify_audit_chain() == {
        "valid": False,
        "events": check["events"],
        "error": "event hash mismatch at 1",
    }


def test_backup_bundle_round_trip_preserves_state_raw_data_audit_and_export(tmp_path):
    store, service, account_id = imported_store(tmp_path)
    before_export = tmp_path / "before.jsonl"
    store.export(before_export)
    bundle = tmp_path / "backup.clausula.zip"

    manifest = store.backup_bundle(bundle)
    verified = store.verify_backup(bundle)

    assert verified["valid"] is True
    assert verified["sha256"] == manifest["sha256"]
    assert "database/clausula.db" in verified["files"]
    assert "export/canonical.jsonl" in verified["files"]
    assert any(name.startswith("raw/") for name in verified["files"])

    restored_store = Store(tmp_path / "restored")
    restored_store.restore_bundle(bundle)
    restored_service = LedgerService(restored_store)
    after_export = tmp_path / "after.jsonl"
    restored_store.export(after_export)

    assert restored_service.state(account_id)["cash"] == "-101"
    assert restored_store.integrity_check() == "ok"
    assert restored_store.verify_audit_chain()["valid"] is True
    before_records = [
        json.loads(line) for line in before_export.read_text(encoding="utf-8").splitlines()[1:]
    ]
    after_records = [
        json.loads(line) for line in after_export.read_text(encoding="utf-8").splitlines()[1:]
    ]
    assert [record for record in before_records if record["table"] != "audit_events"] == [
        record for record in after_records if record["table"] != "audit_events"
    ]
    assert restored_store.db.execute(
        "SELECT operation FROM audit_events ORDER BY sequence DESC LIMIT 1"
    ).fetchone()[0] == "system.restore"
    assert sorted(path.name for path in restored_store.raw_root.iterdir()) == [
        row[0] for row in store.db.execute("SELECT sha256 FROM artifacts WHERE path NOT LIKE 'manual://%'")
    ]


def test_backup_rejects_tampered_member(tmp_path):
    store, _, _ = imported_store(tmp_path)
    source = tmp_path / "backup.clausula.zip"
    store.backup_bundle(source)
    tampered = tmp_path / "tampered.clausula.zip"

    with zipfile.ZipFile(source) as original, zipfile.ZipFile(tampered, "w") as changed:
        for name in original.namelist():
            data = original.read(name)
            if name == "export/canonical.jsonl":
                data += b"tampered\n"
            changed.writestr(name, data)

    with pytest.raises(ValueError, match="hash mismatch"):
        store.verify_backup(tampered)


def test_canonical_export_is_stable_jsonl(tmp_path):
    store, _, _ = imported_store(tmp_path)
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"

    store.export(first)
    store.export(second)

    assert first.read_bytes() == second.read_bytes()
    records = [json.loads(line) for line in first.read_text(encoding="utf-8").splitlines()]
    assert records[0] == {"format": "clausula-canonical-jsonl-v1"}
    assert any(record.get("table") == "transactions" for record in records)
