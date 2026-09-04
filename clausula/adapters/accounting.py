from __future__ import annotations

import json
from typing import Any, Mapping

from clausula.domain import canonical_timestamp

from .audit import append_audit_event


class AccountingPolicyProjection:
    """Append-only accounting-policy versions stored in the tamper-evident audit log."""

    OBJECT_TYPE = "accounting_policy_version"

    def __init__(self, repository):
        if not hasattr(repository, "db"):
            raise TypeError("accounting policy projection requires local SQLite storage")
        self.repository = repository
        self.db = repository.db

    def __getattr__(self, name: str):
        return getattr(self.repository, name)

    @staticmethod
    def _record(row) -> dict[str, Any]:
        return {
            "event_id": row["id"],
            "sequence": row["sequence"],
            "policy_id": row["object_id"],
            "recorded_at": row["occurred_at"],
            **json.loads(row["payload_json"]),
        }

    def versions(
        self,
        *,
        policy_id: str | None = None,
        account_id: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT * FROM audit_events WHERE object_type=? ORDER BY sequence",
            (self.OBJECT_TYPE,),
        ).fetchall()
        result = [self._record(row) for row in rows]
        if policy_id is not None:
            result = [row for row in result if row["policy_id"] == policy_id]
        if account_id is not None:
            result = [row for row in result if row["account_id"] == account_id]
        return result

    def active(
        self,
        account_id: str,
        as_of: str,
        known_as_of: str | None = None,
    ) -> dict[str, Any] | None:
        effective = canonical_timestamp(as_of)
        knowledge = canonical_timestamp(known_as_of or as_of)
        candidates = [
            row
            for row in self.versions(account_id=account_id)
            if row["effective_from"] <= effective and row["known_at"] <= knowledge
        ]
        if not candidates:
            return None
        policy_ids = {row["policy_id"] for row in candidates}
        if len(policy_ids) > 1:
            raise ValueError("multiple accounting policy identities are active for the account")
        return max(
            candidates,
            key=lambda row: (
                row["effective_from"],
                row["known_at"],
                int(row["version_number"]),
                int(row["sequence"]),
            ),
        )

    def add_version(self, policy_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        with self.repository.write_transaction():
            event_id = append_audit_event(
                self.db,
                operation="accounting.policy_version",
                object_type=self.OBJECT_TYPE,
                object_id=policy_id,
                payload=dict(payload),
            )
        created = next(
            row
            for row in reversed(self.versions(policy_id=policy_id))
            if row["event_id"] == event_id
        )
        return created
