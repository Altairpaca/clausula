from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import tempfile
from typing import Any, Iterable
import zipfile

from .audit import canonical_json, verify_audit_chain


BACKUP_FORMAT = "clausula-backup-v1"
EXPORT_FORMAT = "clausula-canonical-jsonl-v1"
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)

EXPORT_TABLES = (
    "accounts",
    "instruments",
    "instrument_identifiers",
    "artifacts",
    "artifact_details",
    "imports",
    "import_details",
    "transactions",
    "transaction_order",
    "legs",
    "imported_rows",
    "corrections",
    "transfer_links",
    "reconciliation_records",
    "reconciliation_observations",
    "fx_conversions",
    "security_transfers",
    "security_transfer_allocations",
    "corporate_actions",
    "audit_events",
    "schema_migrations",
    "market_datasets",
    "market_prices",
    "market_fx_rates",
    "portfolios",
    "portfolio_membership_events",
    "investment_policies",
    "policy_versions",
    "policy_rules",
    "plans",
    "plan_scenarios",
    "plan_actions",
    "plan_projected_states",
    "plan_constraints",
    "decisions",
    "decision_alternatives",
    "decision_policy_links",
    "decision_evidence_links",
    "decision_transaction_links",
    "decision_reviews",
    "decision_statements",
    "decision_review_schedules",
    "research_documents",
    "research_claims",
    "research_evidence",
    "research_contradictions",
    "research_theses",
    "thesis_revisions",
    "research_links",
    "recommendations",
    "recommendation_alternatives",
    "recommendation_transitions",
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100444 << 16
    return info


def _write_entry(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    archive.writestr(_zip_info(name), data)


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def canonical_export(connection: sqlite3.Connection) -> bytes:
    lines = [canonical_json({"format": EXPORT_FORMAT})]
    for table in EXPORT_TABLES:
        if not _table_exists(connection, table):
            continue
        columns = [row[1] for row in connection.execute(f"PRAGMA table_info({table})")]
        order = ",".join(f'"{column}"' for column in columns)
        for row in connection.execute(f'SELECT * FROM "{table}" ORDER BY {order}'):
            lines.append(
                canonical_json(
                    {
                        "table": table,
                        "record": {column: row[index] for index, column in enumerate(columns)},
                    }
                )
            )
    return ("\n".join(lines) + "\n").encode("utf-8")


def write_canonical_export(connection: sqlite3.Connection, destination: str | Path) -> str:
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_export(connection))
    return str(path)


def _snapshot_database(connection: sqlite3.Connection, destination: Path) -> None:
    target = sqlite3.connect(destination)
    try:
        connection.backup(target)
    finally:
        target.close()


def _artifact_files(connection: sqlite3.Connection, raw_root: Path) -> Iterable[tuple[str, bytes]]:
    if not _table_exists(connection, "artifacts"):
        return
    for row in connection.execute("SELECT path,sha256 FROM artifacts ORDER BY sha256"):
        digest = row["sha256"]
        candidates = [raw_root / digest, Path(row["path"])]
        candidates.extend(sorted(raw_root.glob(f"{digest}.*")))
        source = next((candidate for candidate in candidates if candidate.is_file()), None)
        if source is None:
            if str(row["path"]).startswith("manual://"):
                continue
            raise FileNotFoundError(f"raw artifact is missing: {digest}")
        data = source.read_bytes()
        if sha256_bytes(data) != digest:
            raise ValueError(f"raw artifact hash mismatch: {source}")
        yield f"raw/{digest}", data


def create_backup_bundle(
    connection: sqlite3.Connection,
    raw_root: Path,
    destination: str | Path,
) -> dict[str, Any]:
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="clausula-backup-") as temporary:
        snapshot = Path(temporary) / "clausula.db"
        _snapshot_database(connection, snapshot)
        with sqlite3.connect(snapshot) as check:
            check.row_factory = sqlite3.Row
            integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
            audit = verify_audit_chain(check)
            schema_version = check.execute("PRAGMA user_version").fetchone()[0]
            export = canonical_export(check)
        if integrity != "ok":
            raise ValueError(f"database integrity check failed before backup: {integrity}")
        if not audit["valid"]:
            raise ValueError(f"audit chain invalid before backup: {audit['error']}")

        entries: dict[str, bytes] = {
            "database/clausula.db": snapshot.read_bytes(),
            "export/canonical.jsonl": export,
        }
        entries.update(dict(_artifact_files(connection, raw_root)))
        manifest = {
            "format": BACKUP_FORMAT,
            "schema_version": schema_version,
            "audit_head": audit["head"],
            "files": {
                name: {"sha256": sha256_bytes(data), "size_bytes": len(data)}
                for name, data in sorted(entries.items())
            },
        }
        manifest_data = (canonical_json(manifest) + "\n").encode("utf-8")
        with zipfile.ZipFile(path, "w") as archive:
            _write_entry(archive, "manifest.json", manifest_data)
            for name, data in sorted(entries.items()):
                _write_entry(archive, name, data)
    return manifest | {"path": str(path), "sha256": sha256_bytes(path.read_bytes())}


