from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from clausula.domain import Claim, Contradiction, Evidence, canonical_timestamp, new_id, now

from .ports import CoreRepository
from .research import RESEARCH_EVENT_FORMAT, ResearchError


class ResearchRecordWriter:
    def __init__(self, repository: CoreRepository):
        self.repository = repository

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
        return self._create_record(
            "claim",
            document_id,
            text=text,
            span_start=span_start,
            span_end=span_end,
            known_at=known_at,
            generated_by=generated_by,
            confidence=confidence,
            effective_at=effective_at,
            recorded_at=recorded_at,
            claim_key=claim_key,
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
        return self._create_record(
            "evidence",
            document_id,
            text=text,
            span_start=span_start,
            span_end=span_end,
            known_at=known_at,
            generated_by=generated_by,
            confidence=confidence,
            effective_at=effective_at,
            recorded_at=recorded_at,
            kind=kind,
            relation=relation,
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
        self.repository.research_claim(claim_a_id)
        self.repository.research_claim(claim_b_id)
        recorded = canonical_timestamp(recorded_at or now())
        knowledge = canonical_timestamp(known_at)
        if knowledge > recorded:
            raise ResearchError("known_at cannot be after recorded_at")
        contradiction_id = new_id()
        event = {
            "format": RESEARCH_EVENT_FORMAT,
            "schema_version": "1",
            "operation": "research.create_contradiction",
            "contradiction_id": contradiction_id,
            "claim_a_id": claim_a_id,
            "claim_b_id": claim_b_id,
            "kind": kind,
            "explanation": explanation,
            "known_at": knowledge,
            "recorded_at": recorded,
        }
        with self.repository.write_transaction():
            artifact_id, _ = self.repository.virtual_artifact(
                "manual://research-contradiction", self._event_json(event)
            )
            batch_id = self.repository.import_batch(
                artifact_id,
                adapter_name="manual-research",
                adapter_version="1",
                schema_version="1",
            )
            value = Contradiction(
                contradiction_id,
                claim_a_id,
                claim_b_id,
                kind,
                explanation,
                knowledge,
                recorded,
                artifact_id,
                batch_id,
            )
            self.repository.add_research_contradiction(value)
            row = next(
                item
                for item in self.repository.research_contradictions(claim_a_id)
                if item["id"] == contradiction_id
            )
        return {"contradiction": dict(row)}

    def _create_record(
        self,
        operation_kind: str,
        document_id: str,
        *,
        text: str,
        span_start: int,
        span_end: int,
        known_at: str,
        generated_by: str,
        confidence: str | None,
        effective_at: str | None,
        recorded_at: str | None,
        claim_key: str | None = None,
        relation: str | None = None,
        **fields: str,
    ) -> dict[str, Any]:
        document = self.repository.research_document(document_id)
        if document["text"][span_start:span_end] != text:
            raise ResearchError("record text must match the document source span")
        effective = canonical_timestamp(effective_at or known_at)
        recorded = canonical_timestamp(recorded_at or now())
        knowledge = canonical_timestamp(known_at)
        if knowledge > recorded:
            raise ResearchError("known_at cannot be after recorded_at")
        item_id = new_id()
        event = {
            "format": RESEARCH_EVENT_FORMAT,
            "schema_version": "1",
            "operation": f"research.create_{operation_kind}",
            "item_id": item_id,
            "document_id": document_id,
            "text": text,
            "span_start": span_start,
            "span_end": span_end,
            "known_at": knowledge,
            "effective_at": effective,
            "recorded_at": recorded,
            "generated_by": generated_by,
            "confidence": confidence,
            **fields,
            **({"claim_key": claim_key} if claim_key is not None else {}),
            **({"relation": relation} if relation is not None else {}),
        }
        with self.repository.write_transaction():
            artifact_id, _ = self.repository.virtual_artifact(
                f"manual://research-{operation_kind}", self._event_json(event)
            )
            batch_id = self.repository.import_batch(
                artifact_id,
                adapter_name="manual-research",
                adapter_version="1",
                schema_version="1",
            )
            if operation_kind == "claim":
                value = Claim(
                    item_id,
                    document_id,
                    claim_key or "",
                    text,
                    span_start,
                    span_end,
                    generated_by,
                    confidence,
                    effective,
                    knowledge,
                    recorded,
                    artifact_id,
                    batch_id,
                )
                self.repository.add_research_claim(value)
                row = next(
                    item
                    for item in self.repository.research_claims(document_id)
                    if item["id"] == item_id
                )
                return {"claim": dict(row)}
            value = Evidence(
                item_id,
                document_id,
                fields["kind"],
                text,
                span_start,
                span_end,
                relation or "context",
                generated_by,
                confidence,
                effective,
                knowledge,
                recorded,
                artifact_id,
                batch_id,
            )
            self.repository.add_research_evidence(value)
            row = next(
                item
                for item in self.repository.research_evidence(document_id)
                if item["id"] == item_id
            )
            return {"evidence": dict(row)}

    @staticmethod
    def _event_json(event: Mapping[str, Any]) -> str:
        return json.dumps(event, sort_keys=True, separators=(",", ":"))
