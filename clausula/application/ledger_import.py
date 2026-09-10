from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import io
from pathlib import Path
from typing import Any, Mapping

from clausula.domain import (
    InstrumentIdentifier,
    Transaction,
    TransactionLeg,
    canonical_decimal,
    canonical_timestamp,
    dec,
    new_id,
    now,
)

from .ledger import CSV_ADAPTER_VERSION, CSV_SCHEMA_VERSION, ImportValidationError
from .ports import CoreRepository


@dataclass(frozen=True)
class CsvImportIssue:
    row: int
    field: str
    code: str
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "row": self.row,
            "field": self.field,
            "code": self.code,
            "message": self.message,
        }


@dataclass(frozen=True)
class ParsedInstrument:
    identifier: str
    scheme: str
    name: str
    asset_type: str
    currency: str

    def as_dict(self) -> dict[str, str]:
        return {
            "identifier": self.identifier,
            "scheme": self.scheme,
            "name": self.name,
            "asset_type": self.asset_type,
            "currency": self.currency,
        }


@dataclass(frozen=True)
class ParsedLeg:
    instrument: ParsedInstrument | None
    quantity: Decimal
    amount: Decimal
    currency: str
    leg_type: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "instrument": None if self.instrument is None else self.instrument.as_dict(),
            "quantity": canonical_decimal(self.quantity),
            "amount": canonical_decimal(self.amount),
            "currency": self.currency,
            "leg_type": self.leg_type,
        }


@dataclass(frozen=True)
class ParsedTransaction:
    row: int
    source_sequence: int
    external_id: str
    type: str
    effective_at: str
    known_at: str
    description: str
    legs: tuple[ParsedLeg, ...]
    defaulted_fields: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "row": self.row,
            "source_sequence": self.source_sequence,
            "external_id": self.external_id,
            "type": self.type,
            "effective_at": self.effective_at,
            "known_at": self.known_at,
            "description": self.description,
            "defaulted_fields": list(self.defaulted_fields),
            "legs": [leg.as_dict() for leg in self.legs],
        }


@dataclass(frozen=True)
class CsvImportPlan:
    source_sha256: str
    source_bytes: int
    checked_at: str
    row_count: int
    transactions: tuple[ParsedTransaction, ...]
    errors: tuple[CsvImportIssue, ...]

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        return {
            "format": "clausula-ledger-csv-preview/v1",
            "ok": self.ok,
            "source_sha256": self.source_sha256,
            "source_bytes": self.source_bytes,
            "checked_at": self.checked_at,
            "row_count": self.row_count,
            "valid_rows": len(self.transactions),
            "errors": [issue.as_dict() for issue in self.errors],
            "transactions": [transaction.as_dict() for transaction in self.transactions],
        }


class _RowError(ValueError):
    def __init__(self, field: str, code: str, message: str):
        super().__init__(message)
        self.field = field
        self.code = code


def _defaulted(row: Mapping[str, str | None], field: str) -> bool:
    value = row.get(field)
    return value is None or value == ""


def _nonnegative(row: Mapping[str, str | None], field: str) -> Decimal:
    raw = row.get(field)
    try:
        value = dec(raw.strip() if raw and raw.strip() else "0")
    except (TypeError, ValueError) as exc:
        raise _RowError(field, "invalid_decimal", str(exc)) from exc
    if value < 0:
        raise _RowError(field, "negative_value", f"{field} must not be negative")
    return value


