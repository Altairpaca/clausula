from __future__ import annotations

from pathlib import Path
from typing import Any

from .rebuild import LedgerRebuilder as _BaseLedgerRebuilder, RebuildError
from .research import ResearchService
from .research_ingest import ResearchIngestionService


class LedgerRebuilder(_BaseLedgerRebuilder):
    """Extend canonical rebuild with deterministic non-plain-text research extraction."""

    def _replay_research_event(
        self,
        research: ResearchService,
        event: dict[str, Any],
        artifact_paths: dict[str, Path],
        mapping: dict[str, str],
    ) -> dict[str, Any]:
        if event.get("operation") != "research.ingest_source":
            return super()._replay_research_event(research, event, artifact_paths, mapping)
        if event.get("schema_version") != "1":
            raise ValueError("unsupported research event schema")
        source_path = artifact_paths.get(event.get("source_artifact_sha256", ""))
        if source_path is None or not source_path.is_file():
            raise RebuildError("research source artifact is missing")
        result = ResearchIngestionService(self.target).ingest_file(
            source_path,
            title=event["title"],
            source_uri=event["source_uri"],
            known_at=event["known_at"],
            effective_at=event["effective_at"],
            recorded_at=event["recorded_at"],
            media_type=event["media_type"],
            capture_metadata=event.get("capture") or {},
        )
        document = result["document"]
        if document["text_sha256"] != event["text_sha256"]:
            raise RebuildError(
                "research extraction changed during rebuild; extractor output is not deterministic"
            )
        source_map = result["source_map"]
        if source_map["extractor"] != event["extractor"]:
            raise RebuildError("research extractor identity changed during rebuild")
        if source_map["extractor_version"] != event["extractor_version"]:
            raise RebuildError("research extractor version changed during rebuild")
        mapping[event["document_id"]] = document["id"]
        return result
