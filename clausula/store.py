"""Public SQLite store facade with local derived-event projections."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

from .adapters.audit import append_audit_event
from .adapters.sqlite import SCHEMA, SCHEMA_VERSION, Store as _SQLiteStore
from .domain import canonical_timestamp, require_uuid


class Store(_SQLiteStore):
    """Canonical local store plus optimized local read projections.

    The base SQLite adapter owns canonical persistence. This public facade adds
    derived attention persistence and bounded batch reads used by application
    services. Batch reads never mutate financial truth and preserve the same
    temporal/dataset conflict semantics as the scalar repository methods.
    """

    @staticmethod
    def _attention_record(row) -> dict[str, Any]:
        payload = json.loads(row["payload_json"])
        return {
            "id": row["id"],
            "fingerprint": row["object_id"],
            "recorded_at": row["occurred_at"],
            **payload,
        }

    def attention_event(self, fingerprint: str) -> dict[str, Any] | None:
        row = self.db.execute(
            """SELECT * FROM audit_events
               WHERE object_type='attention_event' AND object_id=?
               ORDER BY sequence LIMIT 1""",
            (fingerprint,),
        ).fetchone()
        return None if row is None else self._attention_record(row)

    def attention_events(self) -> list[dict[str, Any]]:
        rows = self.db.execute(
            """SELECT * FROM audit_events
               WHERE object_type='attention_event'
               ORDER BY sequence"""
        ).fetchall()
        return [self._attention_record(row) for row in rows]

    def add_attention_event(
        self, fingerprint: str, payload: Mapping[str, Any]
    ) -> dict[str, Any]:
        existing = self.attention_event(fingerprint)
        if existing is not None:
            return existing
        with self.write_transaction():
            existing = self.attention_event(fingerprint)
            if existing is None:
                append_audit_event(
                    self.db,
                    operation="attention.material_change",
                    object_type="attention_event",
                    object_id=fingerprint,
                    payload=dict(payload),
                )
        created = self.attention_event(fingerprint)
        if created is None:
            raise RuntimeError("attention event was not persisted")
        return created

    def transactions_with_legs(
        self,
        account_id: str,
        as_of: str | None = None,
        known_as_of: str | None = None,
    ) -> list[dict[str, Any]]:
        """Materialize an ordered transaction stream with one SQL read.

        This is the batch equivalent of `transactions()` followed by one
        `legs()` query per transaction. Ordering is identical to the scalar
        transaction projection and therefore safe for deterministic replay.
        """

        self.require_account(account_id)
        clauses = ["t.account_id=?"]
        arguments: list[str] = [account_id]
        if as_of is not None:
            clauses.append("t.effective_at<=?")
            arguments.append(canonical_timestamp(as_of))
        knowledge_cutoff = known_as_of if known_as_of is not None else as_of
        if knowledge_cutoff is not None:
            clauses.append("t.known_at<=?")
            arguments.append(canonical_timestamp(knowledge_cutoff))
        rows = self.db.execute(
            """SELECT
                   t.id AS transaction_id,
                   t.account_id AS transaction_account_id,
                   t.type AS transaction_type,
                   t.effective_at,
                   t.known_at,
                   t.recorded_at,
                   t.description,
                   t.artifact_id,
                   t.import_id,
                   t.external_id,
                   l.id AS leg_id,
                   l.account_id AS leg_account_id,
                   l.instrument_id,
                   l.quantity,
                   l.amount,
                   l.currency,
                   l.leg_type
               FROM transactions t
               LEFT JOIN transaction_order o ON o.transaction_id=t.id
               LEFT JOIN legs l ON l.transaction_id=t.id
               WHERE """
            + " AND ".join(clauses)
            + """ ORDER BY t.effective_at,t.known_at,t.recorded_at,
                          COALESCE(o.source_sequence,0),t.id,l.id""",
            arguments,
        ).fetchall()
        result: list[dict[str, Any]] = []
        by_id: dict[str, dict[str, Any]] = {}
        for row in rows:
            transaction_id = row["transaction_id"]
            transaction = by_id.get(transaction_id)
            if transaction is None:
                transaction = {
                    "id": transaction_id,
                    "account_id": row["transaction_account_id"],
                    "type": row["transaction_type"],
                    "effective_at": row["effective_at"],
                    "known_at": row["known_at"],
                    "recorded_at": row["recorded_at"],
                    "description": row["description"],
                    "artifact_id": row["artifact_id"],
                    "import_id": row["import_id"],
                    "external_id": row["external_id"],
                    "legs": [],
                }
                by_id[transaction_id] = transaction
                result.append(transaction)
            if row["leg_id"] is not None:
                transaction["legs"].append(
                    {
                        "id": row["leg_id"],
                        "transaction_id": transaction_id,
                        "account_id": row["leg_account_id"],
                        "instrument_id": row["instrument_id"],
                        "quantity": row["quantity"],
                        "amount": row["amount"],
                        "currency": row["currency"],
                        "leg_type": row["leg_type"],
                    }
                )
        return result

    def transaction_metadata_many(
        self, transaction_ids: Iterable[str]
    ) -> dict[str, dict[str, Any]]:
        """Load FIFO-relevant transaction metadata in a bounded query set."""

        ids = tuple(dict.fromkeys(str(item) for item in transaction_ids))
        for transaction_id in ids:
            require_uuid(transaction_id, "transaction_id")
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        result: dict[str, dict[str, Any]] = {transaction_id: {} for transaction_id in ids}
        for row in self.db.execute(
            f"SELECT * FROM fx_conversions WHERE transaction_id IN ({placeholders})", ids
        ):
            result[row["transaction_id"]]["fx_conversion"] = dict(row)
        for row in self.db.execute(
            f"SELECT * FROM corporate_actions WHERE transaction_id IN ({placeholders})", ids
        ):
            result[row["transaction_id"]]["corporate_action"] = dict(row)
        consequences = self.db.execute(
            f"""SELECT id,event_id,transaction_id FROM corporate_action_account_consequences
                WHERE transaction_id IN ({placeholders})""",
            ids,
        ).fetchall()
        if consequences:
            event_ids = tuple(dict.fromkeys(row["event_id"] for row in consequences))
            event_placeholders = ",".join("?" for _ in event_ids)
            events = {
                row["id"]: dict(row)
                for row in self.db.execute(
                    f"SELECT * FROM corporate_action_events WHERE id IN ({event_placeholders})",
                    event_ids,
                )
            }
            instruments: dict[str, list[dict[str, Any]]] = {item: [] for item in event_ids}
            for row in self.db.execute(
                f"""SELECT * FROM corporate_action_event_instruments
                    WHERE event_id IN ({event_placeholders}) ORDER BY event_id,sequence""",
                event_ids,
            ):
                instruments[row["event_id"]].append(dict(row))
            considerations: dict[str, list[dict[str, Any]]] = {
                item: [] for item in event_ids
            }
            for row in self.db.execute(
                f"""SELECT * FROM corporate_action_considerations
                    WHERE event_id IN ({event_placeholders}) ORDER BY event_id,sequence""",
                event_ids,
            ):
                considerations[row["event_id"]].append(dict(row))
            for consequence in consequences:
                transaction_id = consequence["transaction_id"]
                if transaction_id not in result:
                    continue
                event = events.get(consequence["event_id"])
                if event is None:
                    continue
                action_event = dict(event)
                action_event["instruments"] = instruments.get(
                    consequence["event_id"], []
                )
                action_event["considerations"] = considerations.get(
                    consequence["event_id"], []
                )
                consequence_placeholders = ",".join(["?"])
                action_event["basis_allocations"] = [
                    dict(row)
                    for row in self.db.execute(
                        f"""SELECT * FROM corporate_action_basis_allocations
                            WHERE consequence_id IN ({consequence_placeholders})
                            ORDER BY sequence""",
                        (consequence["id"],),
                    )
                ]
                result[transaction_id]["generalized_corporate_action"] = action_event
        transfers = self.db.execute(
            f"""SELECT * FROM security_transfers
                WHERE source_transaction_id IN ({placeholders})
                   OR destination_transaction_id IN ({placeholders})""",
            (*ids, *ids),
        ).fetchall()
        transfer_ids = [row["id"] for row in transfers]
        allocations: dict[str, list[dict[str, Any]]] = {item: [] for item in transfer_ids}
        if transfer_ids:
            transfer_placeholders = ",".join("?" for _ in transfer_ids)
            for row in self.db.execute(
                f"""SELECT security_transfer_id,source_transaction_id,acquired_at,
                           quantity,basis,currency
                    FROM security_transfer_allocations
                    WHERE security_transfer_id IN ({transfer_placeholders})
                    ORDER BY security_transfer_id,sequence""",
                transfer_ids,
            ):
                allocations[row["security_transfer_id"]].append(
                    {
                        "source_transaction_id": row["source_transaction_id"],
                        "acquired_at": row["acquired_at"],
                        "quantity": row["quantity"],
                        "basis": row["basis"],
                        "currency": row["currency"],
                    }
                )
        for row in transfers:
            transfer = dict(row)
            transfer["allocations"] = allocations[row["id"]]
            for transaction_id in (
                row["source_transaction_id"],
                row["destination_transaction_id"],
            ):
                if transaction_id in result:
                    result[transaction_id]["security_transfer"] = transfer
        return result

    def instrument_details_many(
        self, instrument_ids: Iterable[str]
    ) -> dict[str, dict[str, Any]]:
        ids = tuple(dict.fromkeys(str(item) for item in instrument_ids))
        for instrument_id in ids:
            require_uuid(instrument_id, "instrument_id")
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        rows = self.db.execute(
            f"SELECT * FROM instruments WHERE id IN ({placeholders})", ids
        ).fetchall()
        return {row["id"]: dict(row) for row in rows}

    def market_prices_many(
        self,
        instrument_ids: Iterable[str],
        as_of: str,
        known_as_of: str | None = None,
        dataset_name: str | None = None,
        dataset_version: str | None = None,
    ) -> dict[str, dict[str, Any]]:
        if dataset_version is not None and dataset_name is None:
            raise ValueError("dataset_version requires dataset_name")
        ids = tuple(dict.fromkeys(str(item) for item in instrument_ids))
        for instrument_id in ids:
            require_uuid(instrument_id, "instrument_id")
        if not ids:
            return {}
        observed_cutoff = canonical_timestamp(as_of)
        known_cutoff = canonical_timestamp(known_as_of or as_of)
        placeholders = ",".join("?" for _ in ids)
        clauses = [
            f"p.instrument_id IN ({placeholders})",
            "p.observed_at<=?",
            "p.known_at<=?",
            "p.quality='accepted'",
        ]
        args: list[str] = [*ids, observed_cutoff, known_cutoff]
        if dataset_name is not None:
            clauses.append("d.dataset_name=?")
            args.append(dataset_name)
        if dataset_version is not None:
            clauses.append("d.version=?")
            args.append(dataset_version)
        rows = self.db.execute(
            """SELECT p.*,d.dataset_name,d.version AS dataset_version,d.provider
               FROM market_prices p JOIN market_datasets d ON d.id=p.dataset_id
               WHERE """
            + " AND ".join(clauses)
            + " ORDER BY p.instrument_id,p.observed_at DESC,p.known_at DESC,p.recorded_at DESC,p.id DESC",
            args,
        ).fetchall()
        grouped: dict[str, list[Any]] = {}
        for row in rows:
            grouped.setdefault(row["instrument_id"], []).append(row)
        result: dict[str, dict[str, Any]] = {}
        for instrument_id, candidates in grouped.items():
            latest_observed = candidates[0]["observed_at"]
            latest = [row for row in candidates if row["observed_at"] == latest_observed]
            values = {(row["close"], row["currency"]) for row in latest}
            if len(values) > 1 and (dataset_name is None or dataset_version is None):
                raise ValueError(
                    f"conflicting accepted market prices for {instrument_id} at {latest_observed}; select a dataset version"
                )
            result[instrument_id] = dict(latest[0])
        return result

    def market_fx_rates_many(
        self,
        pairs: Iterable[tuple[str, str]],
        as_of: str,
        known_as_of: str | None = None,
        dataset_name: str | None = None,
        dataset_version: str | None = None,
    ) -> dict[tuple[str, str], dict[str, Any]]:
        if dataset_version is not None and dataset_name is None:
            raise ValueError("dataset_version requires dataset_name")
        normalized = tuple(
            dict.fromkeys((str(left).upper(), str(right).upper()) for left, right in pairs)
        )
        if not normalized:
            return {}
        observed_cutoff = canonical_timestamp(as_of)
        known_cutoff = canonical_timestamp(known_as_of or as_of)
        pair_clauses = ["(r.from_currency=? AND r.to_currency=?)" for _ in normalized]
        clauses = [
            "(" + " OR ".join(pair_clauses) + ")",
            "r.observed_at<=?",
            "r.known_at<=?",
            "r.quality='accepted'",
        ]
        args: list[str] = [value for pair in normalized for value in pair]
        args.extend([observed_cutoff, known_cutoff])
        if dataset_name is not None:
            clauses.append("d.dataset_name=?")
            args.append(dataset_name)
        if dataset_version is not None:
            clauses.append("d.version=?")
            args.append(dataset_version)
        rows = self.db.execute(
            """SELECT r.*,d.dataset_name,d.version AS dataset_version,d.provider
               FROM market_fx_rates r JOIN market_datasets d ON d.id=r.dataset_id
               WHERE """
            + " AND ".join(clauses)
            + " ORDER BY r.from_currency,r.to_currency,r.observed_at DESC,r.known_at DESC,r.recorded_at DESC,r.id DESC",
            args,
        ).fetchall()
        grouped: dict[tuple[str, str], list[Any]] = {}
        for row in rows:
            key = (row["from_currency"], row["to_currency"])
            grouped.setdefault(key, []).append(row)
        result: dict[tuple[str, str], dict[str, Any]] = {}
        for pair, candidates in grouped.items():
            latest_observed = candidates[0]["observed_at"]
            latest = [row for row in candidates if row["observed_at"] == latest_observed]
            values = {row["rate"] for row in latest}
            if len(values) > 1 and (dataset_name is None or dataset_version is None):
                raise ValueError(
                    f"conflicting accepted FX rates for {pair[0]}/{pair[1]} at {latest_observed}; select a dataset version"
                )
            result[pair] = dict(latest[0])
        return result


__all__ = ["SCHEMA", "SCHEMA_VERSION", "Store"]
