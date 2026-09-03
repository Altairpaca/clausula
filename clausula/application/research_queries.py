from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from clausula.domain import ResearchLink, canonical_timestamp, new_id, now

from .ports import CoreRepository
from .research import RESEARCH_EVENT_FORMAT, ResearchError


class ResearchGraphService:
    def __init__(self, repository: CoreRepository):
        self.repository = repository

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
        recorded = canonical_timestamp(recorded_at or now())
        knowledge = canonical_timestamp(known_at)
        effective = canonical_timestamp(effective_at or known_at)
        if knowledge > recorded:
            raise ResearchError("known_at cannot be after recorded_at")
        link_id = new_id()
        event = {
            "format": RESEARCH_EVENT_FORMAT,
            "schema_version": "1",
            "operation": "research.link",
            "link_id": link_id,
            "from_type": from_type,
            "from_id": from_id,
            "to_type": to_type,
            "to_id": to_id,
            "relation": relation,
            "effective_at": effective,
            "known_at": knowledge,
            "recorded_at": recorded,
        }
        with self.repository.write_transaction():
            artifact_id, _ = self.repository.virtual_artifact(
                "manual://research-link", self._event_json(event)
            )
            batch_id = self.repository.import_batch(
                artifact_id,
                adapter_name="manual-research",
                adapter_version="1",
                schema_version="1",
            )
            self.repository.add_research_link(
                ResearchLink(
                    link_id,
                    from_type,
                    from_id,
                    to_type,
                    to_id,
                    relation,
                    effective,
                    knowledge,
                    recorded,
                    artifact_id,
                    batch_id,
                )
            )
        return link_id

    def get_document(self, document_id: str) -> dict[str, Any]:
        document = dict(self.repository.research_document(document_id))
        return {
            "document": document,
            "claims": [dict(row) for row in self.repository.research_claims(document_id)],
            "evidence": [dict(row) for row in self.repository.research_evidence(document_id)],
            "links": [
                dict(row) for row in self.repository.research_links("document", document_id)
            ],
        }

    def get_thesis(self, thesis_id: str) -> dict[str, Any]:
        thesis = dict(self.repository.research_thesis(thesis_id))
        return {
            "thesis": thesis,
            "revisions": [dict(row) for row in self.repository.thesis_revisions(thesis_id)],
            "links": [dict(row) for row in self.repository.research_links("thesis", thesis_id)],
        }

    def search(
        self,
        query: str,
        *,
        as_of: str | None = None,
        known_as_of: str | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        term = query.strip().lower()
        effective_cutoff = (
            None if as_of is None else canonical_timestamp(as_of)
        )
        knowledge_cutoff = (
            None if known_as_of is None else canonical_timestamp(known_as_of)
        )

        def visible(row: Mapping[str, Any]) -> bool:
            keys = row.keys()
            return (
                (
                    effective_cutoff is None
                    or (
                        row["effective_at"]
                        if "effective_at" in keys
                        else effective_cutoff
                    )
                    <= effective_cutoff
                )
                and (
                    knowledge_cutoff is None
                    or (
                        row["known_at"]
                        if "known_at" in keys
                        else knowledge_cutoff
                    )
                    <= knowledge_cutoff
                )
            )

        documents = [
            dict(row)
            for row in self.repository.research_documents(term)
            if visible(row)
        ]
        claims = [
            dict(row)
            for row in self.repository.all_research_claims()
            if visible(row)
            and (term in row["text"].lower() or term in row["claim_key"].lower())
        ]
        evidence = [
            dict(row)
            for row in self.repository.all_research_evidence()
            if visible(row)
            and (term in row["text"].lower() or term in row["kind"].lower())
        ]
        theses = []
        for row in self.repository.research_theses():
            revisions = self.repository.thesis_revisions(row["id"])
            visible_revisions = [revision for revision in revisions if visible(revision)]
            if term in row["title"].lower() or any(
                term in revision["text"].lower() for revision in visible_revisions
            ):
                theses.append(dict(row))
        return {
            "documents": documents,
            "claims": claims,
            "evidence": evidence,
            "theses": theses,
        }

    def trace(
        self,
        node_type: str,
        node_id: str,
        *,
        max_depth: int = 3,
    ) -> dict[str, list[dict[str, Any]] | dict[str, str]]:
        if max_depth < 0:
            raise ValueError("trace max_depth cannot be negative")
        frontier = [(node_type.lower(), node_id, 0)]
        seen = {(node_type.lower(), node_id)}
        nodes = [{"type": node_type.lower(), "id": node_id}]
        edges: list[dict[str, Any]] = []
        while frontier:
            current_type, current_id, depth = frontier.pop(0)
            if depth >= max_depth:
                continue
            for row in self.repository.research_links(current_type, current_id):
                edge = dict(row)
                edges.append(edge)
                neighbor = (
                    (edge["to_type"], edge["to_id"])
                    if edge["from_type"] == current_type and edge["from_id"] == current_id
                    else (edge["from_type"], edge["from_id"])
                )
                if neighbor not in seen:
                    seen.add(neighbor)
                    nodes.append({"type": neighbor[0], "id": neighbor[1]})
                    frontier.append((neighbor[0], neighbor[1], depth + 1))
            if current_type == "document":
                for child_type, rows in (
                    ("claim", self.repository.research_claims(current_id)),
                    ("evidence", self.repository.research_evidence(current_id)),
                ):
                    for row in rows:
                        neighbor = (child_type, row["id"])
                        if neighbor not in seen:
                            seen.add(neighbor)
                            nodes.append({"type": child_type, "id": row["id"]})
                            frontier.append((child_type, row["id"], depth + 1))
        return {
            "root": {"type": node_type.lower(), "id": node_id},
            "nodes": nodes,
            "edges": edges,
        }

    @staticmethod
    def _event_json(event: Mapping[str, Any]) -> str:
        return json.dumps(event, sort_keys=True, separators=(",", ":"))
