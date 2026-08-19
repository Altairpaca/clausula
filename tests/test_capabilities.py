from __future__ import annotations

import json

import pytest

from clausula import Store
from clausula.capabilities import (
    CapabilityError,
    CapabilityPermissionError,
    ConfirmationRequired,
    build_core_registry,
)
from clausula.cli import main
from clausula.sdk import ClausulaClient


def test_capability_specs_are_complete_and_discoverable(tmp_path):
    registry = build_core_registry(Store(tmp_path / "home"))
    descriptions = registry.describe()
    names = [item["name"] for item in descriptions]

    assert names == sorted(names)
    assert {
        "account.create",
        "ledger.get_state",
        "ledger.get_transactions",
        "ledger.import_csv",
        "market.import_fx_csv",
        "market.import_prices_csv",
        "market.list_datasets",
        "portfolio.create",
        "portfolio.get_performance",
        "portfolio.get_valuation",
        "portfolio.set_membership",
        "system.backup",
        "system.check_integrity",
        "system.export",
    } <= set(names)
    for item in descriptions:
        assert item["input_schema"]["type"] == "object"
        assert item["output_schema"]["type"] in {"object", "array"}
        assert item["permissions"]
        assert item["version"]
        assert item["provenance"]


def test_capability_enforces_permission_confirmation_and_schema(tmp_path):
    registry = build_core_registry(Store(tmp_path / "home"))
    arguments = {"institution": "broker", "name": "main"}

    with pytest.raises(CapabilityPermissionError, match="ledger:write"):
        registry.execute("account.create", arguments)
    with pytest.raises(ConfirmationRequired):
        registry.execute("account.create", arguments, permissions={"ledger:write"})
    with pytest.raises(CapabilityError, match="unknown fields"):
        registry.execute(
            "account.create",
            arguments | {"agent_override": True},
            permissions={"ledger:write"},
            confirmed=True,
        )

    dry_run = registry.execute(
        "account.create",
        arguments,
        permissions={"ledger:write"},
        dry_run=True,
    )
    assert dry_run["would_execute"] is True
    assert registry.execute(
        "system.check_integrity", permissions={"system:read"}
    )["database"] == "ok"


def test_cli_is_a_projection_of_capability_registry(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CLAUSULA_HOME", str(tmp_path / "home"))
    assert main(["capability", "list"]) == 0
    descriptions = json.loads(capsys.readouterr().out)
    assert any(item["name"] == "ledger.get_state" for item in descriptions)

    assert main(["account", "create", "broker", "main"]) == 0
    account_id = json.loads(capsys.readouterr().out)["account_id"]
    cutoff = "2025-01-01"
    assert main(["ledger", "state", account_id, "--as-of", cutoff]) == 0
    state = json.loads(capsys.readouterr().out)
    assert state["account_id"] == account_id

    assert main(
        [
            "capability",
            "run",
            "ledger.get_state",
            "--permission",
            "portfolio:read",
            "--input",
            json.dumps({"account_id": account_id, "as_of": cutoff}),
        ]
    ) == 0
    assert json.loads(capsys.readouterr().out) == state


def test_market_portfolio_cli_and_sdk_project_the_same_capabilities(
    tmp_path, monkeypatch, capsys
):
    home = tmp_path / "home"
    monkeypatch.setenv("CLAUSULA_HOME", str(home))
    source = tmp_path / "ledger.csv"
    source.write_text(
        "id,date,type,ticker,quantity,amount,fee,currency\n"
        "cash,2025-01-01,deposit,CASH,0,100,0,USD\n",
        encoding="utf-8",
    )
    prices = tmp_path / "prices.csv"
    prices.write_text(
        "date,known_at,ticker,close,currency\n"
        "2025-01-01,2025-01-01,UNUSED,1,USD\n",
        encoding="utf-8",
    )

    main(["account", "create", "broker", "main"])
    account_id = json.loads(capsys.readouterr().out)["account_id"]
    main(["ledger", "import", account_id, str(source)])
    capsys.readouterr()
    main(
        [
            "market",
            "import-prices",
            str(prices),
            "--dataset",
            "daily",
            "--version",
            "v1",
        ]
    )
    assert json.loads(capsys.readouterr().out)["prices"] == 1
    main(["portfolio", "create", "Household", "--base-currency", "USD"])
    portfolio_id = json.loads(capsys.readouterr().out)["portfolio_id"]
    main(
        [
            "portfolio",
            "membership",
            portfolio_id,
            account_id,
            "add",
            "2025-01-01",
            "--known-at",
            "2025-01-01",
        ]
    )
    capsys.readouterr()
    main(["portfolio", "valuation", portfolio_id, "2025-01-02"])
    cli_valuation = json.loads(capsys.readouterr().out)

    client = ClausulaClient(home)
    assert client.market_datasets("daily")[0]["version"] == "v1"
    assert client.portfolio_valuation(portfolio_id, "2025-01-02") == cli_valuation
    assert cli_valuation["total_value"] == "100"
