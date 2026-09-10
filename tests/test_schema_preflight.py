from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3

from clausula import Store
from clausula.adapters.migrations import LATEST_SCHEMA_VERSION
from clausula.adapters.schema_preflight import inspect_database_schema
from clausula.adapters.sqlite import SCHEMA


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_schema_preflight_does_not_create_missing_database(tmp_path: Path) -> None:
    database = tmp_path / "missing.db"

    report = inspect_database_schema(database, baseline_sql=SCHEMA)

    assert report.compatible is True
    assert report.status == "uninitialized"
    assert report.current_version == 0
    assert report.target_version == LATEST_SCHEMA_VERSION
    assert report.pending_migrations[0].version == 1
    assert not database.exists()


def test_schema_preflight_reports_current_database_without_mutation(tmp_path: Path) -> None:
    home = tmp_path / "home"
    store = Store(home)
    store.close()
    database = home / "clausula.db"
    before = _sha256(database)

    report = inspect_database_schema(database, baseline_sql=SCHEMA)

    assert report.compatible is True
    assert report.status == "ready"
    assert report.current_version == LATEST_SCHEMA_VERSION
    assert report.pending_migrations == ()
    assert report.migration_ledger_present is True
    assert report.integrity == "ok"
    assert {row["version"] for row in report.observed_migrations} == set(
        range(1, LATEST_SCHEMA_VERSION + 1)
    )
    assert _sha256(database) == before


def test_schema_preflight_accepts_legacy_v1_as_forward_upgrade_candidate(tmp_path: Path) -> None:
    database = tmp_path / "legacy.db"
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA user_version = 1")
    connection.commit()
    connection.close()

    report = inspect_database_schema(database, baseline_sql=SCHEMA)

    assert report.compatible is True
    assert report.status == "upgrade_required"
    assert report.current_version == 1
    assert report.migration_ledger_present is False
    assert report.pending_migrations[0].version == 2
    assert any("predates the migration ledger" in warning for warning in report.warnings)


def test_schema_preflight_rejects_database_newer_than_runtime(tmp_path: Path) -> None:
    database = tmp_path / "future.db"
    connection = sqlite3.connect(database)
    connection.execute(f"PRAGMA user_version = {LATEST_SCHEMA_VERSION + 1}")
    connection.commit()
    connection.close()

    report = inspect_database_schema(database, baseline_sql=SCHEMA)

    assert report.compatible is False
    assert report.status == "unsupported_newer"
    assert any("newer than supported" in error for error in report.errors)


def test_schema_preflight_detects_migration_checksum_tampering(tmp_path: Path) -> None:
    home = tmp_path / "home"
    store = Store(home)
    store.close()
    database = home / "clausula.db"

    connection = sqlite3.connect(database)
    connection.execute("DROP TRIGGER schema_migrations_reject_update")
    connection.execute(
        "UPDATE schema_migrations SET checksum=? WHERE version=?",
        ("0" * 64, LATEST_SCHEMA_VERSION),
    )
    connection.commit()
    connection.close()

    report = inspect_database_schema(database, baseline_sql=SCHEMA)

    assert report.compatible is False
    assert report.status == "inconsistent"
    assert any("checksum mismatch" in error for error in report.errors)


def test_schema_preflight_detects_missing_migration_ledger(tmp_path: Path) -> None:
    database = tmp_path / "missing-ledger.db"
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA user_version = 2")
    connection.commit()
    connection.close()

    report = inspect_database_schema(database, baseline_sql=SCHEMA)

    assert report.compatible is False
    assert report.status == "inconsistent"
    assert any("migration" in error and "missing" in error for error in report.errors)
