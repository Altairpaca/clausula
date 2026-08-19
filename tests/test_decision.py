from __future__ import annotations

import csv
from pathlib import Path
import sqlite3

import pytest

from clausula import LedgerService, Store
from clausula.application import (
    DecisionError,
    DecisionService,
    LedgerRebuilder,
    PolicyService,
    PortfolioService,
)
from clausula.capabilities import CapabilityPermissionError, ConfirmationRequired, build_core_registry
from clausula.domain import new_id


def _fixture(tmp_path: Path):
    store = Store(tmp_path / "home")
    ledger = LedgerService(store)
    account = ledger.create_account("broker", "main")
    source = tmp_path / "ledger.csv"
    source.write_text(
        "id,date,type,ticker,quantity,amount,fee,currency\n"
        "cash,2025-01-01,deposit,CASH,0,100,0,USD\n",
        encoding="utf-8",
    )
    ledger.import_csv(account, source)
    transaction = ledger.transactions(account)[0]["id"]
    portfolio = PortfolioService(store).create("Household", "USD")
    PortfolioService(store).set_membership(
        portfolio, account, "add", "2025-01-01", known_at="2025-01-01"
    )
    policy = PolicyService(store).create(
        portfolio,
        "Guardrail",
        "2025-01-01",
        [{"key": "cash", "type": "min_cash_amount", "lower": "0"}],
        known_at="2025-01-01",
        created_at="2025-01-01",
        recorded_at="2025-01-01",
    )
    return store, portfolio, policy["policy_version_id"], transaction


def test_decision_acceptance_links_policy_evidence_transaction_and_reviews(tmp_path):
    store, portfolio, policy_version, transaction = _fixture(tmp_path)
    decisions = DecisionService(store)
    non_trade = decisions.create(
        portfolio,
        "Hold cash",
        "non_trade",
        "Valuation is incomplete for the proposed purchase.",
        "2025-01-01",
        known_as_of="2025-01-01",
        policy_version_id=policy_version,
        alternatives=[
            {"key": "hold", "description": "Wait for complete data", "selected": True},
            {"key": "buy", "description": "Buy now", "selected": False},
        ],
        assumptions=[{"key": "data", "text": "Market data remains incomplete."}],
        expected_outcomes=[{"key": "discipline", "text": "Avoid an uninformed trade."}],
        invalidation_conditions=[{"key": "complete", "text": "All valuation gaps are resolved."}],
        review_schedule=[{"review_type": "process", "due_at": "2025-01-31"}],
        created_at="2025-01-01",
        recorded_at="2025-01-01",
    )
    trade = decisions.create(
        portfolio,
        "Invest reserve",
        "trade",
        "Use the approved reserve after review.",
        "2025-01-02",
        known_as_of="2025-01-02",
        policy_version_id=policy_version,
        alternatives=[{"key": "buy", "description": "Buy reserve", "selected": True}],
    )
    evidence = new_id()
    decisions.link_policy(non_trade["decision"]["id"], policy_version)
    decisions.link_evidence(non_trade["decision"]["id"], evidence, relation="supports")
    decisions.link_transaction(trade["decision"]["id"], transaction)
    decisions.review(non_trade["decision"]["id"], "process", 5, "The no-trade decision respected the data gap.", reviewed_at="2025-02-01")
    decisions.review(trade["decision"]["id"], "outcome", 3, "Outcome review is separate from process quality.", reviewed_at="2025-03-01")

    non_trade_view = decisions.get(non_trade["decision"]["id"])
    trade_view = decisions.get(trade["decision"]["id"])
    assert non_trade_view["decision"]["intent"] == "non_trade"
    assert non_trade_view["policy_links"][0]["policy_version_id"] == policy_version
    assert non_trade_view["evidence_links"][0]["relation"] == "supports"
    assert trade_view["transaction_links"][0]["transaction_id"] == transaction
    assert non_trade_view["reviews"][0]["review_type"] == "process"
    assert {x["kind"] for x in non_trade_view["statements"]} == {"assumption", "expected_outcome", "invalidation_condition"}
    assert non_trade_view["review_schedule"][0]["review_type"] == "process"
    assert trade_view["reviews"][0]["review_type"] == "outcome"
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store.db.execute(
            "UPDATE decisions SET rationale='rewritten' WHERE id=?",
            (non_trade["decision"]["id"],),
        )


def test_decision_temporal_policy_reference_and_capability_contract(tmp_path):
    store, portfolio, policy_version, _ = _fixture(tmp_path)
    later = PolicyService(store).add_version(
        store.policy_version(policy_version)["policy_id"],
        "2025-01-01",
        [{"key": "cash", "type": "min_cash_amount", "lower": "0"}],
        known_at="2025-02-01",
        recorded_at="2025-02-01",
    )
    decisions = DecisionService(store)
    with pytest.raises(DecisionError, match="effective and knowable"):
        decisions.create(
            portfolio,
            "Hindsight",
            "trade",
            "invalid",
            "2025-01-01",
            known_as_of="2025-01-01",
            policy_version_id=later["policy_version_id"],
        )
    registry = build_core_registry(store)
    arguments = {
        "portfolio_id": portfolio,
        "title": "No action",
        "intent": "non_trade",
        "rationale": "Wait",
        "as_of": "2025-01-01",
        "policy_version_id": policy_version,
    }
    with pytest.raises(CapabilityPermissionError):
        registry.execute("decision.create", arguments)
    with pytest.raises(ConfirmationRequired):
        registry.execute("decision.create", arguments, permissions={"decision:write"})
    dry = registry.execute("decision.create", arguments, permissions={"decision:write"}, dry_run=True)
    assert dry["would_execute"] is True
    created = registry.execute("decision.create", arguments, permissions={"decision:write"}, confirmed=True)
    assert created["decision"]["title"] == "No action"


def test_decision_backup_and_clean_rebuild_preserve_lifecycle(tmp_path):
    source, portfolio, policy_version, transaction = _fixture(tmp_path)
    decisions = DecisionService(source)
    created = decisions.create(
        portfolio,
        "Rebuildable",
        "trade",
        "Review before execution.",
        "2025-01-01",
        known_as_of="2025-01-01",
        policy_version_id=policy_version,
        alternatives=[{"key": "buy", "description": "Buy", "selected": True}],
        created_at="2025-01-01",
        recorded_at="2025-01-01",
    )
    decisions.link_policy(created["decision"]["id"], policy_version)
    decisions.link_transaction(created["decision"]["id"], transaction, linked_at="2025-01-02")
    decisions.review(created["decision"]["id"], "process", 4, "Clear rationale.", reviewed_at="2025-02-01")

    bundle = tmp_path / "decisions.zip"
    assert source.backup_bundle(bundle)["schema_version"] == 8
    restored = Store(tmp_path / "restored")
    restored.restore_bundle(bundle)
    assert restored.decision(created["decision"]["id"])["title"] == "Rebuildable"

    target = Store(tmp_path / "target")
    result = LedgerRebuilder(source, target).rebuild()
    assert result["consistent"] is True
    assert result["warnings"] == []
    target_id = result["decision_mapping"][created["decision"]["id"]]
    assert result["decision_comparisons"][0]["matches"] is True
    assert len(DecisionService(target).get(target_id)["transaction_links"]) == 1
