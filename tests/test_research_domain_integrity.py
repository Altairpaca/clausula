from __future__ import annotations

from pathlib import Path
import uuid

import pytest

from clausula.adapters.sqlite import Store
from clausula.application.research import ResearchError, ResearchService
from clausula.domain import (
    DomainValidationError,
    ResearchClaim,
    ResearchContradiction,
    ResearchDocument,
    ResearchEvidence,
    ResearchLink,
    ThesisRevision,
)


def _id() -> str:
    return str(uuid.uuid4())


def _digest(ch: str = "a") -> str:
    return ch * 64


def test_research_document_validates_and_canonicalizes_text_digest() -> None:
    document = ResearchDocument(
        _id(),
        "Source",
        "text/plain",
        "file:///source",
        "evidence",
        "A" * 64,
        "2026-01-01",
        "2026-01-02",
        "2026-01-03",
        _id(),
        _id(),
    )
    assert document.text_sha256 == _digest("a")

    with pytest.raises(DomainValidationError, match="text_sha256"):
        ResearchDocument(
            _id(),
            "Source",
            "text/plain",
            "file:///source",
            "evidence",
            "not-a-digest",
            "2026-01-01",
            "2026-01-02",
            "2026-01-03",
            _id(),
            _id(),
        )


def test_research_domain_rejects_future_known_records() -> None:
    common = {
        "known_at": "2026-01-04",
        "recorded_at": "2026-01-03",
        "source_artifact_id": _id(),
        "import_batch_id": _id(),
    }

    with pytest.raises(DomainValidationError, match="known_at"):
        ResearchClaim(
            _id(), _id(), "claim", "text", 0, 4, "human", None,
            "2026-01-02", common["known_at"], common["recorded_at"],
            common["source_artifact_id"], common["import_batch_id"],
        )

    with pytest.raises(DomainValidationError, match="known_at"):
        ResearchEvidence(
            _id(), _id(), "quote", "text", 0, 4, "supports", "human", None,
            "2026-01-02", common["known_at"], common["recorded_at"],
            common["source_artifact_id"], common["import_batch_id"],
        )

    with pytest.raises(DomainValidationError, match="known_at"):
        ThesisRevision(
            _id(), _id(), 1, "thesis", common["known_at"], common["recorded_at"],
            common["source_artifact_id"], common["import_batch_id"],
        )

    with pytest.raises(DomainValidationError, match="known_at"):
        ResearchContradiction(
            _id(), _id(), _id(), "direct", "conflict",
            common["known_at"], common["recorded_at"],
            common["source_artifact_id"], common["import_batch_id"],
        )

    with pytest.raises(DomainValidationError, match="known_at"):
        ResearchLink(
            _id(), "claim", _id(), "thesis", _id(), "supports",
            "2026-01-02", common["known_at"], common["recorded_at"],
            common["source_artifact_id"], common["import_batch_id"],
        )


def test_thesis_create_rejects_future_knowledge_before_persistence(tmp_path: Path) -> None:
    store = Store(tmp_path / "store")
    service = ResearchService(store)

    with pytest.raises(ResearchError, match="known_at"):
        service.create_thesis(
            title="Future thesis",
            initial_text="This must not persist.",
            known_at="2026-01-04",
            recorded_at="2026-01-03",
        )

    assert store.research_theses() == []
