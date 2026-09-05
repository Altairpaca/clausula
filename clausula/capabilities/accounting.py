from __future__ import annotations

from clausula.adapters.accounting import AccountingPolicyProjection
from clausula.application.accounting import (
    AccountingService,
    DEFAULT_JURISDICTION_PROFILE,
)

from .registry import CapabilityRegistry, CapabilitySpec, SideEffect, object_schema


STRING = {"type": "string"}
NULLABLE_STRING = {"type": ["string", "null"]}
BOOLEAN = {"type": "boolean"}


def register_accounting_capabilities(registry: CapabilityRegistry, repository) -> CapabilityRegistry:
    service = AccountingService(AccountingPolicyProjection(repository))
    registry.register(
        CapabilitySpec(
            "accounting.create_policy",
            "Create the first version of an explicit account-level lot-accounting policy.",
            object_schema(
                {
                    "account_id": STRING,
                    "effective_from": STRING,
                    "lot_method": STRING,
                    "allow_short": BOOLEAN,
                    "jurisdiction_profile": STRING,
                    "tax_profile_ref": NULLABLE_STRING,
                    "known_at": NULLABLE_STRING,
                    "recorded_at": NULLABLE_STRING,
                },
                required=("account_id", "effective_from"),
            ),
            {"type": "object"},
            "write",
            True,
            SideEffect.LOCAL_WRITE,
            ("accounting:write",),
            True,
            "Stores a versioned audit-backed accounting policy with immutable source provenance. Tax law remains an external typed profile, not a hidden default.",
        ),
        lambda account_id, effective_from, lot_method="fifo", allow_short=False, jurisdiction_profile=DEFAULT_JURISDICTION_PROFILE, tax_profile_ref=None, known_at=None, recorded_at=None: service.create_policy(
            account_id,
            effective_from,
            lot_method=lot_method,
            allow_short=allow_short,
            jurisdiction_profile=jurisdiction_profile,
            tax_profile_ref=tax_profile_ref,
            known_at=known_at,
            recorded_at=recorded_at,
        ),
    )
    registry.register(
        CapabilitySpec(
            "accounting.add_policy_version",
            "Append an immutable accounting-policy version without rewriting prior lot semantics.",
            object_schema(
                {
                    "policy_id": STRING,
                    "effective_from": STRING,
                    "lot_method": NULLABLE_STRING,
                    "allow_short": {"type": ["boolean", "null"]},
                    "jurisdiction_profile": NULLABLE_STRING,
                    "tax_profile_ref": NULLABLE_STRING,
                    "known_at": NULLABLE_STRING,
                    "recorded_at": NULLABLE_STRING,
                },
                required=("policy_id", "effective_from"),
            ),
            {"type": "object"},
            "write",
            True,
            SideEffect.LOCAL_WRITE,
            ("accounting:write",),
            True,
            "Every change is a new effective/knowledge-dated version and is audit backed.",
        ),
        lambda policy_id, effective_from, lot_method=None, allow_short=None, jurisdiction_profile=None, tax_profile_ref=None, known_at=None, recorded_at=None: service.add_version(
            policy_id,
            effective_from,
            lot_method=lot_method,
            allow_short=allow_short,
            jurisdiction_profile=jurisdiction_profile,
            tax_profile_ref=tax_profile_ref,
            known_at=known_at,
            recorded_at=recorded_at,
        ),
    )
    registry.register(
        CapabilitySpec(
            "accounting.active_policy",
            "Read the accounting policy visible at an explicit effective/knowledge cutoff.",
            object_schema(
                {"account_id": STRING, "as_of": STRING, "known_as_of": NULLABLE_STRING},
                required=("account_id", "as_of"),
            ),
            {"type": "object"},
            "read",
            True,
            SideEffect.LOCAL_READ,
            ("accounting:read",),
            False,
            "Returns an explicit unavailable object when no policy is visible; no implicit FIFO policy is fabricated on this surface.",
        ),
        lambda account_id, as_of, known_as_of=None: service.active_policy(
            account_id, as_of, known_as_of=known_as_of
        ),
    )
    registry.register(
        CapabilitySpec(
            "accounting.list_policies",
            "List append-only accounting-policy versions.",
            object_schema({"account_id": NULLABLE_STRING}),
            {"type": "array", "items": {"type": "object"}},
            "read",
            True,
            SideEffect.LOCAL_READ,
            ("accounting:read",),
            False,
            "Returns policy/version provenance and temporal fields.",
        ),
        lambda account_id=None: service.list_policies(account_id),
    )
    registry.register(
        CapabilitySpec(
            "accounting.cost_basis",
            "Replay long/short lots under the active explicit accounting policy.",
            object_schema(
                {"account_id": STRING, "as_of": STRING, "known_as_of": NULLABLE_STRING},
                required=("account_id", "as_of"),
            ),
            {"type": "object"},
            "read",
            True,
            SideEffect.LOCAL_READ,
            ("accounting:read", "ledger:read"),
            False,
            "Deterministic FIFO/LIFO/HIFO and short-cover replay over canonical ledger facts; jurisdiction-specific taxes are not invented.",
        ),
        lambda account_id, as_of, known_as_of=None: service.cost_basis(
            account_id, as_of, known_as_of=known_as_of
        ),
    )
    return registry
