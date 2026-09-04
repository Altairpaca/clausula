from __future__ import annotations

from clausula.adapters.execution import ExecutionRepositoryProjection
from clausula.application.execution import ExecutionService

from .registry import CapabilityRegistry, CapabilitySpec, SideEffect, object_schema


STRING = {"type": "string"}
NULLABLE_STRING = {"type": ["string", "null"]}
CONSTRAINT = {
    "type": "object",
    "properties": {
        "key": STRING,
        "type": STRING,
        "subject": NULLABLE_STRING,
        "value": {"type": ["string", "integer", "null"]},
        "values": {"type": "array", "items": STRING},
        "start": NULLABLE_STRING,
        "end": NULLABLE_STRING,
    },
    "required": ["key", "type"],
    "additionalProperties": False,
}
CONSTRAINTS = {"type": "array", "items": CONSTRAINT}
ACTIONS = {"type": "array", "items": {"type": "object", "additionalProperties": True}}
CONTEXT = {"type": "object", "additionalProperties": True}


def register_execution_capabilities(
    registry: CapabilityRegistry, repository
) -> CapabilityRegistry:
    service = ExecutionService(ExecutionRepositoryProjection(repository))
    registry.register(
        CapabilitySpec(
            "execution.create",
            "Create the first append-only execution contract for a Portfolio.",
            object_schema(
                {
                    "portfolio_id": STRING,
                    "name": STRING,
                    "effective_from": STRING,
                    "constraints": CONSTRAINTS,
                    "known_at": NULLABLE_STRING,
                    "recorded_at": NULLABLE_STRING,
                },
                required=("portfolio_id", "name", "effective_from", "constraints"),
            ),
            {"type": "object"},
            "write",
            True,
            SideEffect.LOCAL_WRITE,
            ("execution:write", "portfolio:read"),
            True,
            "Stores normalized versioned control provenance in the local audit-backed execution projection; never creates orders.",
        ),
        lambda portfolio_id, name, effective_from, constraints, known_at=None, recorded_at=None: service.create(
            portfolio_id,
            name,
            effective_from,
            constraints,
            known_at=known_at,
            recorded_at=recorded_at,
        ),
    )
    registry.register(
        CapabilitySpec(
            "execution.add_version",
            "Append a new immutable version of an execution contract.",
            object_schema(
                {
                    "contract_id": STRING,
                    "effective_from": STRING,
                    "constraints": CONSTRAINTS,
                    "known_at": NULLABLE_STRING,
                    "recorded_at": NULLABLE_STRING,
                },
                required=("contract_id", "effective_from", "constraints"),
            ),
            {"type": "object"},
            "write",
            True,
            SideEffect.LOCAL_WRITE,
            ("execution:write",),
            True,
            "Appends normalized constraints with explicit effective/knowledge time and source provenance.",
        ),
        lambda contract_id, effective_from, constraints, known_at=None, recorded_at=None: service.add_version(
            contract_id,
            effective_from,
            constraints,
            known_at=known_at,
            recorded_at=recorded_at,
        ),
    )
    registry.register(
        CapabilitySpec(
            "execution.list",
            "List versioned execution contracts, optionally scoped to a Portfolio.",
            object_schema({"portfolio_id": NULLABLE_STRING}),
            {"type": "array", "items": {"type": "object"}},
            "read",
            True,
            SideEffect.LOCAL_READ,
            ("execution:read",),
            False,
            "Returns append-only execution control versions and provenance.",
        ),
        lambda portfolio_id=None: service.list(portfolio_id),
    )
    registry.register(
        CapabilitySpec(
            "execution.active",
            "Read the execution contract version active at an effective/knowledge cutoff.",
            object_schema(
                {
                    "portfolio_id": STRING,
                    "as_of": STRING,
                    "known_as_of": NULLABLE_STRING,
                },
                required=("portfolio_id", "as_of"),
            ),
            object_schema({"contract": {"type": ["object", "null"]}}, required=("contract",)),
            "read",
            True,
            SideEffect.LOCAL_READ,
            ("execution:read",),
            False,
            "Selects one version by effective and known cutoffs; an absent contract is explicit as contract=null.",
        ),
        lambda portfolio_id, as_of, known_as_of=None: {
            "contract": service.active(
                portfolio_id, as_of, known_as_of=known_as_of
            )
        },
    )
    registry.register(
        CapabilitySpec(
            "execution.evaluate",
            "Evaluate proposed actions against the active deterministic execution contract.",
            object_schema(
                {
                    "portfolio_id": STRING,
                    "as_of": STRING,
                    "known_as_of": NULLABLE_STRING,
                    "actions": ACTIONS,
                    "context": CONTEXT,
                },
                required=("portfolio_id", "as_of", "actions"),
            ),
            {"type": "object"},
            "read",
            True,
            SideEffect.LOCAL_READ,
            ("execution:read",),
            False,
            "Returns executable, blocked, or conditional; missing execution facts fail closed as conditional.",
        ),
        lambda portfolio_id, as_of, actions, known_as_of=None, context=None: service.evaluate(
            portfolio_id,
            as_of,
            actions,
            known_as_of=known_as_of,
            context=context,
        ),
    )
    registry.register(
        CapabilitySpec(
            "execution.evaluate_plan",
            "Evaluate every persisted Plan scenario against its active execution contract.",
            object_schema(
                {
                    "plan_id": STRING,
                    "context_by_scenario": {
                        "type": "object",
                        "additionalProperties": {"type": "object", "additionalProperties": True},
                    },
                },
                required=("plan_id",),
            ),
            {"type": "object"},
            "read",
            True,
            SideEffect.LOCAL_READ,
            ("execution:read", "planning:read"),
            False,
            "Projects planning actions through versioned market/account execution constraints without creating orders.",
        ),
        lambda plan_id, context_by_scenario=None: service.evaluate_plan(
            plan_id, context_by_scenario=context_by_scenario
        ),
    )
    return registry
