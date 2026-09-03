from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from clausula.domain import Thesis, ThesisRevision, canonical_timestamp, new_id, now

from .ports import CoreRepository
from .research import RESEARCH_EVENT_FORMAT, ResearchError


class ResearchThesisWriter:
    def __init__(self, repository: CoreRepository):
        self.repository = repository

    def create(
        self,
        *,
        title: str,
        initial_text: str,
        known_at: str,
        created_at: str | None = None,
        recorded_at: str | None = None,
    ) -> dict[str, Any]:
        created = canonical_timestamp(created_at or known_at)
        recorded = canonical_timestamp(recorded_at or now())
        knowledge = canonical_timestamp(known_at)
        thesis_id = new_id()
        revision_id = new_id()
        event = {
            "format": RESEARCH_EVENT_FORMAT,
            "schema_version": "1",
            "operation": "research.create_thesis",
            "thesis_id": thesis_id,
            "revision_id": revision_id,
            "title": title,
            "initial_text": initial_text,
            "known_at": knowledge,
            "created_at": created,
            "recorded_at": recorded,
        }
        with self.repository.write_transaction():
            artifact_id, _ = self.repository.virtual_artifact(
                "manual://research-thesis", self._event_json(event)
            )
            batch_id = self.repository.import_batch(
                artifact_id,
                adapter_name="manual-research",
                adapter_version="1",
                schema_version="1",
            )
            thesis = Thesis(thesis_id, title, created, artifact_id, batch_id)
            revision = ThesisRevision(
                revision_id,
                thesis_id,
                1,
                initial_text,
                knowledge,
                recorded,
                artifact_id,
                batch_id,
            )
            self.repository.add_research_thesis(thesis, revision)
        return self.get(thesis_id)

    def revise(
        self,
        thesis_id: str,
        *,
        text: str,
        known_at: str,
        recorded_at: str | None = None,
    ) -> dict[str, Any]:
        revisions = self.repository.thesis_revisions(thesis_id)
        recorded = canonical_timestamp(recorded_at or now())
        knowledge = canonical_timestamp(known_at)
        if knowledge > recorded:
            raise ResearchError("known_at cannot be after recorded_at")
        revision_number = len(revisions) + 1
        revision_id = new_id()
        event = {
            "format": RESEARCH_EVENT_FORMAT,
            "schema_version": "1",
            "operation": "research.revise_thesis",
            "thesis_id": thesis_id,
            "revision_id": revision_id,
            "revision_number": revision_number,
            "text": text,
            "known_at": knowledge,
            "recorded_at": recorded,
        }
        with self.repository.write_transaction():
            artifact_id, _ = self.repository.virtual_artifact(
                "manual://research-revision", self._event_json(event)
            )
            batch_id = self.repository.import_batch(
                artifact_id,
                adapter_name="manual-research",
                adapter_version="1",
                schema_version="1",
            )
            revision = ThesisRevision(
                revision_id,
                thesis_id,
                revision_number,
                text,
                knowledge,
                recorded,
                artifact_id,
                batch_id,
            )
            self.repository.add_thesis_revision(revision)
        return {
            "revision": next(
                dict(row)
                for row in self.repository.thesis_revisions(thesis_id)
                if row["id"] == revision_id
            ),
            "thesis": self.get(thesis_id),
        }

    def get(self, thesis_id: str) -> dict[str, Any]:
        thesis = dict(self.repository.research_thesis(thesis_id))
        return {
            "thesis": thesis,
            "revisions": [dict(row) for row in self.repository.thesis_revisions(thesis_id)],
            "links": [dict(row) for row in self.repository.research_links("thesis", thesis_id)],
        }

    @staticmethod
    def _event_json(event: Mapping[str, Any]) -> str:
        return json.dumps(event, sort_keys=True, separators=(",", ":"))
