from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading

import pytest

from clausula import Store
from clausula.adapters.mcp import McpAdapter, McpProfile
from clausula.application import LedgerRebuilder, ResearchError, ResearchIngestionService, ResearchService
from clausula.capabilities import CapabilityPermissionError, ConfirmationRequired, build_core_registry


def _minimal_pdf(text: str) -> bytes:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{index} 0 obj\n".encode("ascii"))
        data.extend(body)
        data.extend(b"\nendobj\n")
    startxref = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    data.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    data.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{startxref}\n%%EOF\n".encode(
            "ascii"
        )
    )
    return bytes(data)


def test_markdown_html_and_pdf_keep_source_locators(tmp_path: Path) -> None:
    store = Store(tmp_path / "home")
    ingest = ResearchIngestionService(store)

    markdown = tmp_path / "note.md"
    markdown.write_text(
        "# Liquidity\nCash remains constrained.\n\n## Catalyst\nRefinancing closes next month.\n",
        encoding="utf-8",
    )
    md = ingest.ingest_file(
        markdown,
        title="Liquidity note",
        source_uri="file:///liquidity.md",
        known_at="2026-01-02",
        recorded_at="2026-01-02",
    )
    assert {segment["locator"] for segment in md["source_map"]["segments"]} == {
        "Liquidity",
        "Catalyst",
    }

    html = tmp_path / "release.html"
    html.write_text(
        "<html><body><h1>Guidance</h1><p>Revenue guidance increased.</p>"
        "<script>secret_session_token='ignore-me'</script>"
        "<h2>Risk</h2><p>Margins remain pressured.</p></body></html>",
        encoding="utf-8",
    )
    page = ingest.ingest_file(
        html,
        title="Issuer release",
        source_uri="file:///release.html",
        known_at="2026-01-03",
        recorded_at="2026-01-03",
    )
    assert "secret_session_token" not in page["document"]["text"]
    assert {segment["locator"] for segment in page["source_map"]["segments"]} >= {
        "Guidance",
        "Risk",
    }

    pdf = tmp_path / "filing.pdf"
    pdf.write_bytes(_minimal_pdf("Liquidity remains constrained."))
    filing = ingest.ingest_file(
        pdf,
        title="Filing",
        source_uri="file:///filing.pdf",
        known_at="2026-01-04",
        recorded_at="2026-01-04",
    )
    assert "Liquidity remains constrained" in filing["document"]["text"]
    segment = filing["source_map"]["segments"][0]
    assert segment["locator_type"] == "page"
    assert segment["locator"] == "1"

    text = filing["document"]["text"]
    start = text.index("Liquidity")
    claim = ResearchService(store).create_claim(
        filing["document"]["id"],
        claim_key="liquidity",
        text="Liquidity remains constrained.",
        span_start=start,
        span_end=start + len("Liquidity remains constrained."),
        known_at="2026-01-04",
        recorded_at="2026-01-04",
    )
    traced = ingest.trace_span(
        filing["document"]["id"],
        claim["claim"]["span_start"],
        claim["claim"]["span_end"],
    )
    assert traced["status"] == "mapped"
    assert traced["segments"][0]["locator"] == "1"


def test_web_capture_has_no_browser_session_and_captures_response_metadata(tmp_path: Path) -> None:
    seen: dict[str, str | None] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            seen["cookie"] = self.headers.get("Cookie")
            body = b"<html><body><h1>Quarterly update</h1><p>Bookings accelerated.</p></body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("ETag", '"fixture-v1"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/release"
        store = Store(tmp_path / "web")
        result = ResearchIngestionService(store).ingest_url(
            url,
            title="Quarterly update",
            known_at="2026-01-05",
            recorded_at="2026-01-05",
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert seen["cookie"] is None
    assert "Bookings accelerated" in result["document"]["text"]
    audit = store.db.execute(
        "SELECT payload_json FROM audit_events WHERE object_type='research_source_map'"
    ).fetchone()
    assert audit is not None
    event_artifact = store.db.execute(
        """SELECT a.path,d.source_path FROM artifacts a
           JOIN artifact_details d ON d.artifact_id=a.id
           WHERE d.source_path='manual://research-ingest-source'"""
    ).fetchone()
    assert event_artifact is not None
    event = json.loads((store.root / event_artifact["path"]).read_text(encoding="utf-8"))
    assert event["capture"]["etag"] == '"fixture-v1"'
    assert event["capture"]["requested_url"] == url
    assert event["capture"]["content_type"] == "text/html"


def test_malformed_pdf_fails_without_creating_research_document(tmp_path: Path) -> None:
    store = Store(tmp_path / "bad")
    path = tmp_path / "bad.pdf"
    path.write_bytes(b"not a pdf")
    with pytest.raises(ResearchError):
        ResearchIngestionService(store).ingest_file(
            path,
            title="Bad PDF",
            source_uri="file:///bad.pdf",
            known_at="2026-01-01",
            recorded_at="2026-01-01",
        )
    assert store.research_documents() == []


def test_extracted_source_rebuild_is_deterministic(tmp_path: Path) -> None:
    source_store = Store(tmp_path / "source")
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(_minimal_pdf("Durable cash reduces forced selling."))
    ingested = ResearchIngestionService(source_store).ingest_file(
        pdf,
        title="Liquidity filing",
        source_uri="file:///source.pdf",
        known_at="2026-01-02",
        recorded_at="2026-01-02",
    )
    document = ingested["document"]
    ResearchService(source_store).create_claim(
        document["id"],
        claim_key="reserve",
        text="Durable cash reduces forced selling.",
        span_start=0,
        span_end=len("Durable cash reduces forced selling."),
        known_at="2026-01-02",
        recorded_at="2026-01-02",
    )

    target_store = Store(tmp_path / "target")
    rebuilt = LedgerRebuilder(source_store, target_store).rebuild()
    assert rebuilt["warnings"] == []
    mapped_id = rebuilt["research_mapping"][document["id"]]
    target = target_store.research_document(mapped_id)
    assert target["text_sha256"] == document["text_sha256"]
    source_map = ResearchIngestionService(target_store).source_map(mapped_id)
    assert source_map is not None
    assert source_map["segments"][0]["locator"] == "1"


def test_research_capabilities_separate_network_permission(tmp_path: Path) -> None:
    store = Store(tmp_path / "caps")
    registry = build_core_registry(store)
    names = {row["name"] for row in registry.describe()}
    assert {"research.ingest_file", "research.capture_url", "research.source_map", "research.trace_span"} <= names

    with pytest.raises(CapabilityPermissionError):
        registry.execute(
            "research.capture_url",
            {"url": "https://example.invalid", "title": "x", "known_at": "2026-01-01"},
            permissions={"research:write"},
            confirmed=True,
        )
    with pytest.raises(ConfirmationRequired):
        registry.execute(
            "research.capture_url",
            {"url": "https://example.invalid", "title": "x", "known_at": "2026-01-01"},
            permissions={"research:write", "network:read"},
        )

    advisor_tools = {tool.name for tool in McpAdapter(store).list_tools(McpProfile.ADVISOR)}
    admin_tools = {tool.name for tool in McpAdapter(store).list_tools(McpProfile.ADMIN)}
    assert "research.ingest_file" in advisor_tools
    assert "research.capture_url" not in advisor_tools
    assert "research.capture_url" in admin_tools
