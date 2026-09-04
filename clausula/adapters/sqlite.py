from __future__ import annotations

import hashlib
import json
import mimetypes
import os
from pathlib import Path
import shutil
import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Iterable, Iterator, Mapping

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
    InvestmentPolicy,
    MarketPrice,
    Plan,
    PlanScenario,
    ProjectedState,
    CandidateAction,
    Decision,
    DecisionAlternative,
    DecisionEvidenceLink,
    DecisionPolicyLink,
    DecisionReview,
    DecisionReviewSchedule,
    DecisionStatement,
    DecisionTransactionLink,
    Portfolio,
    PortfolioMembershipEvent,
    PolicyRule,
    PolicyVersion,
    UnresolvedConstraint,
    SecurityTransfer,
    Transaction,
    ResearchClaim,
    ResearchContradiction,
    ResearchDocument,
    ResearchEvidence,
    ResearchLink,
    ResearchThesis,
    ThesisRevision,
    Recommendation,
    RecommendationAlternative,
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
    "research_documents",
    "research_claims",
    "research_evidence",
    "research_contradictions",
    "research_theses",
    "thesis_revisions",
    "research_links",
    "identifier_validity_ranges",
    "corporate_action_events",
    "corporate_action_event_instruments",
    "corporate_action_considerations",
    "corporate_action_account_consequences",
    "corporate_action_basis_allocations",
    "corporate_action_tax_interpretations",
)


