from __future__ import annotations

from dataclasses import dataclass
import hashlib
from html.parser import HTMLParser
import json
import mimetypes
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping, Protocol, Sequence
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from clausula.adapters.research_sources import ResearchSourceProjection
from clausula.domain import ResearchDocument, canonical_timestamp, new_id, now

from .ports import CoreRepository
from .research import RESEARCH_EVENT_FORMAT, ResearchError


EXTRACTION_SCHEMA_VERSION = "1"
MAX_REMOTE_BYTES = 25 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ExtractedSegment:
    locator_type: str
    locator: str
    text: str


@dataclass(frozen=True, slots=True)
class ExtractedDocument:
    text: str
    segments: tuple[dict[str, Any], ...]
    extractor: str
    extractor_version: str
    media_type: str


class ResearchExtractor(Protocol):
    name: str
    version: str

    def supports(self, media_type: str, path: Path) -> bool: ...

    def extract(self, path: Path, media_type: str) -> Sequence[ExtractedSegment]: ...


def _clean_text(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = "\n".join(line.rstrip() for line in value.splitlines())
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _assemble(
    parts: Sequence[ExtractedSegment], *, extractor: str, version: str, media_type: str
) -> ExtractedDocument:
    rendered: list[str] = []
    segments: list[dict[str, Any]] = []
    cursor = 0
    for part in parts:
        text = _clean_text(part.text)
        if not text:
            continue
        if rendered:
            rendered.append("\n\n")
            cursor += 2
        start = cursor
        rendered.append(text)
        cursor += len(text)
        segments.append(
            {
                "locator_type": part.locator_type,
                "locator": part.locator,
                "span_start": start,
                "span_end": cursor,
                "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            }
        )
    text = "".join(rendered)
    if not text or not segments:
        raise ResearchError("research extraction produced no text")
    return ExtractedDocument(
        text=text,
        segments=tuple(segments),
        extractor=extractor,
        extractor_version=version,
        media_type=media_type,
    )


class PlainTextExtractor:
    name = "plain-text"
    version = "1"

    def supports(self, media_type: str, path: Path) -> bool:
        return media_type.startswith("text/plain") or path.suffix.lower() in {".txt", ".log"}

    def extract(self, path: Path, media_type: str) -> Sequence[ExtractedSegment]:
        text = path.read_text(encoding="utf-8")
        return (ExtractedSegment("document", "document", text),)


class MarkdownExtractor:
    name = "markdown"
    version = "1"

    def supports(self, media_type: str, path: Path) -> bool:
        return media_type in {"text/markdown", "text/x-markdown"} or path.suffix.lower() in {".md", ".markdown"}

    def extract(self, path: Path, media_type: str) -> Sequence[ExtractedSegment]:
        lines = path.read_text(encoding="utf-8").splitlines()
        parts: list[ExtractedSegment] = []
        heading = "document"
        buffer: list[str] = []
        for line in lines:
            match = re.match(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$", line)
            if match:
                if buffer:
                    parts.append(ExtractedSegment("section", heading, "\n".join(buffer)))
                    buffer = []
                heading = match.group(2).strip()
                buffer.append(line)
            else:
                buffer.append(line)
        if buffer:
            parts.append(ExtractedSegment("section", heading, "\n".join(buffer)))
        return parts


class _HTMLBlockParser(HTMLParser):
    BLOCK_TAGS = {"p", "li", "blockquote", "pre", "td", "th"}
    HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
    SKIP_TAGS = {"script", "style", "noscript", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.current_tag: str | None = None
        self.current: list[str] = []
        self.heading = "document"
        self.parts: list[ExtractedSegment] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in self.SKIP_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag in self.BLOCK_TAGS | self.HEADING_TAGS:
            self._flush()
            self.current_tag = tag

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.SKIP_TAGS:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if self.skip_depth:
            return
        if self.current_tag == tag:
            self._flush()

    def handle_data(self, data: str) -> None:
        if not self.skip_depth and self.current_tag:
            self.current.append(data)

    def _flush(self) -> None:
        if not self.current_tag:
            self.current = []
            return
        text = " ".join(" ".join(self.current).split())
        if text:
            if self.current_tag in self.HEADING_TAGS:
                self.heading = text
                self.parts.append(ExtractedSegment("section", self.heading, text))
            else:
                self.parts.append(ExtractedSegment("section", self.heading, text))
        self.current_tag = None
        self.current = []


class HTMLExtractor:
    name = "html"
    version = "1"

    def supports(self, media_type: str, path: Path) -> bool:
        return media_type in {"text/html", "application/xhtml+xml"} or path.suffix.lower() in {".html", ".htm"}

    def extract(self, path: Path, media_type: str) -> Sequence[ExtractedSegment]:
        parser = _HTMLBlockParser()
        parser.feed(path.read_text(encoding="utf-8", errors="replace"))
        parser.close()
        parser._flush()
        return parser.parts


class PDFExtractor:
    name = "pypdf"
    version = "1"

    def supports(self, media_type: str, path: Path) -> bool:
        return media_type == "application/pdf" or path.suffix.lower() == ".pdf"

    def extract(self, path: Path, media_type: str) -> Sequence[ExtractedSegment]:
        try:
            from pypdf import PdfReader
        except ImportError as exc:  # pragma: no cover - exercised by packaging environments
            raise ResearchError(
                "PDF extraction requires the optional 'research' dependency (pypdf)"
            ) from exc
        try:
            reader = PdfReader(str(path))
        except Exception as exc:
            raise ResearchError(f"PDF could not be parsed: {exc}") from exc
        parts: list[ExtractedSegment] = []
        for index, page in enumerate(reader.pages, 1):
            try:
                text = page.extract_text() or ""
            except Exception as exc:
                raise ResearchError(f"PDF page {index} could not be extracted: {exc}") from exc
            if _clean_text(text):
                parts.append(ExtractedSegment("page", str(index), text))
        if not parts:
            raise ResearchError("PDF extraction produced no text")
        return parts


DEFAULT_EXTRACTORS: tuple[ResearchExtractor, ...] = (
    PDFExtractor(),
    HTMLExtractor(),
    MarkdownExtractor(),
    PlainTextExtractor(),
)


class ResearchIngestionService:
    """Capture immutable source bytes, then derive normalized research text.

    Network/page/PDF content remains research evidence only. Extracted text and
    locators can be recomputed from the captured raw artifact and never mutate
    canonical ledger/portfolio state.
    """

    def __init__(
        self,
        repository: CoreRepository,
        *,
        extractors: Sequence[ResearchExtractor] = DEFAULT_EXTRACTORS,
    ) -> None:
        self.repository = repository
        self.extractors = tuple(extractors)

    @staticmethod
    def infer_media_type(path: Path, explicit: str | None = None) -> str:
        if explicit:
            return explicit.split(";", 1)[0].strip().lower()
        guessed, _ = mimetypes.guess_type(path.name)
        return (guessed or "application/octet-stream").lower()

    def _extract(self, path: Path, media_type: str) -> ExtractedDocument:
        for extractor in self.extractors:
            if extractor.supports(media_type, path):
                return _assemble(
                    extractor.extract(path, media_type),
                    extractor=extractor.name,
                    version=extractor.version,
                    media_type=media_type,
                )
        raise ResearchError(f"no deterministic extractor for media type {media_type}")

    def ingest_file(
        self,
        path: str | Path,
        *,
        title: str,
        source_uri: str,
        known_at: str,
        effective_at: str | None = None,
        recorded_at: str | None = None,
        media_type: str | None = None,
        capture_metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        source_path = Path(path)
        if not source_path.is_file():
            raise ResearchError(f"research source does not exist: {source_path}")
        normalized_media_type = self.infer_media_type(source_path, media_type)
        extracted = self._extract(source_path, normalized_media_type)
        effective = canonical_timestamp(effective_at or known_at)
        recorded = canonical_timestamp(recorded_at or now())
        knowledge = canonical_timestamp(known_at)
        if knowledge > recorded:
            raise ResearchError("known_at cannot be after recorded_at")
        document_id = new_id()
        text_digest = hashlib.sha256(extracted.text.encode("utf-8")).hexdigest()
        with self.repository.write_transaction():
            source_artifact_id, source_digest = self.repository.artifact(source_path)
            source_import_batch_id = self.repository.import_batch(
                source_artifact_id,
                adapter_name="research-source",
                adapter_version=extracted.extractor_version,
                schema_version=EXTRACTION_SCHEMA_VERSION,
            )
            event = {
                "format": RESEARCH_EVENT_FORMAT,
                "schema_version": "1",
                "operation": "research.ingest_source",
                "document_id": document_id,
                "title": title,
                "media_type": normalized_media_type,
                "source_uri": source_uri,
                "effective_at": effective,
                "known_at": knowledge,
                "recorded_at": recorded,
                "text_sha256": text_digest,
                "source_artifact_sha256": source_digest,
                "extractor": extracted.extractor,
                "extractor_version": extracted.extractor_version,
                "extraction_schema_version": EXTRACTION_SCHEMA_VERSION,
                "capture": dict(capture_metadata or {}),
            }
            event_artifact_id, _ = self.repository.virtual_artifact(
                "manual://research-ingest-source",
                json.dumps(event, sort_keys=True, separators=(",", ":")),
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
                normalized_media_type,
                source_uri,
                extracted.text,
                text_digest,
                effective,
                knowledge,
                recorded,
                source_artifact_id,
                source_import_batch_id,
            )
            self.repository.add_research_document(document)
            source_map = ResearchSourceProjection(self.repository).add_source_map(
                document_id,
                extractor=extracted.extractor,
                extractor_version=extracted.extractor_version,
                source_media_type=normalized_media_type,
                segments=extracted.segments,
            )
        return {
            "document": dict(self.repository.research_document(document_id)),
            "source_map": source_map,
        }

    def ingest_url(
        self,
        url: str,
        *,
        title: str,
        known_at: str,
        effective_at: str | None = None,
        recorded_at: str | None = None,
        timeout_seconds: float = 20.0,
        max_bytes: int = MAX_REMOTE_BYTES,
    ) -> dict[str, Any]:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise ResearchError("research web capture supports only http/https URLs")
        request = Request(
            url,
            headers={
                "User-Agent": "ClausulaResearchCapture/0.1",
                "Accept": "text/html,application/xhtml+xml,application/pdf,text/plain,text/markdown,*/*;q=0.1",
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                content_type = response.headers.get_content_type()
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > max_bytes:
                    raise ResearchError("remote research source exceeds capture size limit")
                data = response.read(max_bytes + 1)
                if len(data) > max_bytes:
                    raise ResearchError("remote research source exceeds capture size limit")
                final_url = response.geturl()
                capture = {
                    "requested_url": url,
                    "final_url": final_url,
                    "status": getattr(response, "status", 200),
                    "content_type": content_type,
                    "etag": response.headers.get("ETag"),
                    "last_modified": response.headers.get("Last-Modified"),
                    "content_length": len(data),
                }
        except ResearchError:
            raise
        except Exception as exc:
            raise ResearchError(f"research web capture failed: {exc}") from exc

        suffix = ".pdf" if content_type == "application/pdf" else ".html" if content_type in {"text/html", "application/xhtml+xml"} else ".txt"
        with tempfile.TemporaryDirectory(prefix="clausula-research-capture-") as directory:
            path = Path(directory) / f"source{suffix}"
            path.write_bytes(data)
            return self.ingest_file(
                path,
                title=title,
                source_uri=final_url,
                known_at=known_at,
                effective_at=effective_at,
                recorded_at=recorded_at,
                media_type=content_type,
                capture_metadata=capture,
            )

    def source_map(self, document_id: str) -> dict[str, Any] | None:
        return ResearchSourceProjection(self.repository).source_map(document_id)

    def trace_span(self, document_id: str, span_start: int, span_end: int) -> dict[str, Any]:
        return ResearchSourceProjection(self.repository).trace_span(document_id, span_start, span_end)