def _required_text(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise _RowError(field, "empty_value", f"{field} cannot be empty")
    return normalized


def _instrument(row: Mapping[str, str | None], currency: str) -> ParsedInstrument | None:
    raw_ticker = row.get("ticker")
    raw_instrument = row.get("instrument")
    ticker = raw_ticker if raw_ticker not in (None, "") else raw_instrument
    if ticker in (None, ""):
        ticker = "CASH"
    ticker = _required_text(str(ticker), "ticker")
    if ticker.upper() == "CASH":
        return None

    raw_scheme = row.get("identifier_scheme")
    scheme = (
        "ticker"
        if raw_scheme in (None, "")
        else _required_text(str(raw_scheme), "identifier_scheme")
    )
    try:
        identifier = InstrumentIdentifier(ticker, scheme)
    except ValueError as exc:
        raise _RowError("ticker", "invalid_instrument", str(exc)) from exc

    raw_asset_type = row.get("asset_type")
    asset_type = (
        "stock"
        if raw_asset_type in (None, "")
        else _required_text(str(raw_asset_type), "asset_type").lower()
    )
    name = (row.get("instrument_name") or "").strip()
    return ParsedInstrument(
        identifier.value, identifier.scheme, name, asset_type, currency
    )


def _conserve(legs: list[ParsedLeg]) -> None:
    totals: dict[str, Decimal] = {}
    for leg in legs:
        totals[leg.currency] = totals.get(leg.currency, Decimal(0)) + leg.amount
    unbalanced = {currency: value for currency, value in totals.items() if value != 0}
    if unbalanced:
        raise _RowError(
            "amount",
            "unbalanced_transaction",
            f"transaction amounts do not conserve by currency: {unbalanced}",
        )


def _parse_row(
    row: Mapping[str, str | None],
    row_number: int,
    recorded_at: str,
    external_id: str,
) -> ParsedTransaction:
    defaults: list[str] = []

    raw_type = row.get("type")
    if raw_type in (None, ""):
        defaults.append("type")
        transaction_type = "buy"
    else:
        transaction_type = _required_text(str(raw_type), "type").lower()

    raw_effective = row.get("effective_at")
    if raw_effective in (None, ""):
        raw_effective = row.get("date")
        if raw_effective in (None, ""):
            defaults.append("effective_at")
            raw_effective = recorded_at
    try:
        effective_at = canonical_timestamp(str(raw_effective))
    except ValueError as exc:
        raise _RowError("effective_at", "invalid_timestamp", str(exc)) from exc

    raw_known = row.get("known_at")
    if raw_known in (None, ""):
        defaults.append("known_at")
        raw_known = recorded_at
    try:
        known_at = canonical_timestamp(str(raw_known))
    except ValueError as exc:
        raise _RowError("known_at", "invalid_timestamp", str(exc)) from exc
    if known_at > recorded_at:
        raise _RowError(
            "known_at", "future_knowledge", "known_at cannot be after recorded_at"
        )

    raw_currency = row.get("currency")
    if raw_currency in (None, ""):
        defaults.append("currency")
        currency = "USD"
    else:
        currency = _required_text(str(raw_currency), "currency").upper()

    quantity = _nonnegative(row, "quantity")
    gross = _nonnegative(row, "amount")
    fee = _nonnegative(row, "fee")
    for field in ("quantity", "amount", "fee"):
        if _defaulted(row, field):
            defaults.append(field)

    instrument = _instrument(row, currency)
    if row.get("ticker") in (None, "") and row.get("instrument") in (None, ""):
        defaults.append("ticker")
    if instrument is not None:
        if row.get("identifier_scheme") in (None, ""):
            defaults.append("identifier_scheme")
        if row.get("asset_type") in (None, ""):
            defaults.append("asset_type")

    legs: list[ParsedLeg] = []
    if transaction_type in {"buy", "sell"}:
        if instrument is None:
            raise _RowError(
                "ticker", "instrument_required", f"{transaction_type} requires an instrument"
            )
        if quantity <= 0:
            raise _RowError(
                "quantity",
                "positive_required",
                f"{transaction_type} quantity must be positive",
            )
        if transaction_type == "buy":
            legs.append(ParsedLeg(instrument, quantity, gross, currency, "position"))
            cash_amount = -(gross + fee)
        else:
            legs.append(
                ParsedLeg(instrument, -quantity, -gross, currency, "position")
            )
            cash_amount = gross - fee
        legs.append(ParsedLeg(None, Decimal(0), cash_amount, currency, "cash"))
        if fee:
            legs.append(ParsedLeg(None, Decimal(0), fee, currency, "fee"))
    elif transaction_type in {"transfer_in", "transfer_out"}:
        direction = Decimal(1) if transaction_type == "transfer_in" else Decimal(-1)
        if instrument is not None:
            if quantity <= 0:
                raise _RowError(
                    "quantity",
                    "positive_required",
                    "instrument transfer quantity must be positive",
                )
            legs.append(
                ParsedLeg(
                    instrument,
                    direction * quantity,
                    Decimal(0),
                    currency,
                    "position",
                )
            )
            if fee:
                legs.append(ParsedLeg(None, Decimal(0), -fee, currency, "cash"))
                legs.append(ParsedLeg(None, Decimal(0), fee, currency, "fee"))
        else:
            cash_amount = gross - fee if direction > 0 else -(gross + fee)
            legs.append(ParsedLeg(None, Decimal(0), cash_amount, currency, "cash"))
            legs.append(
                ParsedLeg(
                    None, Decimal(0), -direction * gross, currency, "external"
                )
            )
            if fee:
                legs.append(ParsedLeg(None, Decimal(0), fee, currency, "fee"))
    elif transaction_type in {"deposit", "withdrawal"}:
        direction = Decimal(1) if transaction_type == "deposit" else Decimal(-1)
        cash_amount = gross - fee if direction > 0 else -(gross + fee)
        legs.append(ParsedLeg(None, Decimal(0), cash_amount, currency, "cash"))
        legs.append(
            ParsedLeg(None, Decimal(0), -direction * gross, currency, "external")
        )
        if fee:
            legs.append(ParsedLeg(None, Decimal(0), fee, currency, "fee"))
    elif transaction_type in {"dividend", "interest"}:
        legs.append(ParsedLeg(None, Decimal(0), gross - fee, currency, "cash"))
        legs.append(
            ParsedLeg(instrument, Decimal(0), -gross, currency, "income")
        )
        if fee:
            legs.append(ParsedLeg(None, Decimal(0), fee, currency, "fee"))
    elif transaction_type in {"fee", "tax"}:
        if gross <= 0:
            raise _RowError(
                "amount",
                "positive_required",
                f"{transaction_type} amount must be positive",
            )
        legs.append(ParsedLeg(None, Decimal(0), -gross, currency, "cash"))
        legs.append(
            ParsedLeg(instrument, Decimal(0), gross, currency, transaction_type)
        )
    else:
        raise _RowError(
            "type",
            "unsupported_type",
            f"unsupported transaction type: {transaction_type}",
        )

    _conserve(legs)
    description = (row.get("description") or f"CSV row {row_number}").strip()
    if row.get("description") in (None, ""):
        defaults.append("description")
    return ParsedTransaction(
        row=row_number,
        source_sequence=row_number - 1,
        external_id=external_id,
        type=transaction_type,
        effective_at=effective_at,
        known_at=known_at,
        description=description,
        legs=tuple(legs),
        defaulted_fields=tuple(dict.fromkeys(defaults)),
    )


def parse_csv_content(
    content: bytes | str, *, recorded_at: str | None = None
) -> CsvImportPlan:
    raw = content.encode("utf-8") if isinstance(content, str) else bytes(content)
    digest = hashlib.sha256(raw).hexdigest()
    checked_at = canonical_timestamp(recorded_at) if recorded_at is not None else now()
    errors: list[CsvImportIssue] = []
    transactions: list[ParsedTransaction] = []
    external_ids: set[str] = set()
    row_count = 0

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        return CsvImportPlan(
            digest,
            len(raw),
            checked_at,
            0,
            (),
            (CsvImportIssue(1, "file", "invalid_encoding", str(exc)),),
        )

    reader = csv.DictReader(io.StringIO(text, newline=""))
    if reader.fieldnames is None:
        return CsvImportPlan(
            digest,
            len(raw),
            checked_at,
            0,
            (),
            (CsvImportIssue(1, "header", "missing_header", "header row is required"),),
        )

    for row_number, row in enumerate(reader, 2):
        row_count += 1
        raw_id = row.get("id")
        external_id = (
            str(row_number - 1) if raw_id in (None, "") else str(raw_id).strip()
        )
        if not external_id:
            errors.append(
                CsvImportIssue(row_number, "id", "empty_value", "id cannot be empty")
            )
            continue
        if external_id in external_ids:
            errors.append(
                CsvImportIssue(
                    row_number,
                    "id",
                    "duplicate_id",
                    f"duplicate id {external_id!r}",
                )
            )
            continue
        external_ids.add(external_id)
        try:
            transactions.append(
                _parse_row(row, row_number, checked_at, external_id)
            )
        except _RowError as exc:
            errors.append(CsvImportIssue(row_number, exc.field, exc.code, str(exc)))
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(
                CsvImportIssue(row_number, "row", "invalid_row", str(exc))
            )

    return CsvImportPlan(
        digest,
        len(raw),
        checked_at,
        row_count,
        tuple(transactions),
        tuple(errors),
    )


def parse_csv_import(
    path: str | Path, *, recorded_at: str | None = None
) -> CsvImportPlan:
    return parse_csv_content(Path(path).read_bytes(), recorded_at=recorded_at)


def preview_csv_import(
    repository: CoreRepository,
    account_id: str,
    path: str | Path,
) -> dict[str, Any]:
    repository.require_account(account_id)
    return parse_csv_import(path).as_dict()


def _resolve_instruments(
    repository: CoreRepository,
    plan: CsvImportPlan,
) -> dict[ParsedInstrument, str]:
    resolved: dict[ParsedInstrument, str] = {}
    for transaction in plan.transactions:
        for leg in transaction.legs:
            instrument = leg.instrument
            if instrument is None or instrument in resolved:
                continue
            resolved[instrument] = repository.instrument(
                InstrumentIdentifier(instrument.identifier, instrument.scheme),
                instrument.name,
                instrument.asset_type,
                instrument.currency,
            )
    return resolved


def commit_csv_import(
    repository: CoreRepository,
    account_id: str,
    path: str | Path,
) -> dict[str, str | int]:
    repository.require_account(account_id)
    plan = parse_csv_import(path)
    if plan.errors:
        first = plan.errors[0]
        raise ImportValidationError(first.row, f"{first.field}: {first.message}")

    source_path = Path(path)
    if hashlib.sha256(source_path.read_bytes()).hexdigest() != plan.source_sha256:
        raise ImportValidationError(
            1, "source changed while import was being validated"
        )

    with repository.write_transaction():
        repository.require_account(account_id)
        artifact_id, digest = repository.artifact(source_path)
        if digest != plan.source_sha256:
            raise ImportValidationError(1, "source changed before artifact capture")
        batch_id = new_id()
        instrument_ids = _resolve_instruments(repository, plan)
        entries: list[tuple[Transaction, str]] = []
        for parsed in plan.transactions:
            legs = tuple(
                TransactionLeg(
                    account_id,
                    None
                    if leg.instrument is None
                    else instrument_ids[leg.instrument],
                    leg.quantity,
                    leg.amount,
                    leg.currency,
                    leg.leg_type,
                )
                for leg in parsed.legs
            )
            entries.append(
                (
                    Transaction(
                        new_id(),
                        account_id,
                        parsed.type,
                        parsed.effective_at,
                        parsed.known_at,
                        plan.checked_at,
                        parsed.description,
                        artifact_id,
                        batch_id,
                        legs,
                        source_sequence=parsed.source_sequence,
                    ),
                    parsed.external_id,
                )
            )
        inserted = repository.add_import(
            batch_id,
            artifact_id,
            entries,
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
