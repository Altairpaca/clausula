from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Protocol

from clausula.domain import canonical_timestamp


class AttentionRepository(Protocol):
    def attention_event(self, fingerprint: str) -> Mapping[str, Any] | None: ...

    def attention_events(self) -> list[Mapping[str, Any]]: ...

    def add_attention_event(
        self, fingerprint: str, payload: Mapping[str, Any]
    ) -> Mapping[str, Any]: ...


class AttentionService:
    """Record only material attention changes and deduplicate exact repeats.

    Attention is a derived, local notification surface. It does not create or
    mutate ledger, policy, recommendation, or decision facts. Exact material
    events are keyed by a stable fingerprint of their normalized semantic
    payload so repeated evaluation is idempotent.
    """

    def __init__(self, repository: AttentionRepository):
        self.repository = repository

    @staticmethod
    def _required_text(value: str, field: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError(f"attention {field} cannot be empty")
        return normalized

    @classmethod
    def _payload(
        cls,
        *,
        event_key: str,
        event_type: str,
        severity: str,
        summary: str,
        occurred_at: str,
    ) -> dict[str, str]:
        return {
            "event_key": cls._required_text(event_key, "event_key"),
            "event_type": cls._required_text(event_type, "event_type"),
            "severity": cls._required_text(severity, "severity"),
            "summary": cls._required_text(summary, "summary"),
            "occurred_at": canonical_timestamp(occurred_at),
        }

    @staticmethod
    def _fingerprint(payload: Mapping[str, Any]) -> str:
        material = json.dumps(
            dict(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def evaluate(
        self,
        *,
        event_key: str,
        event_type: str,
        severity: str,
        material: bool,
        summary: str,
        occurred_at: str,
    ) -> dict[str, Any] | None:
        if not isinstance(material, bool):
            raise ValueError("attention material must be boolean")
        if not material:
            return None
        payload = self._payload(
            event_key=event_key,
            event_type=event_type,
            severity=severity,
            summary=summary,
            occurred_at=occurred_at,
        )
        fingerprint = self._fingerprint(payload)
        existing = self.repository.attention_event(fingerprint)
        if existing is not None:
            return dict(existing)
        return dict(self.repository.add_attention_event(fingerprint, payload))

    def list(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self.repository.attention_events()]
