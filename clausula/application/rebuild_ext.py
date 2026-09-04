from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from clausula.adapters.accounting import AccountingPolicyProjection

from .accounting import AccountingService
from .rebuild import LedgerRebuilder as _BaseLedgerRebuilder, RebuildError
from .research import ResearchService
from .research_ingest import ResearchIngestionService


class LedgerRebuilder(_BaseLedgerRebuilder):
    """Extend canonical rebuild with deterministic extracted research and local policy state."""

    def rebuild(self) -> dict[str, Any]:
        result = super().rebuild()
        # Raw research inputs and accounting-policy provenance are replayed by
        # extension-owned contracts. Suppress only those expected diagnostics.
        result["warnings"] = [
            warning
            for warning in result.get("warnings", [])
            if warning.get("adapter_name")
            not in {"research-source", "manual-accounting-policy"}
        ]
        accounting = self._rebuild_accounting_policies(result["account_mapping"])
        result["accounting_policy_mapping"] = accounting["mapping"]
        result["accounting_policy_comparisons"] = accounting["comparisons"]
        comparison_groups = (
            "comparisons",
            "portfolio_comparisons",
            "policy_comparisons",
            "plan_comparisons",
            "decision_comparisons",
            "research_comparisons",
        )
        base_matches = all(
            row.get("matches", True)
            for key in comparison_groups
            for row in result.get(key, [])
        )
        result["consistent"] = (
            base_matches
            and not result["warnings"]
            and all(row["matches"] for row in accounting["comparisons"])
        )
        return result

    def _rebuild_accounting_policies(
        self, account_mapping: dict[str, str]
    ) -> dict[str, Any]:
        if not hasattr(self.source, "db") or not hasattr(self.target, "db"):
            return {"mapping": {}, "comparisons": []}
        rows = self.source.db.execute(
            """SELECT * FROM audit_events
               WHERE object_type='accounting_policy_version'
               ORDER BY sequence"""
        ).fetchall()
        if not rows:
            return {"mapping": {}, "comparisons": []}
        target_service = AccountingService(AccountingPolicyProjection(self.target))
        mapping: dict[str, str] = {}
        source_by_policy: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            payload = json.loads(row["payload_json"])
            source_by_policy.setdefault(row["object_id"], []).append(payload)
        for source_policy_id, versions in source_by_policy.items():
            ordered = sorted(versions, key=lambda item: int(item["version_number"]))
            first = ordered[0]
            target_account_id = account_mapping[first["account_id"]]
            created = target_service.create_policy(
                target_account_id,
                first["effective_from"],
                lot_method=first["lot_method"],
                allow_short=bool(first["allow_short"]),
                jurisdiction_profile=first["jurisdiction_profile"],
                tax_profile_ref=first.get("tax_profile_ref"),
                known_at=first["known_at"],
            )
            target_policy_id = created["policy_id"]
            mapping[source_policy_id] = target_policy_id
            for version in ordered[1:]:
                target_service.add_version(
                    target_policy_id,
                    version["effective_from"],
                    lot_method=version["lot_method"],
                    allow_short=bool(version["allow_short"]),
                    jurisdiction_profile=version["jurisdiction_profile"],
                    tax_profile_ref=version.get("tax_profile_ref"),
                    known_at=version["known_at"],
                )
        comparisons = []
        target_projection = AccountingPolicyProjection(self.target)
        for source_policy_id, versions in source_by_policy.items():
            target_policy_id = mapping[source_policy_id]
            target_versions = target_projection.versions(policy_id=target_policy_id)
            source_semantics = [self._accounting_semantics(row) for row in versions]
            target_semantics = [self._accounting_semantics(row) for row in target_versions]
            comparisons.append(
                {
                    "source_policy_id": source_policy_id,
                    "target_policy_id": target_policy_id,
                    "source_count": len(source_semantics),
                    "target_count": len(target_semantics),
                    "matches": source_semantics == target_semantics,
                }
            )
        return {"mapping": mapping, "comparisons": comparisons}

    @staticmethod
    def _accounting_semantics(row: dict[str, Any]) -> tuple[Any, ...]:
        return (
            int(row["version_number"]),
            row["effective_from"],
            row["known_at"],
            row["lot_method"],
            bool(row["allow_short"]),
            row["jurisdiction_profile"],
            row.get("tax_profile_ref"),
        )

    def _replay_research_event(
        self,
        research: ResearchService,
        event: dict[str, Any],
        artifact_paths: dict[str, Path],
        mapping: dict[str, str],
    ) -> dict[str, Any]:
        if event.get("operation") != "research.ingest_source":
            return super()._replay_research_event(research, event, artifact_paths, mapping)
        if event.get("schema_version") != "1":
            raise ValueError("unsupported research event schema")
        source_path = artifact_paths.get(event.get("source_artifact_sha256", ""))
        if source_path is None or not source_path.is_file():
            raise RebuildError("research source artifact is missing")
        result = ResearchIngestionService(self.target).ingest_file(
            source_path,
            title=event["title"],
            source_uri=event["source_uri"],
            known_at=event["known_at"],
            effective_at=event["effective_at"],
            recorded_at=event["recorded_at"],
            media_type=event["media_type"],
            capture_metadata=event.get("capture") or {},
        )
        document = result["document"]
        if document["text_sha256"] != event["text_sha256"]:
            raise RebuildError(
                "research extraction changed during rebuild; extractor output is not deterministic"
            )
        source_map = result["source_map"]
        if source_map["extractor"] != event["extractor"]:
            raise RebuildError("research extractor identity changed during rebuild")
        if source_map["extractor_version"] != event["extractor_version"]:
            raise RebuildError("research extractor version changed during rebuild")
        mapping[event["document_id"]] = document["id"]
        return result
