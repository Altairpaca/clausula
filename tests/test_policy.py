from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

import pytest

from clausula import LedgerService, Store
from clausula.application import (
    LedgerRebuilder,
    MarketService,
    PolicyService,
    PortfolioService,
)
from clausula.capabilities import (
    CapabilityPermissionError,
    ConfirmationRequired,
    build_core_registry,
)


def write_rows(path: Path, fields: list[str], rows: list[dict]) -> None:
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


def fixture(tmp_path: Path):
    store = Store(tmp_path / "home")
    ledger = LedgerService(store)
    account = ledger.create_account("broker", "main")
    transactions = tmp_path / "ledger.csv"
    write_rows(
        transactions,
        ["id", "date", "type", "ticker", "quantity", "amount", "fee", "currency", "asset_type"],
        [
            {"id": "cash", "date": "2025-01-01", "type": "deposit", "ticker": "CASH", "quantity": "0", "amount": "200", "fee": "0", "currency": "USD", "asset_type": "cash"},
            {"id": "buy", "date": "2025-01-01", "type": "buy", "ticker": "ABC", "quantity": "2", "amount": "100", "fee": "0", "currency": "USD", "asset_type": "stock"},
        ],
    )
    ledger.import_csv(account, transactions)
    prices = tmp_path / "prices.csv"
    write_rows(
        prices,
        ["date", "known_at", "ticker", "close", "currency", "asset_type"],
        [
            {"date": "2025-01-01", "known_at": "2025-01-01", "ticker": "ABC", "close": "50", "currency": "USD", "asset_type": "stock"},
            {"date": "2025-03-01", "known_at": "2025-03-01", "ticker": "ABC", "close": "50", "currency": "USD", "asset_type": "stock"},
        ],
    )
    MarketService(store).import_prices_csv(prices, dataset_name="daily", version="v1")
    portfolios = PortfolioService(store)
    portfolio = portfolios.create("Household", "USD")
    portfolios.set_membership(
        portfolio, account, "add", "2025-01-01", known_at="2025-01-01"
    )
    instrument = store.db.execute(
        "SELECT id FROM instruments WHERE identifier='ABC'"
    ).fetchone()[0]
    return store, account, portfolio, instrument


def policy_rules(max_single="0.4"):
    return [
        {
            "key": "equity-band",
            "type": "allocation_band",
            "severity": "soft",
            "subject": "stock",
            "target": "0.4",
            "lower": "0.3",
            "upper": "0.5",
        },
        {
            "key": "cash-floor",
            "type": "min_cash_amount",
            "severity": "hard",
            "lower": "80",
        },
        {
            "key": "single-name",
            "type": "max_single_instrument_weight",
            "severity": "hard",
            "upper": max_single,
        },
    ]


def test_policy_versions_are_append_only_temporal_and_provenanced(tmp_path):
    store, _, portfolio, _ = fixture(tmp_path)
    policies = PolicyService(store)
    first = policies.create(
        portfolio,
        "Core allocation",
        "2025-01-01",
        policy_rules("0.6"),
        known_at="2025-01-01",
    )
    second = policies.add_version(
        first["policy_id"],
        "2025-02-01",
        policy_rules("0.4"),
        known_at="2025-03-01",
    )

    assert first["version_number"] == 1
    assert second["version_number"] == 2
    assert first["rules_sha256"] != second["rules_sha256"]
    raw = store.raw_root / store.db.execute(
        "SELECT sha256 FROM artifacts WHERE id=?", (second["source_artifact_id"],)
    ).fetchone()[0]
    assert raw.is_file()
    event = json.loads(raw.read_text(encoding="utf-8"))
    assert event["schema_version"] == "1"
    assert {item["id"] for item in event["rules"]} == {
        row["id"] for row in store.policy_rules(second["policy_version_id"])
    }
    assert store.policy_version_at(
        first["policy_id"], "2025-02-15", "2025-02-15"
    )["version_number"] == 1
    assert store.policy_version_at(
        first["policy_id"], "2025-02-15", "2025-03-15"
    )["version_number"] == 2

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store.db.execute(
            "UPDATE policy_rules SET upper_bound='1' WHERE policy_version_id=?",
            (second["policy_version_id"],),
        )


