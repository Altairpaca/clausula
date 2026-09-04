from __future__ import annotations

import csv
from pathlib import Path

import pytest

from clausula import LedgerService, Store
from clausula.adapters.accounting import AccountingPolicyProjection
from clausula.adapters.mcp import McpAdapter, McpProfile
from clausula.application.accounting import AccountingPolicyError, AccountingService
from clausula.application import LedgerRebuilder
from clausula.capabilities import CapabilityPermissionError, ConfirmationRequired, build_core_registry


def _import(service: LedgerService, account_id: str, path: Path, rows: list[dict]) -> None:
    fields = ["id", "date", "known_at", "type", "ticker", "quantity", "amount", "fee", "currency"]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(
            [{**row, "known_at": row.get("known_at") or row["date"]} for row in rows]
        )
    service.import_csv(account_id, path)


def _accounting(store: Store) -> AccountingService:
    return AccountingService(AccountingPolicyProjection(store))


def test_accounting_policy_is_temporal_and_fail_closed(tmp_path: Path) -> None:
    store = Store(tmp_path / "home")
    ledger = LedgerService(store)
    account_id = ledger.create_account("broker", "main")
    service = _accounting(store)

    unavailable = service.active_policy(
        account_id, "2026-01-15", known_as_of="2026-01-15"
    )
    assert unavailable["status"] == "unavailable"

    created = service.create_policy(
        account_id,
        "2026-01-01",
        lot_method="fifo",
        allow_short=False,
        jurisdiction_profile="HK-brokerage-profile",
        tax_profile_ref="local://tax/hk-v1",
        known_at="2026-02-01",
        recorded_at="2026-02-01",
    )
    assert service.active_policy(
        account_id, "2026-01-15", known_as_of="2026-01-15"
    )["status"] == "unavailable"
    visible = service.active_policy(
        account_id, "2026-01-15", known_as_of="2026-02-15"
    )
    assert visible["lot_method"] == "fifo"
    assert visible["tax_profile_ref"] == "local://tax/hk-v1"

    service.add_version(
        created["policy_id"],
        "2026-03-01",
        lot_method="lifo",
        known_at="2026-03-02",
        recorded_at="2026-03-02",
    )
    assert service.active_policy(
        account_id, "2026-03-01", known_as_of="2026-03-01"
    )["lot_method"] == "fifo"
    assert service.active_policy(
        account_id, "2026-03-01", known_as_of="2026-03-03"
    )["lot_method"] == "lifo"


def test_lifo_and_hifo_change_selected_long_lots_without_changing_ledger(tmp_path: Path) -> None:
    store = Store(tmp_path / "home")
    ledger = LedgerService(store)
    account_id = ledger.create_account("broker", "main")
    _import(
        ledger,
        account_id,
        tmp_path / "trades.csv",
        [
            {"id": "b1", "date": "2026-01-01", "type": "buy", "ticker": "ABC", "quantity": "10", "amount": "100", "fee": "0", "currency": "USD"},
            {"id": "b2", "date": "2026-01-02", "type": "buy", "ticker": "ABC", "quantity": "5", "amount": "75", "fee": "0", "currency": "USD"},
            {"id": "s1", "date": "2026-01-03", "type": "sell", "ticker": "ABC", "quantity": "5", "amount": "100", "fee": "0", "currency": "USD"},
        ],
    )
    service = _accounting(store)
    policy = service.create_policy(
        account_id,
        "2026-01-01",
        lot_method="lifo",
        known_at="2026-01-01",
        recorded_at="2026-01-01",
    )
    lifo = service.cost_basis(account_id, "2026-01-04", known_as_of="2026-01-04")
    assert lifo["method"] == "LIFO"
    assert lifo["realized_gain_by_currency"] == {"USD": "25"}
    assert lifo["realized"][0]["matches"][0]["source_transaction_id"] != ""

    service.add_version(
        policy["policy_id"],
        "2026-01-04",
        lot_method="hifo",
        known_at="2026-01-04",
        recorded_at="2026-01-04",
    )
    hifo = service.cost_basis(account_id, "2026-01-04", known_as_of="2026-01-04")
    assert hifo["method"] == "HIFO"
    assert hifo["realized_gain_by_currency"] == {"USD": "25"}

    # Existing public ledger surface intentionally remains the legacy FIFO contract.
    legacy = ledger.cost_basis(account_id, "2026-01-04", known_as_of="2026-01-04")
    assert legacy["method"] == "FIFO"
    assert legacy["realized_gain_by_currency"] == {"USD": "50"}


