from __future__ import annotations

import json
from pathlib import Path
import zipfile

import pytest

from clausula import LedgerService, Store
from clausula.application import DecisionError, DecisionService, PolicyService, PortfolioService
from clausula.application.ledger import ImportValidationError


def test_missing_known_at_uses_recorded_time_not_effective_time(tmp_path: Path) -> None:
    store = Store(tmp_path / "home")
    ledger = LedgerService(store)
    account = ledger.create_account("broker", "main")
    source = tmp_path / "historical.csv"
    source.write_text(
        "id,date,type,ticker,quantity,amount,fee,currency\n"
        "1,2025-01-01,deposit,CASH,0,10,0,USD\n",
        encoding="utf-8",
    )

    ledger.import_csv(account, source)
    row = store.transactions(account)[0]

    assert row["known_at"] == row["recorded_at"]
    assert row["known_at"] != row["effective_at"]


def test_failed_import_does_not_commit_instruments_or_import_rows(tmp_path: Path) -> None:
    store = Store(tmp_path / "home")
    ledger = LedgerService(store)
    account = ledger.create_account("broker", "main")
    source = tmp_path / "invalid.csv"
    source.write_text(
        "id,date,type,ticker,quantity,amount,fee,currency\n"
        "1,2025-01-01,buy,ABC,1,10,0,USD\n"
        "2,not-a-date,buy,DEF,1,10,0,USD\n",
        encoding="utf-8",
    )

    with pytest.raises(ImportValidationError):
        ledger.import_csv(account, source)

    assert store.db.execute("SELECT count(*) FROM instruments").fetchone()[0] == 0
    assert store.db.execute("SELECT count(*) FROM imports").fetchone()[0] == 0


def test_decision_links_reject_cross_portfolio_policy_and_transaction(tmp_path: Path) -> None:
    store = Store(tmp_path / "home")
    ledger = LedgerService(store)
    first_account = ledger.create_account("broker", "first")
    second_account = ledger.create_account("broker", "second")
    source = tmp_path / "cash.csv"
    source.write_text(
        "id,date,type,ticker,quantity,amount,fee,currency\n"
        "1,2025-01-01,deposit,CASH,0,10,0,USD\n",
        encoding="utf-8",
    )
    ledger.import_csv(first_account, source)
    transaction = ledger.transactions(first_account)[0]["id"]
    portfolios = PortfolioService(store)
    first_portfolio = portfolios.create("First", "USD")
    second_portfolio = portfolios.create("Second", "USD")
    portfolios.set_membership(first_portfolio, first_account, "add", "2025-01-01", known_at="2025-01-01")
    portfolios.set_membership(second_portfolio, second_account, "add", "2025-01-01", known_at="2025-01-01")
    policy = PolicyService(store).create(
        first_portfolio,
        "First policy",
        "2025-01-01",
        [{"key": "cash", "type": "min_cash_amount", "lower": "0"}],
        known_at="2025-01-01",
        created_at="2025-01-01",
        recorded_at="2025-01-01",
    )
    decisions = DecisionService(store)
    with pytest.raises(DecisionError, match="different portfolio"):
        decisions.create(
            second_portfolio,
            "Invalid",
            "non_trade",
            "Cross-portfolio reference",
            "2025-01-01",
            known_as_of="2025-01-01",
            policy_version_id=policy["policy_version_id"],
        )
    decision = decisions.create(
        second_portfolio,
        "Valid",
        "non_trade",
        "No action",
        "2025-01-01",
        known_as_of="2025-01-01",
        created_at="2025-01-01",
        recorded_at="2025-01-01",
    )
    with pytest.raises(ValueError, match="portfolio boundary"):
        decisions.link_transaction(decision["decision"]["id"], transaction, linked_at="2025-01-01")


def test_decision_alternative_selected_rejects_non_boolean_values(tmp_path: Path) -> None:
    store = Store(tmp_path / "home")
    portfolio = PortfolioService(store).create("Household", "USD")

    with pytest.raises(DecisionError, match="must be boolean"):
        DecisionService(store).create(
            portfolio,
            "Invalid alternative",
            "non_trade",
            "invalid",
            "2025-01-01",
            known_as_of="2025-01-01",
            alternatives=[{"key": "hold", "description": "Hold", "selected": "yes"}],
        )


def test_backup_rejects_missing_database_artifact_member(tmp_path: Path) -> None:
    store = Store(tmp_path / "home")
    ledger = LedgerService(store)
    account = ledger.create_account("broker", "main")
    source = tmp_path / "cash.csv"
    source.write_text(
        "id,date,type,ticker,quantity,amount,fee,currency\n"
        "1,2025-01-01,deposit,CASH,0,10,0,USD\n",
        encoding="utf-8",
    )
    ledger.import_csv(account, source)
    original = tmp_path / "original.zip"
    store.backup_bundle(original)
    changed = tmp_path / "missing-raw.zip"
    with zipfile.ZipFile(original) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        raw_name = next(name for name in manifest["files"] if name.startswith("raw/"))
        del manifest["files"][raw_name]
        with zipfile.ZipFile(changed, "w") as output:
            for name in archive.namelist():
                if name == "manifest.json":
                    data = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()
                elif name == raw_name:
                    continue
                else:
                    data = archive.read(name)
                output.writestr(name, data)

    with pytest.raises(ValueError, match="missing raw artifact"):
        store.verify_backup(changed)
