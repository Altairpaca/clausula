from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

import pytest

from clausula import LedgerService, Store
from clausula.analytics import PolicyEvaluationError, compare_plan_scenarios
from clausula.application import (
    LedgerRebuilder,
    MarketService,
    PlanningError,
    PlanningService,
    PolicyService,
    PortfolioService,
)
from clausula.capabilities import (
    CapabilityPermissionError,
    ConfirmationRequired,
    build_core_registry,
)
from clausula.domain import PolicyRule, new_id


def _write(path: Path, fields: list[str], rows: list[dict]) -> None:
    if "known_at" not in fields:
        fields = [*fields[:2], "known_at", *fields[2:]]
        rows = [
            {**row, "known_at": row.get("date") or row.get("effective_at") or "2025-01-01"}
            for row in rows
        ]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _fixture(tmp_path: Path):
    store = Store(tmp_path / "home")
    ledger = LedgerService(store)
    account = ledger.create_account("broker", "main")
    ledger_path = tmp_path / "ledger.csv"
    _write(
        ledger_path,
        ["id", "date", "type", "ticker", "quantity", "amount", "fee", "currency", "asset_type"],
        [
            {"id": "cash", "date": "2025-01-01", "type": "deposit", "ticker": "CASH", "quantity": "0", "amount": "1000", "fee": "0", "currency": "USD", "asset_type": "cash"},
            {"id": "buy", "date": "2025-01-01", "type": "buy", "ticker": "ABC", "quantity": "7", "amount": "700", "fee": "0", "currency": "USD", "asset_type": "stock"},
        ],
    )
    ledger.import_csv(account, ledger_path)
    prices = tmp_path / "prices.csv"
    _write(
        prices,
        ["date", "known_at", "ticker", "close", "currency", "asset_type"],
        [{"date": "2025-02-01", "known_at": "2025-02-01", "ticker": "ABC", "close": "100", "currency": "USD", "asset_type": "stock"}],
    )
    MarketService(store).import_prices_csv(prices, dataset_name="daily", version="v1")
    portfolios = PortfolioService(store)
    portfolio = portfolios.create("Household", "USD")
    portfolios.set_membership(portfolio, account, "add", "2025-01-01", known_at="2025-01-01")
    policy = PolicyService(store).create(
        portfolio,
        "Allocation",
        "2025-01-01",
        [
            {"key": "single", "type": "max_single_instrument_weight", "severity": "hard", "upper": "0.6"},
            {"key": "cash", "type": "min_cash_weight", "severity": "soft", "lower": "0.2"},
        ],
        known_at="2025-01-01",
    )
    instrument = store.db.execute(
        "SELECT id FROM instruments WHERE identifier='ABC'"
    ).fetchone()[0]
    return store, account, portfolio, policy["policy_id"], instrument


def test_compare_plan_scenarios_ranks_constraints_then_fees():
    instrument = new_id()
    portfolio = new_id()
    version = new_id()
    valuation = {
        "portfolio_id": portfolio,
        "as_of": "2025-01-01",
        "known_as_of": "2025-01-01",
        "base_currency": "USD",
        "complete": True,
        "total_value": "1000",
        "partial_value": "1000",
        "allocation": [
            {"asset_type": "cash", "base_value": "300", "weight": "0.3"},
            {"asset_type": "stock", "base_value": "700", "weight": "0.7"},
        ],
        "concentration": [{"instrument_id": instrument, "identifier": "ticker:ABC", "base_value": "700", "weight": "0.7"}],
        "currency_exposure": [{"currency": "USD", "base_value": "1000"}],
        "gaps": [],
    }
    rules = [
        PolicyRule(new_id(), version, "single", "max_single_instrument_weight", "hard", upper_bound="0.6")
    ]
    instruments = {
        instrument: {"scheme": "ticker", "identifier": "ABC", "asset_type": "stock", "currency": "USD"}
    }
    result = compare_plan_scenarios(
        valuation,
        rules,
        [
            {"key": "hold", "cash_available": "0", "actions": []},
            {"key": "contribute", "cash_available": "200", "actions": []},
            {"key": "sell", "cash_available": "0", "actions": [{"instrument_id": instrument, "base_value_delta": "-103", "fee": "1", "tax_estimate": "2"}]},
        ],
        instruments,
        policy_version_id=version,
        portfolio_id=portfolio,
        as_of="2025-01-01",
        known_as_of="2025-01-01",
    )

    assert result["recommended_scenario"] == "contribute"
    assert [item["status"] for item in result["scenarios"]] == [
        "feasible",
        "feasible",
        "violates_policy",
    ]
    hold = next(item for item in result["scenarios"] if item["scenario_key"] == "hold")
    assert hold["unresolved_constraints"][0]["gap"] == "0.1"
    assert result["ledger_mutated"] is False


