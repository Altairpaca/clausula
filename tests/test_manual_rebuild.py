from __future__ import annotations

from decimal import Decimal

from clausula import LedgerService, Store
from clausula.application import LedgerRebuilder
from clausula.models import TransactionLeg


def test_manual_event_envelopes_rebuild_all_supported_operations(tmp_path):
    source_store = Store(tmp_path / "source")
    source_service = LedgerService(source_store)
    source = source_service.create_account("broker", "source")
    destination = source_service.create_account("broker", "destination")
    source_service.record_fx_conversion(source, "USD", "TWD", "10", "320", "2025-01-01")
    source_service.record_cash_transfer(source, destination, "5", "TWD", "2025-01-02")
    instrument_id = source_service.resolve_instrument("ABC", currency="USD")
    source_file = tmp_path / "trade.csv"
    source_file.write_text(
        "id,date,type,ticker,quantity,amount,fee,currency\n"
        "buy-1,2025-01-01,buy,ABC,2,20,0,USD\n",
        encoding="utf-8",
    )
    source_service.import_csv(source, source_file)
    source_service.record_split(source, instrument_id, "2", "1", "2025-01-03")
    source_service.record_correction(
        source,
        [
            # Compensating legs preserve the original transaction and are replayable.
            # The cash leg pair intentionally sums to zero.
                TransactionLeg(source, None, Decimal(0), Decimal(-1), "USD", "cash"),
                TransactionLeg(source, None, Decimal(0), Decimal(1), "USD", "external"),
        ],
        "2025-01-04",
        "manual correction",
    )
    source_service.reconcile(
        source,
        {"cash_by_currency": {"USD": "-1", "TWD": "315"}, "positions": {instrument_id: "4"}},
        "2025-01-04",
    )

    target_store = Store(tmp_path / "target")
    result = LedgerRebuilder(source_store, target_store).rebuild()

    assert result["consistent"] is True
    assert result["warnings"] == []
    assert {
        item["operation"]
        for item in result["replayed_imports"]
        if item["kind"] == "manual_event"
    } >= {
        "ledger.record_fx_conversion",
        "ledger.record_cash_transfer",
        "ledger.record_split",
        "ledger.record_correction",
        "ledger.reconcile",
    }
