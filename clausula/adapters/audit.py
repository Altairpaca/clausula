from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any, Mapping

from clausula.domain import new_id, now


GENESIS_HASH = "0" * 64


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _event_hash(event: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(event).encode("utf-8")).hexdigest()


def append_audit_event(
    connection: sqlite3.Connection,
    *,
    operation: str,
    object_type: str,
    object_id: str,
    payload: Mapping[str, Any] | None = None,
    actor_type: str = "service",
    actor_id: str = "local-user",
) -> str:
    previous = connection.execute(
        "SELECT sequence,event_hash FROM audit_events ORDER BY sequence DESC LIMIT 1"
    ).fetchone()
    sequence = 1 if previous is None else previous["sequence"] + 1
    previous_hash = GENESIS_HASH if previous is None else previous["event_hash"]
    event_id = new_id()
    occurred_at = now()
    payload_json = canonical_json(payload or {})
    material = {
        "sequence": sequence,
        "id": event_id,
        "occurred_at": occurred_at,
        "actor_type": actor_type,
        "actor_id": actor_id,
        "operation": operation,
        "object_type": object_type,
        "object_id": object_id,
        "payload_json": payload_json,
        "previous_hash": previous_hash,
    }
    event_hash = _event_hash(material)
    connection.execute(
        "INSERT INTO audit_events VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            sequence,
            event_id,
            occurred_at,
            actor_type,
            actor_id,
            operation,
            object_type,
            object_id,
            payload_json,
            previous_hash,
            event_hash,
        ),
    )
    return event_id


def verify_audit_chain(connection: sqlite3.Connection) -> dict[str, Any]:
    rows = connection.execute("SELECT * FROM audit_events ORDER BY sequence").fetchall()
    previous_hash = GENESIS_HASH
    for expected_sequence, row in enumerate(rows, 1):
        if row["sequence"] != expected_sequence:
            return {
                "valid": False,
                "events": len(rows),
                "error": f"sequence gap at {expected_sequence}",
            }
        if row["previous_hash"] != previous_hash:
            return {
                "valid": False,
                "events": len(rows),
                "error": f"previous hash mismatch at {expected_sequence}",
            }
        material = {
            "sequence": row["sequence"],
            "id": row["id"],
            "occurred_at": row["occurred_at"],
            "actor_type": row["actor_type"],
            "actor_id": row["actor_id"],
            "operation": row["operation"],
            "object_type": row["object_type"],
            "object_id": row["object_id"],
            "payload_json": row["payload_json"],
            "previous_hash": row["previous_hash"],
        }
        calculated = _event_hash(material)
        if calculated != row["event_hash"]:
            return {
                "valid": False,
                "events": len(rows),
                "error": f"event hash mismatch at {expected_sequence}",
            }
        previous_hash = row["event_hash"]
    return {
        "valid": True,
        "events": len(rows),
        "head": previous_hash,
    }
