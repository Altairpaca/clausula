from __future__ import annotations

from pathlib import Path

from clausula.adapters.sqlite import Store
from clausula.application import LedgerRebuilder
from clausula.application.research import ResearchService


def test_research_graph_preserves_source_and_revision_history(tmp_path: Path) -> None:
    source_path = tmp_path / "thesis.txt"
    source_path.write_text(
        "Liquidity remains the primary constraint for the portfolio. "
        "Liquidity is not a constraint for this portfolio.",
        encoding="utf-8",
    )
    store = Store(tmp_path / "store")
    service = ResearchService(store)

    document = service.ingest_text(
        source_path,
        title="Liquidity note",
        source_uri="file:///research/liquidity-note",
        known_at="2026-01-02",
    )
    document_id = document["document"]["id"]
    assert document["document"]["text"] == source_path.read_text(encoding="utf-8")
    assert document["document"]["source_artifact_id"]
    assert document["document"]["text_sha256"]

    evidence = service.create_evidence(
        document_id,
        kind="quotation",
            text="Liquidity remains the primary constraint",
            span_start=0,
            span_end=40,
        relation="supports",
        generated_by="human",
        known_at="2026-01-02",
    )
    claim = service.create_claim(
        document_id,
        claim_key="liquidity-constraint",
        text="Liquidity remains the primary constraint for the portfolio.",
        span_start=0,
        span_end=59,
        generated_by="human",
        known_at="2026-01-02",
    )
    thesis = service.create_thesis(
        title="Liquidity first",
        initial_text="Preserve sufficient liquidity before adding risk.",
        known_at="2026-01-02",
    )
    revision = service.revise_thesis(
        thesis["thesis"]["id"],
        text="Preserve liquidity before increasing risk exposure.",
        known_at="2026-01-03",
    )
    second_claim = service.create_claim(
        document_id,
        claim_key="liquidity-counterpoint",
        text="Liquidity is not a constraint for this portfolio.",
        span_start=60,
        span_end=109,
        known_at="2026-01-04",
    )
    contradiction = service.create_contradiction(
        claim["claim"]["id"],
        second_claim["claim"]["id"],
        kind="direct",
        explanation="The propositions disagree about the constraint.",
        known_at="2026-01-04",
    )
    service.link(
        "evidence",
        evidence["evidence"]["id"],
        "thesis",
        thesis["thesis"]["id"],
        relation="supports",
        known_at="2026-01-02",
    )
    service.link(
        "claim",
        claim["claim"]["id"],
        "thesis",
        thesis["thesis"]["id"],
        relation="supports",
        known_at="2026-01-02",
    )

    found = service.search("liquidity")
    graph = service.get_thesis(thesis["thesis"]["id"])

    assert [row["id"] for row in found["documents"]] == [document_id]
    assert graph["thesis"]["title"] == "Liquidity first"
    assert len(graph["revisions"]) == 2
    assert graph["revisions"][0]["text"] != graph["revisions"][1]["text"]
    assert graph["links"][0]["relation"] == "supports"
    assert revision["revision"]["revision_number"] == 2
    assert contradiction["contradiction"]["kind"] == "direct"
    assert len(store.research_contradictions(claim["claim"]["id"])) == 1
    assert service.search("liquidity", known_as_of="2026-01-02")["claims"]
    assert service.search("liquidity", known_as_of="2025-12-31")["claims"] == []
    trace = service.trace("thesis", thesis["thesis"]["id"])
    assert {"type": "claim", "id": claim["claim"]["id"]} in trace["nodes"]


def test_research_events_rebuild_into_clean_store(tmp_path: Path) -> None:
    source_path = tmp_path / "rebuild.txt"
    source_path.write_text("A durable reserve reduces forced selling.", encoding="utf-8")
    source_store = Store(tmp_path / "source")
    service = ResearchService(source_store)
    document = service.ingest_text(
        source_path,
        title="Reserve note",
        source_uri="file:///reserve",
        known_at="2026-01-02",
        recorded_at="2026-01-02",
    )
    claim = service.create_claim(
        document["document"]["id"],
        claim_key="reserve",
        text="A durable reserve reduces forced selling.",
        span_start=0,
        span_end=41,
        known_at="2026-01-02",
        recorded_at="2026-01-02",
    )
    thesis = service.create_thesis(
        title="Reserve discipline",
        initial_text="Maintain a durable reserve.",
        known_at="2026-01-02",
        created_at="2026-01-02",
        recorded_at="2026-01-02",
    )
    service.link(
        "claim",
        claim["claim"]["id"],
        "thesis",
        thesis["thesis"]["id"],
        relation="supports",
        known_at="2026-01-02",
        recorded_at="2026-01-02",
    )

    result = LedgerRebuilder(source_store, Store(tmp_path / "target")).rebuild()

    assert result["warnings"] == []
    assert result["research_mapping"][document["document"]["id"]]
    assert result["research_mapping"][thesis["thesis"]["id"]]
