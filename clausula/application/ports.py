from __future__ import annotations

from pathlib import Path
from typing import Any, ContextManager, Iterable, Mapping, Protocol, runtime_checkable

from clausula.domain import (
    CorporateAction,
    DatasetVersion,
    FxRate,
    FxConversion,
    InstrumentIdentifier,
    MarketPrice,
    InvestmentPolicy,
    PolicyRule,
    PolicyVersion,
    Portfolio,
    PortfolioMembershipEvent,
    SecurityTransfer,
    Transaction,
)


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

    def instrument_details(self, instrument_id: str) -> Mapping[str, Any]: ...


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

    def add_fx_conversion(self, transaction: Transaction, conversion: FxConversion) -> None: ...

    def add_security_transfer(
        self,
        transfer: SecurityTransfer,
        source_transaction: Transaction,
        destination_transaction: Transaction,
    ) -> None: ...

    def add_corporate_action(
        self, transaction: Transaction, action: CorporateAction
    ) -> None: ...

    def transactions(
        self,
        account_id: str,
        as_of: str | None = None,
        known_as_of: str | None = None,
    ) -> list[Mapping[str, Any]]: ...

    def transaction(self, transaction_id: str) -> Mapping[str, Any] | None: ...

    def legs(self, transaction_id: str) -> list[Mapping[str, Any]]: ...

    def transaction_metadata(self, transaction_id: str) -> Mapping[str, Any]: ...

    def corporate_action_transaction(self, action_id: str) -> str: ...

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
    def write_transaction(self) -> ContextManager[None]: ...

    def integrity_check(self) -> str: ...

    def verify_audit_chain(self) -> dict[str, Any]: ...

    def export(self, destination: str | Path) -> str: ...

    def backup_bundle(self, destination: str | Path) -> dict[str, Any]: ...

    def rebuild_catalog(self) -> Mapping[str, Any]: ...

    def imported_transaction_mapping(
        self, account_id: str, artifact_id: str
    ) -> Mapping[str, str]: ...

    def add_market_dataset(
        self,
        dataset: DatasetVersion,
        prices: Iterable[MarketPrice],
        fx_rates: Iterable[FxRate],
    ) -> Mapping[str, Any]: ...

    def market_price(
        self,
        instrument_id: str,
        as_of: str,
        known_as_of: str | None = None,
        dataset_name: str | None = None,
        dataset_version: str | None = None,
    ) -> Mapping[str, Any] | None: ...

    def market_fx_rate(
        self,
        from_currency: str,
        to_currency: str,
        as_of: str,
        known_as_of: str | None = None,
        dataset_name: str | None = None,
        dataset_version: str | None = None,
    ) -> Mapping[str, Any] | None: ...

    def market_datasets(self, dataset_name: str | None = None) -> list[Mapping[str, Any]]: ...

    def add_portfolio(self, portfolio: Portfolio) -> None: ...

    def portfolio(self, portfolio_id: str) -> Mapping[str, Any]: ...

    def add_portfolio_membership(self, event: PortfolioMembershipEvent) -> None: ...

    def portfolio_accounts(
        self, portfolio_id: str, as_of: str, known_as_of: str | None = None
    ) -> list[str]: ...

    def add_policy(
        self,
        policy: InvestmentPolicy,
        version: PolicyVersion,
        rules: Iterable[PolicyRule],
    ) -> None: ...

    def add_policy_version(
        self, version: PolicyVersion, rules: Iterable[PolicyRule]
    ) -> None: ...

    def policy(self, policy_id: str) -> Mapping[str, Any]: ...

    def policies(
        self, portfolio_id: str | None = None
    ) -> list[Mapping[str, Any]]: ...

    def next_policy_version_number(self, policy_id: str) -> int: ...

    def policy_version_at(
        self, policy_id: str, as_of: str, known_as_of: str | None = None
    ) -> Mapping[str, Any]: ...

    def policy_versions(self, policy_id: str) -> list[Mapping[str, Any]]: ...

    def policy_rules(self, policy_version_id: str) -> list[Mapping[str, Any]]: ...
