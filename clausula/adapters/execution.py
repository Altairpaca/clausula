from __future__ import annotations

import json
from typing import Any, Mapping

from clausula.domain import canonical_timestamp

from .audit import append_audit_event


class ExecutionRepositoryProjection:
    """Add execution-contract persistence to the local SQLite repository.

    The projection delegates all canonical repository operations and stores
    versioned execution controls as tamper-evident audit events. Execution
    controls are operating configuration, not ledger facts, so this avoids a
    migration while keeping append-only provenance and backup/audit coverage.
    """

    def __init__(self, repository):
        if not hasattr(repository, "db"):
            raise TypeError("execution repository projection requires local SQLite storage")
        self.repository = repository
        self.db = repository.db

    def __getattr__(self, name: str):
        return getattr(self.repository, name)

    @staticmethod
    def _record(row) -> dict[str, Any]:
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
        result = [self._record(row) for row in rows]
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
        with self.repository.write_transaction():
            event_id = append_audit_event(
                self.db,
                operation="execution.contract_version",
                object_type="execution_contract_version",
                object_id=contract_id,
                payload=dict(payload),
            )
        rows = self.execution_contract_versions(contract_id=contract_id)
        created = next(
            (row for row in reversed(rows) if row["event_id"] == event_id), None
        )
        if created is None:
            raise RuntimeError("execution contract version was not persisted")
        return created
