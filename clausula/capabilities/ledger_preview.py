from __future__ import annotations

from pathlib import Path

from clausula.application import LedgerService

from .registry import CapabilityRegistry, CapabilitySpec, SideEffect, object_schema


STRING = {"type": "string"}


def register_ledger_preview_capability(
    registry: CapabilityRegistry,
    repository,
) -> CapabilityRegistry:
    service = LedgerService(repository)
    registry.register(
        CapabilitySpec(
            "ledger.preview_csv",
            "Validate and normalize a ledger CSV without persisting any financial state.",
            object_schema(
                {"account_id": STRING, "path": STRING},
                required=("account_id", "path"),
            ),
            {"type": "object"},
            "read",
            True,
            SideEffect.LOCAL_READ,
            ("ledger:read",),
            False,
            "Reads the requested local CSV and canonical account identity only; it does not create artifacts, instruments, imports, transactions, or audit write events.",
        ),
        lambda account_id, path: service.preview_csv(account_id, Path(path)),
    )
    return registry
