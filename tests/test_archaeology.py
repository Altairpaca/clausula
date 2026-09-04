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


def test_public_archaeology_metadata_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    inventory = json.loads((root / "migration_inventory.yaml").read_text(encoding="utf-8"))
    manifest = json.loads((root / "source_snapshot_manifest.yaml").read_text(encoding="utf-8"))
    catalog = json.loads((root / "data_asset_catalog.yaml").read_text(encoding="utf-8"))

    assert inventory["status"] == "public_summary"
    assert set(inventory["approved_sources"]) == set(ROOTS)
    assert "file_catalog" not in inventory

    assert {item["name"] for item in manifest["roots"]} == set(ROOTS)
    assert {item["name"] for item in manifest["bundles"]} == set(BUNDLES)
    assert all(item["tree_sha256"] for item in manifest["roots"])
    assert all(bundle["sha256"] for bundle in manifest["bundles"])

    serialized = json.dumps(
        {"inventory": inventory, "manifest": manifest, "catalog": catalog},
        ensure_ascii=False,
    )
    assert "/home/" not in serialized
    assert "refs/heads/" not in serialized
    assert "worktrees/" not in serialized
