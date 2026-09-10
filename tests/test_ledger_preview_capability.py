from __future__ import annotations

from clausula import LedgerService, Store
from clausula.capabilities import build_core_registry


def test_ledger_preview_capability_is_read_only_and_non_persisting(tmp_path):
    store = Store(tmp_path / "home")
    service = LedgerService(store)
    account_id = service.create_account("broker", "main")
    source = tmp_path / "preview.csv"
    source.write_text(
        "id,date,known_at,type,ticker,quantity,amount,fee,currency\n"
        "1,2025-01-01,2025-01-01,buy,ABC,2,100,1,USD\n",
        encoding="utf-8",
    )
    registry = build_core_registry(store)
    spec = registry.get("ledger.preview_csv")

    assert spec.mode == "read"
    assert spec.side_effect.value == "local_read"
    assert spec.permissions == ("ledger:read",)
    assert spec.confirmation_required is False

    before = {
        table: store.db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in ("artifacts", "imports", "instruments", "transactions", "legs")
    }
    result = registry.execute(
        "ledger.preview_csv",
        {"account_id": account_id, "path": str(source)},
        permissions={"ledger:read"},
    )
    after = {
        table: store.db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in ("artifacts", "imports", "instruments", "transactions", "legs")
    }

    assert result["ok"] is True
    assert result["transactions"][0]["legs"][0]["instrument"]["identifier"] == "ABC"
    assert after == before
