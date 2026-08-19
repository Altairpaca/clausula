from __future__ import annotations

from pathlib import Path
from typing import Any

from clausula.application import CoreRepository, LedgerService

from .registry import CapabilityRegistry, CapabilitySpec, SideEffect, object_schema


STRING = {"type": "string"}
NULLABLE_STRING = {"type": ["string", "null"]}
STRING_MAP = {"type": "object", "additionalProperties": {"type": "string"}}


def _state_schema() -> dict[str, Any]:
    return object_schema(
        {
            "account_id": STRING,
            "as_of": STRING,
            "cash": NULLABLE_STRING,
            "cash_currency": NULLABLE_STRING,
            "cash_by_currency": STRING_MAP,
            "positions": STRING_MAP,
        },
        required=(
            "account_id",
            "as_of",
            "cash",
            "cash_currency",
            "cash_by_currency",
            "positions",
        ),
    )


def build_core_registry(repository: CoreRepository) -> CapabilityRegistry:
    service = LedgerService(repository)
    registry = CapabilityRegistry()
    registry.register(
        CapabilitySpec(
            "account.create",
            "Create a canonical investment account.",
            object_schema(
                {"institution": STRING, "name": STRING},
                required=("institution", "name"),
            ),
            object_schema({"account_id": STRING}, required=("account_id",)),
            "write",
            True,
            SideEffect.LOCAL_WRITE,
            ("ledger:write",),
            True,
            "Creates an append-only audit event.",
        ),
        lambda institution, name: {"account_id": service.create_account(institution, name)},
    )
    registry.register(
        CapabilitySpec(
            "ledger.import_csv",
            "Import validated CSV investment facts with immutable provenance.",
            object_schema(
                {"account_id": STRING, "path": STRING},
                required=("account_id", "path"),
            ),
            object_schema(
                {
                    "artifact_id": STRING,
                    "sha256": STRING,
                    "import_batch_id": STRING,
                    "transactions": {"type": "integer"},
                },
                required=("artifact_id", "sha256", "import_batch_id", "transactions"),
            ),
            "write",
            True,
            SideEffect.LOCAL_WRITE,
            ("ledger:write",),
            True,
            "Every fact links to a source artifact and import batch.",
        ),
        lambda account_id, path: service.import_csv(account_id, Path(path)),
    )
    registry.register(
        CapabilitySpec(
            "ledger.get_state",
            "Replay account cash and positions at a strict knowledge cutoff.",
            object_schema(
                {"account_id": STRING, "as_of": NULLABLE_STRING},
                required=("account_id",),
            ),
            _state_schema(),
            "read",
            True,
            SideEffect.LOCAL_READ,
            ("portfolio:read",),
            False,
            "Excludes facts whose effective_at or known_at exceeds the cutoff.",
        ),
        lambda account_id, as_of=None: service.state(account_id, as_of),
    )
    registry.register(
        CapabilitySpec(
            "ledger.get_transactions",
            "Return transactions and their legs at a strict knowledge cutoff.",
            object_schema(
                {"account_id": STRING, "as_of": NULLABLE_STRING},
                required=("account_id",),
            ),
            {"type": "array", "items": {"type": "object"}},
            "read",
            True,
            SideEffect.LOCAL_READ,
            ("ledger:read",),
            False,
            "Returns source artifact, import batch, and temporal fields.",
        ),
        lambda account_id, as_of=None: service.transactions(account_id, as_of),
    )

    system_methods = {
        "system.check_integrity": (
            "Check SQLite integrity and the audit hash chain.",
            lambda: {
                "database": repository.integrity_check(),
                "audit": repository.verify_audit_chain(),
            },
            object_schema(
                {"database": STRING, "audit": {"type": "object"}},
                required=("database", "audit"),
            ),
        ),
        "system.export": (
            "Write a stable canonical JSONL export.",
            None,
            object_schema({"path": STRING}, required=("path",)),
        ),
        "system.backup": (
            "Create a verified database, raw artifact, and export backup bundle.",
            None,
            {"type": "object"},
        ),
    }
    description, handler, output_schema = system_methods["system.check_integrity"]
    registry.register(
        CapabilitySpec(
            "system.check_integrity",
            description,
            object_schema(),
            output_schema,
            "read",
            True,
            SideEffect.LOCAL_READ,
            ("system:read",),
            False,
            "Verifies database pages and the append-only audit chain.",
        ),
        handler,
    )
    if hasattr(repository, "export"):
        registry.register(
            CapabilitySpec(
                "system.export",
                system_methods["system.export"][0],
                object_schema({"path": STRING}, required=("path",)),
                system_methods["system.export"][2],
                "write",
                True,
                SideEffect.LOCAL_WRITE,
                ("system:export",),
                True,
                "Exports canonical rows without modifying financial truth.",
            ),
            lambda path: {"path": repository.export(path)},
        )
    if hasattr(repository, "backup_bundle"):
        registry.register(
            CapabilitySpec(
                "system.backup",
                system_methods["system.backup"][0],
                object_schema({"path": STRING}, required=("path",)),
                system_methods["system.backup"][2],
                "write",
                True,
                SideEffect.LOCAL_WRITE,
                ("system:backup",),
                True,
                "Manifest hashes database, raw artifacts, export, and audit head.",
            ),
            lambda path: repository.backup_bundle(path),
        )
    return registry
