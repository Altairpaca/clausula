from __future__ import annotations

from clausula.application.research_ingest import ResearchIngestionService

from .registry import CapabilityRegistry, CapabilitySpec, SideEffect, object_schema


STRING = {"type": "string"}
NULLABLE_STRING = {"type": ["string", "null"]}


def register_research_ingestion_capabilities(registry: CapabilityRegistry, repository) -> CapabilityRegistry:
    service = ResearchIngestionService(repository)
    registry.register(
        CapabilitySpec(
            "research.ingest_file",
            "Capture a local research source and deterministically extract provenance-mapped text.",
            object_schema(
                {
                    "path": STRING,
                    "title": STRING,
                    "source_uri": STRING,
                    "known_at": STRING,
                    "effective_at": NULLABLE_STRING,
                    "recorded_at": NULLABLE_STRING,
                    "media_type": NULLABLE_STRING,
                },
                required=("path", "title", "source_uri", "known_at"),
            ),
            {"type": "object"},
            "write",
            True,
            SideEffect.LOCAL_WRITE,
            ("research:write",),
            True,
            "Captures immutable source bytes, extracted text, source-map provenance and audit events; never mutates financial truth.",
        ),
        lambda path, title, source_uri, known_at, effective_at=None, recorded_at=None, media_type=None: service.ingest_file(
            path,
            title=title,
            source_uri=source_uri,
            known_at=known_at,
            effective_at=effective_at,
            recorded_at=recorded_at,
            media_type=media_type,
        ),
    )
    registry.register(
        CapabilitySpec(
            "research.capture_url",
            "Fetch an HTTP(S) research source, capture immutable bytes, then deterministically extract it.",
            object_schema(
                {
                    "url": STRING,
                    "title": STRING,
                    "known_at": STRING,
                    "effective_at": NULLABLE_STRING,
                    "recorded_at": NULLABLE_STRING,
                },
                required=("url", "title", "known_at"),
            ),
            {"type": "object"},
            "write",
            True,
            SideEffect.EXTERNAL_READ,
            ("research:write", "network:read"),
            True,
            "Performs an explicit network read without browser session state, captures response bytes before extraction, and records source metadata.",
        ),
        lambda url, title, known_at, effective_at=None, recorded_at=None: service.ingest_url(
            url,
            title=title,
            known_at=known_at,
            effective_at=effective_at,
            recorded_at=recorded_at,
        ),
    )
    registry.register(
        CapabilitySpec(
            "research.source_map",
            "Return the immutable locator map from normalized research text back to source pages/sections.",
            object_schema({"document_id": STRING}, required=("document_id",)),
            {"type": "object"},
            "read",
            True,
            SideEffect.LOCAL_READ,
            ("research:read",),
            False,
            "Returns an audit-backed extraction map or an explicit unavailable status object.",
        ),
        lambda document_id: service.source_map(document_id)
        or {"document_id": document_id, "status": "unavailable", "segments": []},
    )
    registry.register(
        CapabilitySpec(
            "research.trace_span",
            "Resolve a normalized character span to its original page/section locators.",
            object_schema(
                {
                    "document_id": STRING,
                    "span_start": {"type": "integer"},
                    "span_end": {"type": "integer"},
                },
                required=("document_id", "span_start", "span_end"),
            ),
            {"type": "object"},
            "read",
            True,
            SideEffect.LOCAL_READ,
            ("research:read",),
            False,
            "Maps evidence/claim spans to immutable source locators without retrieval heuristics.",
        ),
        lambda document_id, span_start, span_end: service.trace_span(
            document_id, span_start, span_end
        ),
    )
    return registry