class Store:
    def __init__(self, path: str | Path | None = None):
        self.root = Path(path or os.environ.get("CLAUSULA_HOME", Path.home() / ".clausula"))
        self.root.mkdir(parents=True, exist_ok=True)
        self.raw_root = self.root / "raw"
        self.raw_root.mkdir(exist_ok=True)
        self.db = sqlite3.connect(self.root / "clausula.db", check_same_thread=False)
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
            if self.db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone() is None:
                continue
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

    @contextmanager
    def write_transaction(self) -> Iterator[None]:
        """Join an existing write transaction or commit a standalone one."""
        if self.db.in_transaction:
            yield
            return
        self.db.execute("BEGIN")
        try:
            yield
        except Exception:
            self.db.rollback()
            raise
        else:
            self.db.commit()

    def integrity_check(self) -> str:
        return self.db.execute("PRAGMA integrity_check").fetchone()[0]

    def verify_audit_chain(self) -> dict:
        return verify_audit_chain(self.db)

    def record_adapter_invocation(
        self,
        *,
        adapter: str,
        actor_type: str,
        actor_id: str,
        capability: str,
        side_effect: str,
        confirmed: bool,
        succeeded: bool,
    ) -> str:
        with self.write_transaction():
            return append_audit_event(
                self.db,
                operation=f"{adapter}.invoke",
                object_type="capability_invocation",
                object_id=new_id(),
                actor_type=actor_type,
                actor_id=actor_id,
                payload={
                    "capability": capability,
                    "side_effect": side_effect,
                    "confirmed": confirmed,
                    "succeeded": succeeded,
                },
            )

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
        with self.write_transaction():
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
        with self.write_transaction():
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
        policies = []
        for policy in self.db.execute(
            "SELECT * FROM investment_policies ORDER BY created_at,id"
        ):
            versions = []
            for version in self.db.execute(
                "SELECT * FROM policy_versions WHERE policy_id=? ORDER BY version_number,id",
                (policy["id"],),
            ):
                rules = [
                    dict(rule)
                    for rule in self.db.execute(
                        "SELECT * FROM policy_rules WHERE policy_version_id=? ORDER BY rule_key,id",
                        (version["id"],),
                    )
                ]
                versions.append({"version": dict(version), "rules": rules})
            policies.append({"policy": dict(policy), "versions": versions})
        plans = []
        for plan in self.db.execute("SELECT * FROM plans ORDER BY created_at,id"):
            scenarios = []
            for scenario in self.db.execute(
                "SELECT * FROM plan_scenarios WHERE plan_id=? ORDER BY scenario_key,id",
                (plan["id"],),
            ):
                scenarios.append(
                    {
                        "scenario": dict(scenario),
                        "actions": [
                            dict(action)
                            for action in self.db.execute(
                                "SELECT * FROM plan_actions WHERE scenario_id=? ORDER BY sequence,id",
                                (scenario["id"],),
                            )
                        ],
                        "projected_state": dict(
                            self.db.execute(
                                "SELECT * FROM plan_projected_states WHERE scenario_id=?",
                                (scenario["id"],),
                            ).fetchone()
                        ),
                        "constraints": [
                            dict(constraint)
                            for constraint in self.db.execute(
                                "SELECT * FROM plan_constraints WHERE scenario_id=? ORDER BY id",
                                (scenario["id"],),
                            )
                        ],
                    }
                )
            plans.append({"plan": dict(plan), "scenarios": scenarios})
        decisions = []
        for decision in self.db.execute("SELECT * FROM decisions ORDER BY created_at,id"):
            decision_id = decision["id"]
            decisions.append(
                {
                    "decision": dict(decision),
                    "alternatives": [
                        dict(row)
                        for row in self.db.execute(
                            "SELECT * FROM decision_alternatives WHERE decision_id=? ORDER BY alternative_key,id",
                            (decision_id,),
                        )
                    ],
                    "policy_links": [
                        dict(row)
                        for row in self.db.execute(
                            "SELECT * FROM decision_policy_links WHERE decision_id=? ORDER BY id",
                            (decision_id,),
                        )
                    ],
                    "evidence_links": [
                        dict(row)
                        for row in self.db.execute(
                            "SELECT * FROM decision_evidence_links WHERE decision_id=? ORDER BY id",
                            (decision_id,),
                        )
                    ],
                    "transaction_links": [
                        dict(row)
                        for row in self.db.execute(
                            "SELECT * FROM decision_transaction_links WHERE decision_id=? ORDER BY id",
                            (decision_id,),
                        )
                    ],
                    "reviews": [
                        dict(row)
                        for row in self.db.execute(
                            "SELECT * FROM decision_reviews WHERE decision_id=? ORDER BY reviewed_at,id",
                            (decision_id,),
                        )
                    ],
                    "statements": [dict(row) for row in self.db.execute("SELECT * FROM decision_statements WHERE decision_id=? ORDER BY kind,statement_key,id", (decision_id,))],
                    "review_schedules": [dict(row) for row in self.db.execute("SELECT * FROM decision_review_schedules WHERE decision_id=? ORDER BY due_at,id", (decision_id,))],
                }
            )
        research = {
            "documents": [dict(row) for row in self.db.execute(
                "SELECT * FROM research_documents ORDER BY recorded_at,id"
            )],
            "claims": [dict(row) for row in self.db.execute(
                "SELECT * FROM research_claims ORDER BY recorded_at,id"
            )],
            "evidence": [dict(row) for row in self.db.execute(
                "SELECT * FROM research_evidence ORDER BY recorded_at,id"
            )],
            "contradictions": [dict(row) for row in self.db.execute(
                "SELECT * FROM research_contradictions ORDER BY recorded_at,id"
            )],
            "theses": [],
            "links": [dict(row) for row in self.db.execute(
                "SELECT * FROM research_links ORDER BY created_at,id"
            )],
        }
        for thesis in self.db.execute(
            "SELECT * FROM research_theses ORDER BY created_at,id"
        ):
            research["theses"].append(
                {
                    "thesis": dict(thesis),
                    "revisions": [
                        dict(row)
                        for row in self.db.execute(
                            "SELECT * FROM thesis_revisions WHERE thesis_id=? "
                            "ORDER BY revision_number,id",
                            (thesis["id"],),
                        )
                    ],
                }
            )
        return {
            "accounts": accounts,
            "portfolios": portfolios,
            "policies": policies,
            "plans": plans,
            "decisions": decisions,
            "research": research,
            "imports": imports,
        }

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
        with self.write_transaction():
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

    def register_identifier_range(
        self,
        *,
        instrument_id: str,
        scheme: str,
        value: str,
        valid_from: str,
        valid_to: str | None,
        known_at: str,
        recorded_at: str,
        provenance: str,
    ) -> str:
        self.instrument_details(instrument_id)
        normalized_scheme = str(scheme).strip().lower()
        normalized_value = str(value).strip()
        if not normalized_scheme or not normalized_value:
            raise ValueError("identifier scheme and value cannot be empty")
        normalized_from = canonical_timestamp(valid_from)
        normalized_to = None if valid_to is None else canonical_timestamp(valid_to)
        normalized_known = canonical_timestamp(known_at)
        normalized_recorded = canonical_timestamp(recorded_at)
        if normalized_to is not None and normalized_to <= normalized_from:
            raise ValueError("valid_to must be after valid_from")
        if normalized_known > normalized_recorded:
            raise ValueError("known_at cannot be after recorded_at")
        if not str(provenance).strip():
            raise ValueError("provenance cannot be empty")
        range_id = new_id()
        with self.write_transaction():
            self.db.execute(
                "INSERT INTO identifier_validity_ranges"
                "(id,instrument_id,scheme,value,valid_from,valid_to,known_at,recorded_at,provenance)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    range_id,
                    instrument_id,
                    normalized_scheme,
                    normalized_value,
                    normalized_from,
                    normalized_to,
                    normalized_known,
                    normalized_recorded,
                    str(provenance).strip(),
                ),
            )
            append_audit_event(
                self.db,
                operation="identifier.register_range",
                object_type="identifier_validity_range",
                object_id=range_id,
                payload={
                    "instrument_id": instrument_id,
                    "scheme": normalized_scheme,
                    "value": normalized_value,
                    "valid_from": normalized_from,
                    "valid_to": normalized_to,
                    "known_at": normalized_known,
                    "provenance": str(provenance).strip(),
                },
            )
        return range_id

    def resolve_identifier_at(
        self,
        *,
        scheme: str,
        value: str,
        as_of: str,
        known_as_of: str,
    ) -> str | None:
        normalized_scheme = str(scheme).strip().lower()
        normalized_value = str(value).strip()
        effective = canonical_timestamp(as_of)
        knowledge = canonical_timestamp(known_as_of)
        rows = self.db.execute(
            """SELECT instrument_id FROM identifier_validity_ranges
               WHERE scheme=? AND value=? AND valid_from<=? AND known_at<=?
                 AND (valid_to IS NULL OR valid_to>?)
               ORDER BY valid_from, recorded_at, id""",
            (normalized_scheme, normalized_value, effective, knowledge, effective),
        ).fetchall()
        if not rows:
            return None
        if len(rows) > 1:
            raise ValueError(
                f"multiple active identifier ranges for {normalized_scheme}:{normalized_value} at {effective}"
            )
        return rows[0]["instrument_id"]

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

    @staticmethod
    def _policy_version_values(version: PolicyVersion) -> tuple:
        return (
            version.id,
            version.policy_id,
            version.version_number,
            version.effective_from,
            version.known_at,
            version.recorded_at,
            version.rules_sha256,
            version.source_artifact_id,
            version.import_batch_id,
        )

    @staticmethod
    def _policy_rule_values(rule: PolicyRule) -> tuple:
        return (
            rule.id,
            rule.policy_version_id,
            rule.rule_key,
            rule.rule_type,
            rule.severity,
            rule.description,
            rule.subject,
            None if rule.target is None else canonical_decimal(rule.target),
            None
            if rule.lower_bound is None
            else canonical_decimal(rule.lower_bound),
            None
            if rule.upper_bound is None
            else canonical_decimal(rule.upper_bound),
        )

    def add_policy(
        self,
        policy: InvestmentPolicy,
        version: PolicyVersion,
        rules: Iterable[PolicyRule],
    ) -> None:
        self.portfolio(policy.portfolio_id)
        rule_rows = tuple(rules)
        if version.policy_id != policy.id:
            raise ValueError("policy version belongs to a different policy")
        if not rule_rows:
            raise ValueError("policy version requires at least one rule")
        if (
            policy.source_artifact_id != version.source_artifact_id
            or policy.import_batch_id != version.import_batch_id
        ):
            raise ValueError("policy and version provenance must match")
        if any(rule.policy_version_id != version.id for rule in rule_rows):
            raise ValueError("policy rule belongs to a different version")
        self._require_import_artifact(version.source_artifact_id, version.import_batch_id)
        with self.write_transaction():
            self.db.execute(
                "INSERT INTO investment_policies VALUES(?,?,?,?,?,?)",
                (
                    policy.id,
                    policy.portfolio_id,
                    policy.name,
                    policy.created_at,
                    policy.source_artifact_id,
                    policy.import_batch_id,
                ),
            )
            self.db.execute(
                "INSERT INTO policy_versions VALUES(?,?,?,?,?,?,?,?,?)",
                self._policy_version_values(version),
            )
            self.db.executemany(
                "INSERT INTO policy_rules VALUES(?,?,?,?,?,?,?,?,?,?)",
                (self._policy_rule_values(rule) for rule in rule_rows),
            )
            append_audit_event(
                self.db,
                operation="policy.create",
                object_type="investment_policy",
                object_id=policy.id,
                payload={
                    "portfolio_id": policy.portfolio_id,
                    "policy_version_id": version.id,
                    "version_number": version.version_number,
                    "rules_sha256": version.rules_sha256,
                    "rule_count": len(rule_rows),
                    "source_artifact_id": version.source_artifact_id,
                    "import_batch_id": version.import_batch_id,
                },
            )

    def add_policy_version(
        self, version: PolicyVersion, rules: Iterable[PolicyRule]
    ) -> None:
        self.policy(version.policy_id)
        rule_rows = tuple(rules)
        if not rule_rows:
            raise ValueError("policy version requires at least one rule")
        if any(rule.policy_version_id != version.id for rule in rule_rows):
            raise ValueError("policy rule belongs to a different version")
        self._require_import_artifact(version.source_artifact_id, version.import_batch_id)
        expected_number = self.next_policy_version_number(version.policy_id)
        if version.version_number != expected_number:
            raise ValueError(
                f"policy version_number must be {expected_number}, got {version.version_number}"
            )
        with self.write_transaction():
            self.db.execute(
                "INSERT INTO policy_versions VALUES(?,?,?,?,?,?,?,?,?)",
                self._policy_version_values(version),
            )
            self.db.executemany(
                "INSERT INTO policy_rules VALUES(?,?,?,?,?,?,?,?,?,?)",
                (self._policy_rule_values(rule) for rule in rule_rows),
            )
            append_audit_event(
                self.db,
                operation="policy.add_version",
                object_type="policy_version",
                object_id=version.id,
                payload={
                    "policy_id": version.policy_id,
                    "version_number": version.version_number,
                    "effective_from": version.effective_from,
                    "known_at": version.known_at,
                    "rules_sha256": version.rules_sha256,
                    "rule_count": len(rule_rows),
                    "source_artifact_id": version.source_artifact_id,
                    "import_batch_id": version.import_batch_id,
                },
            )

    def _require_import_artifact(self, artifact_id: str, import_batch_id: str) -> None:
        artifact = self.db.execute(
            "SELECT 1 FROM artifacts WHERE id=?", (artifact_id,)
        ).fetchone()
        batch = self.db.execute(
            "SELECT artifact_id FROM imports WHERE id=?", (import_batch_id,)
        ).fetchone()
        if artifact is None or batch is None or batch["artifact_id"] != artifact_id:
            raise ValueError(
                "policy provenance must reference a matching artifact and import batch"
            )

    def policy(self, policy_id: str) -> sqlite3.Row:
        require_uuid(policy_id, "policy_id")
        row = self.db.execute(
            "SELECT * FROM investment_policies WHERE id=?", (policy_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown policy: {policy_id}")
        return row

    def policies(self, portfolio_id: str | None = None) -> list[sqlite3.Row]:
        query = "SELECT * FROM investment_policies"
        arguments: tuple[str, ...] = ()
        if portfolio_id is not None:
            require_uuid(portfolio_id, "portfolio_id")
            query += " WHERE portfolio_id=?"
            arguments = (portfolio_id,)
        return self.db.execute(query + " ORDER BY created_at,id", arguments).fetchall()

    def next_policy_version_number(self, policy_id: str) -> int:
        self.policy(policy_id)
        return self.db.execute(
            "SELECT coalesce(max(version_number),0)+1 FROM policy_versions WHERE policy_id=?",
            (policy_id,),
        ).fetchone()[0]

    def policy_version_at(
        self, policy_id: str, as_of: str, known_as_of: str | None = None
    ) -> sqlite3.Row:
        self.policy(policy_id)
        effective_cutoff = canonical_timestamp(as_of)
        knowledge_cutoff = canonical_timestamp(known_as_of or as_of)
        row = self.db.execute(
            """SELECT * FROM policy_versions
               WHERE policy_id=? AND effective_from<=? AND known_at<=?
               ORDER BY effective_from DESC,known_at DESC,version_number DESC,id DESC
               LIMIT 1""",
            (policy_id, effective_cutoff, knowledge_cutoff),
        ).fetchone()
        if row is None:
            raise KeyError(
                f"no policy version for {policy_id} at effective={effective_cutoff} known={knowledge_cutoff}"
            )
        return row

    def policy_versions(self, policy_id: str) -> list[sqlite3.Row]:
        self.policy(policy_id)
        return self.db.execute(
            "SELECT * FROM policy_versions WHERE policy_id=? ORDER BY version_number,id",
            (policy_id,),
        ).fetchall()

    def policy_version(self, policy_version_id: str) -> sqlite3.Row:
        require_uuid(policy_version_id, "policy_version_id")
        row = self.db.execute(
            "SELECT * FROM policy_versions WHERE id=?", (policy_version_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown policy version: {policy_version_id}")
        return row

    def policy_rules(self, policy_version_id: str) -> list[sqlite3.Row]:
        require_uuid(policy_version_id, "policy_version_id")
        exists = self.db.execute(
            "SELECT 1 FROM policy_versions WHERE id=?", (policy_version_id,)
        ).fetchone()
        if exists is None:
            raise KeyError(f"unknown policy version: {policy_version_id}")
        return self.db.execute(
            """SELECT * FROM policy_rules WHERE policy_version_id=?
               ORDER BY rule_key,id""",
            (policy_version_id,),
        ).fetchall()

    @staticmethod
    def _plan_values(plan: Plan) -> tuple:
        return (
            plan.id,
            plan.portfolio_id,
            plan.policy_id,
            plan.policy_version_id,
            plan.name,
            plan.as_of,
            plan.known_as_of,
            plan.created_at,
            plan.source_artifact_id,
            plan.import_batch_id,
        )

    @staticmethod
    def _plan_scenario_values(scenario: PlanScenario, result_json: str) -> tuple:
        return (
            scenario.id,
            scenario.plan_id,
            scenario.scenario_key,
            scenario.description,
            canonical_decimal(scenario.cash_available),
            canonical_decimal(scenario.total_fees),
            canonical_decimal(scenario.total_tax_estimate),
            scenario.status,
            None
            if scenario.projected_total is None
            else canonical_decimal(scenario.projected_total),
            scenario.result_sha256,
            result_json,
        )

    @staticmethod
    def _plan_action_values(action: CandidateAction) -> tuple:
        return (
            action.id,
            action.scenario_id,
            action.sequence,
            action.instrument_id,
            canonical_decimal(action.base_value_delta),
            canonical_decimal(action.fee),
            canonical_decimal(action.tax_estimate),
        )

    @staticmethod
    def _projected_state_values(state: ProjectedState) -> tuple:
        return (
            state.id,
            state.scenario_id,
            int(state.complete),
            None if state.total_value is None else canonical_decimal(state.total_value),
            state.valuation_sha256,
        )

    @staticmethod
    def _plan_constraint_values(constraint: UnresolvedConstraint) -> tuple:
        return (
            constraint.id,
            constraint.scenario_id,
            constraint.rule_id,
            constraint.rule_key,
            constraint.severity,
            constraint.status,
            constraint.kind,
            None if constraint.gap is None else canonical_decimal(constraint.gap),
            constraint.explanation,
        )

    def add_plan(
        self,
        plan: Plan,
        scenarios: Iterable[PlanScenario],
        actions: Iterable[CandidateAction],
        constraints: Iterable[UnresolvedConstraint],
        projected_states: Iterable[ProjectedState],
        results: Mapping[str, Mapping[str, Any]],
    ) -> None:
        self.portfolio(plan.portfolio_id)
        self.policy(plan.policy_id)
        version = self.policy_version(plan.policy_version_id)
        if version["policy_id"] != plan.policy_id:
            raise ValueError("plan policy version belongs to a different policy")
        self._require_import_artifact(plan.source_artifact_id, plan.import_batch_id)
        scenario_rows = tuple(scenarios)
        action_rows = tuple(actions)
        constraint_rows = tuple(constraints)
        projected_rows = tuple(projected_states)
        if not scenario_rows:
            raise ValueError("plan requires at least one scenario")
        if any(row.plan_id != plan.id for row in scenario_rows):
            raise ValueError("plan scenario belongs to a different plan")
        scenario_ids = {row.id for row in scenario_rows}
        if any(row.scenario_id not in scenario_ids for row in action_rows + constraint_rows):
            raise ValueError("plan child belongs to an unknown scenario")
        if {row.scenario_id for row in projected_rows} != scenario_ids:
            raise ValueError("plan requires one projected state per scenario")
        if set(results) != {row.id for row in scenario_rows}:
            raise ValueError("plan results must cover every scenario")
        with self.write_transaction():
            self.db.execute("INSERT INTO plans VALUES(?,?,?,?,?,?,?,?,?,?)", self._plan_values(plan))
            self.db.executemany(
                "INSERT INTO plan_scenarios VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    self._plan_scenario_values(
                        row,
                        json.dumps(results[row.id], sort_keys=True, separators=(",", ":")),
                    )
                    for row in scenario_rows
                ),
            )
            self.db.executemany(
                "INSERT INTO plan_actions VALUES(?,?,?,?,?,?,?)",
                (self._plan_action_values(row) for row in action_rows),
            )
            self.db.executemany(
                "INSERT INTO plan_projected_states VALUES(?,?,?,?,?)",
                (self._projected_state_values(row) for row in projected_rows),
            )
            self.db.executemany(
                "INSERT INTO plan_constraints VALUES(?,?,?,?,?,?,?,?,?)",
                (self._plan_constraint_values(row) for row in constraint_rows),
            )
            append_audit_event(
                self.db,
                operation="planning.create",
                object_type="plan",
                object_id=plan.id,
                payload={
                    "portfolio_id": plan.portfolio_id,
                    "policy_id": plan.policy_id,
                    "policy_version_id": plan.policy_version_id,
                    "scenario_count": len(scenario_rows),
                    "source_artifact_id": plan.source_artifact_id,
                    "import_batch_id": plan.import_batch_id,
                },
            )

    def plan(self, plan_id: str) -> sqlite3.Row:
        require_uuid(plan_id, "plan_id")
        row = self.db.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown plan: {plan_id}")
        return row

    def plans(self, portfolio_id: str | None = None) -> list[sqlite3.Row]:
        query = "SELECT * FROM plans"
        arguments: tuple[str, ...] = ()
        if portfolio_id is not None:
            require_uuid(portfolio_id, "portfolio_id")
            query += " WHERE portfolio_id=?"
            arguments = (portfolio_id,)
        return self.db.execute(query + " ORDER BY created_at,id", arguments).fetchall()

    def plan_scenarios(self, plan_id: str) -> list[sqlite3.Row]:
        self.plan(plan_id)
        return self.db.execute(
            "SELECT * FROM plan_scenarios WHERE plan_id=? ORDER BY scenario_key,id",
            (plan_id,),
        ).fetchall()

    def plan_actions(self, scenario_id: str) -> list[sqlite3.Row]:
        require_uuid(scenario_id, "scenario_id")
        return self.db.execute(
            "SELECT * FROM plan_actions WHERE scenario_id=? ORDER BY sequence,id",
            (scenario_id,),
        ).fetchall()

    def plan_constraints(self, scenario_id: str) -> list[sqlite3.Row]:
        require_uuid(scenario_id, "scenario_id")
        return self.db.execute(
            "SELECT * FROM plan_constraints WHERE scenario_id=? ORDER BY id",
            (scenario_id,),
        ).fetchall()

    def plan_projected_state(self, scenario_id: str) -> sqlite3.Row:
        require_uuid(scenario_id, "scenario_id")
        row = self.db.execute(
            "SELECT * FROM plan_projected_states WHERE scenario_id=?", (scenario_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown projected state for scenario: {scenario_id}")
        return row

    @staticmethod
    def _decision_values(decision: Decision) -> tuple:
        return (
            decision.id,
            decision.portfolio_id,
            decision.title,
            decision.intent,
            decision.rationale,
            decision.as_of,
            decision.known_as_of,
            decision.created_at,
            decision.policy_version_id,
            decision.plan_id,
            decision.source_artifact_id,
            decision.import_batch_id,
        )

    @staticmethod
    def _alternative_values(alternative: DecisionAlternative) -> tuple:
        return (
            alternative.id,
            alternative.decision_id,
            alternative.alternative_key,
            alternative.description,
            int(alternative.selected),
        )

    def add_decision(
        self, decision: Decision, alternatives: Iterable[DecisionAlternative],
        statements: Iterable[DecisionStatement] = (),
        review_schedules: Iterable[DecisionReviewSchedule] = (),
    ) -> None:
        self.portfolio(decision.portfolio_id)
        if decision.policy_version_id is not None:
            self.policy_version(decision.policy_version_id)
        if decision.plan_id is not None:
            self.plan(decision.plan_id)
        self._require_import_artifact(decision.source_artifact_id, decision.import_batch_id)
        alternative_rows = tuple(alternatives)
        statement_rows = tuple(statements)
        schedule_rows = tuple(review_schedules)
        if any(row.decision_id != decision.id for row in alternative_rows):
            raise ValueError("decision alternative belongs to a different decision")
        with self.write_transaction():
            self.db.execute("INSERT INTO decisions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", self._decision_values(decision))
            self.db.executemany(
                "INSERT INTO decision_alternatives VALUES(?,?,?,?,?)",
                (self._alternative_values(row) for row in alternative_rows),
            )
            self.db.executemany("INSERT INTO decision_statements VALUES(?,?,?,?,?)", ((row.id,row.decision_id,row.kind,row.statement_key,row.text) for row in statement_rows))
            self.db.executemany("INSERT INTO decision_review_schedules VALUES(?,?,?,?)", ((row.id,row.decision_id,row.review_type,row.due_at) for row in schedule_rows))
            append_audit_event(
                self.db,
                operation="decision.create",
                object_type="decision",
                object_id=decision.id,
                payload={
                    "portfolio_id": decision.portfolio_id,
                    "policy_version_id": decision.policy_version_id,
                    "plan_id": decision.plan_id,
                    "intent": decision.intent,
                    "alternative_count": len(alternative_rows),
                    "source_artifact_id": decision.source_artifact_id,
                    "import_batch_id": decision.import_batch_id,
                },
            )

    def decision(self, decision_id: str) -> sqlite3.Row:
        require_uuid(decision_id, "decision_id")
        row = self.db.execute("SELECT * FROM decisions WHERE id=?", (decision_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown decision: {decision_id}")
        return row

    def decisions(self, portfolio_id: str | None = None) -> list[sqlite3.Row]:
        query = "SELECT * FROM decisions"
        args: tuple[str, ...] = ()
        if portfolio_id is not None:
            require_uuid(portfolio_id, "portfolio_id")
            query += " WHERE portfolio_id=?"
            args = (portfolio_id,)
        return self.db.execute(query + " ORDER BY created_at,id", args).fetchall()

    def decision_alternatives(self, decision_id: str) -> list[sqlite3.Row]:
        self.decision(decision_id)
        return self.db.execute(
            "SELECT * FROM decision_alternatives WHERE decision_id=? ORDER BY alternative_key,id",
            (decision_id,),
        ).fetchall()

    def add_decision_policy_link(self, link: DecisionPolicyLink) -> None:
        decision = self.decision(link.decision_id)
        version = self.policy_version(link.policy_version_id)
        policy = self.policy(version["policy_id"])
        if policy["portfolio_id"] != decision["portfolio_id"]:
            raise ValueError("decision policy link crosses portfolio boundary")
        with self.write_transaction():
            self.db.execute(
                "INSERT INTO decision_policy_links VALUES(?,?,?,?)",
                (link.id, link.decision_id, link.policy_version_id, link.link_type),
            )
            append_audit_event(
                self.db,
                operation="decision.link_policy",
                object_type="decision_policy_link",
                object_id=link.id,
                payload={
                    "decision_id": link.decision_id,
                    "policy_version_id": link.policy_version_id,
                    "link_type": link.link_type,
                },
            )

    def add_decision_evidence_link(self, link: DecisionEvidenceLink) -> None:
        self.decision(link.decision_id)
        with self.write_transaction():
            self.db.execute(
                "INSERT INTO decision_evidence_links VALUES(?,?,?,?,?)",
                (link.id, link.decision_id, link.evidence_id, link.evidence_kind, link.relation),
            )
            append_audit_event(
                self.db,
                operation="decision.link_evidence",
                object_type="decision_evidence_link",
                object_id=link.id,
                payload={
                    "decision_id": link.decision_id,
                    "evidence_id": link.evidence_id,
                    "relation": link.relation,
                },
            )

    def add_decision_transaction_link(self, link: DecisionTransactionLink) -> None:
        decision = self.decision(link.decision_id)
        transaction = self.transaction(link.transaction_id)
        if transaction is None:
            raise KeyError(f"unknown transaction: {link.transaction_id}")
        account_ids = self.portfolio_accounts(
            decision["portfolio_id"],
            transaction["effective_at"],
            transaction["known_at"],
        )
        if transaction["account_id"] not in account_ids:
            raise ValueError("decision transaction link crosses portfolio boundary")
        with self.write_transaction():
            self.db.execute(
                "INSERT INTO decision_transaction_links VALUES(?,?,?,?,?)",
                (link.id, link.decision_id, link.transaction_id, link.relation, link.linked_at),
            )
            append_audit_event(
                self.db,
                operation="decision.link_transaction",
                object_type="decision_transaction_link",
                object_id=link.id,
                payload={
                    "decision_id": link.decision_id,
                    "transaction_id": link.transaction_id,
                    "relation": link.relation,
                },
            )

    def add_decision_review(self, review: DecisionReview) -> None:
        self.decision(review.decision_id)
        with self.write_transaction():
            self.db.execute(
                "INSERT INTO decision_reviews VALUES(?,?,?,?,?,?)",
                (
                    review.id,
                    review.decision_id,
                    review.review_type,
                    review.score,
                    review.notes,
                    review.reviewed_at,
                ),
            )
            append_audit_event(
                self.db,
                operation="decision.review",
                object_type="decision_review",
                object_id=review.id,
                payload={
                    "decision_id": review.decision_id,
                    "review_type": review.review_type,
                    "score": review.score,
                },
            )

    def decision_links(self, decision_id: str) -> dict[str, list[sqlite3.Row]]:
        self.decision(decision_id)
        return {
            "policy": self.db.execute(
                "SELECT * FROM decision_policy_links WHERE decision_id=? ORDER BY id",
                (decision_id,),
            ).fetchall(),
            "evidence": self.db.execute(
                "SELECT * FROM decision_evidence_links WHERE decision_id=? ORDER BY id",
                (decision_id,),
            ).fetchall(),
            "transaction": self.db.execute(
                "SELECT * FROM decision_transaction_links WHERE decision_id=? ORDER BY id",
                (decision_id,),
            ).fetchall(),
            "reviews": self.db.execute(
                "SELECT * FROM decision_reviews WHERE decision_id=? ORDER BY reviewed_at,id",
                (decision_id,),
            ).fetchall(),
            "statements": self.db.execute("SELECT * FROM decision_statements WHERE decision_id=? ORDER BY kind,statement_key,id", (decision_id,)).fetchall(),
            "review_schedules": self.db.execute("SELECT * FROM decision_review_schedules WHERE decision_id=? ORDER BY due_at,id", (decision_id,)).fetchall(),
        }

    def add_research_document(self, document: ResearchDocument) -> None:
        self._require_import_artifact(document.source_artifact_id, document.import_batch_id)
        with self.write_transaction():
            self.db.execute(
                """INSERT INTO research_documents
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    document.id,
                    document.title,
                    document.media_type,
                    document.source_uri,
                    document.text,
                    document.text_sha256,
                    document.effective_at,
                    document.known_at,
                    document.recorded_at,
                    document.source_artifact_id,
                    document.import_batch_id,
                ),
            )
            append_audit_event(
                self.db,
                operation="research.ingest_text",
                object_type="research_document",
                object_id=document.id,
                payload={
                    "source_artifact_id": document.source_artifact_id,
                    "import_batch_id": document.import_batch_id,
                    "text_sha256": document.text_sha256,
                },
            )

    def research_document(self, document_id: str) -> sqlite3.Row:
        require_uuid(document_id, "document_id")
        row = self.db.execute(
            "SELECT * FROM research_documents WHERE id=?", (document_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown research document: {document_id}")
        return row

    def research_documents(self, query: str | None = None) -> list[sqlite3.Row]:
        if query is None or not query.strip():
            return self.db.execute(
                "SELECT * FROM research_documents ORDER BY recorded_at,id"
            ).fetchall()
        pattern = f"%{query.strip().lower()}%"
        return self.db.execute(
            """SELECT * FROM research_documents
               WHERE lower(title) LIKE ? OR lower(source_uri) LIKE ? OR lower(text) LIKE ?
               ORDER BY recorded_at,id""",
            (pattern, pattern, pattern),
        ).fetchall()

    def add_research_claim(self, claim: ResearchClaim) -> None:
        self.research_document(claim.document_id)
        with self.write_transaction():
            self.db.execute(
                "INSERT INTO research_claims VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    claim.id,
                    claim.document_id,
                    claim.claim_key,
                    claim.text,
                    claim.span_start,
                    claim.span_end,
                    claim.generated_by,
                    claim.confidence,
                    claim.effective_at,
                    claim.known_at,
                    claim.recorded_at,
                    claim.source_artifact_id,
                    claim.import_batch_id,
                ),
            )
            append_audit_event(
                self.db,
                operation="research.create_claim",
                object_type="research_claim",
                object_id=claim.id,
                payload={"document_id": claim.document_id, "claim_key": claim.claim_key},
            )

    def research_claim(self, claim_id: str) -> sqlite3.Row:
        require_uuid(claim_id, "claim_id")
        row = self.db.execute(
            "SELECT * FROM research_claims WHERE id=?", (claim_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown research claim: {claim_id}")
        return row

    def research_claims(self, document_id: str) -> list[sqlite3.Row]:
        self.research_document(document_id)
        return self.db.execute(
            "SELECT * FROM research_claims WHERE document_id=? ORDER BY claim_key,id",
            (document_id,),
        ).fetchall()

    def all_research_claims(self) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM research_claims ORDER BY recorded_at,id"
        ).fetchall()

    def add_research_evidence(self, evidence: ResearchEvidence) -> None:
        self.research_document(evidence.document_id)
        with self.write_transaction():
            self.db.execute(
                "INSERT INTO research_evidence VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    evidence.id,
                    evidence.document_id,
                    evidence.kind,
                    evidence.text,
                    evidence.span_start,
                    evidence.span_end,
                    evidence.relation,
                    evidence.generated_by,
                    evidence.confidence,
                    evidence.effective_at,
                    evidence.known_at,
                    evidence.recorded_at,
                    evidence.source_artifact_id,
                    evidence.import_batch_id,
                ),
            )
            append_audit_event(
                self.db,
                operation="research.create_evidence",
                object_type="research_evidence",
                object_id=evidence.id,
                payload={"document_id": evidence.document_id, "relation": evidence.relation},
            )

    def research_evidence(self, document_id: str) -> list[sqlite3.Row]:
        self.research_document(document_id)
        return self.db.execute(
            "SELECT * FROM research_evidence WHERE document_id=? ORDER BY id",
            (document_id,),
        ).fetchall()

    def all_research_evidence(self) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM research_evidence ORDER BY recorded_at,id"
        ).fetchall()

    def add_research_contradiction(
        self, contradiction: ResearchContradiction
    ) -> None:
        for claim_id in (contradiction.claim_a_id, contradiction.claim_b_id):
            if self.db.execute(
                "SELECT 1 FROM research_claims WHERE id=?", (claim_id,)
            ).fetchone() is None:
                raise KeyError(f"unknown research claim: {claim_id}")
        self._require_import_artifact(
            contradiction.source_artifact_id, contradiction.import_batch_id
        )
        with self.write_transaction():
            self.db.execute(
                "INSERT INTO research_contradictions VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    contradiction.id,
                    contradiction.claim_a_id,
                    contradiction.claim_b_id,
                    contradiction.kind,
                    contradiction.explanation,
                    contradiction.known_at,
                    contradiction.recorded_at,
                    contradiction.source_artifact_id,
                    contradiction.import_batch_id,
                ),
            )
            append_audit_event(
                self.db,
                operation="research.create_contradiction",
                object_type="research_contradiction",
                object_id=contradiction.id,
                payload={
                    "claim_a_id": contradiction.claim_a_id,
                    "claim_b_id": contradiction.claim_b_id,
                    "kind": contradiction.kind,
                },
            )

    def research_contradictions(self, claim_id: str) -> list[sqlite3.Row]:
        require_uuid(claim_id, "claim_id")
        return self.db.execute(
            """SELECT * FROM research_contradictions
               WHERE claim_a_id=? OR claim_b_id=?
               ORDER BY recorded_at,id""",
            (claim_id, claim_id),
        ).fetchall()

    def add_research_thesis(
        self, thesis: ResearchThesis, revision: ThesisRevision
    ) -> None:
        if revision.thesis_id != thesis.id or revision.revision_number != 1:
            raise ValueError("initial thesis revision must belong to thesis and be version one")
        self._require_import_artifact(thesis.source_artifact_id, thesis.import_batch_id)
        self._require_import_artifact(revision.source_artifact_id, revision.import_batch_id)
        with self.write_transaction():
            self.db.execute(
                "INSERT INTO research_theses VALUES(?,?,?,?,?)",
                (
                    thesis.id,
                    thesis.title,
                    thesis.created_at,
                    thesis.source_artifact_id,
                    thesis.import_batch_id,
                ),
            )
            self.db.execute(
                "INSERT INTO thesis_revisions VALUES(?,?,?,?,?,?,?,?)",
                (
                    revision.id,
                    revision.thesis_id,
                    revision.revision_number,
                    revision.text,
                    revision.known_at,
                    revision.recorded_at,
                    revision.source_artifact_id,
                    revision.import_batch_id,
                ),
            )
            append_audit_event(
                self.db,
                operation="research.create_thesis",
                object_type="research_thesis",
                object_id=thesis.id,
                payload={"revision_number": revision.revision_number},
            )

    def add_thesis_revision(self, revision: ThesisRevision) -> None:
        self.research_thesis(revision.thesis_id)
        latest = self.db.execute(
            "SELECT MAX(revision_number) AS number FROM thesis_revisions WHERE thesis_id=?",
            (revision.thesis_id,),
        ).fetchone()["number"]
        if revision.revision_number != latest + 1:
            raise ValueError("thesis revisions must be appended sequentially")
        self._require_import_artifact(revision.source_artifact_id, revision.import_batch_id)
        with self.write_transaction():
            self.db.execute(
                "INSERT INTO thesis_revisions VALUES(?,?,?,?,?,?,?,?)",
                (
                    revision.id,
                    revision.thesis_id,
                    revision.revision_number,
                    revision.text,
                    revision.known_at,
                    revision.recorded_at,
                    revision.source_artifact_id,
                    revision.import_batch_id,
                ),
            )
            append_audit_event(
                self.db,
                operation="research.revise_thesis",
                object_type="thesis_revision",
                object_id=revision.id,
                payload={
                    "thesis_id": revision.thesis_id,
                    "revision_number": revision.revision_number,
                },
            )

    def research_thesis(self, thesis_id: str) -> sqlite3.Row:
        require_uuid(thesis_id, "thesis_id")
        row = self.db.execute(
            "SELECT * FROM research_theses WHERE id=?", (thesis_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown research thesis: {thesis_id}")
        return row

    def research_theses(self) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM research_theses ORDER BY created_at,id"
        ).fetchall()

    def thesis_revisions(self, thesis_id: str) -> list[sqlite3.Row]:
        self.research_thesis(thesis_id)
        return self.db.execute(
            "SELECT * FROM thesis_revisions WHERE thesis_id=? ORDER BY revision_number,id",
            (thesis_id,),
        ).fetchall()

    def _research_node_exists(self, node_type: str, node_id: str) -> bool:
        tables = {
            "document": "research_documents",
            "claim": "research_claims",
            "evidence": "research_evidence",
            "thesis": "research_theses",
            "decision": "decisions",
            "transaction": "transactions",
        }
        table = tables.get(node_type)
        if table is None:
            raise ValueError(f"unsupported research node type: {node_type}")
        require_uuid(node_id, f"{node_type}_id")
        return self.db.execute(f"SELECT 1 FROM {table} WHERE id=?", (node_id,)).fetchone() is not None

    def add_research_link(self, link: ResearchLink) -> None:
        if not self._research_node_exists(link.from_type, link.from_id):
            raise KeyError(f"unknown research source node: {link.from_id}")
        if not self._research_node_exists(link.to_type, link.to_id):
            raise KeyError(f"unknown research target node: {link.to_id}")
        self._require_import_artifact(link.source_artifact_id, link.import_batch_id)
        with self.write_transaction():
            self.db.execute(
                """INSERT INTO research_links(
                   id,from_type,from_id,to_type,to_id,relation,created_at,
                   source_artifact_id,import_batch_id,effective_at,known_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    link.id,
                    link.from_type,
                    link.from_id,
                    link.to_type,
                    link.to_id,
                    link.relation,
                    link.created_at,
                    link.source_artifact_id,
                    link.import_batch_id,
                    link.effective_at,
                    link.known_at,
                ),
            )
            append_audit_event(
                self.db,
                operation="research.link",
                object_type="research_link",
                object_id=link.id,
                payload={
                    "from_type": link.from_type,
                    "from_id": link.from_id,
                    "to_type": link.to_type,
                    "to_id": link.to_id,
                    "relation": link.relation,
                },
            )

    def research_links(self, node_type: str, node_id: str) -> list[sqlite3.Row]:
        if not self._research_node_exists(node_type, node_id):
            raise KeyError(f"unknown research node: {node_id}")
        return self.db.execute(
            """SELECT * FROM research_links
               WHERE (from_type=? AND from_id=?) OR (to_type=? AND to_id=?)
               ORDER BY created_at,id""",
            (node_type, node_id, node_type, node_id),
        ).fetchall()

    def add_recommendation(
        self,
        recommendation: Recommendation,
        alternatives: Iterable[RecommendationAlternative],
    ) -> None:
        self.portfolio(recommendation.portfolio_id)
        self._require_import_artifact(
            recommendation.source_artifact_id, recommendation.import_batch_id
        )
        rows = tuple(alternatives)
        if any(row.recommendation_id != recommendation.id for row in rows):
            raise ValueError("recommendation alternative belongs to another recommendation")
        with self.write_transaction():
            self.db.execute(
                "INSERT INTO recommendations VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    recommendation.id,
                    recommendation.portfolio_id,
                    recommendation.subject,
                    recommendation.recommendation_type,
                    recommendation.rationale,
                    recommendation.origin.value,
                    recommendation.as_of,
                    recommendation.known_as_of,
                    recommendation.created_at,
                    recommendation.payload_json,
                    recommendation.source_artifact_id,
                    recommendation.import_batch_id,
                ),
            )
            self.db.executemany(
                "INSERT INTO recommendation_alternatives VALUES(?,?,?,?,?)",
                (
                    (row.id, row.recommendation_id, row.key, row.description, int(row.selected))
                    for row in rows
                ),
            )
            append_audit_event(
                self.db,
                operation="recommendation.create",
                object_type="recommendation",
                object_id=recommendation.id,
                payload={"portfolio_id": recommendation.portfolio_id, "origin": recommendation.origin.value},
            )

    def recommendation(self, recommendation_id: str) -> sqlite3.Row:
        require_uuid(recommendation_id, "recommendation_id")
        row = self.db.execute(
            """SELECT r.*,
               COALESCE((
                 SELECT status FROM recommendation_transitions t
                 WHERE t.recommendation_id=r.id
                 ORDER BY t.transitioned_at DESC,t.id DESC LIMIT 1
               ), 'draft') AS status
               FROM recommendations r WHERE r.id=?""",
            (recommendation_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown recommendation: {recommendation_id}")
        return row

    def recommendation_alternatives(
        self, recommendation_id: str
    ) -> list[sqlite3.Row]:
        self.recommendation(recommendation_id)
        return self.db.execute(
            """SELECT * FROM recommendation_alternatives
               WHERE recommendation_id=? ORDER BY alternative_key,id""",
            (recommendation_id,),
        ).fetchall()

    def transition_recommendation(self, recommendation_id: str, status: str) -> None:
        current = self.recommendation(recommendation_id)
        artifact_id, _ = self.virtual_artifact(
            "manual://recommendation-transition",
            json.dumps(
                {"recommendation_id": recommendation_id, "status": status},
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
        batch_id = self.import_batch(
            artifact_id,
            adapter_name="manual-recommendation",
            adapter_version="1",
            schema_version="1",
        )
        with self.write_transaction():
            self.db.execute(
                "INSERT INTO recommendation_transitions VALUES(?,?,?,?,?,?)",
                (new_id(), recommendation_id, status, now(), artifact_id, batch_id),
            )
            append_audit_event(
                self.db,
                operation="recommendation.transition",
                object_type="recommendation",
                object_id=recommendation_id,
                payload={"from": current["status"], "to": status},
            )

    def import_batch(
        self,
        artifact_id: str,
        *,
        adapter_name: str = "manual",
        adapter_version: str = "1",
        schema_version: str = "1",
    ) -> str:
        batch_id = new_id()
        with self.write_transaction():
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