def test_policy_evaluation_and_simulation_use_canonical_portfolio_without_writes(tmp_path):
    store, account, portfolio, instrument = fixture(tmp_path)
    policies = PolicyService(store)
    created = policies.create(
        portfolio,
        "Core allocation",
        "2025-01-01",
        policy_rules(),
        known_at="2025-01-01",
    )

    before = policies.evaluate(
        created["policy_id"], "2025-03-01", known_as_of="2025-03-01"
    )
    transaction_count = store.db.execute("SELECT count(*) FROM transactions").fetchone()[0]
    simulated = policies.simulate(
        created["policy_id"],
        "2025-03-01",
        [{"instrument_id": instrument, "base_value_delta": "-20", "fee": "0"}],
        known_as_of="2025-03-01",
    )

    assert before["status"] == "violation"
    assert [item["rule_key"] for item in before["violations"]] == ["single-name"]
    assert simulated["after"]["status"] == "compliant"
    assert simulated["simulated_valuation"]["simulation"]["ledger_mutated"] is False
    assert store.db.execute("SELECT count(*) FROM transactions").fetchone()[0] == transaction_count
    assert LedgerService(store).state(account, "2025-03-01")["positions"][instrument] == "2"


def test_policy_evaluation_fails_closed_on_incomplete_valuation(tmp_path):
    store = Store(tmp_path / "home")
    ledger = LedgerService(store)
    account = ledger.create_account("broker", "main")
    source = tmp_path / "ledger.csv"
    write_rows(
        source,
        ["id", "date", "type", "ticker", "quantity", "amount", "fee", "currency"],
        [{"id": "buy", "date": "2025-01-01", "type": "buy", "ticker": "ABC", "quantity": "1", "amount": "10", "fee": "0", "currency": "USD"}],
    )
    ledger.import_csv(account, source)
    portfolios = PortfolioService(store)
    portfolio = portfolios.create("Incomplete")
    portfolios.set_membership(
        portfolio, account, "add", "2025-01-01", known_at="2025-01-01"
    )
    policies = PolicyService(store)
    policy = policies.create(
        portfolio,
        "Guarded",
        "2025-01-01",
        policy_rules(),
        known_at="2025-01-01",
    )

    result = policies.evaluate(
        policy["policy_id"], "2025-01-02", known_as_of="2025-01-02"
    )

    assert result["status"] == "unavailable"
    assert result["complete"] is False
    assert all(item["status"] == "unavailable" for item in result["results"])


def test_policy_evaluation_propagates_market_provider_conflict(tmp_path):
    store, _, portfolio, _ = fixture(tmp_path)
    conflicting = tmp_path / "conflicting.csv"
    write_rows(
        conflicting,
        ["date", "known_at", "ticker", "close", "currency", "asset_type"],
        [
            {
                "date": "2025-03-01",
                "known_at": "2025-03-01",
                "ticker": "ABC",
                "close": "60",
                "currency": "USD",
                "asset_type": "stock",
            }
        ],
    )
    MarketService(store).import_prices_csv(
        conflicting, dataset_name="other", version="v1", provider="other"
    )
    policy = PolicyService(store).create(
        portfolio,
        "Conflict guarded",
        "2025-01-01",
        policy_rules(),
        known_at="2025-01-01",
    )

    with pytest.raises(ValueError, match="conflicting accepted"):
        PolicyService(store).evaluate(
            policy["policy_id"], "2025-03-01", known_as_of="2025-03-01"
        )


def test_invalid_policy_is_rejected_before_provenance_write(tmp_path):
    store, _, portfolio, _ = fixture(tmp_path)
    before = store.db.execute("SELECT count(*) FROM imports").fetchone()[0]

    with pytest.raises(ValueError, match="unknown fields"):
        PolicyService(store).create(
            portfolio,
            "Invalid",
            "2025-01-01",
            [{"key": "bad", "type": "min_cash_weight", "lower": "0.1", "agent_override": True}],
            known_at="2025-01-01",
        )

    assert store.db.execute("SELECT count(*) FROM imports").fetchone()[0] == before

    with pytest.raises(ValueError, match="binary floating point"):
        PolicyService(store).create(
            portfolio,
            "Invalid float",
            "2025-01-01",
            [{"key": "cash", "type": "min_cash_weight", "lower": 0.1}],
            known_at="2025-01-01",
        )
    assert store.db.execute("SELECT count(*) FROM imports").fetchone()[0] == before


