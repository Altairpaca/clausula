from __future__ import annotations

import pytest

from clausula import Store
from clausula.adapters.execution import ExecutionRepositoryProjection
from clausula.analytics.execution import evaluate_execution_contract
from clausula.application import PortfolioService
from clausula.application.cockpit import CapitalCockpitService
from clausula.application.execution import ExecutionContractError, ExecutionService
from clausula.capabilities import build_core_registry
from clausula.ui import workspace_document


def test_execution_evaluator_distinguishes_executable_blocked_and_conditional() -> None:
    constraints = [
        {"key": "universe", "type": "allowed_instruments", "values": ["A"]},
        {"key": "turnover", "type": "max_total_turnover", "value": "100"},
        {"key": "cash", "type": "require_settled_cash"},
        {"key": "lot", "type": "minimum_lot", "value": "100", "subject": "A"},
        {"key": "delay", "type": "sell_delay_days", "value": 1, "subject": "A"},
    ]
    executable = evaluate_execution_contract(
        constraints,
        [{"instrument_id": "A", "base_value_delta": "50", "quantity": "100"}],
        context={"settled_cash_base": "60"},
    )
    assert executable["status"] == "executable"
    assert executable["missing_facts"] == []

    blocked = evaluate_execution_contract(
        constraints,
        [{"instrument_id": "B", "base_value_delta": "50", "quantity": "100"}],
        context={"settled_cash_base": "60"},
    )
    assert blocked["status"] == "blocked"
    assert any(row["constraint_key"] == "universe" for row in blocked["violations"])

    conditional = evaluate_execution_contract(
        constraints,
        [{"instrument_id": "A", "base_value_delta": "50"}],
        context={"settled_cash_base": "60"},
    )
    assert conditional["status"] == "conditional"
    assert any(row["constraint_key"] == "lot" for row in conditional["missing_facts"])


def test_execution_contract_versions_respect_effective_and_known_time(tmp_path) -> None:
    store = Store(tmp_path / "home")
    portfolios = PortfolioService(store)
    portfolio_id = portfolios.create("Execution", "USD", created_at="2025-01-01")
    service = ExecutionService(ExecutionRepositoryProjection(store))

    first = service.create(
        portfolio_id,
        "Primary execution",
        "2025-01-01",
        [{"key": "turnover", "type": "max_total_turnover", "value": "100"}],
        known_at="2025-01-01",
        recorded_at="2025-01-01",
    )
    second = service.add_version(
        first["contract_id"],
        "2025-02-01",
        [{"key": "turnover", "type": "max_total_turnover", "value": "50"}],
        known_at="2025-03-01",
        recorded_at="2025-03-01",
    )

    before_knowledge = service.active(
        portfolio_id, "2025-02-15", known_as_of="2025-02-15"
    )
    after_knowledge = service.active(
        portfolio_id, "2025-02-15", known_as_of="2025-03-15"
    )
    assert before_knowledge["version_number"] == 1
    assert after_knowledge["version_number"] == 2
    assert second["version_number"] == 2
    assert store.verify_audit_chain()["valid"] is True

    with pytest.raises(ExecutionContractError, match="already has"):
        service.create(
            portfolio_id,
            "duplicate",
            "2025-04-01",
            [{"key": "turnover", "type": "max_total_turnover", "value": "10"}],
            known_at="2025-04-01",
            recorded_at="2025-04-01",
        )


def test_missing_execution_contract_fails_closed() -> None:
    class Repository:
        def execution_contract_version_at(self, portfolio_id, as_of, known_as_of=None):
            return None

    result = ExecutionService(Repository()).evaluate(
        "portfolio", "2025-01-01", [{"instrument_id": "A", "base_value_delta": "10"}]
    )
    assert result["status"] == "conditional"
    assert result["complete"] is False
    assert result["missing_facts"][0]["constraint_type"] == "contract"


def test_execution_capabilities_and_cockpit_projection(tmp_path) -> None:
    store = Store(tmp_path / "home")
    portfolio_id = PortfolioService(store).create(
        "Execution", "USD", created_at="2025-01-01"
    )
    registry = build_core_registry(store)
    assert registry.get("execution.evaluate").side_effect.value == "local_read"

    created = registry.execute(
        "execution.create",
        {
            "portfolio_id": portfolio_id,
            "name": "Primary execution",
            "effective_from": "2025-01-01",
            "known_at": "2025-01-01",
            "recorded_at": "2025-01-01",
            "constraints": [
                {"key": "sides", "type": "allowed_sides", "values": ["buy", "sell"]}
            ],
        },
        permissions=("execution:write", "portfolio:read"),
        confirmed=True,
    )
    assert created["version_number"] == 1

    cockpit = CapitalCockpitService(
        store, execution_repository=ExecutionRepositoryProjection(store)
    )
    snapshot = cockpit.snapshot(
        portfolio_id, "2025-01-02", known_as_of="2025-01-02"
    )
    assert snapshot["execution"]["status"] == "configured"
    assert snapshot["execution"]["contract"]["version_number"] == 1
    assert "execution-panel" in workspace_document()
