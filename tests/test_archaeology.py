from __future__ import annotations

import json
from pathlib import Path


APPROVED_SOURCES = {
    "clawalpha_repository",
    "clawalpha_data",
    "clawalpha_state",
    "clawalpha_artifacts",
    "clawalpha_archive",
    "migration",
}
APPROVED_BUNDLES = {"legacy_clausula", "clawalpha_history"}


def test_public_archaeology_metadata_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    inventory = json.loads((root / "migration_inventory.yaml").read_text(encoding="utf-8"))
    manifest = json.loads((root / "source_snapshot_manifest.yaml").read_text(encoding="utf-8"))
    catalog = json.loads((root / "data_asset_catalog.yaml").read_text(encoding="utf-8"))

    assert inventory["status"] == "public_summary"
    assert set(inventory["approved_sources"]) == APPROVED_SOURCES
    assert "file_catalog" not in inventory

    assert {item["name"] for item in manifest["roots"]} == APPROVED_SOURCES
    assert {item["name"] for item in manifest["bundles"]} == APPROVED_BUNDLES
    assert all(item["tree_sha256"] for item in manifest["roots"])
    assert all(bundle["sha256"] for bundle in manifest["bundles"])

    serialized = json.dumps(
        {"inventory": inventory, "manifest": manifest, "catalog": catalog},
        ensure_ascii=False,
    )
    assert "/home/" not in serialized
    assert "refs/heads/" not in serialized
    assert "worktrees/" not in serialized
    assert "relative_path" not in serialized


def test_public_inventory_exposes_only_logical_classifications() -> None:
    root = Path(__file__).resolve().parents[1]
    inventory = json.loads((root / "migration_inventory.yaml").read_text(encoding="utf-8"))
    assert set(inventory["classification_contract"]) == {
        "MIGRATE_AS_IS",
        "MIGRATE_WITH_REWRITE",
        "ARCHIVE",
        "IGNORE",
    }
