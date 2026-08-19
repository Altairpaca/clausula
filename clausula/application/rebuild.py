from __future__ import annotations

from pathlib import Path
import json
from typing import Any

from clausula.domain import TransactionLeg, canonical_decimal, dec

from .ledger import MANUAL_EVENT_FORMAT, LedgerService
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
        if self.target.rebuild_catalog()["accounts"]:
            raise RebuildError("target repository must be empty")
        target_service = LedgerService(self.target)
        account_mapping: dict[str, str] = {}
        transaction_mapping: dict[str, str] = {}
        instrument_mapping: dict[str, str] = {}
        for account in catalog["accounts"]:
            account_mapping[account["id"]] = target_service.create_account(
                account["institution"], account["name"]
            )

        replayed: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for batch in catalog["imports"]:
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
                if event.get("format") != MANUAL_EVENT_FORMAT:
                    raise ValueError("unknown manual event format")
                result = self._replay_manual_event(
                    target_service,
                    event,
                    account_mapping,
                    instrument_mapping,
                    transaction_mapping,
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
        return {
            "consistent": consistent and not warnings,
            "account_mapping": account_mapping,
            "instrument_mapping": instrument_mapping,
            "transaction_mapping": transaction_mapping,
            "replayed_imports": replayed,
            "comparisons": comparisons,
            "warnings": warnings,
        }

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
        event: dict[str, Any],
        account_mapping: dict[str, str],
        instrument_mapping: dict[str, str],
        transaction_mapping: dict[str, str],
    ) -> Any:
        operation = event["operation"]
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
