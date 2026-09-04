from __future__ import annotations

from clausula.adapters.equity_case import EquityCaseProjection
from clausula.application.equity_monitor import EquityCaseService

from .registry import CapabilityRegistry, CapabilitySpec, SideEffect, object_schema


STRING = {"type": "string"}
NULLABLE_STRING = {"type": ["string", "null"]}
ARRAY_OBJECT = {"type": "array", "items": {"type": "object", "additionalProperties": True}}
ARRAY_STRING = {"type": "array", "items": STRING}


def _case_payload_schema(required=()):
    return object_schema(
        {
            "company_status": STRING,
            "security_readiness": STRING,
            "action": STRING,
            "portfolio_role": NULLABLE_STRING,
            "horizon": NULLABLE_STRING,
            "variant_view": NULLABLE_STRING,
            "valuation_anchor": NULLABLE_STRING,
            "pillars": ARRAY_OBJECT,
            "kpis": ARRAY_OBJECT,
            "catalysts": ARRAY_OBJECT,
            "action_thresholds": ARRAY_OBJECT,
            "missing_inputs": ARRAY_STRING,
            "key_risks": ARRAY_STRING,
            "override_rationale": NULLABLE_STRING,
            "thesis_id": NULLABLE_STRING,
            "known_at": NULLABLE_STRING,
            "recorded_at": NULLABLE_STRING,
        },
        required=required,
    )


def register_equity_monitor_capabilities(registry: CapabilityRegistry, repository) -> CapabilityRegistry:
    service = EquityCaseService(EquityCaseProjection(repository))
    create_schema = _case_payload_schema(
        required=("company_status", "security_readiness", "action")
    )
    create_schema["properties"].update(
        {
            "instrument_id": STRING,
            "name": STRING,
            "effective_from": STRING,
            "portfolio_id": NULLABLE_STRING,
        }
    )
    create_schema["required"] = [
        "instrument_id", "name", "effective_from", "company_status", "security_readiness", "action"
    ]
    registry.register(
        CapabilitySpec(
            "equity_case.create",
            "Create the first append-only version of a falsifiable listed-equity monitoring case.",
            create_schema,
            {"type": "object"},
            "write",
            True,
            SideEffect.LOCAL_WRITE,
            ("equity:write",),
            True,
            "Stores explicit thesis/security/action state, thresholds and provenance; creates no market or ledger facts.",
        ),
        lambda **kwargs: service.create(**kwargs),
    )
    update_schema = _case_payload_schema()
    update_schema["properties"].update({"case_id": STRING, "effective_from": STRING})
    update_schema["required"] = ["case_id", "effective_from"]
    registry.register(
        CapabilitySpec(
            "equity_case.add_version",
            "Append a new immutable equity-case monitoring version.",
            update_schema,
            {"type": "object"},
            "write",
            True,
            SideEffect.LOCAL_WRITE,
            ("equity:write",),
            True,
            "Preserves prior underwriting and monitoring state; updates are explicit versions, not rewrites.",
        ),
        lambda case_id, effective_from, **changes: service.add_version(case_id, effective_from, **changes),
    )
    registry.register(
        CapabilitySpec(
            "equity_case.list",
            "List equity-case versions by portfolio or instrument.",
            object_schema({"portfolio_id": NULLABLE_STRING, "instrument_id": NULLABLE_STRING}),
            {"type": "array", "items": {"type": "object"}},
            "read",
            True,
            SideEffect.LOCAL_READ,
            ("equity:read",),
            False,
            "Returns append-only case versions and threshold/source provenance.",
        ),
        lambda portfolio_id=None, instrument_id=None: service.list(
            portfolio_id=portfolio_id, instrument_id=instrument_id
        ),
    )
    registry.register(
        CapabilitySpec(
            "equity_case.active",
            "Read the case version active at an effective/knowledge cutoff.",
            object_schema(
                {"case_id": STRING, "as_of": STRING, "known_as_of": NULLABLE_STRING},
                required=("case_id", "as_of"),
            ),
            {"type": ["object", "null"]},
            "read",
            True,
            SideEffect.LOCAL_READ,
            ("equity:read",),
            False,
            "Uses strict effective and knowledge cutoffs; later thesis updates cannot leak backward.",
        ),
        lambda case_id, as_of, known_as_of=None: service.active(
            case_id, as_of, known_as_of=known_as_of
        ),
    )
    registry.register(
        CapabilitySpec(
            "equity_case.portfolio_snapshot",
            "Project company thesis, security readiness, action posture, pressure pillars and next gates for a portfolio.",
            object_schema(
                {"portfolio_id": STRING, "as_of": STRING, "known_as_of": NULLABLE_STRING},
                required=("portfolio_id", "as_of"),
            ),
            {"type": "object"},
            "read",
            True,
            SideEffect.LOCAL_READ,
            ("equity:read",),
            False,
            "Derived monitoring surface with no composite conviction score and explicit decision-grade blockers.",
        ),
        lambda portfolio_id, as_of, known_as_of=None: service.portfolio_snapshot(
            portfolio_id, as_of, known_as_of=known_as_of
        ),
    )
    return registry
