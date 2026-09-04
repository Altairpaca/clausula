from __future__ import annotations

import json
from typing import Any, Mapping

from clausula.domain import canonical_timestamp

from .audit import append_audit_event


class EquityCaseProjection:
    """Audit-backed append-only persistence for listed-equity monitoring cases."""

    OBJECT_TYPE = "equity_case_version"

    def __init__(self, repository):
        if not hasattr(repository, "db"):
            raise TypeError("equity-case projection requires local SQLite storage")
        self.repository = repository
        self.db = repository.db

    def __getattr__(self, name: str):
        return getattr(self.repository, name)

    @staticmethod
    def _record(row) -> dict[str, Any]:
        return {
            "event_id": row["id"],
            "sequence": row["sequence"],
            "case_id": row["object_id"],
            "recorded_at": row["occurred_at"],
            **json.loads(row["payload_json"]),
        }

    def versions(
        self,
        *,
        case_id: str | None = None,
        instrument_id: str | None = None,
        portfolio_id: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT * FROM audit_events WHERE object_type=? ORDER BY sequence",
            (self.OBJECT_TYPE,),
        ).fetchall()
        result = [self._record(row) for row in rows]
        if case_id is not None:
            result = [row for row in result if row["case_id"] == case_id]
        if instrument_id is not None:
            result = [row for row in result if row["instrument_id"] == instrument_id]
        if portfolio_id is not None:
            result = [row for row in result if row.get("portfolio_id") == portfolio_id]
        return result

    def active(
        self,
        case_id: str,
        as_of: str,
        known_as_of: str | None = None,
    ) -> dict[str, Any] | None:
        effective = canonical_timestamp(as_of)
        knowledge = canonical_timestamp(known_as_of or as_of)
        candidates = [
            row
            for row in self.versions(case_id=case_id)
            if row["effective_from"] <= effective and row["known_at"] <= knowledge
        ]
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda row: (
                row["effective_from"],
                row["known_at"],
                int(row["version_number"]),
                int(row["sequence"]),
            ),
        )

    def add_version(self, case_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        with self.repository.write_transaction():
            event_id = append_audit_event(
                self.db,
                operation="equity.case_version",
                object_type=self.OBJECT_TYPE,
                object_id=case_id,
                payload=dict(payload),
            )
        created = next(
            row
            for row in reversed(self.versions(case_id=case_id))
            if row["event_id"] == event_id
        )
        return created