def test_planning_create_persists_explainable_artifact_without_ledger_mutation(tmp_path):
    store, account, portfolio, policy, instrument = _fixture(tmp_path)
    transactions = store.db.execute("SELECT count(*) FROM transactions").fetchone()[0]
    audit = store.verify_audit_chain()["events"]
    planning = PlanningService(store)

    result = planning.create(
        policy,
        "Contribution options",
        "2025-02-01",
        [
            {"key": "hold", "cash_available": "0", "actions": []},
            {"key": "contribute", "cash_available": "200", "actions": []},
            {"key": "sell", "cash_available": "0", "actions": [{"instrument_id": instrument, "base_value_delta": "-101", "fee": "1", "tax_estimate": "2"}]},
        ],
        known_as_of="2025-02-01",
    )

    assert result["plan"]["portfolio_id"] == portfolio
    assert len(result["scenarios"]) == 3
    assert store.db.execute("SELECT count(*) FROM transactions").fetchone()[0] == transactions
    assert LedgerService(store).state(account, "2025-02-01")["positions"][instrument] == "7"
    assert store.verify_audit_chain()["events"] == audit + 3
    assert {item["status"] for item in result["scenarios"]} == {"feasible", "violates_policy"}
    sell = next(item for item in result["scenarios"] if item["scenario_key"] == "sell")
    assert sell["total_tax_estimate"] == "2"
    assert sell["actions"][0]["tax_estimate"] == "2"
    contribute = next(
        item for item in result["scenarios"] if item["scenario_key"] == "contribute"
    )
    assert contribute["result"]["cash_reserve"]["projected_amount"] == "500"
    assert contribute["result"]["cash_reserve"]["weight_gap"] == "0"
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store.db.execute("UPDATE plans SET name='changed' WHERE id=?", (result["plan"]["id"],))


def test_planning_rejects_float_insufficient_cash_short_and_incomplete_valuation(tmp_path):
    store, _, _, policy, instrument = _fixture(tmp_path)
    planning = PlanningService(store)
    before = store.db.execute("SELECT count(*) FROM imports").fetchone()[0]
    with pytest.raises(PlanningError, match="invalid planning action"):
        planning.create(
            policy,
            "float",
            "2025-02-01",
            [{"key": "bad", "actions": [{"instrument_id": instrument, "base_value_delta": 1.0}]}],
            known_as_of="2025-02-01",
        )
    with pytest.raises(PlanningError, match="unknown fields"):
        planning.create(
            policy,
            "unknown",
            "2025-02-01",
            [{"key": "bad", "agent_override": True, "actions": []}],
            known_as_of="2025-02-01",
        )
    with pytest.raises(PolicyEvaluationError, match="negative base cash"):
        planning.compare(
            policy,
            "2025-02-01",
            [{"key": "bad", "actions": [{"instrument_id": instrument, "base_value_delta": "400"}]}],
            known_as_of="2025-02-01",
        )
    with pytest.raises(PolicyEvaluationError, match="short position"):
        planning.compare(
            policy,
            "2025-02-01",
            [{"key": "bad", "actions": [{"instrument_id": instrument, "base_value_delta": "-800"}]}],
            known_as_of="2025-02-01",
        )
    assert store.db.execute("SELECT count(*) FROM imports").fetchone()[0] == before

    incomplete_store = Store(tmp_path / "incomplete")
    ledger = LedgerService(incomplete_store)
    account = ledger.create_account("broker", "incomplete")
    source = tmp_path / "incomplete.csv"
    _write(
        source,
        ["id", "date", "type", "ticker", "quantity", "amount", "fee", "currency"],
        [{"id": "buy", "date": "2025-01-01", "type": "buy", "ticker": "XYZ", "quantity": "1", "amount": "10", "fee": "0", "currency": "USD"}],
    )
    ledger.import_csv(account, source)
    portfolios = PortfolioService(incomplete_store)
    portfolio = portfolios.create("Incomplete")
    portfolios.set_membership(portfolio, account, "add", "2025-01-01", known_at="2025-01-01")
    guarded = PolicyService(incomplete_store).create(
        portfolio,
        "Guarded",
        "2025-01-01",
        [{"key": "cash", "type": "min_cash_weight", "lower": "0.1"}],
        known_at="2025-01-01",
    )
    with pytest.raises(PolicyEvaluationError, match="complete valuation"):
        PlanningService(incomplete_store).compare(
            guarded["policy_id"],
            "2025-01-02",
            [{"key": "hold", "actions": []}],
            known_as_of="2025-01-02",
        )


