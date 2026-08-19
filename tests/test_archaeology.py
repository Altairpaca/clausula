from __future__ import annotations

import json
from pathlib import Path

from scripts.archaeology import BUNDLES, ROOTS, classify


def test_all_approved_legacy_sources_are_declared() -> None:
    assert set(ROOTS) == {
        "clawalpha_repository",
        "clawalpha_data",
        "clawalpha_state",
        "clawalpha_artifacts",
        "clawalpha_archive",
        "migration",
    }
    assert set(BUNDLES) == {"legacy_clausula", "clawalpha_history"}


def test_binding_classification_examples() -> None:
    assert classify("clawalpha_data/canonical/510300.parquet").classification == "MIGRATE_AS_IS"
    assert classify("clawalpha_repository/behavior/portfolio/state.py").classification == "MIGRATE_WITH_REWRITE"
    assert classify("clawalpha_repository/code/mcp_server/server.py").classification == "ARCHIVE"


def test_generated_inventory_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    inventory = json.loads((root / "migration_inventory.yaml").read_text(encoding="utf-8"))
    manifest = json.loads((root / "source_snapshot_manifest.yaml").read_text(encoding="utf-8"))
    assert inventory["status"] == "reviewed_inventory"
    assert len(inventory["file_catalog"]) > 10_000
    assert all(item["sha256"] for item in inventory["file_catalog"])
    assert len(manifest["bundles"]) == 2
    assert all(bundle["sha256"] for bundle in manifest["bundles"])
