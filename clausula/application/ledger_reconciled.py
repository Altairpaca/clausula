from __future__ import annotations

from decimal import Decimal
import hashlib
from pathlib import Path
from typing import Any, Iterable, Mapping

from clausula.domain import Transaction, TransactionLeg, canonical_decimal, new_id

from .ledger import CSV_ADAPTER_VERSION, CSV_SCHEMA_VERSION, ImportValidationError
from .ledger_fast import LedgerService as _FastLedgerService
from .ledger_import import (
    CsvImportIssue,
    CsvImportPlan,
    ParsedInstrument,
    ParsedTransaction,
    _resolve_instruments,
    parse_csv_import,
)
from .ports import CoreRepository


IMPORT_NEW = "new"
IMPORT_DUPLICATE_EXACT = "duplicate_exact"
IMPORT_CONFLICT = "conflict_external_id"


def _generic_existing_transactions(
    repository: CoreRepository,
    account_id: str,
    external_ids: Iterable[str],
) -> dict[str, list[dict[str, Any]]]:
    """Portable fallback over existing public provenance projections.

    The optimized public Store exposes `imported_external_transactions()` and
    avoids this catalog walk. The fallback keeps third-party repositories able
    to participate in read-only reconciliation without acquiring a SQLite
    dependency in the application layer.
    """

    wanted = set(external_ids)
    result: dict[str, list[dict[str, Any]]] = {value: [] for value in wanted}
    seen: set[tuple[str, str]] = set()
    catalog = repository.rebuild_catalog()
    for item in catalog.get("imports", ()):
        if account_id not in item.get("account_ids", ()):
            continue
        artifact_id = item.get("artifact_id")
        if not artifact_id:
            continue
        mapping = repository.imported_transaction_mapping(account_id, artifact_id)
        for external_id, transaction_id in mapping.items():
            if external_id not in wanted or (external_id, transaction_id) in seen:
                continue
            seen.add((external_id, transaction_id))
            transaction = repository.transaction(transaction_id)
            if transaction is None:
                continue
            normalized = dict(transaction)
            normalized["id"] = transaction_id
            normalized["external_id"] = external_id
            normalized["legs"] = [
                dict(leg) for leg in repository.legs(transaction_id)
            ]
            result.setdefault(external_id, []).append(normalized)
    return result


def _load_existing_transactions(
    repository: CoreRepository,
    account_id: str,
    external_ids: Iterable[str],
) -> dict[str, list[dict[str, Any]]]:
    optimized = getattr(repository, "imported_external_transactions", None)
    if optimized is not None:
        loaded = optimized(account_id, external_ids)
        return {
            str(external_id): [dict(item) for item in candidates]
            for external_id, candidates in loaded.items()
        }
    return _generic_existing_transactions(repository, account_id, external_ids)


def _parsed_instrument_key(
    repository: CoreRepository, instrument: ParsedInstrument | None
) -> str:
    if instrument is None:
        return "cash:"
    resolver = getattr(repository, "instrument_id_for_identifier", None)
    if resolver is not None:
        instrument_id = resolver(instrument.scheme, instrument.identifier)
        if instrument_id is not None:
            return f"id:{instrument_id}"
    return (
        "external:"
        f"{instrument.scheme.strip().lower()}:{instrument.identifier.strip()}"
    )


def _stored_instrument_key(
    repository: CoreRepository, instrument_id: str | None
) -> str:
    if instrument_id is None:
        return "cash:"
    if getattr(repository, "instrument_id_for_identifier", None) is not None:
        # Public Store reconciliation uses canonical UUID identity, so aliases
        # of the same security do not manufacture a conflict.
        return f"id:{instrument_id}"
    details = repository.instrument_details(str(instrument_id))
    return (
        "external:"
        f"{str(details['scheme']).strip().lower()}:{str(details['identifier']).strip()}"
    )


def _parsed_semantic(
    repository: CoreRepository, transaction: ParsedTransaction
) -> tuple[Any, ...]:
    legs = sorted(
        (
            _parsed_instrument_key(repository, leg.instrument),
            canonical_decimal(leg.quantity),
            canonical_decimal(leg.amount),
            leg.currency.upper(),
            leg.leg_type.lower(),
        )
        for leg in transaction.legs
    )
    return (
        transaction.type,
        transaction.effective_at,
        transaction.known_at,
        tuple(legs),
    )


def _stored_semantic(
    repository: CoreRepository, transaction: Mapping[str, Any]
) -> tuple[Any, ...]:
    legs = sorted(
        (
            _stored_instrument_key(repository, leg.get("instrument_id")),
            canonical_decimal(Decimal(str(leg["quantity"]))),
            canonical_decimal(Decimal(str(leg["amount"]))),
            str(leg["currency"]).upper(),
            str(leg["leg_type"]).lower(),
        )
        for leg in transaction.get("legs", ())
    )
    return (
        str(transaction["type"]).lower(),
        str(transaction["effective_at"]),
        str(transaction["known_at"]),
        tuple(legs),
    )


