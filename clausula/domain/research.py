from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .common import canonical_decimal, canonical_timestamp, require_uuid


def _text(value: str, field: str) -> str:
    result = str(value).strip()
    if not result:
        raise ValueError(f"{field} cannot be empty")
    return result


def _span(start: int, end: int) -> tuple[int, int]:
    if isinstance(start, bool) or isinstance(end, bool) or start < 0 or end <= start:
        raise ValueError("source span must have non-negative start before end")
    return start, end


def _confidence(value: Decimal | str | None) -> str | None:
    if value is None:
        return None
    normalized = canonical_decimal(value)
    if not Decimal("0") <= Decimal(normalized) <= Decimal("1"):
        raise ValueError("confidence must be between 0 and 1")
    return normalized


@dataclass(frozen=True, slots=True)
class ResearchDocument:
    id: str
    title: str
    media_type: str
    source_uri: str
    text: str
    text_sha256: str
    effective_at: str
    known_at: str
    recorded_at: str
    source_artifact_id: str
    import_batch_id: str
    source_artifact_id: str
    import_batch_id: str

    def __post_init__(self) -> None:
        for field in ("id", "source_artifact_id", "import_batch_id"):
            object.__setattr__(self, field, require_uuid(getattr(self, field), field))
        object.__setattr__(self, "title", _text(self.title, "document title"))
        object.__setattr__(self, "media_type", _text(self.media_type, "media type"))
        object.__setattr__(self, "source_uri", _text(self.source_uri, "source URI"))
        if not self.text:
            raise ValueError("document text cannot be empty")
        for field in ("effective_at", "known_at", "recorded_at"):
            object.__setattr__(self, field, canonical_timestamp(getattr(self, field)))
        for field in ("source_artifact_id", "import_batch_id"):
            object.__setattr__(self, field, require_uuid(getattr(self, field), field))


@dataclass(frozen=True, slots=True)
class ResearchClaim:
    id: str
    document_id: str
    claim_key: str
    text: str
    span_start: int
    span_end: int
    generated_by: str
    confidence: str | None
    effective_at: str
    known_at: str
    recorded_at: str
    source_artifact_id: str
    import_batch_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", require_uuid(self.id, "claim id"))
        object.__setattr__(self, "document_id", require_uuid(self.document_id, "document_id"))
        object.__setattr__(self, "claim_key", _text(self.claim_key, "claim key"))
        object.__setattr__(self, "text", _text(self.text, "claim text"))
        _span(self.span_start, self.span_end)
        object.__setattr__(self, "generated_by", _text(self.generated_by, "generated_by"))
        object.__setattr__(self, "confidence", _confidence(self.confidence))
        for field in ("effective_at", "known_at", "recorded_at"):
            object.__setattr__(self, field, canonical_timestamp(getattr(self, field)))
        for field in ("source_artifact_id", "import_batch_id"):
            object.__setattr__(self, field, require_uuid(getattr(self, field), field))


@dataclass(frozen=True, slots=True)
class ResearchEvidence:
    id: str
    document_id: str
    kind: str
    text: str
    span_start: int
    span_end: int
    relation: str
    generated_by: str
    confidence: str | None
    effective_at: str
    known_at: str
    recorded_at: str
    source_artifact_id: str
    import_batch_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", require_uuid(self.id, "evidence id"))
        object.__setattr__(self, "document_id", require_uuid(self.document_id, "document_id"))
        object.__setattr__(self, "kind", _text(self.kind, "evidence kind"))
        object.__setattr__(self, "text", _text(self.text, "evidence text"))
        _span(self.span_start, self.span_end)
        object.__setattr__(self, "relation", _text(self.relation, "evidence relation").lower())
        if self.relation not in {"supports", "contradicts", "context"}:
            raise ValueError("evidence relation is invalid")
        object.__setattr__(self, "generated_by", _text(self.generated_by, "generated_by"))
        object.__setattr__(self, "confidence", _confidence(self.confidence))
        for field in ("effective_at", "known_at", "recorded_at"):
            object.__setattr__(self, field, canonical_timestamp(getattr(self, field)))
        for field in ("source_artifact_id", "import_batch_id"):
            object.__setattr__(self, field, require_uuid(getattr(self, field), field))


