from __future__ import annotations

from pathlib import Path
import json
from typing import Any

from clausula.domain import TransactionLeg, canonical_decimal, dec

from .ledger import MANUAL_EVENT_FORMAT, LedgerService
from .market import MarketService
from .policy import POLICY_EVENT_FORMAT, PolicyService
from .portfolio import PORTFOLIO_EVENT_FORMAT, PortfolioService
from .ports import CoreRepository


class RebuildError(RuntimeError):
    pass


class LedgerRebuilder:
    """Replay supported immutable raw imports into an empty target repository."""

    def __init__(self, source: CoreRepository, target: CoreRepository):
        self.source = source
        self.target = target

    def rebuild(self) -> dict[str, Any]:
        catalog = self.source.rebuild_catalog()
        target_catalog = self.target.rebuild_catalog()
        if (
            target_catalog["accounts"]
            or target_catalog["portfolios"]
            or target_catalog.get("policies")
            or target_catalog["imports"]
        ):
            raise RebuildError("target repository must be empty")
        target_service = LedgerService(self.target)
        target_market = MarketService(self.target)
        target_portfolios = PortfolioService(self.target)
        target_policies = PolicyService(self.target)
        account_mapping: dict[str, str] = {}
        transaction_mapping: dict[str, str] = {}
        instrument_mapping: dict[str, str] = {}
        portfolio_mapping: dict[str, str] = {}
        policy_mapping: dict[str, str] = {}
        policy_version_mapping: dict[str, str] = {}
        policy_rule_mapping: dict[str, str] = {}
        for account in catalog["accounts"]:
            account_mapping[account["id"]] = target_service.create_account(
                account["institution"], account["name"]
            )

        replayed: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for batch in catalog["imports"]:
            if batch["adapter_name"] in {"csv-prices", "csv-fx"}:
                source_path = Path(batch["raw_path"])
                if batch["adapter_name"] == "csv-prices":
                    result = target_market.import_prices_csv(
                        source_path,
                        dataset_name=batch["dataset_name"],
                        version=batch["dataset_version"],
                        provider=batch["dataset_provider"],
                    )
                else:
                    result = target_market.import_fx_csv(
                        source_path,
                        dataset_name=batch["dataset_name"],
                        version=batch["dataset_version"],
                        provider=batch["dataset_provider"],
                    )
                if result["manifest_sha256"] != batch["dataset_manifest_sha256"]:
                    raise RebuildError(
                        f"market manifest mismatch during rebuild: {batch['id']}"
                    )
                replayed.append(
                    {
                        "kind": "market_dataset",
                        "operation": "market.import",
                        "source_import_batch_id": batch["id"],
                        "source_artifact_sha256": batch["sha256"],
                        "result": result,
                    }
                )
                continue
            if batch["adapter_name"] == "csv":
                source_path = Path(batch["raw_path"])
                if not source_path.is_file():
                    raise RebuildError(f"raw artifact missing: {batch['sha256']}")
                if not batch["account_ids"]:
                    continue
                if len(batch["account_ids"]) != 1:
                    raise RebuildError(
                        f"CSV import must map to exactly one account: {batch['id']}"
                    )
                source_account_id = batch["account_ids"][0]
                deduplication_key = (source_account_id, batch["sha256"])
                if deduplication_key in seen:
                    continue
                seen.add(deduplication_key)
                target_account_id = account_mapping[source_account_id]
                result = target_service.import_csv(target_account_id, source_path)
                source_rows = self.source.imported_transaction_mapping(
                    source_account_id, batch["artifact_id"]
                )
                target_rows = self.target.imported_transaction_mapping(
                    target_account_id, result["artifact_id"]
                )
                for external_id, source_transaction_id in source_rows.items():
                    if external_id in target_rows:
                        transaction_mapping[source_transaction_id] = target_rows[external_id]
                replayed.append(
                {
                    "kind": "csv_import",
                    "operation": "ledger.import_csv",
                    "source_import_batch_id": batch["id"],
                        "source_artifact_sha256": batch["sha256"],
                        "target_import_batch_id": result["import_batch_id"],
                        "transactions": result["transactions"],
                    }
                )
                continue
            if batch["adapter_name"] == "manual":
                if batch["inserted_rows"]:
                    warnings.append(
                        {
                            "kind": "unsupported_manual_event",
                            "import_batch_id": batch["id"],
                            "adapter_name": batch["adapter_name"],
                            "error": "manual batch has no replayable event envelope",
                        }
                    )
                continue
            source_path = Path(batch["raw_path"])
            try:
                event = json.loads(source_path.read_text(encoding="utf-8"))
                if event.get("format") not in {
                    MANUAL_EVENT_FORMAT,
                    PORTFOLIO_EVENT_FORMAT,
                    POLICY_EVENT_FORMAT,
                }:
                    raise ValueError("unknown manual event format")
                if event["format"] == POLICY_EVENT_FORMAT:
                    result = self._replay_policy_event(
                        target_policies,
                        event,
                        portfolio_mapping,
                        policy_mapping,
                        policy_version_mapping,
                        policy_rule_mapping,
                    )
                else:
                    result = self._replay_manual_event(
                        target_service,
                        target_portfolios,
                        event,
                        account_mapping,
                        instrument_mapping,
                        transaction_mapping,
                        portfolio_mapping,
                    )
                replayed.append(
                    {
                        "kind": "manual_event",
                        "source_import_batch_id": batch["id"],
                        "source_artifact_sha256": batch["sha256"],
                        "operation": event["operation"],
                        "result": result,
                    }
                )
            except (KeyError, TypeError, ValueError) as exc:
                warnings.append(
                    {
                        "kind": "unsupported_manual_event",
                        "import_batch_id": batch["id"],
                        "adapter_name": batch["adapter_name"],
                        "error": str(exc),
                    }
                )

        comparisons = []
        consistent = True
        source_service = LedgerService(self.source)
        for source_account_id, target_account_id in account_mapping.items():
            source_state = source_service.state(source_account_id)
            target_state = target_service.state(target_account_id)
            source_positions = self._positions_by_identifier(self.source, source_state["positions"])
            target_positions = self._positions_by_identifier(self.target, target_state["positions"])
            matches = (
                source_state["cash_by_currency"] == target_state["cash_by_currency"]
                and source_positions == target_positions
            )
            consistent = consistent and matches
            comparisons.append(
                {
                    "source_account_id": source_account_id,
                    "target_account_id": target_account_id,
                    "matches": matches,
                    "source": {
                        "cash_by_currency": source_state["cash_by_currency"],
                        "positions": source_positions,
                    },
                    "target": {
                        "cash_by_currency": target_state["cash_by_currency"],
                        "positions": target_positions,
                    },
                }
            )
        portfolio_comparisons = []
        for source_portfolio in catalog["portfolios"]:
            source_portfolio_id = source_portfolio["id"]
            target_portfolio_id = portfolio_mapping.get(source_portfolio_id)
            if target_portfolio_id is None:
                consistent = False
                portfolio_comparisons.append(
                    {
                        "source_portfolio_id": source_portfolio_id,
                        "target_portfolio_id": None,
                        "matches": False,
                    }
                )
                continue
            source_accounts = self.source.portfolio_accounts(
                source_portfolio_id, "9999-12-31", "9999-12-31"
            )
            target_accounts = self.target.portfolio_accounts(
                target_portfolio_id, "9999-12-31", "9999-12-31"
            )
            expected_accounts = sorted(account_mapping[item] for item in source_accounts)
            target_portfolio = self.target.portfolio(target_portfolio_id)
            matches = (
                target_portfolio["name"] == source_portfolio["name"]
                and target_portfolio["base_currency"] == source_portfolio["base_currency"]
                and target_accounts == expected_accounts
            )
            consistent = consistent and matches
            portfolio_comparisons.append(
                {
                    "source_portfolio_id": source_portfolio_id,
                    "target_portfolio_id": target_portfolio_id,
                    "matches": matches,
                    "source_accounts": source_accounts,
                    "target_accounts": target_accounts,
                }
            )
        policy_comparisons = []
        for source_entry in catalog.get("policies", []):
            source_policy = source_entry["policy"]
            source_policy_id = source_policy["id"]
            target_policy_id = policy_mapping.get(source_policy_id)
            matches = target_policy_id is not None
            target_entry = None
            if target_policy_id is not None:
                target_policy = dict(self.target.policy(target_policy_id))
                target_versions = [
                    {
                        "version": dict(version),
                        "rules": [
                            dict(rule)
                            for rule in self.target.policy_rules(version["id"])
                        ],
                    }
                    for version in self.target.policy_versions(target_policy_id)
                ]
                target_entry = {"policy": target_policy, "versions": target_versions}
                matches = matches and (
                    target_policy["name"] == source_policy["name"]
                    and target_policy["created_at"] == source_policy["created_at"]
                    and target_policy["portfolio_id"]
                    == portfolio_mapping[source_policy["portfolio_id"]]
                )
                source_versions = source_entry["versions"]
                if len(source_versions) != len(target_versions):
                    matches = False
                else:
                    for source_version, target_version in zip(
                        source_versions, target_versions
                    ):
                        sv = source_version["version"]
                        tv = target_version["version"]
                        source_rules = [
                            self._policy_rule_semantics(rule)
                            for rule in source_version["rules"]
                        ]
                        target_rules = [
                            self._policy_rule_semantics(rule)
                            for rule in target_version["rules"]
                        ]
                        matches = matches and (
                            sv["version_number"] == tv["version_number"]
                            and sv["effective_from"] == tv["effective_from"]
                            and sv["known_at"] == tv["known_at"]
                            and sv["recorded_at"] == tv["recorded_at"]
                            and sv["rules_sha256"] == tv["rules_sha256"]
                            and source_rules == target_rules
                        )
            consistent = consistent and matches
            policy_comparisons.append(
                {
                    "source_policy_id": source_policy_id,
                    "target_policy_id": target_policy_id,
                    "matches": matches,
                    "source": source_entry,
                    "target": target_entry,
                }
            )
        return {
            "consistent": consistent and not warnings,
            "account_mapping": account_mapping,
            "instrument_mapping": instrument_mapping,
            "transaction_mapping": transaction_mapping,
            "portfolio_mapping": portfolio_mapping,
            "policy_mapping": policy_mapping,
            "policy_version_mapping": policy_version_mapping,
            "policy_rule_mapping": policy_rule_mapping,
            "replayed_imports": replayed,
            "comparisons": comparisons,
            "portfolio_comparisons": portfolio_comparisons,
            "policy_comparisons": policy_comparisons,
            "warnings": warnings,
        }

    @staticmethod
    def _policy_rule_semantics(rule: dict[str, Any]) -> tuple:
        return (
            rule["rule_key"],
            rule["rule_type"],
            rule["severity"],
            rule["description"],
            rule["subject"],
            rule["target"],
            rule["lower_bound"],
            rule["upper_bound"],
        )

    @staticmethod
    def _policy_rule_definitions(event: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {key: value for key, value in definition.items() if key != "id"}
            for definition in event["rules"]
        ]

    def _replay_policy_event(
        self,
        policies: PolicyService,
        event: dict[str, Any],
        portfolio_mapping: dict[str, str],
        policy_mapping: dict[str, str],
        policy_version_mapping: dict[str, str],
        policy_rule_mapping: dict[str, str],
    ) -> dict[str, Any]:
        if event.get("schema_version") != "1":
            raise ValueError("unsupported policy event schema version")
        operation = event["operation"]
        definitions = self._policy_rule_definitions(event)
        if operation == "policy.create":
            target = policies.create(
                portfolio_mapping[event["portfolio_id"]],
                event["name"],
                event["effective_from"],
                definitions,
                known_at=event["known_at"],
                created_at=event["created_at"],
                recorded_at=event["recorded_at"],
            )
            if (
                target["rules_sha256"] != event["rules_sha256"]
                or target["version_number"] != event["version_number"]
            ):
                raise RebuildError("policy create semantics changed during rebuild")
            policy_mapping[event["policy_id"]] = target["policy_id"]
            policy_version_mapping[event["policy_version_id"]] = target[
                "policy_version_id"
            ]
            target_rules = self.target.policy_rules(target["policy_version_id"])
            target_by_key = {row["rule_key"]: row["id"] for row in target_rules}
            for source_rule in event["rules"]:
                if "id" in source_rule:
                    policy_rule_mapping[source_rule["id"]] = target_by_key[
                        source_rule["key"]
                    ]
            return target
        if operation == "policy.add_version":
            target = policies.add_version(
                policy_mapping[event["policy_id"]],
                event["effective_from"],
                definitions,
                known_at=event["known_at"],
                recorded_at=event["recorded_at"],
            )
            if (
                target["rules_sha256"] != event["rules_sha256"]
                or target["version_number"] != event["version_number"]
            ):
                raise RebuildError("policy version semantics changed during rebuild")
            policy_version_mapping[event["policy_version_id"]] = target[
                "policy_version_id"
            ]
            target_rules = self.target.policy_rules(target["policy_version_id"])
            target_by_key = {row["rule_key"]: row["id"] for row in target_rules}
            for source_rule in event["rules"]:
                if "id" in source_rule:
                    policy_rule_mapping[source_rule["id"]] = target_by_key[
                        source_rule["key"]
                    ]
            return target
        raise ValueError(f"unsupported policy operation: {operation}")

    def _map_instrument(
        self,
        service: LedgerService,
        source_instrument_id: str,
        mapping: dict[str, str],
    ) -> str:
        if source_instrument_id not in mapping:
            instrument = self.source.instrument_details(source_instrument_id)
            mapping[source_instrument_id] = service.resolve_instrument(
                instrument["identifier"],
                instrument["name"],
                instrument["asset_type"],
                instrument["currency"],
                scheme=instrument["scheme"],
            )
        return mapping[source_instrument_id]

    def _replay_manual_event(
        self,
        service: LedgerService,
        portfolios: PortfolioService,
        event: dict[str, Any],
        account_mapping: dict[str, str],
        instrument_mapping: dict[str, str],
        transaction_mapping: dict[str, str],
        portfolio_mapping: dict[str, str],
    ) -> Any:
        operation = event["operation"]
        if event.get("format") == PORTFOLIO_EVENT_FORMAT:
            if operation == "portfolio.create":
                portfolio_id = portfolios.create(
                    event["name"],
                    event["base_currency"],
                    created_at=event["created_at"],
                )
                portfolio_mapping[event["portfolio_id"]] = portfolio_id
                return {"portfolio_id": portfolio_id}
            if operation == "portfolio.set_membership":
                membership_event_id = portfolios.set_membership(
                    portfolio_mapping[event["portfolio_id"]],
                    account_mapping[event["account_id"]],
                    event["action"],
                    event["effective_at"],
                    known_at=event["known_at"],
                    recorded_at=event["recorded_at"],
                )
                return {"membership_event_id": membership_event_id}
            raise ValueError(f"unsupported portfolio operation: {operation}")
        if operation == "ledger.record_cash_transfer":
            result = service.record_cash_transfer(
                account_mapping[event["source_account_id"]],
                account_mapping[event["destination_account_id"]],
                event["amount"],
                event["currency"],
                event["effective_at"],
                fee=event["fee"],
                known_at=event["known_at"],
                description=event["description"],
            )
            transaction_mapping[event["source_transaction_id"]] = result["source_transaction_id"]
            transaction_mapping[event["destination_transaction_id"]] = result["destination_transaction_id"]
            return result
        if operation == "ledger.record_fx_conversion":
            transaction_id = service.record_fx_conversion(
                account_mapping[event["account_id"]],
                event["from_currency"],
                event["to_currency"],
                event["from_amount"],
                event["to_amount"],
                event["effective_at"],
                fee=event["fee"],
                fee_currency=event["fee_currency"],
                known_at=event["known_at"],
                description=event["description"],
            )
            transaction_mapping[event["transaction_id"]] = transaction_id
            return {"transaction_id": transaction_id}
        if operation == "ledger.record_security_transfer":
            target_instrument = self._map_instrument(
                service, event["instrument_id"], instrument_mapping
            )
            result = service.record_security_transfer(
                account_mapping[event["source_account_id"]],
                account_mapping[event["destination_account_id"]],
                target_instrument,
                event["quantity"],
                event["effective_at"],
                known_at=event["known_at"],
                description=event["description"],
            )
            transaction_mapping[event["source_transaction_id"]] = result["source_transaction_id"]
            transaction_mapping[event["destination_transaction_id"]] = result["destination_transaction_id"]
            return result
        if operation == "ledger.record_split":
            target_instrument = self._map_instrument(
                service, event["instrument_id"], instrument_mapping
            )
            action_id = service.record_split(
                account_mapping[event["account_id"]],
                target_instrument,
                event["numerator"],
                event["denominator"],
                event["effective_at"],
                known_at=event["known_at"],
                description=event["description"],
            )
            transaction_mapping[event["transaction_id"]] = self.target.corporate_action_transaction(
                action_id
            )
            return {"action_id": action_id}
        if operation == "ledger.record_correction":
            legs = []
            for raw_leg in event["legs"]:
                instrument_id = raw_leg["instrument_id"]
                legs.append(
                    TransactionLeg(
                        account_mapping[raw_leg["account_id"]],
                        None
                        if instrument_id is None
                        else self._map_instrument(service, instrument_id, instrument_mapping),
                        dec(raw_leg["quantity"]),
                        dec(raw_leg["amount"]),
                        raw_leg["currency"],
                        raw_leg["leg_type"],
                    )
                )
            corrected = event.get("corrects_transaction_id")
            transaction_id = service.record_correction(
                account_mapping[event["account_id"]],
                legs,
                event["effective_at"],
                event["reason"],
                corrects_transaction_id=None
                if corrected is None
                else transaction_mapping[corrected],
                known_at=event["known_at"],
            )
            transaction_mapping[event["transaction_id"]] = transaction_id
            return {"transaction_id": transaction_id}
        if operation == "ledger.reconcile":
            positions = {
                self._map_instrument(service, source_id, instrument_mapping): value
                for source_id, value in event["observed"]["positions"].items()
            }
            result = service.reconcile(
                account_mapping[event["account_id"]],
                {
                    "cash_by_currency": event["observed"]["cash_by_currency"],
                    "positions": positions,
                },
                event["effective_at"],
                known_at=event["known_at"],
            )
            return {"reconciliation_id": result.record_id}
        raise ValueError(f"unsupported operation: {operation}")

    @staticmethod
    def _positions_by_identifier(
        repository: CoreRepository, positions: dict[str, str]
    ) -> dict[str, str]:
        result = {}
        for instrument_id, quantity in positions.items():
            instrument = repository.instrument_details(instrument_id)
            key = f"{instrument['scheme']}:{instrument['identifier']}"
            result[key] = quantity
        return dict(sorted(result.items()))
