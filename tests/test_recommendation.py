from __future__ import annotations

import pytest

from clausula import Store
from clausula.application.recommendation import RecommendationService
from clausula.application.portfolio import PortfolioService


def test_recommendation_lifecycle_is_append_only_and_does_not_create_transaction(tmp_path) -> None:
    store = Store(tmp_path / "home")
    portfolio = PortfolioService(store).create("Household", "USD")
    recommendation = RecommendationService(store).create(
        portfolio_id=portfolio,
        subject="cash reserve",
        recommendation_type="allocation",
        rationale="Preserve liquidity before adding risk.",
        as_of="2026-01-01",
        known_as_of="2026-01-01",
        origin="rule",
        alternatives=[{"key": "hold", "description": "Hold cash", "selected": True}],
    )
    service = RecommendationService(store)

    reviewed = service.transition(recommendation["recommendation"]["id"], "reviewed")
    accepted = service.transition(recommendation["recommendation"]["id"], "accepted")

    assert reviewed["status"] == "reviewed"
    assert accepted["status"] == "accepted"
    assert len(service.get(recommendation["recommendation"]["id"])["alternatives"]) == 1
    assert store.db.execute("SELECT count(*) FROM transactions").fetchone()[0] == 0
    with pytest.raises(ValueError, match="invalid recommendation transition"):
        service.transition(recommendation["recommendation"]["id"], "draft")
