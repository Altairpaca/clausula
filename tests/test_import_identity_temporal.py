from __future__ import annotations

from clausula import LedgerService, Store


def test_reimport_without_known_at_preserves_first_accepted_knowledge_time(tmp_path):
    store = Store(tmp_path / "home")
    service = LedgerService(store)
    account_id = service.create_account("broker", "main")

    # known_at is deliberately absent. The parser defaults it to each ingest's
    # checked_at, so duplicate identity must not depend on that later timestamp.
    first = tmp_path / "first.csv"
    first.write_text(
        "id,date,type,ticker,quantity,amount,fee,currency\n"
        "event-1,2025-01-01,buy,ABC,2,100,1,USD\n",
        encoding="utf-8",
    )
    assert service.import_csv(account_id, first)["transactions"] == 1
    original = store.db.execute(
        "SELECT id,known_at FROM transactions WHERE account_id=?",
        (account_id,),
    ).fetchone()

    later = tmp_path / "later.csv"
    later.write_text(
        "id,date,type,ticker,quantity,amount,fee,currency,description\n"
        "event-1,2025-01-01,buy,ABC,2,100,1,USD,later export\n",
        encoding="utf-8",
    )
    preview = service.preview_csv(account_id, later)
    assert preview["ok"] is True
    assert preview["reconciliation"]["duplicate_exact"] == 1
    assert preview["transactions"][0]["import_status"] == "duplicate_exact"

    assert service.import_csv(account_id, later)["transactions"] == 0
    after = store.db.execute(
        "SELECT id,known_at FROM transactions WHERE account_id=?",
        (account_id,),
    ).fetchall()
    assert len(after) == 1
    assert after[0]["id"] == original["id"]
    assert after[0]["known_at"] == original["known_at"]
