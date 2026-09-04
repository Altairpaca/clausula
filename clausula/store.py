"""Public SQLite store facade with local derived-event projections."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .adapters.audit import append_audit_event
from .adapters.sqlite import SCHEMA, SCHEMA_VERSION, Store as _SQLiteStore


class Store(_SQLiteStore):
    """Canonical local store plus derived attention-event persistence.

    Attention events are derived notifications rather than financial facts, so
    they reuse the existing tamper-evident audit ledger instead of introducing
    a second canonical fact table. The event fingerprint is stored as the audit
    object id, which makes exact material changes idempotent while preserving
    the append-only audit chain and canonical export/backup behavior.
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


__all__ = ["SCHEMA", "SCHEMA_VERSION", "Store"]
