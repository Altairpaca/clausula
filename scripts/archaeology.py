#!/usr/bin/env python3
"""Build a metadata-only, read-only inventory of legacy Clausula assets."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


WORKSPACE = Path(__file__).resolve().parents[1]
ROOTS = {
    "clawalpha_repository": Path("/home/altair/projects/clawalpha"),
    "clawalpha_data": Path("/home/altair/data/clawalpha"),
    "clawalpha_state": Path("/home/altair/state/clawalpha"),
    "clawalpha_artifacts": Path("/home/altair/artifacts/clawalpha"),
    "clawalpha_archive": Path("/home/altair/archive/clawalpha"),
    "migration": Path("/home/altair/migration"),
}
BUNDLES = {
    "legacy_clausula": Path(
        "/home/altair/migration/backups/git/Clausula-a2c4a581/Clausula-a2c4a581.bundle"
    ),
    "clawalpha_history": Path(
        "/home/altair/migration/backups/git/projects_clawalpha-30c606d9/"
        "projects_clawalpha-30c606d9.bundle"
    ),
}
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules", ".cache"}


@dataclass(frozen=True)
class ComponentRule:
    name: str
    needles: tuple[str, ...]
    responsibility: str
    classification: str
    capability: str | None
    migration_value: str
    migration_risk: str
    future_leakage: str


COMPONENT_RULES = (
    ComponentRule(
        "canonical_market_dataset",
        ("clawalpha_data/canonical/",),
        "Daily canonical ETF Parquet dataset and content-addressed manifest.",
        "MIGRATE_AS_IS",
        "market.get_daily_prices",
        "High: validated daily history is immediately useful for M3 valuation.",
        "Medium: most canonical rows cannot currently be reconstructed from the thin raw store.",
        "Daily market facts are safe when queried with explicit effective/known timestamps.",
    ),
    ComponentRule(
        "instrument_registry",
        ("clawalpha_data/instruments.json", "data/pipeline/instruments.py"),
        "Instrument metadata and external identifier resolution.",
        "MIGRATE_WITH_REWRITE",
        "instrument.resolve",
        "High: 1,560 observed instruments and identifier metadata.",
        "Medium: ticker is used as identity and identifier history is absent.",
        "No intrinsic leakage; updated_at must become known_at during migration.",
    ),
    ComponentRule(
        "market_adapters_and_quality",
        ("data/pipeline/adapters/", "data/pipeline/quality.py", "data/pipeline/snapshots.py"),
        "Market provider adapters, fail-closed quality gates, and immutable raw snapshots.",
        "MIGRATE_WITH_REWRITE",
        "market.import_daily_prices",
        "High: provider failure taxonomy and quality tests are reusable contracts.",
        "Medium: provider names, paths, and ETF-only schema are embedded in the implementation.",
        "Freshness checks and fetched_at must never substitute for known_at.",
    ),
    ComponentRule(
        "runtime_ledger_and_reconciliation",
        ("behavior/runtime/", "behavior/portfolio/", "accounts.db"),
        "Paper-runtime fills, cash, positions, snapshots, and fill-ledger reconciliation.",
        "MIGRATE_WITH_REWRITE",
        "ledger.reconcile",
        "High: conservation and reconciliation tests encode useful invariants.",
        "High: it is execution-oriented, ticker-keyed, float-based, and not a canonical personal ledger.",
        "Replay ordering is explicit but historical knowledge time is not modeled.",
    ),
    ComponentRule(
        "decision_packages",
        ("behavior/decisions/", "quant/bridge/", "decisionops/"),
        "Immutable hashed research decision packages and runtime bridge validation.",
        "MIGRATE_WITH_REWRITE",
        "decision.create",
        "High: immutable justification and fail-closed validation match Decision provenance goals.",
        "High: old packages conflate research signal, proposal, decision, and execution intent.",
        "Anti-lookahead checks are valuable but must map to effective_at and known_at.",
    ),
    ComponentRule(
        "research_evidence_database",
        ("evidence_engine.db", "evidence_engine/"),
        "Documents, observations, evidence, theses, belief updates, and research job provenance.",
        "MIGRATE_WITH_REWRITE",
        "research.search",
        "High: source spans, contradictions, revisions, and job lineage are strong reference assets.",
        "High: denormalized JSON and domain-specific belief machinery should not define the new ontology.",
        "event_time and ingestion time exist, but must be normalized to the three-time contract.",
    ),
    ComponentRule(
        "temporal_and_statistical_contracts",
        ("quant/time_contract.py", "quant/evaluation/", "test_anti_lookahead", "test_time_contract"),
        "Anti-lookahead contracts and deterministic statistical evaluation utilities.",
        "MIGRATE_WITH_REWRITE",
        "analysis.run",
        "Medium: tests and definitions can seed future analytics contracts.",
        "Medium: research-specific inputs and semantics require isolation from core portfolio truth.",
        "This component exists specifically to detect future leakage.",
    ),
    ComponentRule(
        "research_documents",
        ("knowledge/", "research_library/", "research_reports/", "project_assets_20260801/knowledge/"),
        "Books, papers, reports, source registries, and extracted research notes.",
        "MIGRATE_WITH_REWRITE",
        "research.ingest",
        "High: primary documents should become immutable ResearchDocument source artifacts.",
        "Medium: duplicates, uncertain licenses, generated notes, and incomplete manifests require review.",
        "Research is evidence, never canonical financial truth.",
    ),
    ComponentRule(
        "legacy_clausula_portfolio",
        ("Clausula-a2c4a581",),
        "Legacy Clausula portfolio YAML/JSON, constitution, planning, and paper-trading implementation.",
        "MIGRATE_WITH_REWRITE",
        "ledger.import",
        "High: contains personal portfolio snapshots, cash-flow context, and policy history.",
        "High: bundle mixes private data, generated outputs, MCP logic, and canonical-looking caches.",
        "Snapshot dates exist, but source-known and recorded times are incomplete.",
    ),
    ComponentRule(
        "strategies_signals_and_backtests",
        ("quant/products/", "quant/factors/", "backtest/", "strategies/", "signals/", "paper_trading/"),
        "Factors, signals, strategies, backtests, paper trading, and experimental outputs.",
        "REFERENCE_ONLY",
        None,
        "Low for M0-M2; selected pure statistics may later move to Research Lab.",
        "High: duplicate engines, unproven correctness, execution assumptions, and scope expansion.",
        "Many assets are explicitly future-looking experiments and require independent temporal audit.",
    ),
    ComponentRule(
        "agent_mcp_scheduler_glue",
        ("mcp/", "mcp_server/", "behavior/agent/", ".hermes", "cron", "gateway/", ".omo/", ".opencode/"),
        "Legacy Agent, MCP, gateway, scheduler, and orchestration integration.",
        "ARCHIVE",
        None,
        "Low: interaction ideas only; no domain capability may be migrated from here.",
        "High: runtime-specific coupling would violate the new dependency direction.",
        "Agent-generated content may contain hindsight and is non-canonical by definition.",
    ),
    ComponentRule(
        "generated_outputs_and_caches",
        ("/cache/", "/output/", "/logs/", "__pycache__", ".pytest_cache", "artifacts/clawalpha/"),
        "Generated reports, caches, logs, charts, and experiment output.",
        "DELETE_CANDIDATE",
        None,
        "Low: retain only reports that are independently valuable evidence.",
        "High storage and provenance debt if copied into the canonical repository.",
        "Derived outputs may embed future information and must not seed canonical facts.",
    ),
)


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_files(root: Path) -> Iterable[Path]:
    if root.is_file():
        yield root
        return
    for current, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        base = Path(current)
        for name in sorted(files):
            path = base / name
            if path.is_file() and not path.is_symlink():
                yield path


def classify(key: str) -> ComponentRule | None:
    normalized = key.replace("\\", "/")
    for rule in COMPONENT_RULES:
        if any(needle in normalized for needle in rule.needles):
            return rule
    return None


def python_imports(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, SyntaxError):
        return []
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return sorted(names)


def git_output(root: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return completed.stdout.strip()


def bundle_heads(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        output = subprocess.run(
            ["git", "bundle", "list-heads", str(path)],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return []
    heads = []
    for line in output.splitlines():
        commit, _, reference = line.partition(" ")
        heads.append({"commit": commit, "reference": reference})
    return heads


def write_json_yaml(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def scan(generated_at: str | None = None) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    generated_at = generated_at or iso_now()
    roots: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    component_files: dict[str, list[str]] = defaultdict(list)
    extension_totals: Counter[str] = Counter()
    extension_bytes: Counter[str] = Counter()

    for root_name, root in ROOTS.items():
        tree_digest = hashlib.sha256()
        root_count = 0
        root_bytes = 0
        for path in iter_files(root) if root.exists() else ():
            relative = path.relative_to(root).as_posix()
            logical_path = f"{root_name}/{relative}"
            digest = sha256_file(path)
            stat = path.stat()
            suffix = path.suffix.lower() or "[none]"
            rule = classify(logical_path)
            item: dict[str, Any] = {
                "source_root": root_name,
                "relative_path": relative,
                "size_bytes": stat.st_size,
                "sha256": digest,
                "classification": rule.classification if rule else "REFERENCE_ONLY",
                "component": rule.name if rule else "unclassified_reference",
                "provenance": "external_local_read_only",
            }
            if path.suffix == ".py" and stat.st_size <= 2_000_000:
                item["imports"] = python_imports(path)
            files.append(item)
            component_files[item["component"]].append(logical_path)
            extension_totals[suffix] += 1
            extension_bytes[suffix] += stat.st_size
            root_count += 1
            root_bytes += stat.st_size
            tree_digest.update(relative.encode())
            tree_digest.update(b"\0")
            tree_digest.update(digest.encode())

        root_entry: dict[str, Any] = {
            "name": root_name,
            "path": str(root),
            "exists": root.exists(),
            "file_count": root_count,
            "size_bytes": root_bytes,
            "tree_sha256": tree_digest.hexdigest(),
        }
        if (root / ".git").exists():
            root_entry["git_head"] = git_output(root, "rev-parse", "HEAD")
            root_entry["git_branch"] = git_output(root, "branch", "--show-current")
            status = git_output(root, "status", "--porcelain=v1") or ""
            root_entry["git_dirty_entries"] = len(status.splitlines()) if status else 0
        roots.append(root_entry)

    bundle_entries = []
    for name, path in BUNDLES.items():
        bundle_entries.append(
            {
                "name": name,
                "path": str(path),
                "exists": path.exists(),
                "size_bytes": path.stat().st_size if path.exists() else 0,
                "sha256": sha256_file(path) if path.exists() else None,
                "heads": bundle_heads(path),
            }
        )

    components = []
    for rule in COMPONENT_RULES:
        matched = component_files.get(rule.name, [])
        components.append(
            {
                "component": rule.name,
                "classification": rule.classification,
                "current_responsibility": rule.responsibility,
                "observed_paths": matched,
                "observed_file_count": len(matched),
                "real_callers": "See file_catalog imports and ClawAlpha tests; confirm dynamically before migration.",
                "input_output_contract": "Legacy contract must be extracted from source and tests before code migration.",
                "test_coverage": "Legacy tests are inventory evidence, not Clausula acceptance tests.",
                "production_path": "No legacy runtime is a Clausula production dependency.",
                "external_dependencies": "Recorded per Python file in file_catalog imports.",
                "data_provenance": "External local source; immutable hash recorded in source snapshot.",
                "future_leakage": rule.future_leakage,
                "duplication": "Compare observed_paths and content hashes before selecting an implementation.",
                "migration_value": rule.migration_value,
                "migration_risk": rule.migration_risk,
                "clausula_capability": rule.capability,
            }
        )

    source_manifest = {
        "version": 2,
        "generated_at": generated_at,
        "mode": "metadata_hashes_only",
        "roots": roots,
        "bundles": bundle_entries,
        "guarantees": [
            "No legacy file was modified.",
            "No legacy file content is copied into this repository.",
            "Tree hashes cover path and file content hashes while excluding tool caches and Git object storage.",
        ],
    }
    migration_inventory = {
        "version": 2,
        "generated_at": generated_at,
        "status": "reviewed_inventory",
        "classification_vocabulary": [
            "MIGRATE_AS_IS",
            "MIGRATE_WITH_REWRITE",
            "REFERENCE_ONLY",
            "ARCHIVE",
            "DELETE_CANDIDATE",
        ],
        "components": components,
        "file_catalog": files,
    }
    data_catalog = {
        "version": 2,
        "generated_at": generated_at,
        "privacy": {
            "policy": "Real personal data remains outside Git and is imported only into ~/.clausula.",
            "catalog_content": "Metadata, paths, sizes, classifications, and hashes only.",
        },
        "extension_summary": [
            {"extension": ext, "file_count": extension_totals[ext], "size_bytes": extension_bytes[ext]}
            for ext in sorted(extension_totals)
        ],
        "notable_assets": [
            {
                "path": "/home/altair/data/clawalpha/canonical",
                "kind": "canonical_market_series",
                "decision": "MIGRATE_AS_IS after hash/schema validation; preserve as legacy dataset version.",
            },
            {
                "path": "/home/altair/data/clawalpha/instruments.json",
                "kind": "instrument_metadata",
                "decision": "MIGRATE_WITH_REWRITE into stable instruments plus historical identifiers.",
            },
            {
                "path": "/home/altair/state/clawalpha/evidence_engine.db",
                "kind": "research_evidence_database",
                "decision": "MIGRATE_WITH_REWRITE through validated intermediate records.",
            },
            {
                "path": str(BUNDLES["legacy_clausula"]),
                "kind": "legacy_clausula_repository_and_private_snapshots",
                "decision": "REFERENCE_ONLY for code; selected private data requires explicit local ETL review.",
            },
        ],
    }
    return source_manifest, migration_inventory, data_catalog


def render_report(manifest: dict[str, Any], inventory: dict[str, Any], catalog: dict[str, Any]) -> str:
    roots = manifest["roots"]
    total_files = sum(root["file_count"] for root in roots)
    total_bytes = sum(root["size_bytes"] for root in roots)
    classifications = Counter(
        file["classification"] for file in inventory["file_catalog"]
    )
    lines = [
        "# Clausula Capability Archaeology",
        "",
        f"Generated: `{manifest['generated_at']}`",
        "",
        "## Scope and method",
        "",
        "This M0 inventory is a metadata-only, read-only scan of every approved legacy root, "
        "both migration Git bundles, the active ClawAlpha worktree, external data/state/artifact "
        "directories, and migration manifests. It records file hashes without copying source content "
        "or personal financial data into Clausula.",
        "",
        f"The scan catalogued **{total_files:,} files** totaling **{total_bytes / 1024**3:.2f} GiB**.",
        "",
        "## Source snapshots",
        "",
        "| Source | Files | Size | Tree SHA-256 | Git state |",
        "|---|---:|---:|---|---|",
    ]
    for root in roots:
        git_state = "n/a"
        if root.get("git_head"):
            git_state = f"{root.get('git_branch') or 'detached'}@{root['git_head'][:12]}, dirty={root.get('git_dirty_entries', 0)}"
        lines.append(
            f"| `{root['path']}` | {root['file_count']:,} | {root['size_bytes']/1024**2:.1f} MiB | "
            f"`{root['tree_sha256'][:16]}…` | {git_state} |"
        )
    lines.extend(["", "## Classification", ""])
    for name in ("MIGRATE_AS_IS", "MIGRATE_WITH_REWRITE", "REFERENCE_ONLY", "ARCHIVE", "DELETE_CANDIDATE"):
        lines.append(f"- `{name}`: {classifications[name]:,} files")
    lines.extend(
        [
            "",
            "## Binding findings",
            "",
            "1. The active ClawAlpha worktree is heavily modified, so `HEAD`, worktree, and the history bundle are separate evidence sources.",
            "2. The legacy Clausula bundle contains private portfolio snapshots and a script-oriented paper-trading system; it is not a valid new-domain baseline.",
            "3. Existing canonical ETF Parquet is useful, but the observed raw store is insufficient to prove a full rebuild. The dataset must be imported as a versioned legacy artifact until reconstructed.",
            "4. ClawAlpha reconciliation, immutable decision hashes, anti-lookahead tests, source spans, and evidence links are valuable contracts, but their implementations require domain rewrites.",
            "5. Strategy, execution, Agent/MCP, cron, cache, and generated-output code must not enter the Clausula core dependency graph.",
            "",
            "## Migration gate",
            "",
            "No legacy implementation may be copied solely because it exists. A component may move only after its "
            "canonical Clausula contract, temporal semantics, provenance behavior, and acceptance tests are defined. "
            "Items marked `DELETE_CANDIDATE` are inventory decisions only; this scan deletes nothing.",
            "",
            "Detailed component decisions and the complete file catalog are in `migration_inventory.yaml`; data summaries "
            "are in `data_asset_catalog.yaml`; reproducible root and bundle hashes are in `source_snapshot_manifest.yaml`.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Scan and compare generated output without writing")
    args = parser.parse_args()
    generated_at = None
    manifest_path = WORKSPACE / "source_snapshot_manifest.yaml"
    if args.check and manifest_path.exists():
        try:
            generated_at = json.loads(manifest_path.read_text(encoding="utf-8"))["generated_at"]
        except (KeyError, json.JSONDecodeError):
            generated_at = None
    manifest, inventory, catalog = scan(generated_at=generated_at)
    outputs = {
        WORKSPACE / "source_snapshot_manifest.yaml": json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        WORKSPACE / "migration_inventory.yaml": json.dumps(inventory, ensure_ascii=False, indent=2) + "\n",
        WORKSPACE / "data_asset_catalog.yaml": json.dumps(catalog, ensure_ascii=False, indent=2) + "\n",
        WORKSPACE / "ARCHAEOLOGY.md": render_report(manifest, inventory, catalog),
    }
    if args.check:
        changed = [str(path.name) for path, text in outputs.items() if not path.exists() or path.read_text(encoding="utf-8") != text]
        if changed:
            print("stale:", ", ".join(changed))
            return 1
        print("archaeology outputs are current")
        return 0
    for path, text in outputs.items():
        path.write_text(text, encoding="utf-8")
    print(f"catalogued {len(inventory['file_catalog'])} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