def reconcile_csv_plan(
    repository: CoreRepository,
    account_id: str,
    plan: CsvImportPlan,
) -> dict[str, Any]:
    repository.require_account(account_id)
    existing = _load_existing_transactions(
        repository,
        account_id,
        (transaction.external_id for transaction in plan.transactions),
    )
    counts = {
        IMPORT_NEW: 0,
        IMPORT_DUPLICATE_EXACT: 0,
        IMPORT_CONFLICT: 0,
    }
    statuses: dict[str, tuple[str, list[str]]] = {}
    conflict_issues: list[CsvImportIssue] = []

    for transaction in plan.transactions:
        candidates = existing.get(transaction.external_id, [])
        candidate_ids = [str(item["id"]) for item in candidates]
        if not candidates:
            status = IMPORT_NEW
        else:
            expected = _parsed_semantic(repository, transaction)
            exact = [
                candidate
                for candidate in candidates
                if _stored_semantic(repository, candidate) == expected
            ]
            if len(exact) == len(candidates):
                status = IMPORT_DUPLICATE_EXACT
            else:
                status = IMPORT_CONFLICT
                conflict_issues.append(
                    CsvImportIssue(
                        transaction.row,
                        "id",
                        IMPORT_CONFLICT,
                        f"external id {transaction.external_id!r} already identifies different canonical transaction semantics",
                    )
                )
        counts[status] += 1
        statuses[transaction.external_id] = (status, candidate_ids)

    payload = plan.as_dict()
    payload["reconciliation"] = {
        "account_id": account_id,
        **counts,
    }
    payload["errors"] = [
        *payload["errors"],
        *(issue.as_dict() for issue in conflict_issues),
    ]
    payload["ok"] = not payload["errors"]
    payload["transactions"] = [
        {
            **transaction.as_dict(),
            "import_status": statuses[transaction.external_id][0],
            "existing_transaction_ids": statuses[transaction.external_id][1],
        }
        for transaction in plan.transactions
    ]
    return payload


def _first_error(payload: Mapping[str, Any]) -> ImportValidationError:
    issue = payload["errors"][0]
    return ImportValidationError(
        int(issue["row"]), f"{issue['field']}: {issue['message']}"
    )


def commit_reconciled_csv_import(
    repository: CoreRepository,
    account_id: str,
    path: str | Path,
) -> dict[str, str | int]:
    repository.require_account(account_id)
    source_path = Path(path)
    plan = parse_csv_import(source_path)
    preview = reconcile_csv_plan(repository, account_id, plan)
    if not preview["ok"]:
        raise _first_error(preview)

    # A repository that can classify account-scoped imported events is required
    # to safely accept a changed artifact containing old IDs. Purely new files
    # remain compatible with the portable baseline repository contract.
    if (
        preview["reconciliation"][IMPORT_DUPLICATE_EXACT]
        and getattr(repository, "imported_external_transactions", None) is None
    ):
        raise ImportValidationError(
            1,
            "repository cannot safely preserve cross-artifact duplicate provenance",
        )

    if hashlib.sha256(source_path.read_bytes()).hexdigest() != plan.source_sha256:
        raise ImportValidationError(
            1, "source changed after reconciliation and before import"
        )

    with repository.write_transaction():
        # Reconcile again inside the write boundary. This is both a stale-preview
        # guard and the last chance to fail before artifact/instrument publication.
        inside = reconcile_csv_plan(repository, account_id, plan)
        if not inside["ok"]:
            raise _first_error(inside)
        if hashlib.sha256(source_path.read_bytes()).hexdigest() != plan.source_sha256:
            raise ImportValidationError(
                1, "source changed while reconciled import was being committed"
            )

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


class LedgerService(_FastLedgerService):
    """Ledger service with account-aware import reconciliation."""

    def preview_csv(self, account_id: str, path: str | Path) -> dict[str, Any]:
        return reconcile_csv_plan(
            self.repository, account_id, parse_csv_import(path)
        )

    def import_csv(
        self, account_id: str, path: str | Path
    ) -> dict[str, str | int]:
        return commit_reconciled_csv_import(self.repository, account_id, path)


__all__ = [
    "IMPORT_CONFLICT",
    "IMPORT_DUPLICATE_EXACT",
    "IMPORT_NEW",
    "LedgerService",
    "commit_reconciled_csv_import",
    "reconcile_csv_plan",
]
