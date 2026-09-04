from __future__ import annotations

import csv
from decimal import Decimal
import json
from pathlib import Path
from typing import Mapping

from .ports import CoreRepository

from clausula.analytics import plan_fifo_transfer, replay_fifo

from clausula.domain import (
    ActionBasisAllocation,
    ActionConsiderationFact,
    ActionInstrumentFact,
    CORPORATE_ACTION_TYPES,
    CorporateAction,
    FxConversion,
    InstrumentIdentifier,
    LotTransferAllocation,
    ReconciliationResult,
    SecurityTransfer,
    Transaction,
    TransactionLeg,
    canonical_decimal,
    canonical_timestamp,
    dec,
    new_id,
    now,
)


CSV_ADAPTER_VERSION = "1"
CSV_SCHEMA_VERSION = "1"
MANUAL_EVENT_FORMAT = "clausula-manual-event-v1"


class ImportValidationError(ValueError):
    def __init__(self, row_number: int, message: str):
        super().__init__(f"CSV row {row_number}: {message}")
        self.row_number = row_number


class LedgerService:
    def __init__(self, repository: CoreRepository):
        self.repository = repository

    def create_account(self, institution: str, name: str) -> str:
        return self.repository.create_account(institution, name)

    def resolve_instrument(
        self,
        ticker: str,
        name: str = "",
        asset_type: str = "stock",
        currency: str = "USD",
        *,
        scheme: str = "ticker",
    ) -> str:
        return self.repository.instrument(
            InstrumentIdentifier(ticker, scheme), name, asset_type, currency
        )

    def _import_csv_unscoped(self, account_id: str, path: str | Path) -> dict[str, str | int]:
        self.repository.require_account(account_id)
        artifact_id, digest = self.repository.artifact(path)
        batch_id = new_id()
        recorded_at = now()
        parsed: list[tuple[Transaction, str]] = []
        external_ids: set[str] = set()

        with Path(path).open(newline="", encoding="utf-8-sig") as source:
            reader = csv.DictReader(source)
            if reader.fieldnames is None:
                raise ImportValidationError(1, "header row is required")
            for row_number, row in enumerate(reader, 2):
                external_id = (row.get("id") or str(row_number - 1)).strip()
                if not external_id:
                    raise ImportValidationError(row_number, "id cannot be empty")
                if external_id in external_ids:
                    raise ImportValidationError(row_number, f"duplicate id {external_id!r}")
                external_ids.add(external_id)
                try:
                    transaction = self._transaction_from_csv_row(
                        account_id,
                        row,
                        row_number,
                        artifact_id,
                        batch_id,
                        recorded_at,
                    )
                except ImportValidationError:
                    raise
                except (KeyError, TypeError, ValueError) as exc:
                    raise ImportValidationError(row_number, str(exc)) from exc
                parsed.append((transaction, external_id))

        inserted = self.repository.add_import(
            batch_id,
            artifact_id,
            parsed,
            adapter_name="csv",
            adapter_version=CSV_ADAPTER_VERSION,
            schema_version=CSV_SCHEMA_VERSION,
        )
        return {
            "artifact_id": artifact_id,
            "sha256": digest,
            "import_batch_id": batch_id,
            "transactions": inserted,
        }

    def import_csv(self, account_id: str, path: str | Path) -> dict[str, str | int]:
        with self.repository.write_transaction():
            return self._import_csv_unscoped(account_id, path)

    def _transaction_from_csv_row(
        self,
        account_id: str,
        row: Mapping[str, str | None],
        row_number: int,
        artifact_id: str,
        batch_id: str,
        recorded_at: str,
    ) -> Transaction:
        transaction_type = (row.get("type") or "buy").strip().lower()
        effective_at = row.get("effective_at") or row.get("date") or recorded_at
        known_at = row.get("known_at") or recorded_at
        currency = (row.get("currency") or "USD").strip().upper()
        ticker = (row.get("ticker") or row.get("instrument") or "CASH").strip()
        quantity = self._nonnegative(row.get("quantity"), "quantity")
        gross = self._nonnegative(row.get("amount"), "amount")
        fee = self._nonnegative(row.get("fee"), "fee")
        legs: list[TransactionLeg] = []

        instrument_id = None
        if ticker.upper() != "CASH":
            instrument_id = self.resolve_instrument(
                ticker,
                name=(row.get("instrument_name") or "").strip(),
                asset_type=(row.get("asset_type") or "stock").strip(),
                currency=currency,
                scheme=(row.get("identifier_scheme") or "ticker").strip(),
            )

        if transaction_type in {"buy", "sell"}:
            if instrument_id is None:
                raise ValueError(f"{transaction_type} requires an instrument")
            if quantity <= 0:
                raise ValueError(f"{transaction_type} quantity must be positive")
            if transaction_type == "buy":
                legs.append(TransactionLeg(account_id, instrument_id, quantity, gross, currency, "position"))
                cash_amount = -(gross + fee)
            else:
                legs.append(TransactionLeg(account_id, instrument_id, -quantity, -gross, currency, "position"))
                cash_amount = gross - fee
            legs.append(TransactionLeg(account_id, None, Decimal(0), cash_amount, currency, "cash"))
            if fee:
                legs.append(TransactionLeg(account_id, None, Decimal(0), fee, currency, "fee"))
        elif transaction_type in {"transfer_in", "transfer_out"}:
            direction = Decimal(1) if transaction_type == "transfer_in" else Decimal(-1)
            if instrument_id is not None:
                if quantity <= 0:
                    raise ValueError("instrument transfer quantity must be positive")
                legs.append(TransactionLeg(account_id, instrument_id, direction * quantity, Decimal(0), currency, "position"))
                if fee:
                    legs.append(TransactionLeg(account_id, None, Decimal(0), -fee, currency, "cash"))
                    legs.append(TransactionLeg(account_id, None, Decimal(0), fee, currency, "fee"))
            else:
                cash_amount = gross - fee if direction > 0 else -(gross + fee)
                legs.append(TransactionLeg(account_id, None, Decimal(0), cash_amount, currency, "cash"))
                legs.append(TransactionLeg(account_id, None, Decimal(0), -direction * gross, currency, "external"))
                if fee:
                    legs.append(TransactionLeg(account_id, None, Decimal(0), fee, currency, "fee"))
        elif transaction_type in {"deposit", "withdrawal"}:
            direction = Decimal(1) if transaction_type == "deposit" else Decimal(-1)
            cash_amount = gross - fee if direction > 0 else -(gross + fee)
            legs.append(TransactionLeg(account_id, None, Decimal(0), cash_amount, currency, "cash"))
            legs.append(TransactionLeg(account_id, None, Decimal(0), -direction * gross, currency, "external"))
            if fee:
                legs.append(TransactionLeg(account_id, None, Decimal(0), fee, currency, "fee"))
        elif transaction_type in {"dividend", "interest"}:
            legs.append(TransactionLeg(account_id, None, Decimal(0), gross - fee, currency, "cash"))
            legs.append(TransactionLeg(account_id, instrument_id, Decimal(0), -gross, currency, "income"))
            if fee:
                legs.append(TransactionLeg(account_id, None, Decimal(0), fee, currency, "fee"))
        elif transaction_type in {"fee", "tax"}:
            if gross <= 0:
                raise ValueError(f"{transaction_type} amount must be positive")
            legs.append(TransactionLeg(account_id, None, Decimal(0), -gross, currency, "cash"))
            legs.append(TransactionLeg(account_id, instrument_id, Decimal(0), gross, currency, transaction_type))
        else:
            raise ValueError(f"unsupported transaction type: {transaction_type}")

        self._require_amount_conservation(legs)
        return Transaction(
            new_id(),
            account_id,
            transaction_type,
            effective_at,
            known_at,
            recorded_at,
            (row.get("description") or f"CSV row {row_number}").strip(),
            artifact_id,
            batch_id,
            tuple(legs),
            source_sequence=row_number - 1,
        )

    @staticmethod
    def _nonnegative(value: str | None, field: str) -> Decimal:
        result = dec(value.strip() if value and value.strip() else "0")
        if result < 0:
            raise ValueError(f"{field} must not be negative")
        return result

    @staticmethod
    def _require_amount_conservation(legs: list[TransactionLeg]) -> None:
        totals: dict[str, Decimal] = {}
        for leg in legs:
            totals[leg.currency] = totals.get(leg.currency, Decimal(0)) + leg.amount
        unbalanced = {currency: value for currency, value in totals.items() if value != 0}
        if unbalanced:
            raise ValueError(f"transaction amounts do not conserve by currency: {unbalanced}")

    def transactions(
        self,
        account_id: str,
        as_of: str | None = None,
        *,
        known_as_of: str | None = None,
    ) -> list[dict]:
        return [
            dict(row) | {"legs": [dict(leg) for leg in self.repository.legs(row["id"])]}
            for row in self.repository.transactions(account_id, as_of, known_as_of)
        ]

    def state(
        self,
        account_id: str,
        as_of: str | None = None,
        *,
        known_as_of: str | None = None,
    ) -> dict:
        positions: dict[str, Decimal] = {}
        cash_by_currency: dict[str, Decimal] = {}
        for transaction in self.repository.transactions(account_id, as_of, known_as_of):
            for leg in self.repository.legs(transaction["id"]):
                if leg["leg_type"] == "cash":
                    currency = leg["currency"]
                    cash_by_currency[currency] = cash_by_currency.get(currency, Decimal(0)) + dec(leg["amount"])
                if leg["instrument_id"] and leg["leg_type"] == "position":
                    instrument_id = leg["instrument_id"]
                    positions[instrument_id] = positions.get(instrument_id, Decimal(0)) + dec(leg["quantity"])

        cash_output = {
            currency: canonical_decimal(amount)
            for currency, amount in sorted(cash_by_currency.items())
            if amount != 0
        }
        if not cash_output:
            legacy_cash, cash_currency = "0", None
        elif len(cash_output) == 1:
            cash_currency, legacy_cash = next(iter(cash_output.items()))
        else:
            legacy_cash, cash_currency = None, None
        return {
            "account_id": account_id,
            "as_of": canonical_timestamp(as_of) if as_of else now(),
            "cash": legacy_cash,
            "cash_currency": cash_currency,
            "cash_by_currency": cash_output,
            "positions": {
                instrument_id: canonical_decimal(quantity)
                for instrument_id, quantity in sorted(positions.items())
                if quantity != 0
            },
        }

    def positions(self, account_id: str, as_of: str | None = None) -> dict[str, str]:
        return self.state(account_id, as_of)["positions"]

    def external_flows(
        self,
        account_id: str,
        through: str,
        *,
        known_as_of: str | None = None,
    ) -> dict[str, str]:
        flows: dict[str, Decimal] = {}
        for transaction in self.transactions(
            account_id, through, known_as_of=known_as_of
        ):
            day = transaction["effective_at"][:10]
            for leg in transaction["legs"]:
                if leg["leg_type"] == "external":
                    flows[day] = flows.get(day, Decimal(0)) - dec(leg["amount"])
        return {day: canonical_decimal(amount) for day, amount in sorted(flows.items())}

    def cost_basis(
        self,
        account_id: str,
        as_of: str | None = None,
        *,
        known_as_of: str | None = None,
    ) -> dict:
        transactions = self.transactions(account_id, as_of, known_as_of=known_as_of)
        metadata = {
            transaction["id"]: dict(self.repository.transaction_metadata(transaction["id"]))
            for transaction in transactions
        }
        report = replay_fifo(transactions, metadata)
        return {
            "account_id": account_id,
            "as_of": canonical_timestamp(as_of) if as_of else now(),
            **report,
        }

    def reconcile(
        self,
        account_id: str,
        observed: Mapping,
        as_of: str,
        *,
        known_at: str | None = None,
    ) -> ReconciliationResult:
        derived = self.state(account_id, as_of)
        observed_positions = {
            instrument_id: canonical_decimal(value)
            for instrument_id, value in observed.get("positions", {}).items()
        }
        if "cash_by_currency" in observed:
            observed_cash = {
                currency.upper(): canonical_decimal(value)
                for currency, value in observed["cash_by_currency"].items()
            }
        else:
            currency = observed.get("cash_currency") or derived.get("cash_currency") or "USD"
            observed_cash = {currency.upper(): canonical_decimal(observed.get("cash", 0))}

        differences: list[dict] = []
        derived_cash = derived["cash_by_currency"]
        for currency in sorted(set(derived_cash) | set(observed_cash)):
            actual = canonical_decimal(observed_cash.get(currency, "0"))
            expected = canonical_decimal(derived_cash.get(currency, "0"))
            if dec(actual) != dec(expected):
                differences.append(
                    {"kind": "cash", "currency": currency, "derived": expected, "observed": actual}
                )
        for instrument_id in sorted(set(derived["positions"]) | set(observed_positions)):
            actual = canonical_decimal(observed_positions.get(instrument_id, "0"))
            expected = canonical_decimal(derived["positions"].get(instrument_id, "0"))
            if dec(actual) != dec(expected):
                differences.append(
                    {
                        "kind": "position",
                        "instrument_id": instrument_id,
                        "derived": expected,
                        "observed": actual,
                    }
                )

        normalized_observed = {
            "cash_by_currency": observed_cash,
            "positions": observed_positions,
        }
        knowledge_time = known_at or now()
        provenance_content = json.dumps(
            {
                "format": MANUAL_EVENT_FORMAT,
                "operation": "ledger.reconcile",
                "account_id": account_id,
                "effective_at": canonical_timestamp(as_of),
                "known_at": canonical_timestamp(knowledge_time),
                "observed": normalized_observed,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        artifact_id, _ = self.repository.virtual_artifact("manual://reconciliation", provenance_content)
        batch_id = self.repository.import_batch(
            artifact_id,
            adapter_name="manual-reconciliation",
            adapter_version="1",
            schema_version="1",
        )
        record_id = self.repository.record_reconciliation(
            account_id=account_id,
            effective_at=as_of,
            known_at=knowledge_time,
            source_artifact_id=artifact_id,
            import_batch_id=batch_id,
            observed=normalized_observed,
            derived=derived,
            differences=differences,
        )
        return ReconciliationResult(
            account_id,
            canonical_timestamp(as_of),
            tuple(differences),
            record_id,
        )

    def record_correction(
        self,
        account_id: str,
        legs: list[TransactionLeg] | tuple[TransactionLeg, ...],
        effective_at: str,
        reason: str = "correction",
        *,
        corrects_transaction_id: str | None = None,
        known_at: str | None = None,
    ) -> str:
        self.repository.require_account(account_id)
        if not reason.strip():
            raise ValueError("correction reason is required")
        self._require_amount_conservation(list(legs))
        transaction_id = new_id()
        recorded_at = now()
        knowledge_time = known_at or recorded_at
        provenance_content = json.dumps(
            {
                "format": MANUAL_EVENT_FORMAT,
                "operation": "ledger.record_correction",
                "transaction_id": transaction_id,
                "account_id": account_id,
                "effective_at": canonical_timestamp(effective_at),
                "known_at": canonical_timestamp(knowledge_time),
                "corrects_transaction_id": corrects_transaction_id,
                "reason": reason,
                "legs": [
                    {
                        "account_id": leg.account_id,
                        "instrument_id": leg.instrument_id,
                        "quantity": canonical_decimal(leg.quantity),
                        "amount": canonical_decimal(leg.amount),
                        "currency": leg.currency,
                        "leg_type": leg.leg_type,
                    }
                    for leg in legs
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        artifact_id, _ = self.repository.virtual_artifact("manual://ledger-correction", provenance_content)
        batch_id = self.repository.import_batch(
            artifact_id,
            adapter_name="manual-correction",
            adapter_version="1",
            schema_version="1",
        )
        transaction = Transaction(
            transaction_id,
            account_id,
            "correction",
            effective_at,
            knowledge_time,
            recorded_at,
            reason.strip(),
            artifact_id,
            batch_id,
            tuple(legs),
            corrects_transaction_id,
        )
        self.repository.add_transaction(transaction)
        return transaction.id

    def record_cash_transfer(
        self,
        source_account_id: str,
        destination_account_id: str,
        amount: Decimal | str | int,
        currency: str,
        effective_at: str,
        *,
        fee: Decimal | str | int = "0",
        known_at: str | None = None,
        description: str = "account transfer",
    ) -> dict[str, str]:
        self.repository.require_account(source_account_id)
        self.repository.require_account(destination_account_id)
        if source_account_id == destination_account_id:
            raise ValueError("transfer accounts must be distinct")
        transfer_amount = dec(amount)
        transfer_fee = dec(fee)
        if transfer_amount <= 0:
            raise ValueError("transfer amount must be positive")
        if transfer_fee < 0:
            raise ValueError("transfer fee must not be negative")

        transfer_id = new_id()
        source_transaction_id = new_id()
        destination_transaction_id = new_id()
        recorded_at = now()
        knowledge_time = known_at or recorded_at
        normalized_currency = currency.strip().upper()
        provenance = json.dumps(
            {
                "format": MANUAL_EVENT_FORMAT,
                "operation": "ledger.record_cash_transfer",
                "transfer_id": transfer_id,
                "source_transaction_id": source_transaction_id,
                "destination_transaction_id": destination_transaction_id,
                "source_account_id": source_account_id,
                "destination_account_id": destination_account_id,
                "amount": canonical_decimal(transfer_amount),
                "fee": canonical_decimal(transfer_fee),
                "currency": normalized_currency,
                "effective_at": canonical_timestamp(effective_at),
                "known_at": canonical_timestamp(knowledge_time),
                "description": description,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        artifact_id, _ = self.repository.virtual_artifact("manual://account-transfer", provenance)
        batch_id = self.repository.import_batch(
            artifact_id,
            adapter_name="manual-transfer",
            adapter_version="1",
            schema_version="1",
        )

        source_legs = [
            TransactionLeg(
                source_account_id,
                None,
                Decimal(0),
                -(transfer_amount + transfer_fee),
                normalized_currency,
                "cash",
            ),
            TransactionLeg(
                source_account_id,
                None,
                Decimal(0),
                transfer_amount,
                normalized_currency,
                "transfer",
            ),
        ]
        if transfer_fee:
            source_legs.append(
                TransactionLeg(
                    source_account_id,
                    None,
                    Decimal(0),
                    transfer_fee,
                    normalized_currency,
                    "fee",
                )
            )
        destination_legs = (
            TransactionLeg(
                destination_account_id,
                None,
                Decimal(0),
                transfer_amount,
                normalized_currency,
                "cash",
            ),
            TransactionLeg(
                destination_account_id,
                None,
                Decimal(0),
                -transfer_amount,
                normalized_currency,
                "transfer",
            ),
        )
        source_transaction = Transaction(
            source_transaction_id,
            source_account_id,
            "transfer_out",
            effective_at,
            knowledge_time,
            recorded_at,
            description,
            artifact_id,
            batch_id,
            tuple(source_legs),
        )
        destination_transaction = Transaction(
            destination_transaction_id,
            destination_account_id,
            "transfer_in",
            effective_at,
            knowledge_time,
            recorded_at,
            description,
            artifact_id,
            batch_id,
            destination_legs,
        )
        self.repository.add_transfer(transfer_id, source_transaction, destination_transaction)
        return {
            "transfer_id": transfer_id,
            "source_transaction_id": source_transaction.id,
            "destination_transaction_id": destination_transaction.id,
        }

    def record_fx_conversion(
        self,
        account_id: str,
        from_currency: str,
        to_currency: str,
        from_amount: Decimal | str | int,
        to_amount: Decimal | str | int,
        effective_at: str,
        *,
        fee: Decimal | str | int = "0",
        fee_currency: str | None = None,
        known_at: str | None = None,
        description: str = "FX conversion",
    ) -> str:
        self.repository.require_account(account_id)
        source_amount = dec(from_amount)
        destination_amount = dec(to_amount)
        fee_amount = dec(fee)
        if source_amount <= 0 or destination_amount <= 0:
            raise ValueError("FX amounts must be positive")
        if fee_amount < 0:
            raise ValueError("FX fee must not be negative")
        source_currency = from_currency.strip().upper()
        destination_currency = to_currency.strip().upper()
        normalized_fee_currency = fee_currency.strip().upper() if fee_currency else None
        if fee_amount and normalized_fee_currency is None:
            normalized_fee_currency = source_currency
        transaction_id = new_id()
        conversion = FxConversion(
            transaction_id,
            source_currency,
            destination_currency,
            source_amount,
            destination_amount,
            destination_amount / source_amount,
            fee_amount,
            normalized_fee_currency,
        )
        recorded_at = now()
        provenance = json.dumps(
            {
                "format": MANUAL_EVENT_FORMAT,
                "operation": "ledger.record_fx_conversion",
                "transaction_id": transaction_id,
                "account_id": account_id,
                "from_currency": source_currency,
                "to_currency": destination_currency,
                "from_amount": canonical_decimal(source_amount),
                "to_amount": canonical_decimal(destination_amount),
                "fee": canonical_decimal(fee_amount),
                "fee_currency": normalized_fee_currency,
                "effective_at": canonical_timestamp(effective_at),
                "known_at": canonical_timestamp(known_at or recorded_at),
                "description": description,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        artifact_id, _ = self.repository.virtual_artifact("manual://fx-conversion", provenance)
        batch_id = self.repository.import_batch(
            artifact_id,
            adapter_name="manual-fx",
            adapter_version="1",
            schema_version="1",
        )
        source_cash = -source_amount
        destination_cash = destination_amount
        if fee_amount and normalized_fee_currency == source_currency:
            source_cash -= fee_amount
        elif fee_amount and normalized_fee_currency == destination_currency:
            destination_cash -= fee_amount
        legs = [
            TransactionLeg(account_id, None, Decimal(0), source_cash, source_currency, "cash"),
            TransactionLeg(account_id, None, Decimal(0), source_amount, source_currency, "fx"),
            TransactionLeg(account_id, None, Decimal(0), destination_cash, destination_currency, "cash"),
            TransactionLeg(account_id, None, Decimal(0), -destination_amount, destination_currency, "fx"),
        ]
        if fee_amount:
            legs.append(
                TransactionLeg(
                    account_id,
                    None,
                    Decimal(0),
                    fee_amount,
                    normalized_fee_currency or source_currency,
                    "fee",
                )
            )
        self._require_amount_conservation(legs)
        transaction = Transaction(
            transaction_id,
            account_id,
            "fx_conversion",
            effective_at,
            known_at or recorded_at,
            recorded_at,
            description,
            artifact_id,
            batch_id,
            tuple(legs),
        )
        self.repository.add_fx_conversion(transaction, conversion)
        return transaction_id

    def record_security_transfer(
        self,
        source_account_id: str,
        destination_account_id: str,
        instrument_id: str,
        quantity: Decimal | str | int,
        effective_at: str,
        *,
        known_at: str | None = None,
        description: str = "security transfer",
    ) -> dict[str, str]:
        self.repository.require_account(source_account_id)
        self.repository.require_account(destination_account_id)
        instrument = self.repository.instrument_details(instrument_id)
        if source_account_id == destination_account_id:
            raise ValueError("security transfer accounts must be distinct")
        transfer_quantity = dec(quantity)
        if transfer_quantity <= 0:
            raise ValueError("security transfer quantity must be positive")
        recorded_at = now()
        knowledge_time = known_at or recorded_at
        report = self.cost_basis(
            source_account_id,
            effective_at,
            known_as_of=knowledge_time,
        )
        raw_allocations = plan_fifo_transfer(report, instrument_id, transfer_quantity)
        allocations = tuple(
            LotTransferAllocation(
                item["source_transaction_id"],
                item["acquired_at"],
                dec(item["quantity"]),
                dec(item["basis"]),
                item["currency"],
            )
            for item in raw_allocations
        )
        currencies = {item.currency for item in allocations}
        if currencies != {instrument["currency"]}:
            raise ValueError("lot currency does not match instrument currency")
        carried_basis = sum((item.basis for item in allocations), Decimal(0))
        transfer_id = new_id()
        source_transaction_id = new_id()
        destination_transaction_id = new_id()
        provenance = json.dumps(
            {
                "format": MANUAL_EVENT_FORMAT,
                "operation": "ledger.record_security_transfer",
                "transfer_id": transfer_id,
                "source_transaction_id": source_transaction_id,
                "destination_transaction_id": destination_transaction_id,
                "source_account_id": source_account_id,
                "destination_account_id": destination_account_id,
                "instrument_id": instrument_id,
                "quantity": canonical_decimal(transfer_quantity),
                "carried_basis": canonical_decimal(carried_basis),
                "allocations": raw_allocations,
                "effective_at": canonical_timestamp(effective_at),
                "known_at": canonical_timestamp(knowledge_time),
                "description": description,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        artifact_id, _ = self.repository.virtual_artifact("manual://security-transfer", provenance)
        batch_id = self.repository.import_batch(
            artifact_id,
            adapter_name="manual-security-transfer",
            adapter_version="1",
            schema_version="1",
        )
        source_transaction = Transaction(
            source_transaction_id,
            source_account_id,
            "transfer_out",
            effective_at,
            knowledge_time,
            recorded_at,
            description,
            artifact_id,
            batch_id,
            (
                TransactionLeg(
                    source_account_id,
                    instrument_id,
                    -transfer_quantity,
                    Decimal(0),
                    instrument["currency"],
                    "position",
                ),
            ),
        )
        destination_transaction = Transaction(
            destination_transaction_id,
            destination_account_id,
            "transfer_in",
            effective_at,
            knowledge_time,
            recorded_at,
            description,
            artifact_id,
            batch_id,
            (
                TransactionLeg(
                    destination_account_id,
                    instrument_id,
                    transfer_quantity,
                    Decimal(0),
                    instrument["currency"],
                    "position",
                ),
            ),
        )
        transfer = SecurityTransfer(
            transfer_id,
            source_transaction_id,
            destination_transaction_id,
            instrument_id,
            transfer_quantity,
            carried_basis,
            instrument["currency"],
            allocations,
        )
        self.repository.add_security_transfer(
            transfer, source_transaction, destination_transaction
        )
        return {
            "transfer_id": transfer_id,
            "source_transaction_id": source_transaction_id,
            "destination_transaction_id": destination_transaction_id,
        }

    def record_split(
        self,
        account_id: str,
        instrument_id: str,
        numerator: Decimal | str | int,
        denominator: Decimal | str | int,
        effective_at: str,
        *,
        known_at: str | None = None,
        description: str = "security split",
    ) -> str:
        self.repository.require_account(account_id)
        instrument = self.repository.instrument_details(instrument_id)
        split_numerator = dec(numerator)
        split_denominator = dec(denominator)
        if split_numerator <= 0 or split_denominator <= 0:
            raise ValueError("split ratio must be positive")
        if split_numerator == split_denominator:
            raise ValueError("split ratio must change quantity")
        recorded_at = now()
        knowledge_time = known_at or recorded_at
        pre_action_state = self.state(
            account_id,
            effective_at,
            known_as_of=knowledge_time,
        )
        current_quantity = dec(pre_action_state["positions"].get(instrument_id, "0"))
        if current_quantity == 0:
            raise ValueError("cannot split a zero position")
        adjustment = current_quantity * (split_numerator / split_denominator - Decimal(1))
        transaction_id = new_id()
        action_id = new_id()
        provenance = json.dumps(
            {
                "format": MANUAL_EVENT_FORMAT,
                "operation": "ledger.record_split",
                "action_id": action_id,
                "transaction_id": transaction_id,
                "account_id": account_id,
                "instrument_id": instrument_id,
                "numerator": canonical_decimal(split_numerator),
                "denominator": canonical_decimal(split_denominator),
                "pre_action_quantity": canonical_decimal(current_quantity),
                "quantity_adjustment": canonical_decimal(adjustment),
                "effective_at": canonical_timestamp(effective_at),
                "known_at": canonical_timestamp(knowledge_time),
                "description": description,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        artifact_id, _ = self.repository.virtual_artifact("manual://corporate-action", provenance)
        batch_id = self.repository.import_batch(
            artifact_id,
            adapter_name="manual-corporate-action",
            adapter_version="1",
            schema_version="1",
        )
        transaction = Transaction(
            transaction_id,
            account_id,
            "split",
            effective_at,
            knowledge_time,
            recorded_at,
            description,
            artifact_id,
            batch_id,
            (
                TransactionLeg(
                    account_id,
                    instrument_id,
                    adjustment,
                    Decimal(0),
                    instrument["currency"],
                    "position",
                ),
            ),
        )
        action = CorporateAction(
            action_id,
            transaction_id,
            instrument_id,
            "split",
            split_numerator,
            split_denominator,
        )
        self.repository.add_corporate_action(transaction, action)
        return action_id

    def record_corporate_action(
        self,
        account_id: str,
        action_type: str,
        effective_at: str,
        instruments: list[dict] | tuple[dict, ...],
        considerations: list[dict] | tuple[dict, ...],
        *,
        basis_allocations: list[dict] | tuple[dict, ...] = (),
        tax_profile_ref: str | None = None,
        tax_interpretation: dict | None = None,
        known_at: str | None = None,
        description: str = "corporate action",
    ) -> dict[str, str]:
        self.repository.require_account(account_id)
        normalized_type = str(action_type).strip().lower()
        if normalized_type not in CORPORATE_ACTION_TYPES:
            raise ValueError(f"unsupported corporate action type: {action_type}")
        if normalized_type in {"cash_merger", "cash_in_lieu"} and not any(
            item.get("kind") == "cash" for item in considerations
        ):
            raise ValueError(f"{normalized_type} requires explicit cash consideration")
        instrument_facts = [
            item if isinstance(item, ActionInstrumentFact) else ActionInstrumentFact(**item)
            for item in instruments
        ]
        consideration_facts = [
            item
            if isinstance(item, ActionConsiderationFact)
            else ActionConsiderationFact(**item)
            for item in considerations
        ]
        allocation_facts = [
            item if isinstance(item, ActionBasisAllocation) else ActionBasisAllocation(**item)
            for item in basis_allocations
        ]
        for item in instrument_facts:
            self.repository.instrument_details(item.instrument_id)
        for item in consideration_facts:
            if item.instrument_id is not None:
                self.repository.instrument_details(item.instrument_id)
        recorded_at = now()
        knowledge_time = canonical_timestamp(known_at or recorded_at)
        effective = canonical_timestamp(effective_at)
        pre_state = self.state(account_id, effective, known_as_of=knowledge_time)
        source_instrument_ids = {
            item.instrument_id for item in instrument_facts if item.role == "source"
        }
        for source_id in source_instrument_ids:
            quantity = dec(pre_state["positions"].get(source_id, "0"))
            if quantity < 0:
                raise ValueError(
                    f"corporate action on a short position is unsupported: {source_id}"
                )
        event_id = new_id()
        transaction_id = new_id()
        legs: list[TransactionLeg] = []
        position_delta_by_instrument: dict[str, Decimal] = {}
        cash_by_currency: dict[str, Decimal] = {}
        fee_by_currency: dict[str, Decimal] = {}
        tax_by_currency: dict[str, Decimal] = {}
        security_considerations = [
            item for item in consideration_facts if item.kind == "security"
        ]
        cash_considerations = [item for item in consideration_facts if item.kind == "cash"]
        for item in consideration_facts:
            if item.kind == "security":
                position_delta_by_instrument[item.instrument_id] = (
                    position_delta_by_instrument.get(item.instrument_id, Decimal(0))
                    + dec(item.quantity)
                )
            elif item.kind == "cash":
                cash_by_currency[item.currency] = cash_by_currency.get(
                    item.currency, Decimal(0)
                ) + dec(item.amount)
            elif item.kind == "fee":
                fee_by_currency[item.currency] = fee_by_currency.get(
                    item.currency, Decimal(0)
                ) + dec(item.amount)
            elif item.kind == "tax":
                tax_by_currency[item.currency] = tax_by_currency.get(
                    item.currency, Decimal(0)
                ) + dec(item.amount)
        source_qty: dict[str, Decimal] = {}
        for item in instrument_facts:
            if item.role == "source":
                source_qty[item.instrument_id] = dec(
                    pre_state["positions"].get(item.instrument_id, "0")
                )
        if normalized_type in {"merger", "stock_merger", "mixed_consideration", "exchange", "election", "security_change"}:
            if not security_considerations:
                raise ValueError(f"{normalized_type} requires a destination security consideration")
            for source_id, source_quantity in source_qty.items():
                if source_quantity > 0:
                    legs.append(
                        TransactionLeg(
                            account_id,
                            source_id,
                            -source_quantity,
                            Decimal(0),
                            self.repository.instrument_details(source_id)["currency"],
                            "position",
                        )
                    )
        for item in security_considerations:
            delta = dec(item.quantity)
            legs.append(
                TransactionLeg(
                    account_id,
                    item.instrument_id,
                    delta,
                    Decimal(0),
                    self.repository.instrument_details(item.instrument_id)["currency"],
                    "position",
                )
            )
        total_cash_out_by_currency: dict[str, Decimal] = {}
        for item in cash_considerations:
            total_cash_out_by_currency[item.currency] = total_cash_out_by_currency.get(
                item.currency, Decimal(0)
            ) + dec(item.amount)
        for currency, amount in total_cash_out_by_currency.items():
            legs.append(
                TransactionLeg(account_id, None, Decimal(0), amount, currency, "cash")
            )
            legs.append(
                TransactionLeg(
                    account_id,
                    None,
                    Decimal(0),
                    -amount,
                    currency,
                    "income",
                )
            )
        for currency, amount in fee_by_currency.items():
            legs.append(
                TransactionLeg(account_id, None, Decimal(0), -amount, currency, "cash")
            )
            legs.append(TransactionLeg(account_id, None, Decimal(0), amount, currency, "fee"))
        for currency, amount in tax_by_currency.items():
            legs.append(
                TransactionLeg(account_id, None, Decimal(0), -amount, currency, "cash")
            )
            legs.append(TransactionLeg(account_id, None, Decimal(0), amount, currency, "tax"))
        if not legs:
            raise ValueError("corporate action must produce at least one account consequence")
        self._require_amount_conservation(legs)
        provenance_content = json.dumps(
            {
                "format": MANUAL_EVENT_FORMAT,
                "operation": f"ledger.record_{normalized_type}",
                "event_id": event_id,
                "transaction_id": transaction_id,
                "account_id": account_id,
                "action_type": normalized_type,
                "effective_at": effective,
                "known_at": knowledge_time,
                "description": description,
                "instruments": [
                    {
                        "role": item.role,
                        "instrument_id": item.instrument_id,
                        "ratio_numerator": (
                            None
                            if item.ratio_numerator is None
                            else canonical_decimal(item.ratio_numerator)
                        ),
                        "ratio_denominator": (
                            None
                            if item.ratio_denominator is None
                            else canonical_decimal(item.ratio_denominator)
                        ),
                    }
                    for item in instrument_facts
                ],
                "considerations": [
                    {
                        "kind": item.kind,
                        "instrument_id": item.instrument_id,
                        "currency": item.currency,
                        "quantity": (
                            None if item.quantity is None else canonical_decimal(item.quantity)
                        ),
                        "amount": None if item.amount is None else canonical_decimal(item.amount),
                    }
                    for item in consideration_facts
                ],
                "basis_allocations": [
                    {
                        "source_instrument_id": item.source_instrument_id,
                        "destination_instrument_id": item.destination_instrument_id,
                        "source_quantity": canonical_decimal(item.source_quantity),
                        "destination_quantity": canonical_decimal(item.destination_quantity),
                        "source_basis": canonical_decimal(item.source_basis),
                        "destination_basis": canonical_decimal(item.destination_basis),
                        "currency": item.currency,
                    }
                    for item in allocation_facts
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        artifact_id, _ = self.repository.virtual_artifact(
            f"manual://corporate-action-{normalized_type}", provenance_content
        )
        batch_id = self.repository.import_batch(
            artifact_id,
            adapter_name="manual-corporate-action",
            adapter_version="2",
            schema_version="2",
        )
        transaction = Transaction(
            transaction_id,
            account_id,
            normalized_type,
            effective,
            knowledge_time,
            recorded_at,
            description,
            artifact_id,
            batch_id,
            tuple(legs),
        )
        self.repository.add_generalized_corporate_action(
            event_id=event_id,
            action_type=normalized_type,
            effective_at=effective,
            known_at=knowledge_time,
            recorded_at=recorded_at,
            description=description,
            provenance=provenance_content,
            source_artifact_id=artifact_id,
            import_batch_id=batch_id,
            instruments=instrument_facts,
            considerations=consideration_facts,
            transactions=[transaction],
            consequence_type="transform",
            basis_allocations=allocation_facts,
            tax_profile_ref=tax_profile_ref,
            tax_interpretation=tax_interpretation,
        )
        cash_amount = str(
            sum(
                (dec(item.amount) for item in cash_considerations),
                Decimal(0),
            )
        )
        return {
            "event_id": event_id,
            "action_id": event_id,
            "transaction_id": transaction_id,
            "cash_in_lieu_amount": cash_amount if normalized_type == "cash_in_lieu" else None,
        }
