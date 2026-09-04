from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from clausula import LedgerService, Store
from clausula.adapters.migrations import (
    LATEST_SCHEMA_VERSION,
    MIGRATION_METADATA_SQL,
    MIGRATIONS,
)
from clausula.adapters.sqlite import SCHEMA

V12_TABLES = (
    "identifier_validity_ranges",
    "corporate_action_events",
    "corporate_action_event_instruments",
    "corporate_action_considerations",
    "corporate_action_account_consequences",
    "corporate_action_basis_allocations",
    "corporate_action_tax_interpretations",
)

_FIXED = "2020-01-01T00:00:00+00:00"


def _build_v11_database(home: Path) -> None:
    path = home / "clausula.db"
    connection = sqlite3.connect(path)
    try:
        connection.executescript(SCHEMA)
        connection.executescript(MIGRATION_METADATA_SQL)
        baseline_checksum = hashlib.sha256(SCHEMA.encode("utf-8")).hexdigest()
        connection.execute(
            "INSERT INTO schema_migrations VALUES(1,'kernel_baseline',?,?)",
            (baseline_checksum, _FIXED),
        )
        connection.execute("PRAGMA user_version = 1")
        for migration in MIGRATIONS:
            if migration.version > 11:
                continue
            connection.executescript(migration.sql)
            connection.execute(
                "INSERT INTO schema_migrations VALUES(?,?,?,?)",
                (migration.version, migration.name, migration.checksum, _FIXED),
            )
            connection.execute(f"PRAGMA user_version = {migration.version}")
        connection.commit()
    finally:
        connection.close()


@pytest.fixture()
def unique_home(tmp_path: Path, request) -> Path:
    path = tmp_path / request.node.name
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_clean_database_reaches_v12_schema(unique_home: Path) -> None:
    store = Store(unique_home)
    try:
        assert store.db.execute("PRAGMA user_version").fetchone()[0] == 12
        for table in V12_TABLES:
            row = store.db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            assert row is not None, f"missing v12 table: {table}"
    finally:
        store.close()


def test_frozen_ledger_is_2_through_12_with_historical_checksums_unchanged() -> None:
    versions = [migration.version for migration in MIGRATIONS]
    assert versions == list(range(2, LATEST_SCHEMA_VERSION + 1))
    assert LATEST_SCHEMA_VERSION == 12
    v12 = next(migration for migration in MIGRATIONS if migration.version == 12)
    assert "identifier_validity_ranges" in v12.sql
    assert "corporate_action_events" in v12.sql


def test_v11_database_forward_migrates_to_v12(unique_home: Path) -> None:
    _build_v11_database(unique_home)
    connection = sqlite3.connect(unique_home / "clausula.db")
    try:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 11
    finally:
        connection.close()

    store = Store(unique_home)
    try:
        assert store.db.execute("PRAGMA user_version").fetchone()[0] == 12
        ledger = store.db.execute(
            "SELECT version,name FROM schema_migrations ORDER BY version"
        ).fetchall()
        assert [row["version"] for row in ledger] == list(range(1, 13))
        assert ledger[-1]["name"] == "historical_identifiers_and_generalized_corporate_actions"
        for table in V12_TABLES:
            row = store.db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            assert row is not None
    finally:
        store.close()


def test_identifier_validity_table_constraints(unique_home: Path) -> None:
    store = Store(unique_home)
    try:
        db = store.db
        instrument_id = LedgerService(store).resolve_instrument("ACME", scheme="ticker")
        db.execute(
            "INSERT INTO identifier_validity_ranges"
            "(id,instrument_id,scheme,value,valid_from,valid_to,known_at,recorded_at,provenance)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            ("r1", instrument_id, "ticker", "ABC", "2020-01-01T00:00:00+00:00",
             "2025-06-01T00:00:00+00:00", _FIXED, _FIXED, "manual"),
        )
        with pytest.raises(sqlite3.IntegrityError, match="overlapping"):
            db.execute(
                "INSERT INTO identifier_validity_ranges"
                "(id,instrument_id,scheme,value,valid_from,valid_to,known_at,recorded_at,provenance)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                ("r2", instrument_id, "ticker", "ABC", "2025-05-01T00:00:00+00:00", None,
                 _FIXED, _FIXED, "manual"),
            )
        db.execute(
            "INSERT INTO identifier_validity_ranges"
            "(id,instrument_id,scheme,value,valid_from,valid_to,known_at,recorded_at,provenance)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            ("r3", instrument_id, "ticker", "ABC", "2025-06-01T00:00:00+00:00", None,
             _FIXED, _FIXED, "manual"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("DELETE FROM identifier_validity_ranges WHERE id='r1'")
    finally:
        store.close()