def test_short_sale_and_cover_are_explicit_and_deterministic(tmp_path: Path) -> None:
    store = Store(tmp_path / "home")
    ledger = LedgerService(store)
    account_id = ledger.create_account("broker", "short")
    _import(
        ledger,
        account_id,
        tmp_path / "short.csv",
        [
            {"id": "s1", "date": "2026-01-01", "type": "sell", "ticker": "XYZ", "quantity": "10", "amount": "100", "fee": "0", "currency": "USD"},
            {"id": "b1", "date": "2026-01-02", "type": "buy", "ticker": "XYZ", "quantity": "4", "amount": "32", "fee": "0", "currency": "USD"},
        ],
    )
    service = _accounting(store)
    service.create_policy(
        account_id,
        "2026-01-01",
        lot_method="fifo",
        allow_short=True,
        known_at="2026-01-01",
        recorded_at="2026-01-01",
    )
    report = service.cost_basis(account_id, "2026-01-03", known_as_of="2026-01-03")
    assert report["realized_gain_by_currency"] == {"USD": "8"}
    assert report["realized"][0]["direction"] == "short"
    assert report["realized"][0]["quantity"] == "4"
    assert report["open_lots"][0]["side"] == "short"
    assert report["open_lots"][0]["quantity"] == "6"
    assert report["open_short_proceeds_by_currency"] == {"USD": "60"}


def test_shorting_fails_closed_when_policy_disallows_it(tmp_path: Path) -> None:
    store = Store(tmp_path / "home")
    ledger = LedgerService(store)
    account_id = ledger.create_account("broker", "cash-only")
    _import(
        ledger,
        account_id,
        tmp_path / "short.csv",
        [{"id": "s1", "date": "2026-01-01", "type": "sell", "ticker": "XYZ", "quantity": "1", "amount": "10", "fee": "0", "currency": "USD"}],
    )
    service = _accounting(store)
    service.create_policy(
        account_id,
        "2026-01-01",
        allow_short=False,
        known_at="2026-01-01",
        recorded_at="2026-01-01",
    )
    with pytest.raises(AccountingPolicyError, match="insufficient long quantity"):
        service.cost_basis(account_id, "2026-01-02", known_as_of="2026-01-02")


def test_accounting_capabilities_and_mcp_permissions(tmp_path: Path) -> None:
    store = Store(tmp_path / "home")
    account_id = LedgerService(store).create_account("broker", "main")
    registry = build_core_registry(store)
    names = {row["name"] for row in registry.describe()}
    assert {
        "accounting.create_policy",
        "accounting.add_policy_version",
        "accounting.active_policy",
        "accounting.list_policies",
        "accounting.cost_basis",
    } <= names

    with pytest.raises(ConfirmationRequired):
        registry.execute(
            "accounting.create_policy",
            {"account_id": account_id, "effective_from": "2026-01-01"},
            permissions={"accounting:write"},
        )
    with pytest.raises(CapabilityPermissionError):
        registry.execute(
            "accounting.create_policy",
            {"account_id": account_id, "effective_from": "2026-01-01"},
            permissions={"accounting:read"},
            confirmed=True,
        )
    advisor = {tool.name for tool in McpAdapter(store).list_tools(McpProfile.ADVISOR)}
    admin = {tool.name for tool in McpAdapter(store).list_tools(McpProfile.ADMIN)}
    assert "accounting.cost_basis" in advisor
    assert "accounting.create_policy" not in advisor
    assert "accounting.create_policy" in admin


def test_accounting_policy_survives_clean_rebuild(tmp_path: Path) -> None:
    source = Store(tmp_path / "source")
    account_id = LedgerService(source).create_account("broker", "main")
    service = _accounting(source)
    created = service.create_policy(
        account_id,
        "2026-01-01",
        lot_method="hifo",
        allow_short=True,
        jurisdiction_profile="configured-local-profile",
        known_at="2026-01-01",
        recorded_at="2026-01-01",
    )
    service.add_version(
        created["policy_id"],
        "2026-02-01",
        lot_method="lifo",
        known_at="2026-02-01",
        recorded_at="2026-02-01",
    )

    target = Store(tmp_path / "target")
    result = LedgerRebuilder(source, target).rebuild()
    assert result["warnings"] == []
    target_account = result["account_mapping"][account_id]
    rebuilt = AccountingService(AccountingPolicyProjection(target)).active_policy(
        target_account, "2026-02-02", known_as_of="2026-02-02"
    )
    assert rebuilt["status"] == "available"
    assert rebuilt["lot_method"] == "lifo"
    assert rebuilt["allow_short"] is True
    assert result["accounting_policy_comparisons"][0]["matches"] is True