def _safe_entries(archive: zipfile.ZipFile) -> list[str]:
    names = archive.namelist()
    if len(names) != len(set(names)):
        raise ValueError("backup contains duplicate paths")
    for name in names:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name:
            raise ValueError(f"unsafe backup path: {name}")
    return names


def verify_backup_bundle(source: str | Path) -> dict[str, Any]:
    path = Path(source)
    with zipfile.ZipFile(path) as archive:
        names = _safe_entries(archive)
        if "manifest.json" not in names:
            raise ValueError("backup manifest is missing")
        manifest = json.loads(archive.read("manifest.json"))
        if manifest.get("format") != BACKUP_FORMAT:
            raise ValueError("unsupported backup format")
        expected_names = {"manifest.json", *manifest.get("files", {})}
        if set(names) != expected_names:
            raise ValueError("backup entries do not match manifest")
        for name, expected in manifest["files"].items():
            data = archive.read(name)
            if len(data) != expected["size_bytes"] or sha256_bytes(data) != expected["sha256"]:
                raise ValueError(f"backup file hash mismatch: {name}")
        with tempfile.TemporaryDirectory(prefix="clausula-verify-") as temporary:
            database = Path(temporary) / "clausula.db"
            database.write_bytes(archive.read("database/clausula.db"))
            with sqlite3.connect(database) as connection:
                connection.row_factory = sqlite3.Row
                integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
                audit = verify_audit_chain(connection)
                schema_version = connection.execute("PRAGMA user_version").fetchone()[0]
                artifact_hashes = {
                    row["sha256"]
                    for row in connection.execute("SELECT sha256 FROM artifacts")
                } if _table_exists(connection, "artifacts") else set()
            if integrity != "ok":
                raise ValueError(f"backup database integrity check failed: {integrity}")
            if not audit["valid"]:
                raise ValueError(f"backup audit chain is invalid: {audit['error']}")
            if audit["head"] != manifest["audit_head"]:
                raise ValueError("backup audit head does not match manifest")
            if schema_version != manifest["schema_version"]:
                raise ValueError("backup schema version does not match manifest")
            for digest in artifact_hashes:
                name = f"raw/{digest}"
                if name not in manifest["files"]:
                    raise ValueError(f"backup is missing raw artifact: {digest}")
                if sha256_bytes(archive.read(name)) != digest:
                    raise ValueError(f"raw artifact filename/hash mismatch: {name}")
    return manifest | {"path": str(path), "sha256": sha256_bytes(path.read_bytes()), "valid": True}


def restore_backup_bundle(
    connection: sqlite3.Connection,
    raw_root: Path,
    source: str | Path,
) -> dict[str, Any]:
    manifest = verify_backup_bundle(source)
    with zipfile.ZipFile(source) as archive, tempfile.TemporaryDirectory(
        prefix="clausula-restore-"
    ) as temporary:
        raw_entries: list[tuple[str, bytes]] = []
        for name in sorted(manifest["files"]):
            if not name.startswith("raw/"):
                continue
            digest = name.removeprefix("raw/")
            data = archive.read(name)
            if sha256_bytes(data) != digest:
                raise ValueError(f"raw artifact filename/hash mismatch: {name}")
            target = raw_root / digest
            if target.exists() and sha256_bytes(target.read_bytes()) != digest:
                raise ValueError(f"existing raw artifact conflicts with backup: {digest}")
            raw_entries.append((digest, data))

        database = Path(temporary) / "clausula.db"
        database.write_bytes(archive.read("database/clausula.db"))
        source_db = sqlite3.connect(database)
        try:
            source_db.backup(connection)
        finally:
            source_db.close()
        raw_root.mkdir(parents=True, exist_ok=True)
        for digest, data in raw_entries:
            target = raw_root / digest
            if not target.exists():
                target.write_bytes(data)
                target.chmod(0o444)
    return manifest
