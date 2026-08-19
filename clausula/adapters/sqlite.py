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
    CorporateAction,
    DatasetVersion,
    FxRate,
    FxConversion,
    InstrumentIdentifier,
    MarketPrice,
    Portfolio,
    PortfolioMembershipEvent,
    SecurityTransfer,
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
                (artifact_id, f"raw/{digest}", digest, now()),
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
        data = content.encode("utf-8")
        digest = hashlib.sha256(data).hexdigest()
        existing = self.db.execute(
            """SELECT a.id FROM artifacts a
               JOIN artifact_details d ON d.artifact_id=a.id
               WHERE d.source_path=? AND a.sha256=? ORDER BY a.created_at LIMIT 1""",
            (uri, digest),
        ).fetchone()
        if existing:
            return existing["id"], digest
        stored = self.raw_root / digest
        if not stored.exists():
            temporary = self.raw_root / f".{digest}.{new_id()}.tmp"
            temporary.write_bytes(data)
            try:
                os.link(temporary, stored)
            except FileExistsError:
                pass
            finally:
                temporary.unlink(missing_ok=True)
            stored.chmod(0o444)
        artifact_id = new_id()
        with self.db:
            self.db.execute(
                "INSERT INTO artifacts(id,path,sha256,created_at) VALUES(?,?,?,?)",
                (artifact_id, f"raw/{digest}", digest, now()),
            )
            self.db.execute(
                "INSERT INTO artifact_details VALUES(?,?,?,?,?)",
                (artifact_id, uri, len(data), "application/json", "manual"),
            )
            append_audit_event(
                self.db,
                operation="artifact.capture",
                object_type="source_artifact",
                object_id=artifact_id,
                payload={
                    "sha256": digest,
                    "size_bytes": len(data),
                    "kind": "manual",
                    "uri": uri,
                },
            )
        return artifact_id, digest

    def rebuild_catalog(self) -> dict:
        accounts = [dict(row) for row in self.db.execute("SELECT * FROM accounts ORDER BY created_at,id")]
        portfolios = [
            dict(row)
            for row in self.db.execute("SELECT * FROM portfolios ORDER BY created_at,id")
        ]
        imports = [
            dict(row)
            for row in self.db.execute(
                """SELECT i.id,i.artifact_id,i.created_at,d.adapter_name,d.adapter_version,
                          d.schema_version,d.input_rows,d.inserted_rows,a.path,a.sha256,
                          ad.source_path,ad.artifact_kind,md.dataset_name,md.version AS dataset_version,
                          md.provider AS dataset_provider,md.manifest_sha256 AS dataset_manifest_sha256,
                          md.manifest_json AS dataset_manifest_json
                   FROM imports i
                   JOIN import_details d ON d.import_id=i.id
                   JOIN artifacts a ON a.id=i.artifact_id
                   JOIN artifact_details ad ON ad.artifact_id=a.id
                   LEFT JOIN market_datasets md ON md.import_batch_id=i.id
                   ORDER BY i.created_at,i.id"""
            )
        ]
        for item in imports:
            item["raw_path"] = str(self.raw_root / item["sha256"])
            item["account_ids"] = [
                row[0]
                for row in self.db.execute(
                    """SELECT DISTINCT account_id FROM imported_rows
                       WHERE artifact_id=? ORDER BY account_id""",
                    (item["artifact_id"],),
                )
            ]
        return {"accounts": accounts, "portfolios": portfolios, "imports": imports}

    def imported_transaction_mapping(self, account_id: str, artifact_id: str) -> dict[str, str]:
        self.require_account(account_id)
        require_uuid(artifact_id, "artifact_id")
        return {
            row["external_id"]: row["transaction_id"]
            for row in self.db.execute(
                """SELECT external_id,transaction_id FROM imported_rows
                   WHERE account_id=? AND artifact_id=? ORDER BY external_id""",
                (account_id, artifact_id),
            )
        }

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

    def instrument_details(self, instrument_id: str) -> sqlite3.Row:
        require_uuid(instrument_id, "instrument_id")
        row = self.db.execute("SELECT * FROM instruments WHERE id=?", (instrument_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown instrument: {instrument_id}")
        return row

    def add_market_dataset(
        self,
        dataset: DatasetVersion,
        prices: Iterable[MarketPrice],
        fx_rates: Iterable[FxRate],
    ) -> dict:
        price_rows = list(prices)
        fx_rows = list(fx_rates)
        if any(row.dataset_id != dataset.id for row in (*price_rows, *fx_rows)):
            raise ValueError("market observation dataset mismatch")
        if not price_rows and not fx_rows:
            raise ValueError("market dataset must contain prices or FX rates")
        existing = self.db.execute(
            "SELECT * FROM market_datasets WHERE dataset_name=? AND version=?",
            (dataset.dataset_name, dataset.version),
        ).fetchone()
        if existing is not None:
            if existing["manifest_sha256"] != dataset.manifest_sha256:
                raise ValueError(
                    f"market dataset version conflict: {dataset.dataset_name}/{dataset.version}"
                )
            return {
                "dataset_id": existing["id"],
                "dataset_name": existing["dataset_name"],
                "version": existing["version"],
                "provider": existing["provider"],
                "source_artifact_id": existing["source_artifact_id"],
                "import_batch_id": existing["import_batch_id"],
                "manifest_sha256": existing["manifest_sha256"],
                "prices": self.db.execute(
                    "SELECT count(*) FROM market_prices WHERE dataset_id=?", (existing["id"],)
                ).fetchone()[0],
                "fx_rates": self.db.execute(
                    "SELECT count(*) FROM market_fx_rates WHERE dataset_id=?", (existing["id"],)
                ).fetchone()[0],
            }
        with self.db:
            self._insert_import_batch(
                dataset.import_batch_id,
                dataset.source_artifact_id,
                dataset.adapter_name,
                dataset.adapter_version,
                dataset.schema_version,
                len(price_rows) + len(fx_rows),
                len(price_rows) + len(fx_rows),
            )
            self.db.execute(
                """INSERT INTO market_datasets(
                       id,dataset_name,version,provider,adapter_name,adapter_version,
                       schema_version,source_artifact_id,import_batch_id,manifest_sha256,
                       manifest_json,recorded_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    dataset.id,
                    dataset.dataset_name,
                    dataset.version,
                    dataset.provider,
                    dataset.adapter_name,
                    dataset.adapter_version,
                    dataset.schema_version,
                    dataset.source_artifact_id,
                    dataset.import_batch_id,
                    dataset.manifest_sha256,
                    dataset.manifest_json,
                    dataset.recorded_at,
                ),
            )
            for price in price_rows:
                instrument = self.db.execute(
                    "SELECT currency FROM instruments WHERE id=?", (price.instrument_id,)
                ).fetchone()
                if instrument is None:
                    raise KeyError(f"unknown instrument: {price.instrument_id}")
                if instrument["currency"] != price.currency:
                    raise ValueError("market price currency must match instrument currency")
                self.db.execute(
                    "INSERT INTO market_prices VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        price.id,
                        price.dataset_id,
                        price.instrument_id,
                        price.observed_at,
                        price.known_at,
                        price.recorded_at,
                        canonical_decimal(price.close),
                        price.currency,
                        price.quality,
                    ),
                )
            for rate in fx_rows:
                self.db.execute(
                    "INSERT INTO market_fx_rates VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        rate.id,
                        rate.dataset_id,
                        rate.observed_at,
                        rate.known_at,
                        rate.recorded_at,
                        rate.from_currency,
                        rate.to_currency,
                        canonical_decimal(rate.rate),
                        rate.quality,
                    ),
                )
            append_audit_event(
                self.db,
                operation="market.dataset_import",
                object_type="market_dataset",
                object_id=dataset.id,
                payload={
                    "dataset_name": dataset.dataset_name,
                    "version": dataset.version,
                    "provider": dataset.provider,
                    "source_artifact_id": dataset.source_artifact_id,
                    "import_batch_id": dataset.import_batch_id,
                    "manifest_sha256": dataset.manifest_sha256,
                    "price_rows": len(price_rows),
                    "fx_rows": len(fx_rows),
                },
            )
        return {
            "dataset_id": dataset.id,
            "dataset_name": dataset.dataset_name,
            "version": dataset.version,
            "provider": dataset.provider,
            "source_artifact_id": dataset.source_artifact_id,
            "import_batch_id": dataset.import_batch_id,
            "manifest_sha256": dataset.manifest_sha256,
            "prices": len(price_rows),
            "fx_rates": len(fx_rows),
        }

    def market_datasets(self, dataset_name: str | None = None) -> list[sqlite3.Row]:
        query = "SELECT * FROM market_datasets"
        args: list[str] = []
        if dataset_name is not None:
            query += " WHERE dataset_name=?"
            args.append(dataset_name)
        return self.db.execute(query + " ORDER BY recorded_at,id", args).fetchall()

    def market_price(
        self,
        instrument_id: str,
        as_of: str,
        known_as_of: str | None = None,
        dataset_name: str | None = None,
        dataset_version: str | None = None,
    ) -> sqlite3.Row | None:
        require_uuid(instrument_id, "instrument_id")
        if dataset_version is not None and dataset_name is None:
            raise ValueError("dataset_version requires dataset_name")
        observed_cutoff = canonical_timestamp(as_of)
        known_cutoff = canonical_timestamp(known_as_of or as_of)
        clauses = [
            "p.instrument_id=?",
            "p.observed_at<=?",
            "p.known_at<=?",
            "p.quality='accepted'",
        ]
        args: list[str] = [instrument_id, observed_cutoff, known_cutoff]
        if dataset_name is not None:
            clauses.append("d.dataset_name=?")
            args.append(dataset_name)
        if dataset_version is not None:
            clauses.append("d.version=?")
            args.append(dataset_version)
        rows = self.db.execute(
            """SELECT p.*,d.dataset_name,d.version AS dataset_version,d.provider
               FROM market_prices p JOIN market_datasets d ON d.id=p.dataset_id
               WHERE """
            + " AND ".join(clauses)
            + " ORDER BY p.observed_at DESC,p.known_at DESC,p.recorded_at DESC,p.id DESC",
            args,
        ).fetchall()
        if not rows:
            return None
        latest_observed = rows[0]["observed_at"]
        latest = [row for row in rows if row["observed_at"] == latest_observed]
        values = {(row["close"], row["currency"]) for row in latest}
        if len(values) > 1 and (dataset_name is None or dataset_version is None):
            raise ValueError(
                f"conflicting accepted market prices for {instrument_id} at {latest_observed}; select a dataset version"
            )
        return latest[0]

    def market_fx_rate(
        self,
        from_currency: str,
        to_currency: str,
        as_of: str,
        known_as_of: str | None = None,
        dataset_name: str | None = None,
        dataset_version: str | None = None,
    ) -> sqlite3.Row | None:
        if dataset_version is not None and dataset_name is None:
            raise ValueError("dataset_version requires dataset_name")
        observed_cutoff = canonical_timestamp(as_of)
        known_cutoff = canonical_timestamp(known_as_of or as_of)
        clauses = [
            "r.from_currency=?",
            "r.to_currency=?",
            "r.observed_at<=?",
            "r.known_at<=?",
            "r.quality='accepted'",
        ]
        args: list[str] = [from_currency.upper(), to_currency.upper(), observed_cutoff, known_cutoff]
        if dataset_name is not None:
            clauses.append("d.dataset_name=?")
            args.append(dataset_name)
        if dataset_version is not None:
            clauses.append("d.version=?")
            args.append(dataset_version)
        rows = self.db.execute(
            """SELECT r.*,d.dataset_name,d.version AS dataset_version,d.provider
               FROM market_fx_rates r JOIN market_datasets d ON d.id=r.dataset_id
               WHERE """
            + " AND ".join(clauses)
            + " ORDER BY r.observed_at DESC,r.known_at DESC,r.recorded_at DESC,r.id DESC",
            args,
        ).fetchall()
        if not rows:
            return None
        latest_observed = rows[0]["observed_at"]
        latest = [row for row in rows if row["observed_at"] == latest_observed]
        values = {row["rate"] for row in latest}
        if len(values) > 1 and (dataset_name is None or dataset_version is None):
            raise ValueError(
                f"conflicting accepted FX rates for {from_currency}/{to_currency} at {latest_observed}; select a dataset version"
            )
        return latest[0]

    def add_portfolio(self, portfolio: Portfolio) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO portfolios VALUES(?,?,?,?,?,?)",
                (
                    portfolio.id,
                    portfolio.name,
                    portfolio.base_currency,
                    portfolio.created_at,
                    portfolio.source_artifact_id,
                    portfolio.import_batch_id,
                ),
            )
            append_audit_event(
                self.db,
                operation="portfolio.create",
                object_type="portfolio",
                object_id=portfolio.id,
                payload={"name": portfolio.name, "base_currency": portfolio.base_currency},
            )

    def portfolio(self, portfolio_id: str) -> sqlite3.Row:
        require_uuid(portfolio_id, "portfolio_id")
        row = self.db.execute("SELECT * FROM portfolios WHERE id=?", (portfolio_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown portfolio: {portfolio_id}")
        return row

    def add_portfolio_membership(self, event: PortfolioMembershipEvent) -> None:
        self.portfolio(event.portfolio_id)
        self.require_account(event.account_id)
        with self.db:
            self.db.execute(
                "INSERT INTO portfolio_membership_events VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    event.id,
                    event.portfolio_id,
                    event.account_id,
                    event.action,
                    event.effective_at,
                    event.known_at,
                    event.recorded_at,
                    event.source_artifact_id,
                    event.import_batch_id,
                ),
            )
            append_audit_event(
                self.db,
                operation=f"portfolio.membership_{event.action}",
                object_type="portfolio_membership",
                object_id=event.id,
                payload={
                    "portfolio_id": event.portfolio_id,
                    "account_id": event.account_id,
                    "effective_at": event.effective_at,
                    "known_at": event.known_at,
                },
            )

    def portfolio_accounts(
        self, portfolio_id: str, as_of: str, known_as_of: str | None = None
    ) -> list[str]:
        self.portfolio(portfolio_id)
        effective_cutoff = canonical_timestamp(as_of)
        knowledge_cutoff = canonical_timestamp(known_as_of or as_of)
        rows = self.db.execute(
            """SELECT e.account_id,e.action
               FROM portfolio_membership_events e
               WHERE e.portfolio_id=? AND e.effective_at<=? AND e.known_at<=?
                 AND e.id=(
                     SELECT x.id FROM portfolio_membership_events x
                     WHERE x.portfolio_id=e.portfolio_id AND x.account_id=e.account_id
                       AND x.effective_at<=? AND x.known_at<=?
                     ORDER BY x.effective_at DESC,x.known_at DESC,x.recorded_at DESC,x.id DESC
                     LIMIT 1
                 )
               ORDER BY e.account_id""",
            (
                portfolio_id,
                effective_cutoff,
                knowledge_cutoff,
                effective_cutoff,
                knowledge_cutoff,
            ),
        ).fetchall()
        return [row["account_id"] for row in rows if row["action"] == "add"]

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

    def add_fx_conversion(self, transaction: Transaction, conversion: FxConversion) -> None:
        if conversion.transaction_id != transaction.id or transaction.type != "fx_conversion":
            raise ValueError("FX metadata must reference an FX conversion transaction")
        with self.db:
            self._insert_transaction(transaction)
            self.db.execute(
                "INSERT INTO fx_conversions VALUES(?,?,?,?,?,?,?,?)",
                (
                    transaction.id,
                    conversion.from_currency,
                    conversion.to_currency,
                    canonical_decimal(conversion.from_amount),
                    canonical_decimal(conversion.to_amount),
                    canonical_decimal(conversion.rate),
                    canonical_decimal(conversion.fee),
                    conversion.fee_currency,
                ),
            )
            self._audit_transaction(transaction)
            append_audit_event(
                self.db,
                operation="ledger.record_fx_conversion",
                object_type="fx_conversion",
                object_id=transaction.id,
                payload={
                    "from_currency": conversion.from_currency,
                    "to_currency": conversion.to_currency,
                    "from_amount": canonical_decimal(conversion.from_amount),
                    "to_amount": canonical_decimal(conversion.to_amount),
                    "rate": canonical_decimal(conversion.rate),
                    "fee": canonical_decimal(conversion.fee),
                    "fee_currency": conversion.fee_currency,
                },
            )

    def add_security_transfer(
        self,
        transfer: SecurityTransfer,
        source_transaction: Transaction,
        destination_transaction: Transaction,
    ) -> None:
        if (
            transfer.source_transaction_id != source_transaction.id
            or transfer.destination_transaction_id != destination_transaction.id
        ):
            raise ValueError("security transfer metadata does not match transactions")
        if source_transaction.account_id == destination_transaction.account_id:
            raise ValueError("security transfer accounts must be distinct")
        with self.db:
            self._insert_transaction(source_transaction)
            self._insert_transaction(destination_transaction)
            self.db.execute(
                "INSERT INTO security_transfers VALUES(?,?,?,?,?,?,?,?)",
                (
                    transfer.id,
                    source_transaction.id,
                    destination_transaction.id,
                    transfer.instrument_id,
                    canonical_decimal(transfer.quantity),
                    canonical_decimal(transfer.carried_basis),
                    transfer.currency,
                    now(),
                ),
            )
            for sequence, allocation in enumerate(transfer.allocations, 1):
                self.db.execute(
                    "INSERT INTO security_transfer_allocations VALUES(?,?,?,?,?,?,?,?)",
                    (
                        new_id(),
                        transfer.id,
                        sequence,
                        allocation.source_transaction_id,
                        allocation.acquired_at,
                        canonical_decimal(allocation.quantity),
                        canonical_decimal(allocation.basis),
                        allocation.currency,
                    ),
                )
            self._audit_transaction(source_transaction)
            self._audit_transaction(destination_transaction)
            append_audit_event(
                self.db,
                operation="ledger.record_security_transfer",
                object_type="security_transfer",
                object_id=transfer.id,
                payload={
                    "source_transaction_id": source_transaction.id,
                    "destination_transaction_id": destination_transaction.id,
                    "instrument_id": transfer.instrument_id,
                    "quantity": canonical_decimal(transfer.quantity),
                    "carried_basis": canonical_decimal(transfer.carried_basis),
                    "currency": transfer.currency,
                    "allocation_count": len(transfer.allocations),
                },
            )

    def add_corporate_action(
        self, transaction: Transaction, action: CorporateAction
    ) -> None:
        if action.transaction_id != transaction.id or transaction.type != action.action_type:
            raise ValueError("corporate action metadata does not match transaction")
        with self.db:
            self._insert_transaction(transaction)
            self.db.execute(
                "INSERT INTO corporate_actions VALUES(?,?,?,?,?,?,?)",
                (
                    action.id,
                    transaction.id,
                    action.instrument_id,
                    action.action_type,
                    canonical_decimal(action.numerator),
                    canonical_decimal(action.denominator),
                    now(),
                ),
            )
            self._audit_transaction(transaction)
            append_audit_event(
                self.db,
                operation="ledger.record_corporate_action",
                object_type="corporate_action",
                object_id=action.id,
                payload={
                    "transaction_id": transaction.id,
                    "instrument_id": action.instrument_id,
                    "action_type": action.action_type,
                    "numerator": canonical_decimal(action.numerator),
                    "denominator": canonical_decimal(action.denominator),
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
        self.db.execute(
            "INSERT INTO transaction_order VALUES(?,?)",
            (transaction.id, transaction.source_sequence),
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

    def transactions(
        self,
        account_id: str,
        as_of: str | None = None,
        known_as_of: str | None = None,
    ) -> list[sqlite3.Row]:
        self.require_account(account_id)
        query = "SELECT * FROM transactions WHERE account_id=?"
        arguments: list[str] = [account_id]
        if as_of is not None:
            query += " AND effective_at<=?"
            arguments.append(canonical_timestamp(as_of))
        knowledge_cutoff = known_as_of if known_as_of is not None else as_of
        if knowledge_cutoff is not None:
            query += " AND known_at<=?"
            arguments.append(canonical_timestamp(knowledge_cutoff))
        return self.db.execute(
            query
            + """ ORDER BY effective_at, known_at, recorded_at,
                         COALESCE((SELECT source_sequence FROM transaction_order o
                                   WHERE o.transaction_id=transactions.id), 0), id""",
            arguments,
        ).fetchall()

    def transaction(self, transaction_id: str) -> sqlite3.Row | None:
        require_uuid(transaction_id, "transaction_id")
        return self.db.execute("SELECT * FROM transactions WHERE id=?", (transaction_id,)).fetchone()

    def legs(self, transaction_id: str) -> list[sqlite3.Row]:
        require_uuid(transaction_id, "transaction_id")
        return self.db.execute(
            "SELECT * FROM legs WHERE transaction_id=? ORDER BY id", (transaction_id,)
        ).fetchall()

    def transaction_metadata(self, transaction_id: str) -> dict:
        require_uuid(transaction_id, "transaction_id")
        result: dict = {}
        fx = self.db.execute(
            "SELECT * FROM fx_conversions WHERE transaction_id=?", (transaction_id,)
        ).fetchone()
        if fx is not None:
            result["fx_conversion"] = dict(fx)
        action = self.db.execute(
            "SELECT * FROM corporate_actions WHERE transaction_id=?", (transaction_id,)
        ).fetchone()
        if action is not None:
            result["corporate_action"] = dict(action)
        transfer = self.db.execute(
            """SELECT * FROM security_transfers
               WHERE source_transaction_id=? OR destination_transaction_id=?""",
            (transaction_id, transaction_id),
        ).fetchone()
        if transfer is not None:
            transfer_data = dict(transfer)
            transfer_data["allocations"] = [
                dict(row)
                for row in self.db.execute(
                    """SELECT source_transaction_id,acquired_at,quantity,basis,currency
                       FROM security_transfer_allocations
                       WHERE security_transfer_id=? ORDER BY sequence""",
                    (transfer["id"],),
                )
            ]
            result["security_transfer"] = transfer_data
        return result

    def corporate_action_transaction(self, action_id: str) -> str:
        require_uuid(action_id, "action_id")
        row = self.db.execute(
            "SELECT transaction_id FROM corporate_actions WHERE id=?", (action_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown corporate action: {action_id}")
        return row["transaction_id"]

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
            for currency, value in sorted(observed.get("cash_by_currency", {}).items()):
                self.db.execute(
                    "INSERT INTO reconciliation_observations VALUES(?,?,?,?,?,?)",
                    (new_id(), record_id, "cash", None, currency, canonical_decimal(value)),
                )
            for instrument_id, value in sorted(observed.get("positions", {}).items()):
                if self.db.execute(
                    "SELECT 1 FROM instruments WHERE id=?", (instrument_id,)
                ).fetchone() is None:
                    raise KeyError(f"unknown instrument: {instrument_id}")
                self.db.execute(
                    "INSERT INTO reconciliation_observations VALUES(?,?,?,?,?,?)",
                    (new_id(), record_id, "position", instrument_id, None, canonical_decimal(value)),
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