def test_planning_capabilities_permissions_confirmation_and_dry_run(tmp_path):
    store, _, _, policy, instrument = _fixture(tmp_path)
    registry = build_core_registry(store)
    scenarios = [
        {
            "key": "sell",
            "actions": [
                {"instrument_id": instrument, "base_value_delta": "-101", "fee": "1"}
            ],
        }
    ]
    arguments = {
        "policy_id": policy,
        "name": "Capability plan",
        "as_of": "2025-02-01",
        "known_as_of": "2025-02-01",
        "scenarios": scenarios,
    }
    with pytest.raises(CapabilityPermissionError):
        registry.execute("planning.create", arguments)
    permissions = {"planning:write", "policy:read", "portfolio:read", "market:read"}
    with pytest.raises(ConfirmationRequired):
        registry.execute("planning.create", arguments, permissions=permissions)
    dry = registry.execute(
        "planning.create", arguments, permissions=permissions, dry_run=True
    )
    assert dry["would_execute"] is True
    assert store.db.execute("SELECT count(*) FROM plans").fetchone()[0] == 0
    created = registry.execute(
        "planning.create", arguments, permissions=permissions, confirmed=True
    )
    assert created["plan"]["name"] == "Capability plan"
    assert registry.execute(
        "planning.get",
        {"plan_id": created["plan"]["id"]},
        permissions={"planning:read"},
    )["scenarios"][0]["status"] == "feasible"


def test_planning_backup_export_and_clean_rebuild(tmp_path):
    store, _, _, policy, instrument = _fixture(tmp_path)
    created = PlanningService(store).create(
        policy,
        "Rebuild plan",
        "2025-02-01",
        [
            {"key": "contribute", "cash_available": "200", "actions": []},
            {
                "key": "sell",
                "cash_available": "0",
                "actions": [
                    {"instrument_id": instrument, "base_value_delta": "-101", "fee": "1"}
                ],
            },
        ],
        known_as_of="2025-02-01",
        created_at="2025-02-01",
        recorded_at="2025-02-01",
    )
    export = tmp_path / "planning.jsonl"
    store.export(export)
    assert b'"table":"plan_projected_states"' in export.read_bytes()
    bundle = tmp_path / "planning.zip"
    assert store.backup_bundle(bundle)["schema_version"] == 11
    restored = Store(tmp_path / "restored")
    restored.restore_bundle(bundle)
    assert restored.plan(created["plan"]["id"])["name"] == "Rebuild plan"

    target = Store(tmp_path / "rebuilt")
    rebuild = LedgerRebuilder(store, target).rebuild()
    assert rebuild["consistent"] is True
    assert rebuild["warnings"] == []
    target_plan = rebuild["plan_mapping"][created["plan"]["id"]]
    assert target_plan != created["plan"]["id"]
    assert rebuild["plan_comparisons"][0]["matches"] is True
    assert len(target.plan_scenarios(target_plan)) == 2
