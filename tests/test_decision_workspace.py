from __future__ import annotations

from clausula import Store
from clausula.adapters.workspace import DecisionWorkspaceProjection
from clausula.application import DecisionService, DecisionWorkspaceService, PortfolioService
from clausula.application.attention import AttentionService
from clausula.application.recommendation import RecommendationService
from clausula.application.research import ResearchService
from clausula.capabilities import ConfirmationRequired, build_core_registry
from clausula.ui import workspace_document


CURRENT_VIEW = "2100-01-01"


def _fixture(tmp_path):
    store = Store(tmp_path / "home")
    portfolio = PortfolioService(store).create("Household", "USD", created_at="2026-01-01")
    decision = DecisionService(store).create(
        portfolio,
        "Preserve reserve",
        "non_trade",
        "Wait until liquidity evidence is resolved.",
        "2026-01-02",
        known_as_of="2026-01-02",
        review_schedule=[{"review_type": "process", "due_at": "2026-01-31"}],
        created_at="2026-01-02",
        recorded_at="2026-01-02",
    )["decision"]
    recommendation = RecommendationService(store).create(
        portfolio_id=portfolio,
        subject="cash reserve",
        recommendation_type="allocation",
        rationale="Preserve liquidity before adding risk.",
        as_of="2026-01-02",
        known_as_of="2026-01-02",
        origin="rule",
        alternatives=[{"key": "hold", "description": "Hold cash", "selected": True}],
        created_at="2026-01-02",
        recorded_at="2026-01-02",
    )["recommendation"]
    return store, portfolio, decision, recommendation


def test_decision_workspace_composes_actionable_surfaces_without_hindsight(tmp_path) -> None:
    store, portfolio, decision, recommendation = _fixture(tmp_path)
    projection = DecisionWorkspaceProjection(store)
    workspace = DecisionWorkspaceService(projection)

    first_link = workspace.link_recommendation_decision(
        recommendation["id"],
        decision["id"],
        relation="considered_in",
        linked_at="2026-02-01",
    )
    second_link = workspace.link_recommendation_decision(
        recommendation["id"],
        decision["id"],
        relation="considered_in",
        linked_at="2026-02-01",
    )
    assert first_link["id"] == second_link["id"]

    source = tmp_path / "evidence.txt"
    source.write_text(
        "Liquidity remains constrained. Liquidity is no longer constrained.",
        encoding="utf-8",
    )
    research = ResearchService(store)
    document = research.ingest_text(
        source,
        title="Liquidity update",
        source_uri="file:///liquidity-update",
        known_at="2026-01-05",
        recorded_at="2026-01-05",
    )["document"]
    support = research.create_claim(
        document["id"],
        claim_key="liquidity-tight",
        text="Liquidity remains constrained.",
        span_start=0,
        span_end=30,
        known_at="2026-01-05",
        recorded_at="2026-01-05",
    )["claim"]
    counter = research.create_claim(
        document["id"],
        claim_key="liquidity-relaxed",
        text="Liquidity is no longer constrained.",
        span_start=31,
        span_end=66,
        known_at="2026-01-06",
        recorded_at="2026-01-06",
    )["claim"]
    research.create_contradiction(
        support["id"],
        counter["id"],
        kind="direct",
        explanation="The claims disagree about liquidity state.",
        known_at="2026-01-06",
        recorded_at="2026-01-06",
    )
    decisions = DecisionService(store)
    decisions.link_evidence(
        decision["id"], support["id"], evidence_kind="claim", relation="supports"
    )
    decisions.link_evidence(
        decision["id"], counter["id"], evidence_kind="claim", relation="contradicts"
    )

    AttentionService(store).evaluate(
        event_key="liquidity-change",
        event_type="evidence_change",
        severity="high",
        material=True,
        summary="Liquidity evidence changed materially.",
        occurred_at="2026-01-06",
    )

    # The canonical recommendation and decision were knowable in early 2026,
    # but the evidence links, attention event and explicit lineage were appended
    # later by this test run. Backdating their business time must not make them
    # visible in an earlier knowledge snapshot.
    historical = workspace.snapshot(
        portfolio,
        "2026-02-01",
        known_as_of="2026-02-01",
    )
    assert historical["recommendation_inbox"][0]["id"] == recommendation["id"]
    assert historical["attention"] == []
    assert historical["evidence"]["linked_evidence"] == 0
    assert historical["lineage"][0]["recommendations"] == []

    current = workspace.snapshot(
        portfolio,
        CURRENT_VIEW,
        known_as_of=CURRENT_VIEW,
    )
    assert current["attention"][0]["scope"] == "global"
    assert current["evidence"]["status"] == "pressure"
    assert current["evidence"]["contradicting_links"] == 1
    assert current["evidence"]["explicit_contradictions"] == 1
    assert current["reviews_due"][0]["decision_id"] == decision["id"]
    assert current["lineage"][0]["recommendations"][0]["link"]["relation"] == "considered_in"
    assert current["lineage"][0]["stage"] == "decided"


def test_review_queue_uses_append_time_as_knowledge_boundary(tmp_path) -> None:
    store, portfolio, decision, _ = _fixture(tmp_path)
    service = DecisionWorkspaceService(DecisionWorkspaceProjection(store))

    before = service.snapshot(portfolio, "2026-02-01", known_as_of="2026-02-01")
    assert before["review_queue"][0]["status"] == "due"

    # The review is about 2026-02-02 but is appended now. A historical snapshot
    # immediately after its business date must still not know about it.
    DecisionService(store).review(
        decision["id"],
        "process",
        5,
        "The decision respected the reserve constraint.",
        reviewed_at="2026-02-02",
    )
    historical_after = service.snapshot(
        portfolio, "2026-02-03", known_as_of="2026-02-03"
    )
    assert historical_after["review_queue"][0]["status"] == "due"
    assert historical_after["lineage"][0]["stage"] == "decided"

    current_after = service.snapshot(
        portfolio, CURRENT_VIEW, known_as_of=CURRENT_VIEW
    )
    assert current_after["review_queue"][0]["status"] == "completed"
    assert current_after["reviews_due"] == []
    assert current_after["lineage"][0]["stage"] == "reviewed"


def test_workspace_capabilities_and_ui_are_composed(tmp_path) -> None:
    store, portfolio, decision, recommendation = _fixture(tmp_path)
    registry = build_core_registry(store)
    names = {item["name"] for item in registry.describe()}
    assert "recommendation.list" in names
    assert "recommendation.link_decision" in names
    assert "workspace.decision_snapshot" in names

    listed = registry.execute(
        "recommendation.list",
        {"portfolio_id": portfolio, "as_of": "2026-02-01"},
        permissions={"recommendation:read"},
    )
    assert listed[0]["id"] == recommendation["id"]

    arguments = {
        "recommendation_id": recommendation["id"],
        "decision_id": decision["id"],
        "relation": "accepted_into",
        "linked_at": "2026-02-01",
    }
    try:
        registry.execute(
            "recommendation.link_decision",
            arguments,
            permissions={"recommendation:write", "decision:read"},
        )
    except ConfirmationRequired:
        pass
    else:
        raise AssertionError("lineage write must require explicit confirmation")

    linked = registry.execute(
        "recommendation.link_decision",
        arguments,
        permissions={"recommendation:write", "decision:read"},
        confirmed=True,
    )
    assert linked["decision_id"] == decision["id"]

    document = workspace_document()
    assert 'id="decision-workspace-panel"' in document
    assert 'id="lineage-panel"' in document
    assert "Recommendation inbox" in document
