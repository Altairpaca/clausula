from __future__ import annotations

from typing import Any

from clausula.adapters.cockpit_intelligence import CockpitIntelligenceProjection

from .cockpit import CapitalCockpitService
from .cockpit_intelligence import build_cockpit_intelligence


class IntelligentCapitalCockpitService(CapitalCockpitService):
    """Extend the stable Cockpit snapshot with derived decision intelligence."""

    def __init__(self, repository):
        super().__init__(repository)
        self.intelligence_projection = CockpitIntelligenceProjection(repository)

    def snapshot(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        result = super().snapshot(*args, **kwargs)
        portfolio_id = result["portfolio"]["id"]
        intelligence = build_cockpit_intelligence(
            self.repository,
            self.intelligence_projection,
            portfolio_id=portfolio_id,
            as_of=result["as_of"],
            known_as_of=result["known_as_of"],
            decisions=result["decisions"],
        )
        return result | intelligence
