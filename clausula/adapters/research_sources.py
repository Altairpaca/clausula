from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from clausula.domain import require_uuid

from .audit import append_audit_event


class ResearchSourceProjection:
    """Audit-backed source locator map for extracted research documents.

    Canonical research text remains in `research_documents`. This projection maps
    normalized character spans back to immutable source locations (PDF pages,
    HTML/Markdown sections, or a whole-document locator) without turning an
    extraction/retrieval index into financial truth.
    """

    OBJECT_TYPE = "research_source_map"

    def __init__(self, repository):
        if not hasattr(repository, "db"):
            raise TypeError("research source projection requires local SQLite storage")
        self.repository = repository
        self.db = repository.db

    def __getattr__(self, name: str):
        return getattr(self.repository, name)

    def add_source_map(
        self,
        document_id: str,
        *,
        extractor: str,
        extractor_version: str,
        source_media_type: str,
        segments: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        require_uuid(document_id, "document_id")
        self.repository.research_document(document_id)
        normalized: list[dict[str, Any]] = []
        previous_end = 0
        for sequence, segment in enumerate(segments):
            start = int(segment["span_start"])
            end = int(segment["span_end"])
            if start < 0 or end <= start:
                raise ValueError("research source segment requires a valid span")
            if sequence and start < previous_end:
                raise ValueError("research source segments must not overlap out of order")
            locator_type = str(segment.get("locator_type") or "document").strip().lower()
            locator = str(segment.get("locator") or "document").strip()
            if not locator:
                raise ValueError("research source segment locator cannot be empty")
            normalized.append(
                {
                    "sequence": sequence,
                    "locator_type": locator_type,
                    "locator": locator,
                    "span_start": start,
                    "span_end": end,
                    "text_sha256": str(segment["text_sha256"]),
                }
            )
            previous_end = end
        if not normalized:
            raise ValueError("research source map requires at least one segment")
        payload = {
            "document_id": document_id,
            "extractor": str(extractor).strip(),
            "extractor_version": str(extractor_version).strip(),
            "source_media_type": str(source_media_type).strip().lower(),
            "segments": normalized,
        }
        with self.repository.write_transaction():
            event_id = append_audit_event(
                self.db,
                operation="research.source_map",
                object_type=self.OBJECT_TYPE,
                object_id=document_id,
                payload=payload,
            )
        return {"event_id": event_id, **payload}

    def source_map(self, document_id: str) -> dict[str, Any] | None:
        require_uuid(document_id, "document_id")
        row = self.db.execute(
            """SELECT * FROM audit_events
               WHERE object_type=? AND object_id=?
               ORDER BY sequence DESC LIMIT 1""",
            (self.OBJECT_TYPE, document_id),
        ).fetchone()
        if row is None:
            return None
        payload = json.loads(row["payload_json"])
        return {
            "event_id": row["id"],
            "recorded_at": row["occurred_at"],
            **payload,
        }

    def trace_span(self, document_id: str, span_start: int, span_end: int) -> dict[str, Any]:
        if span_start < 0 or span_end <= span_start:
            raise ValueError("trace span must have non-negative start before end")
        source_map = self.source_map(document_id)
        if source_map is None:
            return {
                "document_id": document_id,
                "span_start": span_start,
                "span_end": span_end,
                "status": "unavailable",
                "segments": [],
            }
        segments = [
            segment
            for segment in source_map["segments"]
            if int(segment["span_start"]) < span_end
            and int(segment["span_end"]) > span_start
        ]
        return {
            "document_id": document_id,
            "span_start": span_start,
            "span_end": span_end,
            "status": "mapped" if segments else "unmapped",
            "extractor": source_map["extractor"],
            "extractor_version": source_map["extractor_version"],
            "source_media_type": source_map["source_media_type"],
            "segments": segments,
        }
