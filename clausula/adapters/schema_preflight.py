from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import sqlite3
from typing import Any

from .migrations import LATEST_SCHEMA_VERSION, MIGRATIONS


@dataclass(frozen=True, slots=True)
class SchemaMigrationStep:
    version: int
    name: str

    def as_dict(self) -> dict[str, Any]:
        return {"version": self.version, "name": self.name}


@dataclass(frozen=True, slots=True)
class SchemaPreflightReport:
    database_path: str
    exists: bool
    current_version: int | None
    target_version: int
    status: str
    integrity: str
    migration_ledger_present: bool
    observed_migrations: tuple[dict[str, Any], ...]
    pending_migrations: tuple[SchemaMigrationStep, ...]
    errors: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def compatible(self) -> bool:
        return self.status in {"uninitialized", "upgrade_required", "ready"} and not self.errors

    def as_dict(self) -> dict[str, Any]:
        return {
            "compatible": self.compatible,
            "database_path": self.database_path,
            "exists": self.exists,
            "current_version": self.current_version,
            "target_version": self.target_version,
            "status": self.status,
            "integrity": self.integrity,
            "migration_ledger_present": self.migration_ledger_present,
            "observed_migrations": list(self.observed_migrations),
            "pending_migrations": [step.as_dict() for step in self.pending_migrations],
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


def _pending_steps(current_version: int) -> tuple[SchemaMigrationStep, ...]:
    steps: list[SchemaMigrationStep] = []
    if current_version < 1:
        steps.append(SchemaMigrationStep(1, "kernel_baseline"))
    steps.extend(
        SchemaMigrationStep(migration.version, migration.name)
        for migration in MIGRATIONS
        if migration.version > current_version
    )
    return tuple(steps)


def inspect_database_schema(
    path: str | Path,
    *,
    baseline_sql: str | None = None,
) -> SchemaPreflightReport:
    """Inspect migration compatibility without opening Clausula's writable Store.

    The database is opened with SQLite `mode=ro`. The function never creates a
    database, applies schema SQL, changes `user_version`, or repairs the migration
    ledger. It is intended for startup/release evidence before normal Store
    initialization performs forward migrations.
    """

    database = Path(path).expanduser().resolve()
    target = LATEST_SCHEMA_VERSION
    if not database.exists():
        return SchemaPreflightReport(
            database_path=str(database),
            exists=False,
            current_version=0,
            target_version=target,
            status="uninitialized",
            integrity="not_applicable",
            migration_ledger_present=False,
            observed_migrations=(),
            pending_migrations=_pending_steps(0),
            errors=(),
            warnings=("database does not exist; Store initialization will create it",),
        )

    errors: list[str] = []
    warnings: list[str] = []
    observed: list[dict[str, Any]] = []
    current: int | None = None
    integrity = "unknown"
    ledger_present = False

    try:
        connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    except sqlite3.DatabaseError as exc:
        return SchemaPreflightReport(
            database_path=str(database),
            exists=True,
            current_version=None,
            target_version=target,
            status="unreadable",
            integrity="unreadable",
            migration_ledger_present=False,
            observed_migrations=(),
            pending_migrations=(),
            errors=(f"database could not be opened read-only: {exc}",),
            warnings=(),
        )

    try:
        current = int(connection.execute("PRAGMA user_version").fetchone()[0])
        integrity = str(connection.execute("PRAGMA quick_check").fetchone()[0])
        if integrity.lower() != "ok":
            errors.append(f"SQLite quick_check failed: {integrity}")

        ledger_present = (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
            ).fetchone()
            is not None
        )
        if ledger_present:
            rows = connection.execute(
                "SELECT version,name,checksum,applied_at FROM schema_migrations ORDER BY version"
            ).fetchall()
            expected = {
                migration.version: (migration.name, migration.checksum)
                for migration in MIGRATIONS
            }
            baseline_checksum = (
                hashlib.sha256(baseline_sql.encode("utf-8")).hexdigest()
                if baseline_sql is not None
                else None
            )
            expected[1] = ("kernel_baseline", baseline_checksum)

            seen_versions: set[int] = set()
            for version, name, checksum, applied_at in rows:
                version = int(version)
                seen_versions.add(version)
                observed.append(
                    {
                        "version": version,
                        "name": str(name),
                        "checksum": str(checksum),
                        "applied_at": str(applied_at),
                    }
                )
                contract = expected.get(version)
                if contract is None:
                    errors.append(f"unknown migration ledger entry {version}: {name}")
                    continue
                expected_name, expected_checksum = contract
                if str(name) != expected_name:
                    errors.append(
                        f"migration {version} name mismatch: expected {expected_name}, got {name}"
                    )
                if expected_checksum is not None and str(checksum) != expected_checksum:
                    errors.append(f"migration {version} checksum mismatch: {name}")

            expected_applied = {
                version for version in expected if current is not None and version <= current
            }
            missing = sorted(expected_applied - seen_versions)
            if missing:
                errors.append(
                    "migration ledger is missing applied versions: "
                    + ", ".join(str(version) for version in missing)
                )
        elif current >= 2:
            errors.append(
                "schema_migrations ledger is missing for a versioned database at schema >= 2"
            )
        elif current == 1:
            warnings.append(
                "legacy schema v1 predates the migration ledger; normal Store startup will bootstrap it"
            )

        if current > target:
            errors.append(
                f"database schema {current} is newer than supported schema {target}"
            )
            status = "unsupported_newer"
        elif errors:
            status = "inconsistent"
        elif current == target:
            status = "ready"
        elif current == 0:
            status = "uninitialized"
        else:
            status = "upgrade_required"

        pending = _pending_steps(current) if current <= target else ()
        return SchemaPreflightReport(
            database_path=str(database),
            exists=True,
            current_version=current,
            target_version=target,
            status=status,
            integrity=integrity,
            migration_ledger_present=ledger_present,
            observed_migrations=tuple(observed),
            pending_migrations=pending,
            errors=tuple(errors),
            warnings=tuple(warnings),
        )
    except sqlite3.DatabaseError as exc:
        return SchemaPreflightReport(
            database_path=str(database),
            exists=True,
            current_version=current,
            target_version=target,
            status="unreadable",
            integrity=integrity,
            migration_ledger_present=ledger_present,
            observed_migrations=tuple(observed),
            pending_migrations=(),
            errors=(f"schema inspection failed: {exc}",),
            warnings=tuple(warnings),
        )
    finally:
        connection.close()
