from __future__ import annotations

import csv
from pathlib import Path

import pytest

from clausula import LedgerService, Store
from clausula.application import ImportValidationError
from clausula.application.ledger_import import parse_csv_import


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def table_counts(store: Store) -> dict[str, int]:
    return {
        table: store.db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in ("artifacts", "imports", "instruments", "transactions", "legs")
    }


def test_preview_is_side_effect_free_and_exposes_normalized_intent(tmp_path):
    store = Store(tmp_path / "home")
    service = LedgerService(store)
    account_id = service.create_account("broker", "main")
    source = tmp_path / "trades.csv"
    write_csv(
        source,
        ["id", "date", "known_at", "type", "ticker", "quantity", "amount", "fee", "currency"],
        [
            {
                "id": "trade-1",
                "date": "2025-01-01",
                "known_at": "2025-01-01",
                "type": "buy",
                "ticker": "ABC",
                "quantity": "2.500",
                "amount": "100.00",
                "fee": "1.25",
                "currency": "usd",
            }
        ],
    )
    before = table_counts(store)

    preview = service.preview_csv(account_id, source)

    assert preview["format"] == "clausula-ledger-csv-preview/v1"
    assert preview["ok"] is True
    assert preview["row_count"] == 1
    assert preview["valid_rows"] == 1
    assert preview["errors"] == []
    transaction = preview["transactions"][0]
    assert transaction["external_id"] == "trade-1"
    assert transaction["effective_at"] == "2025-01-01T00:00:00.000000+00:00"
    assert transaction["known_at"] == "2025-01-01T00:00:00.000000+00:00"
    assert transaction["legs"] == [
        {
            "instrument": {
                "identifier": "ABC",
                "scheme": "ticker",
                "name": "",
                "asset_type": "stock",
                "currency": "USD",
            },
            "quantity": "2.5",
            "amount": "100",
            "currency": "USD",
            "leg_type": "position",
        },
        {
            "instrument": None,
            "quantity": "0",
            "amount": "-101.25",
            "currency": "USD",
            "leg_type": "cash",
        },
        {
            "instrument": None,
            "quantity": "0",
            "amount": "1.25",
            "currency": "USD",
            "leg_type": "fee",
        },
    ]
    assert table_counts(store) == before


def test_preview_collects_independent_row_errors_without_partial_state(tmp_path):
    store = Store(tmp_path / "home")
    service = LedgerService(store)
    account_id = service.create_account("broker", "main")
    source = tmp_path / "bad.csv"
    write_csv(
        source,
        ["id", "date", "known_at", "type", "ticker", "quantity", "amount", "fee"],
        [
            {"id": "a", "date": "not-a-date", "known_at": "2025-01-01", "type": "buy", "ticker": "ABC", "quantity": "1", "amount": "10", "fee": "0"},
            {"id": "b", "date": "2025-01-01", "known_at": "2025-01-01", "type": "buy", "ticker": "ABC", "quantity": "-1", "amount": "10", "fee": "0"},
            {"id": "c", "date": "2025-01-01", "known_at": "2025-01-01", "type": "mystery", "ticker": "ABC", "quantity": "1", "amount": "10", "fee": "0"},
        ],
    )
    before = table_counts(store)

    preview = service.preview_csv(account_id, source)

    assert preview["ok"] is False
    assert preview["row_count"] == 3
    assert preview["valid_rows"] == 0
    assert [(item["row"], item["field"], item["code"]) for item in preview["errors"]] == [
        (2, "effective_at", "invalid_timestamp"),
        (3, "quantity", "negative_value"),
        (4, "type", "unsupported_type"),
    ]
    assert table_counts(store) == before

    with pytest.raises(ImportValidationError, match="CSV row 2"):
        service.import_csv(account_id, source)
    assert table_counts(store) == before


def test_preview_and_commit_share_transaction_semantics(tmp_path):
    store = Store(tmp_path / "home")
    service = LedgerService(store)
    account_id = service.create_account("broker", "main")
    source = tmp_path / "valid.csv"
    write_csv(
        source,
        ["id", "date", "known_at", "type", "ticker", "quantity", "amount", "fee", "currency", "identifier_scheme", "asset_type"],
        [
            {"id": "1", "date": "2025-01-01", "known_at": "2025-01-01", "type": "buy", "ticker": "ABC", "quantity": "2", "amount": "100", "fee": "1", "currency": "USD", "identifier_scheme": "ticker", "asset_type": "stock"},
            {"id": "2", "date": "2025-01-02", "known_at": "2025-01-02", "type": "deposit", "ticker": "CASH", "quantity": "0", "amount": "50", "fee": "0", "currency": "USD", "identifier_scheme": "", "asset_type": ""},
        ],
    )

    preview = service.preview_csv(account_id, source)
    result = service.import_csv(account_id, source)
    committed = service.transactions(account_id)

    assert result["sha256"] == preview["source_sha256"]
    assert result["transactions"] == 2
    assert len(committed) == len(preview["transactions"]) == 2
    for expected, actual in zip(preview["transactions"], committed, strict=True):
        assert actual["type"] == expected["type"]
        assert actual["effective_at"] == expected["effective_at"]
        assert actual["known_at"] == expected["known_at"]
        actual_legs = actual["legs"]
        assert len(actual_legs) == len(expected["legs"])
        for expected_leg, actual_leg in zip(expected["legs"], actual_legs, strict=True):
            assert actual_leg["quantity"] == expected_leg["quantity"]
            assert actual_leg["amount"] == expected_leg["amount"]
            assert actual_leg["currency"] == expected_leg["currency"]
            assert actual_leg["leg_type"] == expected_leg["leg_type"]
            if expected_leg["instrument"] is None:
                assert actual_leg["instrument_id"] is None
            else:
                details = store.instrument_details(actual_leg["instrument_id"])
                assert details["identifier"] == expected_leg["instrument"]["identifier"]
                assert details["scheme"] == expected_leg["instrument"]["scheme"]


def test_parser_reports_defaults_and_never_materializes_repository_state(tmp_path):
    source = tmp_path / "minimal.csv"
    write_csv(source, ["date", "ticker", "quantity", "amount"], [{"date": "2025-01-01", "ticker": "ABC", "quantity": "1", "amount": "10"}])

    plan = parse_csv_import(source, recorded_at="2025-02-01")

    assert plan.ok is True
    parsed = plan.transactions[0]
    assert parsed.external_id == "1"
    assert set(parsed.defaulted_fields) >= {
        "type",
        "known_at",
        "currency",
        "fee",
        "identifier_scheme",
        "asset_type",
        "description",
    }
    assert parsed.known_at == "2025-02-01T00:00:00.000000+00:00"
