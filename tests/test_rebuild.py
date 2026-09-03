from __future__ import annotations

import csv
from pathlib import Path

from clausula import LedgerService, Store
from clausula.application import LedgerRebuilder


def test_rebuild_csv_raw_imports_into_empty_database_and_reconciles(tmp_path):
    source_store = Store(tmp_path / "source")
    source_service = LedgerService(source_store)
    account_id = source_service.create_account("broker", "main")
    source = tmp_path / "source.csv"
    with source.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=["id", "date", "known_at", "type", "ticker", "quantity", "amount", "fee", "currency"],
        )
        writer.writeheader()
        writer.writerow(
            {"id": "1", "date": "2025-01-01", "known_at": "2025-01-01", "type": "buy", "ticker": "ABC", "quantity": "2", "amount": "100", "fee": "1", "currency": "USD"}
        )
    source_service.import_csv(account_id, source)

    target_store = Store(tmp_path / "target")
    result = LedgerRebuilder(source_store, target_store).rebuild()

    target_account = result["account_mapping"][account_id]
    assert result["consistent"] is True
    assert result["warnings"] == []
    assert target_store.db.execute("SELECT count(*) FROM transactions").fetchone()[0] == 1
    assert LedgerService(target_store).state(target_account)["cash"] == "-101"
    assert target_store.db.execute("SELECT path FROM artifacts").fetchone()[0].startswith("raw/")
    raw_names = sorted(path.name for path in target_store.raw_root.iterdir())
    assert raw_names
    assert all(len(name) == 64 for name in raw_names)


def test_rebuild_rejects_nonempty_target(tmp_path):
    source_store = Store(tmp_path / "source")
    source_service = LedgerService(source_store)
    source_service.create_account("broker", "source")
    target_store = Store(tmp_path / "target")
    LedgerService(target_store).create_account("broker", "already there")

    from clausula.application import RebuildError

    try:
        LedgerRebuilder(source_store, target_store).rebuild()
    except RebuildError as exc:
        assert "empty" in str(exc)
    else:
        raise AssertionError("rebuild should reject a non-empty target")
