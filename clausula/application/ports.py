from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol, runtime_checkable

from clausula.domain import InstrumentIdentifier, Transaction


@runtime_checkable
class LedgerRepository(Protocol):
    """Persistence operations required by the canonical Ledger service."""

    def create_account(self, institution: str, name: str) -> str: ...

    def require_account(self, account_id: str) -> Mapping[str, Any]: ...

    def instrument(
        self,
        identifier: InstrumentIdentifier,
        name: str = "",
        asset_type: str = "stock",
        currency: str = "USD",
    ) -> str: ...


    def artifact(self, path: str | Path) -> tuple[str, str]: ...

    def virtual_artifact(self, uri: str, content: str) -> tuple[str, str]: ...

    def import_batch(
        self,
        artifact_id: str,
        *,
        adapter_name: str = "manual",
        adapter_version: str = "1",
        schema_version: str = "1",
    ) -> str: ...

    def add_import(
        self,
        batch_id: str,
        artifact_id: str,
        entries: Iterable[tuple[Transaction, str]],
        *,
        adapter_name: str,
        adapter_version: str,
        schema_version: str,
    ) -> int: ...

    def add_transaction(self, transaction: Transaction, external_id: str | None = None) -> bool: ...

    def add_transfer(
        self,
        transfer_id: str,
        source_transaction: Transaction,
        destination_transaction: Transaction,
    ) -> None: ...

    def transactions(self, account_id: str, as_of: str | None = None) -> list[Mapping[str, Any]]: ...

    def transaction(self, transaction_id: str) -> Mapping[str, Any] | None: ...

    def legs(self, transaction_id: str) -> list[Mapping[str, Any]]: ...

    def record_reconciliation(
        self,
        *,
        account_id: str,
        effective_at: str,
        known_at: str,
        source_artifact_id: str,
        import_batch_id: str,
        observed: dict,
        derived: dict,
        differences: list[dict],
    ) -> str: ...


@runtime_checkable
class CoreRepository(LedgerRepository, Protocol):
    def integrity_check(self) -> str: ...

    def verify_audit_chain(self) -> dict[str, Any]: ...

    def export(self, destination: str | Path) -> str: ...

    def backup_bundle(self, destination: str | Path) -> dict[str, Any]: ...
