from __future__ import annotations

import csv
from decimal import Decimal
import json
from pathlib import Path
from typing import Mapping

from clausula.domain import (
    InstrumentIdentifier,
    ReconciliationResult,
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


class ImportValidationError(ValueError):
    def __init__(self, row_number: int, message: str):
        super().__init__(f"CSV row {row_number}: {message}")
        self.row_number = row_number


class LedgerService:
    def __init__(self, store):
        self.store = store

    def create_account(self, institution: str, name: str) -> str:
        return self.store.create_account(institution, name)

    def resolve_instrument(
        self,
        ticker: str,
        name: str = "",
        asset_type: str = "stock",
        currency: str = "USD",
        *,
        scheme: str = "ticker",
    ) -> str:
        return self.store.instrument(
            InstrumentIdentifier(ticker, scheme), name, asset_type, currency
        )

    def import_csv(self, account_id: str, path: str | Path) -> dict[str, str | int]:
        self.store.require_account(account_id)
        artifact_id, digest = self.store.artifact(path)
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

        inserted = self.store.add_import(
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
        known_at = row.get("known_at") or effective_at
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

    def transactions(self, account_id: str, as_of: str | None = None) -> list[dict]:
        return [
            dict(row) | {"legs": [dict(leg) for leg in self.store.legs(row["id"])]}
            for row in self.store.transactions(account_id, as_of)
        ]

    def state(self, account_id: str, as_of: str | None = None) -> dict:
        positions: dict[str, Decimal] = {}
        cash_by_currency: dict[str, Decimal] = {}
        for transaction in self.store.transactions(account_id, as_of):
            for leg in self.store.legs(transaction["id"]):
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
        provenance_content = json.dumps(
            {"account_id": account_id, "as_of": as_of, "observed": normalized_observed},
            sort_keys=True,
            separators=(",", ":"),
        )
        artifact_id, _ = self.store.virtual_artifact("manual://reconciliation", provenance_content)
        batch_id = self.store.import_batch(
            artifact_id,
            adapter_name="manual-reconciliation",
            adapter_version="1",
            schema_version="1",
        )
        record_id = self.store.record_reconciliation(
            account_id=account_id,
            effective_at=as_of,
            known_at=known_at or now(),
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
        self.store.require_account(account_id)
        if not reason.strip():
            raise ValueError("correction reason is required")
        self._require_amount_conservation(list(legs))
        transaction_id = new_id()
        provenance_content = json.dumps(
            {
                "transaction_id": transaction_id,
                "corrects_transaction_id": corrects_transaction_id,
                "reason": reason,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        artifact_id, _ = self.store.virtual_artifact("manual://ledger-correction", provenance_content)
        batch_id = self.store.import_batch(
            artifact_id,
            adapter_name="manual-correction",
            adapter_version="1",
            schema_version="1",
        )
        recorded_at = now()
        transaction = Transaction(
            transaction_id,
            account_id,
            "correction",
            effective_at,
            known_at or recorded_at,
            recorded_at,
            reason.strip(),
            artifact_id,
            batch_id,
            tuple(legs),
            corrects_transaction_id,
        )
        self.store.add_transaction(transaction)
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
        self.store.require_account(source_account_id)
        self.store.require_account(destination_account_id)
        if source_account_id == destination_account_id:
            raise ValueError("transfer accounts must be distinct")
        transfer_amount = dec(amount)
        transfer_fee = dec(fee)
        if transfer_amount <= 0:
            raise ValueError("transfer amount must be positive")
        if transfer_fee < 0:
            raise ValueError("transfer fee must not be negative")

        transfer_id = new_id()
        recorded_at = now()
        knowledge_time = known_at or recorded_at
        normalized_currency = currency.strip().upper()
        provenance = json.dumps(
            {
                "transfer_id": transfer_id,
                "source_account_id": source_account_id,
                "destination_account_id": destination_account_id,
                "amount": canonical_decimal(transfer_amount),
                "fee": canonical_decimal(transfer_fee),
                "currency": normalized_currency,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        artifact_id, _ = self.store.virtual_artifact("manual://account-transfer", provenance)
        batch_id = self.store.import_batch(
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
            new_id(),
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
            new_id(),
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
        self.store.add_transfer(transfer_id, source_transaction, destination_transaction)
        return {
            "transfer_id": transfer_id,
            "source_transaction_id": source_transaction.id,
            "destination_transaction_id": destination_transaction.id,
        }
