from __future__ import annotations

from dataclasses import dataclass
import hashlib
import sqlite3
from typing import Callable, Iterable


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


MIGRATION_METADATA_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations(
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS schema_migrations_reject_update
BEFORE UPDATE ON schema_migrations
BEGIN SELECT RAISE(ABORT, 'schema_migrations is append-only'); END;
CREATE TRIGGER IF NOT EXISTS schema_migrations_reject_delete
BEFORE DELETE ON schema_migrations
BEGIN SELECT RAISE(ABORT, 'schema_migrations is append-only'); END;
"""


MIGRATIONS = (
    Migration(
        2,
        "tamper_evident_audit_log",
        """
CREATE TABLE audit_events(
    sequence INTEGER PRIMARY KEY,
    id TEXT NOT NULL UNIQUE,
    occurred_at TEXT NOT NULL,
    actor_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    previous_hash TEXT NOT NULL,
    event_hash TEXT NOT NULL UNIQUE
);
CREATE INDEX audit_events_object ON audit_events(object_type, object_id, sequence);
CREATE TRIGGER audit_events_reject_update
BEFORE UPDATE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;
CREATE TRIGGER audit_events_reject_delete
BEFORE DELETE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;
""",
    ),
)


LATEST_SCHEMA_VERSION = max(migration.version for migration in MIGRATIONS)


def _statements(script: str) -> Iterable[str]:
    pending = ""
    for line in script.splitlines(keepends=True):
        pending += line
        if sqlite3.complete_statement(pending):
            statement = pending.strip()
            if statement:
                yield statement
            pending = ""
    if pending.strip():
        raise MigrationError("incomplete SQL migration statement")


def _execute_script(connection: sqlite3.Connection, script: str) -> None:
    for statement in _statements(script):
        connection.execute(statement)


def migrate(
    connection: sqlite3.Connection,
    *,
    baseline_sql: str,
    apply_baseline: Callable[[], None],
    now: Callable[[], str],
) -> int:
    current = connection.execute("PRAGMA user_version").fetchone()[0]
    if current > LATEST_SCHEMA_VERSION:
        raise MigrationError(
            f"database schema {current} is newer than supported schema {LATEST_SCHEMA_VERSION}"
        )

    baseline_checksum = hashlib.sha256(baseline_sql.encode("utf-8")).hexdigest()
    if current == 0:
        with connection:
            apply_baseline()
            connection.execute("PRAGMA user_version = 1")
        current = 1
    elif current == 1:
        # Version 1 predates the migration ledger. Re-applying its idempotent
        # bootstrap fills the side tables introduced during the prototype.
        with connection:
            apply_baseline()

    with connection:
        _execute_script(connection, MIGRATION_METADATA_SQL)
        connection.execute(
            """INSERT OR IGNORE INTO schema_migrations(version,name,checksum,applied_at)
               VALUES(1,'kernel_baseline',?,?)""",
            (baseline_checksum, now()),
        )

    expected = {1: ("kernel_baseline", baseline_checksum)} | {
        migration.version: (migration.name, migration.checksum) for migration in MIGRATIONS
    }
    rows = connection.execute(
        "SELECT version,name,checksum FROM schema_migrations ORDER BY version"
    ).fetchall()
    for version, name, checksum in rows:
        contract = expected.get(version)
        if contract is None:
            raise MigrationError(f"database contains unknown migration {version}: {name}")
        if contract != (name, checksum):
            raise MigrationError(f"migration checksum mismatch for version {version}: {name}")

    for migration in MIGRATIONS:
        if migration.version <= current:
            continue
        try:
            with connection:
                _execute_script(connection, migration.sql)
                connection.execute(
                    "INSERT INTO schema_migrations(version,name,checksum,applied_at) VALUES(?,?,?,?)",
                    (migration.version, migration.name, migration.checksum, now()),
                )
                connection.execute(f"PRAGMA user_version = {migration.version}")
        except sqlite3.DatabaseError as exc:
            raise MigrationError(
                f"failed to apply migration {migration.version}: {migration.name}"
            ) from exc
        current = migration.version

    return current
