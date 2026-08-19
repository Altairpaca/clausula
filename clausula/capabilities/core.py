from __future__ import annotations

from pathlib import Path
from typing import Any

from clausula.application import CoreRepository, LedgerService, MarketService, PortfolioService

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
    market = MarketService(repository)
    portfolios = PortfolioService(repository)
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
    registry.register(
        CapabilitySpec(
            "ledger.get_cost_basis",
            "Replay FIFO lots and realized gains without market-price assumptions.",
            object_schema(
                {"account_id": STRING, "as_of": NULLABLE_STRING},
                required=("account_id",),
            ),
            {"type": "object"},
            "read",
            True,
            SideEffect.LOCAL_READ,
            ("portfolio:read",),
            False,
            "Every open lot and realized match links to source transaction provenance.",
        ),
        lambda account_id, as_of=None: service.cost_basis(account_id, as_of),
    )
    registry.register(
        CapabilitySpec(
            "ledger.record_fx_conversion",
            "Record a balanced two-currency FX conversion with explicit rate and fee.",
            object_schema(
                {
                    "account_id": STRING,
                    "from_currency": STRING,
                    "to_currency": STRING,
                    "from_amount": STRING,
                    "to_amount": STRING,
                    "effective_at": STRING,
                    "fee": STRING,
                    "fee_currency": NULLABLE_STRING,
                },
                required=(
                    "account_id",
                    "from_currency",
                    "to_currency",
                    "from_amount",
                    "to_amount",
                    "effective_at",
                ),
            ),
            object_schema({"transaction_id": STRING}, required=("transaction_id",)),
            "write",
            True,
            SideEffect.LOCAL_WRITE,
            ("ledger:write",),
            True,
            "Creates a provenance artifact, import batch, balanced transaction, and audit events.",
        ),
        lambda account_id, from_currency, to_currency, from_amount, to_amount, effective_at, fee="0", fee_currency=None: {
            "transaction_id": service.record_fx_conversion(
                account_id,
                from_currency,
                to_currency,
                from_amount,
                to_amount,
                effective_at,
                fee=fee,
                fee_currency=fee_currency,
            )
        },
    )
    registry.register(
        CapabilitySpec(
            "market.import_prices_csv",
            "Import a versioned daily price dataset with temporal provenance and quality flags.",
            object_schema(
                {
                    "path": STRING,
                    "dataset_name": STRING,
                    "version": NULLABLE_STRING,
                    "provider": STRING,
                },
                required=("path",),
            ),
            {"type": "object"},
            "write",
            True,
            SideEffect.LOCAL_WRITE,
            ("market:write",),
            True,
            "Stores raw source, dataset manifest, import batch, observations, and audit event.",
        ),
        lambda path, dataset_name="daily_prices", version=None, provider="local": market.import_prices_csv(
            path, dataset_name=dataset_name, version=version, provider=provider
        ),
    )
    registry.register(
        CapabilitySpec(
            "market.import_fx_csv",
            "Import a versioned daily FX dataset with temporal provenance and quality flags.",
            object_schema(
                {
                    "path": STRING,
                    "dataset_name": STRING,
                    "version": NULLABLE_STRING,
                    "provider": STRING,
                },
                required=("path",),
            ),
            {"type": "object"},
            "write",
            True,
            SideEffect.LOCAL_WRITE,
            ("market:write",),
            True,
            "Stores raw source, dataset manifest, import batch, observations, and audit event.",
        ),
        lambda path, dataset_name="daily_fx", version=None, provider="local": market.import_fx_csv(
            path, dataset_name=dataset_name, version=version, provider=provider
        ),
    )
    registry.register(
        CapabilitySpec(
            "market.list_datasets",
            "List immutable market dataset versions and manifests.",
            object_schema({"dataset_name": NULLABLE_STRING}),
            {"type": "array", "items": {"type": "object"}},
            "read",
            True,
            SideEffect.LOCAL_READ,
            ("market:read",),
            False,
            "Returns source, import, manifest, provider, and version provenance.",
        ),
        lambda dataset_name=None: [
            dict(row) for row in repository.market_datasets(dataset_name)
        ],
    )
    registry.register(
        CapabilitySpec(
            "portfolio.create",
            "Create a cross-account portfolio with a base currency.",
            object_schema(
                {"name": STRING, "base_currency": STRING}, required=("name",)
            ),
            object_schema({"portfolio_id": STRING}, required=("portfolio_id",)),
            "write",
            True,
            SideEffect.LOCAL_WRITE,
            ("portfolio:write",),
            True,
            "Creates an append-only portfolio and audit event.",
        ),
        lambda name, base_currency="USD": {
            "portfolio_id": portfolios.create(name, base_currency)
        },
    )
    registry.register(
        CapabilitySpec(
            "portfolio.set_membership",
            "Append an effective and knowledge-dated account membership event.",
            object_schema(
                {
                    "portfolio_id": STRING,
                    "account_id": STRING,
                    "action": {"type": "string", "enum": ["add", "remove"]},
                    "effective_at": STRING,
                    "known_at": NULLABLE_STRING,
                },
                required=("portfolio_id", "account_id", "action", "effective_at"),
            ),
            object_schema({"membership_event_id": STRING}, required=("membership_event_id",)),
            "write",
            True,
            SideEffect.LOCAL_WRITE,
            ("portfolio:write",),
            True,
            "Creates an append-only membership event and audit event.",
        ),
        lambda portfolio_id, account_id, action, effective_at, known_at=None: {
            "membership_event_id": portfolios.set_membership(
                portfolio_id,
                account_id,
                action,
                effective_at,
                known_at=known_at,
            )
        },
    )
    registry.register(
        CapabilitySpec(
            "portfolio.get_valuation",
            "Value a cross-account portfolio with strict market and knowledge cutoffs.",
            object_schema(
                {
                    "portfolio_id": STRING,
                    "as_of": STRING,
                    "known_as_of": NULLABLE_STRING,
                    "price_dataset_name": NULLABLE_STRING,
                    "price_dataset_version": NULLABLE_STRING,
                    "fx_dataset_name": NULLABLE_STRING,
                    "fx_dataset_version": NULLABLE_STRING,
                },
                required=("portfolio_id", "as_of"),
            ),
            {"type": "object"},
            "read",
            True,
            SideEffect.LOCAL_READ,
            ("portfolio:read", "market:read"),
            False,
            "Returns all price/FX dataset references and structured valuation gaps.",
        ),
        lambda portfolio_id, as_of, known_as_of=None, price_dataset_name=None, price_dataset_version=None, fx_dataset_name=None, fx_dataset_version=None: portfolios.portfolio_valuation(
            portfolio_id,
            as_of,
            known_as_of=known_as_of,
            price_dataset_name=price_dataset_name,
            price_dataset_version=price_dataset_version,
            fx_dataset_name=fx_dataset_name,
            fx_dataset_version=fx_dataset_version,
        ),
    )
    registry.register(
        CapabilitySpec(
            "portfolio.get_performance",
            "Compute Decimal TWR, XIRR, drawdown, flows, and valuation series.",
            object_schema(
                {
                    "portfolio_id": STRING,
                    "dates": {"type": "array", "items": STRING},
                    "known_as_of": NULLABLE_STRING,
                    "price_dataset_name": NULLABLE_STRING,
                    "price_dataset_version": NULLABLE_STRING,
                    "fx_dataset_name": NULLABLE_STRING,
                    "fx_dataset_version": NULLABLE_STRING,
                },
                required=("portfolio_id", "dates"),
            ),
            {"type": "object"},
            "read",
            True,
            SideEffect.LOCAL_READ,
            ("portfolio:read", "market:read"),
            False,
            "Uses point-in-time facts by default and reports external-flow timing semantics.",
        ),
        lambda portfolio_id, dates, known_as_of=None, price_dataset_name=None, price_dataset_version=None, fx_dataset_name=None, fx_dataset_version=None: portfolios.performance(
            portfolio_id,
            dates,
            known_as_of=known_as_of,
            price_dataset_name=price_dataset_name,
            price_dataset_version=price_dataset_version,
            fx_dataset_name=fx_dataset_name,
            fx_dataset_version=fx_dataset_version,
        ),
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
