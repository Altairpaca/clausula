"""Public SQLite store facade with local derived-event projections."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .adapters.audit import append_audit_event
from .adapters.sqlite import SCHEMA, SCHEMA_VERSION, Store as _SQLiteStore
from .domain import canonical_timestamp


class Store(_SQLiteStore):
    """Canonical local store plus derived/versioned local control projections.

    Attention events are derived notifications rather than financial facts.
    Execution contracts are versioned operating constraints rather than ledger
    facts. Both reuse the tamper-evident audit ledger so they remain append-only,
    locally reproducible, and included in backup/export integrity evidence.
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

    @staticmethod
    def _execution_contract_record(row) -> dict[str, Any]:
        payload = json.loads(row["payload_json"])
        return {
            "event_id": row["id"],
            "sequence": row["sequence"],
            "contract_id": row["object_id"],
            "recorded_at": row["occurred_at"],
            **payload,
        }

    def execution_contract_versions(
        self,
        portfolio_id: str | None = None,
        contract_id: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = self.db.execute(
            """SELECT * FROM audit_events
               WHERE object_type='execution_contract_version'
               ORDER BY sequence"""
        ).fetchall()
        result = [self._execution_contract_record(row) for row in rows]
        if portfolio_id is not None:
            result = [row for row in result if row["portfolio_id"] == portfolio_id]
        if contract_id is not None:
            result = [row for row in result if row["contract_id"] == contract_id]
        return result

    def execution_contract_version_at(
        self,
        portfolio_id: str,
        as_of: str,
        known_as_of: str | None = None,
    ) -> dict[str, Any] | None:
        effective_cutoff = canonical_timestamp(as_of)
        knowledge_cutoff = canonical_timestamp(known_as_of or as_of)
        candidates = [
            row
            for row in self.execution_contract_versions(portfolio_id=portfolio_id)
            if row["effective_from"] <= effective_cutoff
            and row["known_at"] <= knowledge_cutoff
        ]
        if not candidates:
            return None
        active_contracts = {row["contract_id"] for row in candidates}
        if len(active_contracts) > 1:
            raise ValueError(
                "multiple execution contract identities are active for the portfolio"
            )
        return max(
            candidates,
            key=lambda row: (
                row["effective_from"],
                row["known_at"],
                int(row["version_number"]),
                int(row["sequence"]),
            ),
        )

    def add_execution_contract_version(
        self, contract_id: str, payload: Mapping[str, Any]
    ) -> dict[str, Any]:
        with self.write_transaction():
            event_id = append_audit_event(
                self.db,
                operation="execution.contract_version",
                object_type="execution_contract_version",
                object_id=contract_id,
                payload=dict(payload),
            )
        rows = self.execution_contract_versions(contract_id=contract_id)
        created = next((row for row in reversed(rows) if row["event_id"] == event_id), None)
        if created is None:
            raise RuntimeError("execution contract version was not persisted")
        return created


__all__ = ["SCHEMA", "SCHEMA_VERSION", "Store"]
