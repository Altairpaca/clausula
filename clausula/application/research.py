from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from clausula.domain import (
    ResearchDocument,
    canonical_timestamp,
    new_id,
    now,
)

from .ports import CoreRepository


RESEARCH_EVENT_FORMAT = "clausula-research-event-v1"


class ResearchError(ValueError):
    """A research operation violates its canonical contract."""


class ResearchService:
    def __init__(self, repository: CoreRepository):
        self.repository = repository

    def ingest_text(
        self,
        path: str | Path,
        *,
        title: str,
        source_uri: str,
        known_at: str,
        effective_at: str | None = None,
        recorded_at: str | None = None,
        media_type: str = "text/plain",
    ) -> dict[str, Any]:
        source_path = Path(path)
        text = source_path.read_text(encoding="utf-8")
        if not text:
            raise ResearchError("research document text cannot be empty")
        effective = canonical_timestamp(effective_at or known_at)
        recorded = canonical_timestamp(recorded_at or now())
        knowledge = canonical_timestamp(known_at)
        if knowledge > recorded:
            raise ResearchError("known_at cannot be after recorded_at")
        document_id = new_id()
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        event = {
            "format": RESEARCH_EVENT_FORMAT,
            "schema_version": "1",
            "operation": "research.ingest_text",
            "document_id": document_id,
            "title": title,
            "media_type": media_type,
            "source_uri": source_uri,
            "effective_at": effective,
            "known_at": knowledge,
            "recorded_at": recorded,
            "text_sha256": digest,
        }
        with self.repository.write_transaction():
            source_artifact_id, source_digest = self.repository.artifact(source_path)
            source_import_batch_id = self.repository.import_batch(
                source_artifact_id,
                adapter_name="text-source",
                adapter_version="1",
                schema_version="1",
            )
            event_artifact_id, _ = self.repository.virtual_artifact(
                "manual://research-ingest",
                self._event_json(event | {"source_artifact_sha256": source_digest}),
            )
            self.repository.import_batch(
                event_artifact_id,
                adapter_name="manual-research",
                adapter_version="1",
                schema_version="1",
            )
            document = ResearchDocument(
                document_id,
                title,
                media_type,
                source_uri,
                text,
                digest,
                effective,
                knowledge,
                recorded,
                source_artifact_id,
                source_import_batch_id,
            )
            self.repository.add_research_document(document)
        return self.get_document(document_id)

    def create_claim(
        self,
        document_id: str,
        *,
        claim_key: str,
        text: str,
        span_start: int,
        span_end: int,
        known_at: str,
        generated_by: str = "human",
        confidence: str | None = None,
        effective_at: str | None = None,
        recorded_at: str | None = None,
    ) -> dict[str, Any]:
        from .research_records import ResearchRecordWriter

        return ResearchRecordWriter(self.repository).create_claim(
            document_id,
            claim_key=claim_key,
            text=text,
            span_start=span_start,
            span_end=span_end,
            known_at=known_at,
            generated_by=generated_by,
            confidence=confidence,
            effective_at=effective_at,
            recorded_at=recorded_at,
        )

    def create_evidence(
        self,
        document_id: str,
        *,
        kind: str,
        text: str,
        span_start: int,
        span_end: int,
        relation: str,
        known_at: str,
        generated_by: str = "human",
        confidence: str | None = None,
        effective_at: str | None = None,
        recorded_at: str | None = None,
    ) -> dict[str, Any]:
        from .research_records import ResearchRecordWriter

        return ResearchRecordWriter(self.repository).create_evidence(
            document_id,
            kind=kind,
            text=text,
            span_start=span_start,
            span_end=span_end,
            relation=relation,
            known_at=known_at,
            generated_by=generated_by,
            confidence=confidence,
            effective_at=effective_at,
            recorded_at=recorded_at,
        )

    def create_contradiction(
        self,
        claim_a_id: str,
        claim_b_id: str,
        *,
        kind: str,
        explanation: str,
        known_at: str,
        recorded_at: str | None = None,
    ) -> dict[str, Any]:
        from .research_records import ResearchRecordWriter

        return ResearchRecordWriter(self.repository).create_contradiction(
            claim_a_id,
            claim_b_id,
            kind=kind,
            explanation=explanation,
            known_at=known_at,
            recorded_at=recorded_at,
        )

    def create_thesis(
        self,
        *,
        title: str,
        initial_text: str,
        known_at: str,
        created_at: str | None = None,
        recorded_at: str | None = None,
    ) -> dict[str, Any]:
        from .research_theses import ResearchThesisWriter

        return ResearchThesisWriter(self.repository).create(
            title=title,
            initial_text=initial_text,
            known_at=known_at,
            created_at=created_at,
            recorded_at=recorded_at,
        )

    def revise_thesis(
        self,
        thesis_id: str,
        *,
        text: str,
        known_at: str,
        recorded_at: str | None = None,
    ) -> dict[str, Any]:
        from .research_theses import ResearchThesisWriter

        return ResearchThesisWriter(self.repository).revise(
            thesis_id,
            text=text,
            known_at=known_at,
            recorded_at=recorded_at,
        )

    def link(
        self,
        from_type: str,
        from_id: str,
        to_type: str,
        to_id: str,
        *,
        relation: str,
        known_at: str,
        effective_at: str | None = None,
        recorded_at: str | None = None,
    ) -> str:
        from .research_queries import ResearchGraphService

        return ResearchGraphService(self.repository).link(
            from_type,
            from_id,
            to_type,
            to_id,
            relation=relation,
            known_at=known_at,
            effective_at=effective_at,
            recorded_at=recorded_at,
        )

    def get_document(self, document_id: str) -> dict[str, Any]:
        from .research_queries import ResearchGraphService

        return ResearchGraphService(self.repository).get_document(document_id)

    def get_thesis(self, thesis_id: str) -> dict[str, Any]:
        from .research_queries import ResearchGraphService

        return ResearchGraphService(self.repository).get_thesis(thesis_id)

    def search(
        self,
        query: str,
        *,
        as_of: str | None = None,
        known_as_of: str | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        from .research_queries import ResearchGraphService

        return ResearchGraphService(self.repository).search(
            query, as_of=as_of, known_as_of=known_as_of
        )

    def trace(
        self, node_type: str, node_id: str, *, max_depth: int = 3
    ) -> dict[str, Any]:
        from .research_queries import ResearchGraphService

        return ResearchGraphService(self.repository).trace(
            node_type, node_id, max_depth=max_depth
        )

    @staticmethod
    def _event_json(event: Mapping[str, Any]) -> str:
        return json.dumps(event, sort_keys=True, separators=(",", ":"))