@dataclass(frozen=True, slots=True)
class ResearchThesis:
    id: str
    title: str
    created_at: str
    source_artifact_id: str
    import_batch_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", require_uuid(self.id, "thesis id"))
        object.__setattr__(self, "title", _text(self.title, "thesis title"))
        object.__setattr__(self, "created_at", canonical_timestamp(self.created_at))
        for field in ("source_artifact_id", "import_batch_id"):
            object.__setattr__(self, field, require_uuid(getattr(self, field), field))


@dataclass(frozen=True, slots=True)
class ThesisRevision:
    id: str
    thesis_id: str
    revision_number: int
    text: str
    known_at: str
    recorded_at: str
    source_artifact_id: str
    import_batch_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", require_uuid(self.id, "revision id"))
        object.__setattr__(self, "thesis_id", require_uuid(self.thesis_id, "thesis_id"))
        if isinstance(self.revision_number, bool) or self.revision_number < 1:
            raise ValueError("revision number must be positive")
        object.__setattr__(self, "text", _text(self.text, "thesis revision text"))
        for field in ("known_at", "recorded_at"):
            object.__setattr__(self, field, canonical_timestamp(getattr(self, field)))
        for field in ("source_artifact_id", "import_batch_id"):
            object.__setattr__(self, field, require_uuid(getattr(self, field), field))


@dataclass(frozen=True, slots=True)
class ResearchLink:
    id: str
    from_type: str
    from_id: str
    to_type: str
    to_id: str
    relation: str
    effective_at: str
    known_at: str
    created_at: str
    source_artifact_id: str
    import_batch_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", require_uuid(self.id, "link id"))
        object.__setattr__(self, "from_type", _text(self.from_type, "from_type").lower())
        object.__setattr__(self, "to_type", _text(self.to_type, "to_type").lower())
        object.__setattr__(self, "from_id", require_uuid(self.from_id, "from_id"))
        object.__setattr__(self, "to_id", require_uuid(self.to_id, "to_id"))
        object.__setattr__(self, "relation", _text(self.relation, "link relation").lower())
        object.__setattr__(self, "effective_at", canonical_timestamp(self.effective_at))
        object.__setattr__(self, "known_at", canonical_timestamp(self.known_at))
        object.__setattr__(self, "created_at", canonical_timestamp(self.created_at))
        for field in ("source_artifact_id", "import_batch_id"):
            object.__setattr__(self, field, require_uuid(getattr(self, field), field))


@dataclass(frozen=True, slots=True)
class ResearchContradiction:
    id: str
    claim_a_id: str
    claim_b_id: str
    kind: str
    explanation: str
    known_at: str
    recorded_at: str
    source_artifact_id: str
    import_batch_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", require_uuid(self.id, "contradiction id"))
        first = require_uuid(self.claim_a_id, "claim_a_id")
        second = require_uuid(self.claim_b_id, "claim_b_id")
        if first == second:
            raise ValueError("a claim cannot contradict itself")
        object.__setattr__(self, "claim_a_id", min(first, second))
        object.__setattr__(self, "claim_b_id", max(first, second))
        object.__setattr__(self, "kind", _text(self.kind, "contradiction kind").lower())
        object.__setattr__(self, "explanation", _text(self.explanation, "contradiction explanation"))
        for field in ("known_at", "recorded_at"):
            object.__setattr__(self, field, canonical_timestamp(getattr(self, field)))
        for field in ("source_artifact_id", "import_batch_id"):
            object.__setattr__(self, field, require_uuid(getattr(self, field), field))


Claim = ResearchClaim
Evidence = ResearchEvidence
Thesis = ResearchThesis
Contradiction = ResearchContradiction
