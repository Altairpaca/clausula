from __future__ import annotations

import hashlib
import json
import mimetypes
import os
from pathlib import Path
import shutil
import sqlite3
from typing import Iterable

from .audit import append_audit_event, verify_audit_chain
from .backup import (
    create_backup_bundle,
    restore_backup_bundle,
    verify_backup_bundle,
    write_canonical_export,
)
from .migrations import LATEST_SCHEMA_VERSION, migrate

from clausula.domain import (
    InstrumentIdentifier,
    Transaction,
    canonical_decimal,
    canonical_timestamp,
    new_id,
    now,
    require_uuid,
)


SCHEMA_VERSION = LATEST_SCHEMA_VERSION

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts(
    id TEXT PRIMARY KEY,
    institution TEXT NOT NULL,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS instruments(
    id TEXT PRIMARY KEY,
    scheme TEXT NOT NULL,
    identifier TEXT NOT NULL,
    name TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    currency TEXT NOT NULL,
    UNIQUE(scheme, identifier)
);
CREATE TABLE IF NOT EXISTS instrument_identifiers(
    id TEXT PRIMARY KEY,
    instrument_id TEXT NOT NULL REFERENCES instruments(id),
    scheme TEXT NOT NULL,
    identifier TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    UNIQUE(scheme, identifier)
);
CREATE TABLE IF NOT EXISTS artifacts(
    id TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS artifact_details(
    artifact_id TEXT PRIMARY KEY REFERENCES artifacts(id),
    source_path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    media_type TEXT,
    artifact_kind TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS imports(
    id TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS import_details(
    import_id TEXT PRIMARY KEY REFERENCES imports(id),
    adapter_name TEXT NOT NULL,
    adapter_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    input_rows INTEGER NOT NULL,
    inserted_rows INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS transactions(
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    type TEXT NOT NULL,
    effective_at TEXT NOT NULL,
    known_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    description TEXT,
    artifact_id TEXT NOT NULL,
    import_id TEXT NOT NULL,
    external_id TEXT,
    UNIQUE(account_id, external_id)
);
CREATE TABLE IF NOT EXISTS legs(
    id INTEGER PRIMARY KEY,
    transaction_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    instrument_id TEXT,
    quantity TEXT NOT NULL,
    amount TEXT NOT NULL,
    currency TEXT NOT NULL,
    leg_type TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS imported_rows(
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(id),
    artifact_id TEXT NOT NULL REFERENCES artifacts(id),
    external_id TEXT NOT NULL,
    transaction_id TEXT NOT NULL REFERENCES transactions(id),
    UNIQUE(account_id, artifact_id, external_id)
);
CREATE TABLE IF NOT EXISTS corrections(
    correction_transaction_id TEXT PRIMARY KEY REFERENCES transactions(id),
    corrected_transaction_id TEXT REFERENCES transactions(id),
    reason TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS transfer_links(
    id TEXT PRIMARY KEY,
    source_transaction_id TEXT NOT NULL REFERENCES transactions(id),
    destination_transaction_id TEXT NOT NULL REFERENCES transactions(id),
    recorded_at TEXT NOT NULL,
    UNIQUE(source_transaction_id, destination_transaction_id)
);
CREATE TABLE IF NOT EXISTS reconciliation_records(
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(id),
    effective_at TEXT NOT NULL,
    known_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    source_artifact_id TEXT NOT NULL REFERENCES artifacts(id),
    import_batch_id TEXT NOT NULL REFERENCES imports(id),
    observed_json TEXT NOT NULL,
    derived_json TEXT NOT NULL,
    differences_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS observations(
    id INTEGER PRIMARY KEY,
    account_id TEXT NOT NULL,
    instrument_id TEXT,
    quantity TEXT NOT NULL,
    cash TEXT NOT NULL,
    as_of TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS transactions_as_of
    ON transactions(account_id, effective_at, known_at, recorded_at);
CREATE INDEX IF NOT EXISTS legs_transaction ON legs(transaction_id);
"""

APPEND_ONLY_TABLES = (
    "accounts",
    "instruments",
    "artifacts",
    "artifact_details",
    "imports",
    "import_details",
    "transactions",
    "legs",
    "instrument_identifiers",
    "imported_rows",
    "corrections",
    "transfer_links",
    "reconciliation_records",
)


class Store:
    def __init__(self, path: str | Path | None = None):
        self.root = Path(path or os.environ.get("CLAUSULA_HOME", Path.home() / ".clausula"))
        self.root.mkdir(parents=True, exist_ok=True)
        self.raw_root = self.root / "raw"
        self.raw_root.mkdir(exist_ok=True)
        self.db = sqlite3.connect(self.root / "clausula.db")
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        migrate(
            self.db,
            baseline_sql=SCHEMA,
            apply_baseline=self._apply_baseline,
            now=now,
        )

    def _apply_baseline(self) -> None:
        self.db.executescript(SCHEMA)
        self.db.execute(
            """
            INSERT OR IGNORE INTO artifact_details(
                artifact_id, source_path, size_bytes, media_type, artifact_kind
            )
            SELECT id, path, 0, NULL, 'legacy' FROM artifacts
            """
        )
        self.db.execute(
            """
            INSERT OR IGNORE INTO import_details(
                import_id, adapter_name, adapter_version, schema_version, input_rows, inserted_rows
            )
            SELECT i.id, 'legacy', 'unknown', 'pre-versioned', count(t.id), count(t.id)
            FROM imports i LEFT JOIN transactions t ON t.import_id = i.id
            GROUP BY i.id
            """
        )
        self.db.execute(
            """
            INSERT OR IGNORE INTO instrument_identifiers(id, instrument_id, scheme, identifier, recorded_at)
            SELECT lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' ||
                   substr(lower(hex(randomblob(2))), 2) || '-' ||
                   substr('89ab', abs(random()) % 4 + 1, 1) || substr(lower(hex(randomblob(2))), 2) || '-' ||
                   lower(hex(randomblob(6))), id, scheme, identifier, ?
            FROM instruments
            """,
            (now(),),
        )
        self.db.execute(
            """
            INSERT OR IGNORE INTO imported_rows(id, account_id, artifact_id, external_id, transaction_id)
            SELECT lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' ||
                   substr(lower(hex(randomblob(2))), 2) || '-' ||
                   substr('89ab', abs(random()) % 4 + 1, 1) || substr(lower(hex(randomblob(2))), 2) || '-' ||
                   lower(hex(randomblob(6))), account_id, artifact_id, external_id, id
            FROM transactions WHERE external_id IS NOT NULL
            """
        )
        for table in APPEND_ONLY_TABLES:
            self.db.executescript(
                f"""
                CREATE TRIGGER IF NOT EXISTS {table}_reject_update
                BEFORE UPDATE ON {table}
                BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS {table}_reject_delete
                BEFORE DELETE ON {table}
                BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END;
                """
            )
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def integrity_check(self) -> str:
        return self.db.execute("PRAGMA integrity_check").fetchone()[0]

    def verify_audit_chain(self) -> dict:
        return verify_audit_chain(self.db)

    def export(self, destination: str | Path) -> str:
        return write_canonical_export(self.db, destination)

    def backup_bundle(self, destination: str | Path) -> dict:
        return create_backup_bundle(self.db, self.raw_root, destination)

    def verify_backup(self, source: str | Path) -> dict:
        return verify_backup_bundle(source)

    def restore_bundle(self, source: str | Path) -> dict:
        manifest = restore_backup_bundle(self.db, self.raw_root, source)
        self.db.execute("PRAGMA foreign_keys = ON")
        self._initialize_schema()
        with self.db:
            append_audit_event(
                self.db,
                operation="system.restore",
                object_type="backup_bundle",
                object_id=manifest["sha256"],
                payload={
                    "format": manifest["format"],
                    "source_audit_head": manifest["audit_head"],
                },
            )
        return manifest

    def backup(self, destination: str | Path) -> str:
        destination_path = Path(destination)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        target = sqlite3.connect(destination_path)
        try:
            self.db.backup(target)
        finally:
            target.close()
        return str(destination_path)

    def restore(self, source: str | Path) -> None:
        source_db = sqlite3.connect(str(source))
        try:
            result = source_db.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise ValueError(f"source database integrity check failed: {result}")
            source_db.backup(self.db)
        finally:
            source_db.close()
        self.db.execute("PRAGMA foreign_keys = ON")
        self._initialize_schema()
        with self.db:
            append_audit_event(
                self.db,
                operation="system.restore",
                object_type="database",
                object_id="clausula.db",
                payload={"format": "sqlite-only-legacy"},
            )

    def artifact(self, path: str | Path) -> tuple[str, str]:
        source = Path(path).resolve()
        data = source.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        existing = self.db.execute("SELECT id FROM artifacts WHERE sha256=? ORDER BY created_at LIMIT 1", (digest,)).fetchone()
        if existing:
            return existing["id"], digest

        stored = self.raw_root / digest
        if not stored.exists():
            temporary = self.raw_root / f".{digest}.{new_id()}.tmp"
            shutil.copyfile(source, temporary)
            if hashlib.sha256(temporary.read_bytes()).hexdigest() != digest:
                temporary.unlink(missing_ok=True)
                raise IOError("raw artifact changed while being copied")
            try:
                os.link(temporary, stored)
            except FileExistsError:
                pass
            finally:
                temporary.unlink(missing_ok=True)
            stored.chmod(0o444)

        artifact_id = new_id()
        media_type = mimetypes.guess_type(source.name)[0]
        with self.db:
            self.db.execute(
                "INSERT INTO artifacts(id,path,sha256,created_at) VALUES(?,?,?,?)",
                (artifact_id, str(stored), digest, now()),
            )
            self.db.execute(
                """INSERT INTO artifact_details(
                       artifact_id,source_path,size_bytes,media_type,artifact_kind
                   ) VALUES(?,?,?,?,?)""",
                (artifact_id, str(source), len(data), media_type, "file"),
            )
            append_audit_event(
                self.db,
                operation="artifact.capture",
                object_type="source_artifact",
                object_id=artifact_id,
                payload={"sha256": digest, "size_bytes": len(data), "kind": "file"},
            )
        return artifact_id, digest

    def virtual_artifact(self, uri: str, content: str) -> tuple[str, str]:
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        existing = self.db.execute(
            "SELECT id FROM artifacts WHERE path=? AND sha256=? ORDER BY created_at LIMIT 1",
            (uri, digest),
        ).fetchone()
        if existing:
            return existing["id"], digest
        artifact_id = new_id()
        with self.db:
            self.db.execute(
                "INSERT INTO artifacts(id,path,sha256,created_at) VALUES(?,?,?,?)",
                (artifact_id, uri, digest, now()),
            )
            self.db.execute(
                "INSERT INTO artifact_details VALUES(?,?,?,?,?)",
                (artifact_id, uri, len(content.encode("utf-8")), "text/plain", "manual"),
            )
            append_audit_event(
                self.db,
                operation="artifact.capture",
                object_type="source_artifact",
                object_id=artifact_id,
                payload={
                    "sha256": digest,
                    "size_bytes": len(content.encode("utf-8")),
                    "kind": "manual",
                    "uri": uri,
                },
            )
        return artifact_id, digest

    def create_account(self, institution: str, name: str) -> str:
        if not institution.strip() or not name.strip():
            raise ValueError("institution and account name are required")
        account_id = new_id()
        with self.db:
            self.db.execute(
                "INSERT INTO accounts VALUES(?,?,?,?)",
                (account_id, institution.strip(), name.strip(), now()),
            )
            append_audit_event(
                self.db,
                operation="account.create",
                object_type="account",
                object_id=account_id,
                payload={"institution": institution.strip(), "name": name.strip()},
            )
        return account_id

    def account(self, account_id: str) -> sqlite3.Row | None:
        require_uuid(account_id, "account_id")
        return self.db.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()

    def require_account(self, account_id: str) -> sqlite3.Row:
        row = self.account(account_id)
        if row is None:
            raise KeyError(f"unknown account: {account_id}")
        return row

    def instrument(
        self,
        identifier: InstrumentIdentifier,
        name: str = "",
        asset_type: str = "stock",
        currency: str = "USD",
    ) -> str:
        row = self.db.execute(
            "SELECT instrument_id FROM instrument_identifiers WHERE scheme=? AND identifier=?",
            (identifier.scheme, identifier.value),
        ).fetchone()
        if row:
            return row["instrument_id"]
        instrument_id = new_id()
        with self.db:
            self.db.execute(
                "INSERT INTO instruments VALUES(?,?,?,?,?,?)",
                (
                    instrument_id,
                    identifier.scheme,
                    identifier.value,
                    name.strip() or identifier.value,
                    asset_type.strip().lower(),
                    currency.strip().upper(),
                ),
            )
            self.db.execute(
                "INSERT INTO instrument_identifiers VALUES(?,?,?,?,?)",
                (new_id(), instrument_id, identifier.scheme, identifier.value, now()),
            )
            append_audit_event(
                self.db,
                operation="instrument.resolve",
                object_type="instrument",
                object_id=instrument_id,
                payload={
                    "scheme": identifier.scheme,
                    "identifier": identifier.value,
                    "asset_type": asset_type.strip().lower(),
                    "currency": currency.strip().upper(),
                },
            )
        return instrument_id

    def import_batch(
        self,
        artifact_id: str,
        *,
        adapter_name: str = "manual",
        adapter_version: str = "1",
        schema_version: str = "1",
    ) -> str:
        batch_id = new_id()
        with self.db:
            self._insert_import_batch(
                batch_id,
                artifact_id,
                adapter_name,
                adapter_version,
                schema_version,
                0,
                0,
            )
            append_audit_event(
                self.db,
                operation="import.create",
                object_type="import_batch",
                object_id=batch_id,
                payload={
                    "artifact_id": artifact_id,
                    "adapter_name": adapter_name,
                    "adapter_version": adapter_version,
                    "schema_version": schema_version,
                    "input_rows": 0,
                    "inserted_rows": 0,
                },
            )
        return batch_id

    def _insert_import_batch(
        self,
        batch_id: str,
        artifact_id: str,
        adapter_name: str,
        adapter_version: str,
        schema_version: str,
        input_rows: int,
        inserted_rows: int,
    ) -> None:
        require_uuid(batch_id, "batch_id")
        require_uuid(artifact_id, "artifact_id")
        if self.db.execute("SELECT 1 FROM artifacts WHERE id=?", (artifact_id,)).fetchone() is None:
            raise KeyError(f"unknown artifact: {artifact_id}")
        self.db.execute("INSERT INTO imports VALUES(?,?,?)", (batch_id, artifact_id, now()))
        self.db.execute(
            "INSERT INTO import_details VALUES(?,?,?,?,?,?)",
            (batch_id, adapter_name, adapter_version, schema_version, input_rows, inserted_rows),
        )

    def add_import(
        self,
        batch_id: str,
        artifact_id: str,
        entries: Iterable[tuple[Transaction, str]],
        *,
        adapter_name: str,
        adapter_version: str,
        schema_version: str,
    ) -> int:
        materialized = list(entries)
        pending: list[tuple[Transaction, str]] = []
        for transaction, external_id in materialized:
            duplicate = self.db.execute(
                "SELECT 1 FROM imported_rows WHERE account_id=? AND artifact_id=? AND external_id=?",
                (transaction.account_id, artifact_id, external_id),
            ).fetchone()
            if duplicate is None:
                pending.append((transaction, external_id))

        with self.db:
            self._insert_import_batch(
                batch_id,
                artifact_id,
                adapter_name,
                adapter_version,
                schema_version,
                len(materialized),
                len(pending),
            )
            for transaction, external_id in pending:
                self._insert_transaction(transaction)
                self.db.execute(
                    "INSERT INTO imported_rows VALUES(?,?,?,?,?)",
                    (new_id(), transaction.account_id, artifact_id, external_id, transaction.id),
                )
                self._audit_transaction(transaction)
            append_audit_event(
                self.db,
                operation="import.create",
                object_type="import_batch",
                object_id=batch_id,
                payload={
                    "artifact_id": artifact_id,
                    "adapter_name": adapter_name,
                    "adapter_version": adapter_version,
                    "schema_version": schema_version,
                    "input_rows": len(materialized),
                    "inserted_rows": len(pending),
                },
            )
        return len(pending)

    def add_transaction(self, transaction: Transaction, external_id: str | None = None) -> bool:
        if external_id is not None:
            duplicate = self.db.execute(
                """SELECT 1 FROM imported_rows
                   WHERE account_id=? AND artifact_id=? AND external_id=?""",
                (transaction.account_id, transaction.source_artifact_id, external_id),
            ).fetchone()
            if duplicate:
                return False
        with self.db:
            self._insert_transaction(transaction)
            if external_id is not None:
                self.db.execute(
                    "INSERT INTO imported_rows VALUES(?,?,?,?,?)",
                    (
                        new_id(),
                        transaction.account_id,
                        transaction.source_artifact_id,
                        external_id,
                        transaction.id,
                    ),
                )
            self._audit_transaction(transaction)
        return True

    def add_transfer(
        self,
        transfer_id: str,
        source_transaction: Transaction,
        destination_transaction: Transaction,
    ) -> None:
        require_uuid(transfer_id, "transfer_id")
        if source_transaction.account_id == destination_transaction.account_id:
            raise ValueError("transfer accounts must be distinct")
        with self.db:
            self._insert_transaction(source_transaction)
            self._insert_transaction(destination_transaction)
            self.db.execute(
                "INSERT INTO transfer_links VALUES(?,?,?,?)",
                (transfer_id, source_transaction.id, destination_transaction.id, now()),
            )
            self._audit_transaction(source_transaction)
            self._audit_transaction(destination_transaction)
            append_audit_event(
                self.db,
                operation="ledger.record_transfer",
                object_type="transfer",
                object_id=transfer_id,
                payload={
                    "source_transaction_id": source_transaction.id,
                    "destination_transaction_id": destination_transaction.id,
                },
            )

    def _audit_transaction(self, transaction: Transaction) -> None:
        append_audit_event(
            self.db,
            operation=f"ledger.{transaction.type}",
            object_type="transaction",
            object_id=transaction.id,
            payload={
                "account_id": transaction.account_id,
                "effective_at": transaction.effective_at,
                "known_at": transaction.known_at,
                "recorded_at": transaction.recorded_at,
                "source_artifact_id": transaction.source_artifact_id,
                "import_batch_id": transaction.import_batch_id,
                "leg_count": len(transaction.legs),
                "corrects_transaction_id": transaction.corrects_transaction_id,
            },
        )

    def _insert_transaction(self, transaction: Transaction) -> None:
        self.require_account(transaction.account_id)
        artifact = self.db.execute(
            "SELECT 1 FROM artifacts WHERE id=?", (transaction.source_artifact_id,)
        ).fetchone()
        batch = self.db.execute(
            "SELECT artifact_id FROM imports WHERE id=?", (transaction.import_batch_id,)
        ).fetchone()
        if artifact is None or batch is None:
            raise ValueError("transaction provenance must reference an existing artifact and import batch")
        if batch["artifact_id"] != transaction.source_artifact_id:
            raise ValueError("transaction artifact must match its import batch artifact")
        if transaction.corrects_transaction_id is not None:
            corrected = self.db.execute(
                "SELECT account_id FROM transactions WHERE id=?", (transaction.corrects_transaction_id,)
            ).fetchone()
            if corrected is None or corrected["account_id"] != transaction.account_id:
                raise ValueError("corrected transaction must exist in the same account")

        self.db.execute(
            """INSERT INTO transactions(
                   id,account_id,type,effective_at,known_at,recorded_at,description,
                   artifact_id,import_id,external_id
               ) VALUES(?,?,?,?,?,?,?,?,?,NULL)""",
            (
                transaction.id,
                transaction.account_id,
                transaction.type,
                transaction.effective_at,
                transaction.known_at,
                transaction.recorded_at,
                transaction.description,
                transaction.source_artifact_id,
                transaction.import_batch_id,
            ),
        )
        for leg in transaction.legs:
            self.require_account(leg.account_id)
            if leg.instrument_id is not None and self.db.execute(
                "SELECT 1 FROM instruments WHERE id=?", (leg.instrument_id,)
            ).fetchone() is None:
                raise KeyError(f"unknown instrument: {leg.instrument_id}")
            self.db.execute(
                """INSERT INTO legs(
                       transaction_id,account_id,instrument_id,quantity,amount,currency,leg_type
                   ) VALUES(?,?,?,?,?,?,?)""",
                (
                    transaction.id,
                    leg.account_id,
                    leg.instrument_id,
                    canonical_decimal(leg.quantity),
                    canonical_decimal(leg.amount),
                    leg.currency,
                    leg.leg_type,
                ),
            )
        if transaction.type == "correction":
            self.db.execute(
                "INSERT INTO corrections VALUES(?,?,?)",
                (transaction.id, transaction.corrects_transaction_id, transaction.description),
            )

    def transactions(self, account_id: str, as_of: str | None = None) -> list[sqlite3.Row]:
        self.require_account(account_id)
        query = "SELECT * FROM transactions WHERE account_id=?"
        arguments: list[str] = [account_id]
        if as_of is not None:
            cutoff = canonical_timestamp(as_of)
            query += " AND effective_at<=? AND known_at<=?"
            arguments.extend((cutoff, cutoff))
        return self.db.execute(
            query + " ORDER BY effective_at, known_at, recorded_at, id", arguments
        ).fetchall()

    def transaction(self, transaction_id: str) -> sqlite3.Row | None:
        require_uuid(transaction_id, "transaction_id")
        return self.db.execute("SELECT * FROM transactions WHERE id=?", (transaction_id,)).fetchone()

    def legs(self, transaction_id: str) -> list[sqlite3.Row]:
        require_uuid(transaction_id, "transaction_id")
        return self.db.execute(
            "SELECT * FROM legs WHERE transaction_id=? ORDER BY id", (transaction_id,)
        ).fetchall()

    def record_reconciliation(
        self,
        *,
        account_id: str,
        effective_at: str,
        known_at: str,
        source_artifact_id: str,
        import_batch_id: str,
        observed: dict,
        derived: dict,
        differences: list[dict],
    ) -> str:
        record_id = new_id()
        normalized_effective_at = canonical_timestamp(effective_at)
        normalized_known_at = canonical_timestamp(known_at)
        recorded_at = now()
        if normalized_known_at > recorded_at:
            raise ValueError("known_at cannot be after recorded_at")
        with self.db:
            self.db.execute(
                "INSERT INTO reconciliation_records VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    record_id,
                    account_id,
                    normalized_effective_at,
                    normalized_known_at,
                    recorded_at,
                    source_artifact_id,
                    import_batch_id,
                    json.dumps(observed, sort_keys=True, separators=(",", ":")),
                    json.dumps(derived, sort_keys=True, separators=(",", ":")),
                    json.dumps(differences, sort_keys=True, separators=(",", ":")),
                ),
            )
            append_audit_event(
                self.db,
                operation="ledger.reconcile",
                object_type="reconciliation",
                object_id=record_id,
                payload={
                    "account_id": account_id,
                    "effective_at": normalized_effective_at,
                    "known_at": normalized_known_at,
                    "source_artifact_id": source_artifact_id,
                    "import_batch_id": import_batch_id,
                    "difference_count": len(differences),
                },
            )
        return record_id
