from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from typing import Any

from .adapters.audit import append_audit_event
from .domain import Transaction, canonical_decimal, new_id
from .store import Store as _BaseStore


class Store(_BaseStore):
    """Public Store hardened for account-scoped external import identity.

    `imported_rows` remains the provenance relation between a source artifact and
    an already-canonical transaction. `transactions.external_id` is populated
    for new imported events as defense in depth. Historical rows whose
    transaction column is NULL remain discoverable through `imported_rows`.
    """

    def instrument_id_for_identifier(self, scheme: str, identifier: str) -> str | None:
        normalized_scheme = str(scheme).strip().lower()
        normalized_identifier = str(identifier).strip()
        if not normalized_scheme or not normalized_identifier:
            raise ValueError("instrument scheme and identifier are required")
        row = self.db.execute(
            """SELECT instrument_id FROM instrument_identifiers
               WHERE scheme=? AND identifier=?""",
            (normalized_scheme, normalized_identifier),
        ).fetchone()
        return None if row is None else str(row["instrument_id"])

    def imported_external_transactions(
        self, account_id: str, external_ids: Iterable[str]
    ) -> dict[str, list[dict[str, Any]]]:
        self.require_account(account_id)
        ids = tuple(dict.fromkeys(str(value).strip() for value in external_ids))
        if any(not value for value in ids):
            raise ValueError("external_id cannot be empty")
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        rows = self.db.execute(
            f"""WITH mapped AS (
                    SELECT DISTINCT external_id,transaction_id
                    FROM imported_rows
                    WHERE account_id=? AND external_id IN ({placeholders})
                )
                SELECT m.external_id,
                       t.id AS transaction_id,
                       t.type AS transaction_type,
                       t.effective_at,
                       t.known_at,
                       t.recorded_at,
                       t.description,
                       t.artifact_id,
                       t.import_id,
                       t.external_id AS transaction_external_id,
                       l.id AS leg_id,
                       l.instrument_id,
                       l.quantity,
                       l.amount,
                       l.currency,
                       l.leg_type
                FROM mapped m
                JOIN transactions t ON t.id=m.transaction_id
                LEFT JOIN legs l ON l.transaction_id=t.id
                ORDER BY m.external_id,t.recorded_at,t.id,l.id""",
            (account_id, *ids),
        ).fetchall()
        grouped: dict[str, list[dict[str, Any]]] = {value: [] for value in ids}
        by_key: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            external_id = str(row["external_id"])
            key = (external_id, str(row["transaction_id"]))
            transaction = by_key.get(key)
            if transaction is None:
                transaction = {
                    "id": str(row["transaction_id"]),
                    "external_id": external_id,
                    "type": str(row["transaction_type"]),
                    "effective_at": str(row["effective_at"]),
                    "known_at": str(row["known_at"]),
                    "recorded_at": str(row["recorded_at"]),
                    "description": str(row["description"] or ""),
                    "artifact_id": str(row["artifact_id"]),
                    "import_id": str(row["import_id"]),
                    "transaction_external_id": row["transaction_external_id"],
                    "legs": [],
                }
                by_key[key] = transaction
                grouped.setdefault(external_id, []).append(transaction)
            if row["leg_id"] is not None:
                transaction["legs"].append(
                    {
                        "instrument_id": row["instrument_id"],
                        "quantity": str(row["quantity"]),
                        "amount": str(row["amount"]),
                        "currency": str(row["currency"]),
                        "leg_type": str(row["leg_type"]),
                    }
                )
        return grouped

    @staticmethod
    def _domain_import_semantic(transaction: Transaction) -> tuple[Any, ...]:
        legs = sorted(
            (
                "cash:" if leg.instrument_id is None else f"id:{leg.instrument_id}",
                canonical_decimal(leg.quantity),
                canonical_decimal(leg.amount),
                leg.currency,
                leg.leg_type,
            )
            for leg in transaction.legs
        )
        return transaction.type, transaction.effective_at, tuple(legs)

    @staticmethod
    def _stored_import_semantic(transaction: dict[str, Any]) -> tuple[Any, ...]:
        legs = sorted(
            (
                "cash:"
                if leg["instrument_id"] is None
                else f"id:{leg['instrument_id']}",
                canonical_decimal(Decimal(str(leg["quantity"]))),
                canonical_decimal(Decimal(str(leg["amount"]))),
                str(leg["currency"]).upper(),
                str(leg["leg_type"]).lower(),
            )
            for leg in transaction.get("legs", ())
        )
        return str(transaction["type"]).lower(), str(transaction["effective_at"]), tuple(legs)

    def _classify_import_identity(
        self, transaction: Transaction, external_id: str
    ) -> tuple[str, str | None]:
        candidates = self.imported_external_transactions(
            transaction.account_id, (external_id,)
        ).get(external_id, [])
        if not candidates:
            return "new", None
        expected = self._domain_import_semantic(transaction)
        exact = [
            candidate
            for candidate in candidates
            if self._stored_import_semantic(candidate) == expected
        ]
        if len(exact) == len(candidates):
            return "duplicate_exact", str(exact[0]["id"])
        raise ValueError(
            f"external_id conflict for account {transaction.account_id}: {external_id!r} "
            "already identifies different canonical transaction semantics"
        )

    def _insert_transaction(
        self, transaction: Transaction, external_id: str | None = None
    ) -> None:
        self.require_account(transaction.account_id)
        artifact = self.db.execute(
            "SELECT 1 FROM artifacts WHERE id=?", (transaction.source_artifact_id,)
        ).fetchone()
        batch = self.db.execute(
            "SELECT artifact_id FROM imports WHERE id=?", (transaction.import_batch_id,)
        ).fetchone()
        if artifact is None or batch is None:
            raise ValueError(
                "transaction provenance must reference an existing artifact and import batch"
            )
        if batch["artifact_id"] != transaction.source_artifact_id:
            raise ValueError("transaction artifact must match its import batch artifact")
        if transaction.corrects_transaction_id is not None:
            corrected = self.db.execute(
                "SELECT account_id FROM transactions WHERE id=?",
                (transaction.corrects_transaction_id,),
            ).fetchone()
            if corrected is None or corrected["account_id"] != transaction.account_id:
                raise ValueError("corrected transaction must exist in the same account")
        normalized_external_id = None
        if external_id is not None:
            normalized_external_id = str(external_id).strip()
            if not normalized_external_id:
                raise ValueError("external_id cannot be empty")

        self.db.execute(
            """INSERT INTO transactions(
                   id,account_id,type,effective_at,known_at,recorded_at,description,
                   artifact_id,import_id,external_id
               ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                transaction.id,
                transaction.account_id,
                transaction.type,
                transaction.effective_at,
                transaction.known_at,
                transaction.recorded_at,
                transaction.description,
                transaction.source_artifact_id,
                transaction.import_batch_id,
                normalized_external_id,
            ),
        )
        self.db.execute(
            "INSERT INTO transaction_order VALUES(?,?)",
            (transaction.id, transaction.source_sequence),
        )
        for leg in transaction.legs:
            self.require_account(leg.account_id)
            if leg.instrument_id is not None and self.db.execute(
                "SELECT 1 FROM instruments WHERE id=?", (leg.instrument_id,)
            ).fetchone() is None:
                raise KeyError(f"unknown instrument: {leg.instrument_id}")
            self.db.execute(
                """INSERT INTO legs(
                       transaction_id,account_id,instrument_id,quantity,amount,currency,leg_type
                   ) VALUES(?,?,?,?,?,?,?)""",
                (
                    transaction.id,
                    leg.account_id,
                    leg.instrument_id,
                    canonical_decimal(leg.quantity),
                    canonical_decimal(leg.amount),
                    leg.currency,
                    leg.leg_type,
                ),
            )
        if transaction.type == "correction":
            self.db.execute(
                "INSERT INTO corrections VALUES(?,?,?)",
                (
                    transaction.id,
                    transaction.corrects_transaction_id,
                    transaction.description,
                ),
            )

    def add_import(
        self,
        batch_id: str,
        artifact_id: str,
        entries: Iterable[tuple[Transaction, str]],
        *,
        adapter_name: str,
        adapter_version: str,
        schema_version: str,
    ) -> int:
        materialized = list(entries)
        pending: list[tuple[Transaction, str]] = []
        duplicates: list[tuple[Transaction, str, str]] = []

        # Reconcile while the caller's write transaction is active. The daemon
        # serializes writes; this second check protects against stale previews.
        for transaction, raw_external_id in materialized:
            external_id = str(raw_external_id).strip()
            if not external_id:
                raise ValueError("external_id cannot be empty")
            status, existing_transaction_id = self._classify_import_identity(
                transaction, external_id
            )
            if status == "new":
                pending.append((transaction, external_id))
            else:
                assert existing_transaction_id is not None
                duplicates.append(
                    (transaction, external_id, existing_transaction_id)
                )

        with self.db:
            self._insert_import_batch(
                batch_id,
                artifact_id,
                adapter_name,
                adapter_version,
                schema_version,
                len(materialized),
                len(pending),
            )
            # A changed export may contain an exact event already accepted from
            # another artifact. Preserve the new artifact/event provenance edge
            # without creating a second economic transaction.
            for transaction, external_id, existing_transaction_id in duplicates:
                self.db.execute(
                    """INSERT OR IGNORE INTO imported_rows(
                           id,account_id,artifact_id,external_id,transaction_id
                       ) VALUES(?,?,?,?,?)""",
                    (
                        new_id(),
                        transaction.account_id,
                        artifact_id,
                        external_id,
                        existing_transaction_id,
                    ),
                )
            for transaction, external_id in pending:
                self._insert_transaction(transaction, external_id)
                self.db.execute(
                    "INSERT INTO imported_rows VALUES(?,?,?,?,?)",
                    (
                        new_id(),
                        transaction.account_id,
                        artifact_id,
                        external_id,
                        transaction.id,
                    ),
                )
                self._audit_transaction(transaction)
            append_audit_event(
                self.db,
                operation="import.create",
                object_type="import_batch",
                object_id=batch_id,
                payload={
                    "artifact_id": artifact_id,
                    "adapter_name": adapter_name,
                    "adapter_version": adapter_version,
                    "schema_version": schema_version,
                    "input_rows": len(materialized),
                    "inserted_rows": len(pending),
                    "duplicate_exact_rows": len(duplicates),
                },
            )
        return len(pending)

    def add_transaction(
        self, transaction: Transaction, external_id: str | None = None
    ) -> bool:
        if external_id is None:
            return super().add_transaction(transaction, external_id=None)
        normalized_external_id = str(external_id).strip()
        if not normalized_external_id:
            raise ValueError("external_id cannot be empty")
        status, _ = self._classify_import_identity(
            transaction, normalized_external_id
        )
        if status == "duplicate_exact":
            return False
        with self.db:
            self._insert_transaction(transaction, normalized_external_id)
            self.db.execute(
                "INSERT INTO imported_rows VALUES(?,?,?,?,?)",
                (
                    new_id(),
                    transaction.account_id,
                    transaction.source_artifact_id,
                    normalized_external_id,
                    transaction.id,
                ),
            )
            self._audit_transaction(transaction)
        return True


__all__ = ["Store"]