def test_policy_write_rolls_back_provenance_on_unexpected_storage_failure(tmp_path, monkeypatch):
    store, _, portfolio, _ = fixture(tmp_path)
    before = {
        table: store.db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in ("artifacts", "imports", "investment_policies", "audit_events")
    }

    def fail(*args, **kwargs):
        raise RuntimeError("injected failure")

    monkeypatch.setattr(store, "add_policy", fail)
    with pytest.raises(RuntimeError, match="injected failure"):
        PolicyService(store).create(
            portfolio,
            "Atomic",
            "2025-01-01",
            policy_rules(),
            known_at="2025-01-01",
        )

    after = {
        table: store.db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in before
    }
    assert after == before


def test_policy_version_knowledge_cutoff_is_respected_for_backdated_rules(tmp_path):
    store, _, portfolio, _ = fixture(tmp_path)
    policies = PolicyService(store)
    first = policies.create(
        portfolio,
        "Temporal",
        "2025-01-01",
        policy_rules("0.6"),
        known_at="2025-01-01",
        recorded_at="2025-01-01",
    )
    second = policies.add_version(
        first["policy_id"],
        "2025-01-15",
        policy_rules("0.4"),
        known_at="2025-03-01",
        recorded_at="2025-03-01",
    )

    before_knowledge = policies.evaluate(
        first["policy_id"], "2025-02-01", known_as_of="2025-02-01"
    )
    after_knowledge = policies.evaluate(
        first["policy_id"], "2025-02-01", known_as_of="2025-03-01"
    )
    assert before_knowledge["version_number"] == 1
    assert after_knowledge["version_number"] == 2
    assert second["rules_sha256"] != first["rules_sha256"]


def test_policy_capabilities_share_permissions_confirmation_and_dry_run(tmp_path):
    store, _, portfolio, _ = fixture(tmp_path)
    registry = build_core_registry(store)
    rules = policy_rules()
    with pytest.raises(CapabilityPermissionError):
        registry.execute(
            "policy.create",
            {"portfolio_id": portfolio, "name": "x", "effective_from": "2025-01-01", "rules": rules},
        )
    with pytest.raises(ConfirmationRequired):
        registry.execute(
            "policy.create",
            {"portfolio_id": portfolio, "name": "x", "effective_from": "2025-01-01", "rules": rules},
            permissions={"policy:write"},
        )
    dry = registry.execute(
        "policy.create",
        {"portfolio_id": portfolio, "name": "x", "effective_from": "2025-01-01", "rules": rules},
        permissions={"policy:write"},
        dry_run=True,
    )
    assert dry["would_execute"] is True
    assert store.db.execute("SELECT count(*) FROM investment_policies").fetchone()[0] == 0


def test_policy_events_rebuild_with_semantic_mappings(tmp_path):
    source_store, _, portfolio, _ = fixture(tmp_path)
    policies = PolicyService(source_store)
    created = policies.create(
        portfolio,
        "Rebuildable",
        "2025-01-01",
        policy_rules("0.6"),
        known_at="2025-01-01",
        recorded_at="2025-01-01",
        created_at="2025-01-01",
    )
    policies.add_version(
        created["policy_id"],
        "2025-02-01",
        policy_rules("0.4"),
        known_at="2025-02-01",
        recorded_at="2025-02-01",
    )

    target_store = Store(tmp_path / "target")
    result = LedgerRebuilder(source_store, target_store).rebuild()

    assert result["consistent"] is True
    assert result["warnings"] == []
    target_policy_id = result["policy_mapping"][created["policy_id"]]
    assert target_policy_id != created["policy_id"]
    assert len(target_store.policy_versions(target_policy_id)) == 2
    assert result["policy_rule_mapping"]


def test_policy_backup_round_trip_includes_v6_tables(tmp_path):
    store, _, portfolio, _ = fixture(tmp_path)
    created = PolicyService(store).create(
        portfolio,
        "Backed up",
        "2025-01-01",
        policy_rules(),
        known_at="2025-01-01",
    )
    bundle = tmp_path / "policy.zip"
    manifest = store.backup_bundle(bundle)
    assert manifest["schema_version"] == 12
    assert store.verify_backup(bundle)["valid"] is True
    export = tmp_path / "export.jsonl"
    store.export(export)
    assert b'"table":"investment_policies"' in export.read_bytes()
    target = Store(tmp_path / "restored")
    target.restore_bundle(bundle)
    assert target.policy(created["policy_id"])["name"] == "Backed up"
    assert target.db.execute("SELECT count(*) FROM policy_rules").fetchone()[0] == 3
