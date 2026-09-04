from __future__ import annotations

from clausula.adapters.workspace import DecisionWorkspaceProjection
from clausula.application.decision_workspace import DecisionWorkspaceService

from .registry import CapabilityRegistry, CapabilitySpec, SideEffect, object_schema


STRING = {"type": "string"}
NULLABLE_STRING = {"type": ["string", "null"]}


def register_decision_workspace_capabilities(
    registry: CapabilityRegistry, repository
) -> CapabilityRegistry:
    projection = DecisionWorkspaceProjection(repository)
    service = DecisionWorkspaceService(projection)

    registry.register(
        CapabilitySpec(
            "recommendation.list",
            "List point-in-time recommendations for a Portfolio with derived lifecycle status.",
            object_schema(
                {
                    "portfolio_id": STRING,
                    "as_of": STRING,
                    "known_as_of": NULLABLE_STRING,
                },
                required=("portfolio_id", "as_of"),
            ),
            {"type": "array", "items": {"type": "object"}},
            "read",
            True,
            SideEffect.LOCAL_READ,
            ("recommendation:read",),
            False,
            "Projects append-only recommendation facts and transitions at explicit effective/knowledge cutoffs.",
        ),
        lambda portfolio_id, as_of, known_as_of=None: projection.recommendations(
            portfolio_id=portfolio_id,
            as_of=as_of,
            known_as_of=known_as_of or as_of,
        ),
    )

    registry.register(
        CapabilitySpec(
            "recommendation.link_decision",
            "Append an explicit relationship from a recommendation to a Decision.",
            object_schema(
                {
                    "recommendation_id": STRING,
                    "decision_id": STRING,
                    "relation": {
                        "type": "string",
                        "enum": ["accepted_into", "considered_in", "rejected_by"],
                    },
                    "linked_at": NULLABLE_STRING,
                },
                required=("recommendation_id", "decision_id"),
            ),
            {"type": "object"},
            "write",
            True,
            SideEffect.LOCAL_WRITE,
            ("recommendation:write", "decision:read"),
            True,
            "Stores only append-only lineage metadata in the tamper-evident audit chain; it does not rewrite either source record.",
        ),
        lambda recommendation_id, decision_id, relation="accepted_into", linked_at=None: service.link_recommendation_decision(
            recommendation_id,
            decision_id,
            relation=relation,
            linked_at=linked_at,
        ),
    )

    registry.register(
        CapabilitySpec(
            "workspace.decision_snapshot",
            "Compose attention, recommendation inbox, evidence pressure, review queue, and decision lineage.",
            object_schema(
                {
                    "portfolio_id": STRING,
                    "as_of": STRING,
                    "known_as_of": NULLABLE_STRING,
                },
                required=("portfolio_id", "as_of"),
            ),
            {"type": "object"},
            "read",
            True,
            SideEffect.LOCAL_READ,
            ("portfolio:read", "decision:read", "research:read", "recommendation:read"),
            False,
            "Derived local read model only; preserves explicit effective/knowledge cutoffs and does not create financial facts.",
        ),
        lambda portfolio_id, as_of, known_as_of=None: service.snapshot(
            portfolio_id,
            as_of,
            known_as_of=known_as_of,
        ),
    )
    return registry
