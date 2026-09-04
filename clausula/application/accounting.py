from __future__ import annotations

import json
from typing import Any

from clausula.analytics.lot_accounting import LOT_METHODS, LotAccountingError, replay_lots
from clausula.domain import canonical_timestamp, new_id, now

from .ledger_fast import LedgerService


ACCOUNTING_EVENT_FORMAT = "clausula-accounting-policy-v1"


class AccountingPolicyError(ValueError):
    pass


class AccountingService:
    """Apply explicit, versioned lot-accounting policy to canonical ledger facts."""

    def __init__(self, repository):
        self.repository = repository
        self.ledger = LedgerService(repository)

    @staticmethod
    def _lot_method(value: str) -> str:
        method = str(value).strip().lower()
        if method not in LOT_METHODS:
            raise AccountingPolicyError(
                f"lot_method must be one of {', '.join(sorted(LOT_METHODS))}"
            )
        return method

    @staticmethod
    def _text(value: str | None, field: str, *, default: str | None = None) -> str | None:
        result = str(value or default or "").strip()
        if not result:
            return None
        return result

    def create_policy(
        self,
        account_id: str,
        effective_from: str,
        *,
        lot_method: str = "fifo",
        allow_short: bool = False,
        jurisdiction_profile: str = "unspecified",
        tax_profile_ref: str | None = None,
        known_at: str | None = None,
        recorded_at: str | None = None,
    ) -> dict[str, Any]:
        self.repository.require_account(account_id)
        if self.repository.versions(account_id=account_id):
            raise AccountingPolicyError("account already has an accounting policy identity")
        return self._append(
            policy_id=new_id(),
            account_id=account_id,
            version_number=1,
            effective_from=effective_from,
            lot_method=lot_method,
            allow_short=allow_short,
            jurisdiction_profile=jurisdiction_profile,
            tax_profile_ref=tax_profile_ref,
            known_at=known_at,
            recorded_at=recorded_at,
        )

    def add_version(
        self,
        policy_id: str,
        effective_from: str,
        *,
        lot_method: str | None = None,
        allow_short: bool | None = None,
        jurisdiction_profile: str | None = None,
        tax_profile_ref: str | None = None,
        known_at: str | None = None,
        recorded_at: str | None = None,
    ) -> dict[str, Any]:
        versions = self.repository.versions(policy_id=policy_id)
        if not versions:
            raise KeyError(f"unknown accounting policy: {policy_id}")
        latest = max(versions, key=lambda row: int(row["version_number"]))
        return self._append(
            policy_id=policy_id,
            account_id=latest["account_id"],
            version_number=int(latest["version_number"]) + 1,
            effective_from=effective_from,
            lot_method=lot_method if lot_method is not None else latest["lot_method"],
            allow_short=allow_short if allow_short is not None else bool(latest["allow_short"]),
            jurisdiction_profile=(
                jurisdiction_profile
                if jurisdiction_profile is not None
                else latest["jurisdiction_profile"]
            ),
            tax_profile_ref=(
                tax_profile_ref if tax_profile_ref is not None else latest.get("tax_profile_ref")
            ),
            known_at=known_at,
            recorded_at=recorded_at,
        )

    def _append(
        self,
        *,
        policy_id: str,
        account_id: str,
        version_number: int,
        effective_from: str,
        lot_method: str,
        allow_short: bool,
        jurisdiction_profile: str,
        tax_profile_ref: str | None,
        known_at: str | None,
        recorded_at: str | None,
    ) -> dict[str, Any]:
        self.repository.require_account(account_id)
        if not isinstance(allow_short, bool):
            raise AccountingPolicyError("allow_short must be a boolean")
        method = self._lot_method(lot_method)
        jurisdiction = self._text(jurisdiction_profile, "jurisdiction_profile")
        if jurisdiction is None:
            raise AccountingPolicyError("jurisdiction_profile cannot be empty")
        effective = canonical_timestamp(effective_from)
        recorded = canonical_timestamp(recorded_at or now())
        knowledge = canonical_timestamp(known_at or recorded)
        if knowledge > recorded:
            raise AccountingPolicyError("known_at cannot be after recorded_at")
        payload = {
            "format": ACCOUNTING_EVENT_FORMAT,
            "schema_version": "1",
            "operation": "accounting.policy_version",
            "policy_id": policy_id,
            "account_id": account_id,
            "version_number": version_number,
            "effective_from": effective,
            "known_at": knowledge,
            "lot_method": method,
            "allow_short": allow_short,
            "jurisdiction_profile": jurisdiction,
            "tax_profile_ref": self._text(tax_profile_ref, "tax_profile_ref"),
        }
        provenance = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        with self.repository.write_transaction():
            artifact_id, _ = self.repository.virtual_artifact(
                "manual://accounting-policy", provenance
            )
            import_batch_id = self.repository.import_batch(
                artifact_id,
                adapter_name="manual-accounting-policy",
                adapter_version="1",
                schema_version="1",
            )
            payload["source_artifact_id"] = artifact_id
            payload["import_batch_id"] = import_batch_id
            created = self.repository.add_version(policy_id, payload)
        return created

    def active_policy(
        self,
        account_id: str,
        as_of: str,
        *,
        known_as_of: str | None = None,
    ) -> dict[str, Any]:
        self.repository.require_account(account_id)
        active = self.repository.active(account_id, as_of, known_as_of)
        if active is None:
            return {
                "status": "unavailable",
                "account_id": account_id,
                "as_of": canonical_timestamp(as_of),
                "known_as_of": canonical_timestamp(known_as_of or as_of),
                "reason": "no accounting policy is visible at the requested cutoff",
            }
        return {"status": "available", **active}

    def list_policies(self, account_id: str | None = None) -> list[dict[str, Any]]:
        return self.repository.versions(account_id=account_id)

    def cost_basis(
        self,
        account_id: str,
        as_of: str,
        *,
        known_as_of: str | None = None,
    ) -> dict[str, Any]:
        policy = self.active_policy(account_id, as_of, known_as_of=known_as_of)
        if policy["status"] != "available":
            return {
                "status": "unavailable",
                "account_id": account_id,
                "as_of": canonical_timestamp(as_of),
                "known_as_of": canonical_timestamp(known_as_of or as_of),
                "policy": policy,
                "reason": "cost basis requires an explicit accounting policy",
            }
        transactions = self.ledger.transactions(
            account_id, as_of, known_as_of=known_as_of
        )
        ids = [row["id"] for row in transactions]
        batch = getattr(self.repository, "transaction_metadata_many", None)
        if batch is not None:
            metadata = {key: dict(value) for key, value in batch(ids).items()}
        else:
            metadata = {
                transaction_id: dict(self.repository.transaction_metadata(transaction_id))
                for transaction_id in ids
            }
        try:
            report = replay_lots(
                transactions,
                metadata,
                method=policy["lot_method"],
                allow_short=bool(policy["allow_short"]),
            )
        except LotAccountingError as exc:
            raise AccountingPolicyError(str(exc)) from exc
        return {
            "status": "available",
            "account_id": account_id,
            "as_of": canonical_timestamp(as_of),
            "known_as_of": canonical_timestamp(known_as_of or as_of),
            "policy": policy,
            "tax_semantics": "external_profile_only",
            "tax_profile_ref": policy.get("tax_profile_ref"),
            **report,
        }
