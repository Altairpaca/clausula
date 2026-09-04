from __future__ import annotations

import pytest

from clausula import LedgerService, Store
from clausula.adapters.equity_case import EquityCaseProjection
from clausula.adapters.mcp import McpAdapter, McpProfile
from clausula.application import PortfolioService
from clausula.application.equity_monitor import EquityCaseError, EquityCaseService
from clausula.capabilities import CapabilityPermissionError, ConfirmationRequired, build_core_registry
from clausula.ui import workspace_document


def _fixture(tmp_path):
    store = Store(tmp_path / "home")
    instrument = LedgerService(store).resolve_instrument(
        "ACME", name="ACME Holdings", asset_type="stock", currency="USD"
    )
    portfolio = PortfolioService(store).create("Long book", "USD", created_at="2026-01-01")
    return store, instrument, portfolio


def _case_payload(instrument, portfolio):
    return dict(
        instrument_id=instrument,
        portfolio_id=portfolio,
        name="ACME core case",
        effective_from="2026-01-01",
        known_at="2026-01-10",
        recorded_at="2026-01-10",
        company_status="watch",
        security_readiness="conditional",
        action="wait_for_proof",
        portfolio_role="core compounder candidate",
        horizon="12-24 months",
        variant_view="Street underestimates durable bookings growth.",
        valuation_anchor="Re-underwrite after evidence and current market inputs are complete.",
        pillars=[
            {
                "key": "demand",
                "statement": "Bookings growth remains durable.",
                "status": "watch",
                "priority": "core",
                "baseline": "Current bookings baseline",
                "expected_path": "Sequential acceleration",
                "conditions": {
                    "confirm": "Bookings accelerate with stable quality.",
                    "warning": "Growth stalls for one reporting period.",
                    "break": "Two periods of material contraction.",
                },
                "kpi_links": ["bookings_growth"],
                "next_proof_point": "Next quarterly bookings disclosure",
            },
            {
                "key": "margin",
                "statement": "Growth does not require structurally lower margins.",
                "status": "intact",
                "priority": "secondary",
                "next_proof_point": "Next gross-margin disclosure",
            },
        ],
        kpis=[
            {
                "key": "bookings_growth",
                "label": "Bookings growth",
                "value": "0.12",
                "unit": "ratio",
                "as_of": "2025-12-31",
                "known_at": "2026-01-10",
                "source_ref": "issuer-quarterly-release",
                "thresholds": [
                    {
                        "key": "bookings-break",
                        "operator": "lt",
                        "value": "0",
                        "origin": "draft",
                        "action": "re_underwrite",
                    }
                ],
            }
        ],
        catalysts=[
            {
                "key": "q1-results",
                "event_type": "earnings",
                "timing_kind": "exact",
                "timing_confidence": "confirmed",
                "date": "2026-02-15",
                "thesis_link": "demand",
                "kpi_links": ["bookings_growth"],
                "prep_action": "Refresh bookings and margin bridge.",
                "decision_implication": "Decide whether the security becomes decision-grade.",
                "source_ref": "issuer-ir-calendar",
            }
        ],
        action_thresholds=[
            {
                "key": "reunderwrite-on-bookings",
                "metric": "bookings_growth",
                "operator": "lt",
                "value": "0",
                "action": "re_underwrite",
                "origin": "draft",
                "source_ref": "analyst-draft",
            }
        ],
        missing_inputs=["current market price", "consensus estimate bridge"],
        key_risks=["Demand decelerates before margins normalize."],
    )


def test_equity_case_is_point_in_time_and_preserves_status_separation(tmp_path) -> None:
    store, instrument, portfolio = _fixture(tmp_path)
    service = EquityCaseService(EquityCaseProjection(store))
    created = service.create(**_case_payload(instrument, portfolio))
    case_id = created["case_id"]

    assert service.active(case_id, "2026-01-05", known_as_of="2026-01-05") is None
    active = service.active(case_id, "2026-01-20", known_as_of="2026-01-20")
    assert active["company_status"] == "watch"
    assert active["security_readiness"] == "conditional"
    assert active["action"] == "wait_for_proof"
    assert active["action_thresholds"][0]["origin"] == "draft"

    updated = service.add_version(
        case_id,
        "2026-01-01",
        known_at="2026-02-16",
        recorded_at="2026-02-16",
        company_status="strengthening",
        security_readiness="ready",
        action="add",
        missing_inputs=[],
        pillars=[
            {
                "key": "demand",
                "statement": "Bookings growth remains durable.",
                "status": "confirming",
                "priority": "core",
                "next_proof_point": "Next customer-retention disclosure",
            }
        ],
    )
    assert updated["version_number"] == 2
    assert service.active(case_id, "2026-02-20", known_as_of="2026-02-01")["version_number"] == 1
    assert service.active(case_id, "2026-02-20", known_as_of="2026-02-20")["version_number"] == 2


def test_readiness_and_pillar_reconciliation_fail_closed(tmp_path) -> None:
    store, instrument, portfolio = _fixture(tmp_path)
    service = EquityCaseService(EquityCaseProjection(store))
    payload = _case_payload(instrument, portfolio)

    with pytest.raises(EquityCaseError, match="ready cannot carry missing"):
        service.create(**(payload | {"name": "ready-with-gap", "security_readiness": "ready", "action": "hold"}))
    with pytest.raises(EquityCaseError, match="add/press"):
        service.create(**(payload | {"name": "premature-add", "action": "add"}))
    with pytest.raises(EquityCaseError, match="override_rationale"):
        service.create(
            **(
                payload
                | {
                    "name": "inconsistent-aggregate",
                    "company_status": "intact",
                    "pillars": [
                        {"key": "p1", "statement": "Core one", "status": "impaired", "priority": "core"},
                        {"key": "p2", "statement": "Core two", "status": "impaired", "priority": "core"},
                    ],
                }
            )
        )

    reconciled = service.create(
        **(
            payload
            | {
                "name": "explicit-override",
                "company_status": "intact",
                "override_rationale": "Both pillars are temporarily impaired by a known one-off; management evidence is pending.",
                "pillars": [
                    {"key": "p1", "statement": "Core one", "status": "impaired", "priority": "core"},
                    {"key": "p2", "statement": "Core two", "status": "impaired", "priority": "core"},
                ],
            }
        )
    )
    assert reconciled["override_rationale"]


def test_catalyst_timing_and_snapshot_keep_windows_distinct(tmp_path) -> None:
    store, instrument, portfolio = _fixture(tmp_path)
    service = EquityCaseService(EquityCaseProjection(store))
    payload = _case_payload(instrument, portfolio)
    payload["catalysts"] = [
        {
            "key": "regulatory-window",
            "event_type": "regulatory",
            "timing_kind": "window",
            "timing_confidence": "medium",
            "start": "2026-02-01",
            "end": "2026-02-28",
            "decision_implication": "Re-underwrite downside if delayed.",
        },
        {
            "key": "customer-check",
            "event_type": "channel-check",
            "timing_kind": "unscheduled",
            "timing_confidence": "unknown",
        },
    ]
    case = service.create(**payload)
    snapshot = service.portfolio_snapshot(portfolio, "2026-01-20", known_as_of="2026-01-20")
    assert snapshot["cases"][0]["summary"]["next_catalyst"]["timing_kind"] == "window"
    assert snapshot["cases"][0]["summary"]["next_proof_point"] == "Next quarterly bookings disclosure"
    assert snapshot["not_decision_grade"] == 0
    assert case["catalysts"][1]["date"] is None


def test_equity_capabilities_mcp_and_ui_surface(tmp_path) -> None:
    store, instrument, portfolio = _fixture(tmp_path)
    registry = build_core_registry(store)
    names = {row["name"] for row in registry.describe()}
    assert {"equity_case.create", "equity_case.add_version", "equity_case.active", "equity_case.portfolio_snapshot"} <= names

    args = _case_payload(instrument, portfolio)
    with pytest.raises(CapabilityPermissionError):
        registry.execute("equity_case.create", args, confirmed=True)
    with pytest.raises(ConfirmationRequired):
        registry.execute("equity_case.create", args, permissions={"equity:write"})
    created = registry.execute(
        "equity_case.create", args, permissions={"equity:write"}, confirmed=True
    )
    assert created["company_status"] == "watch"

    portfolio_tools = {tool.name for tool in McpAdapter(store).list_tools(McpProfile.PORTFOLIO_READ)}
    advisor_tools = {tool.name for tool in McpAdapter(store).list_tools(McpProfile.ADVISOR)}
    assert "equity_case.portfolio_snapshot" in portfolio_tools
    assert "equity_case.create" not in portfolio_tools
    assert "equity_case.create" in advisor_tools

    document = workspace_document()
    assert 'id="equity-monitor-panel"' in document
    assert "Public-equity coverage" in document
    assert "textContent" in document
