from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Mapping, Sequence

from clausula.analytics import evaluate_policy, simulate_base_currency_trades
from clausula.domain import (
    InvestmentPolicy,
    PolicyRule,
    PolicyVersion,
    canonical_decimal,
    canonical_timestamp,
    new_id,
    now,
)

from .portfolio import PortfolioService
from .ports import CoreRepository


POLICY_EVENT_FORMAT = "clausula-policy-event-v1"
RULE_FIELDS = {
    "key",
    "type",
    "severity",
    "description",
    "subject",
    "target",
    "lower",
    "upper",
}


def _stable_rule_id(policy_version_id: str, rule_key: str) -> str:
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"clausula:policy-rule:{policy_version_id}:{rule_key}",
        )
    )


class PolicyService:
    def __init__(self, repository: CoreRepository):
        self.repository = repository
        self.portfolios = PortfolioService(repository)

    def create(
        self,
        portfolio_id: str,
        name: str,
        effective_from: str,
        rules: Sequence[Mapping[str, Any]],
        *,
        known_at: str | None = None,
        created_at: str | None = None,
        recorded_at: str | None = None,
    ) -> dict[str, Any]:
        self.repository.portfolio(portfolio_id)
        policy_id = new_id()
        version_id = new_id()
        recorded_time = canonical_timestamp(recorded_at or now())
        created_time = canonical_timestamp(created_at or recorded_time)
        knowledge_time = canonical_timestamp(known_at or recorded_time)
        normalized_name = str(name).strip()
        if not normalized_name:
            raise ValueError("policy name is required")
        normalized_rules, rule_objects, rules_sha256 = self._rules(
            version_id, rules
        )
        version = PolicyVersion(
            version_id,
            policy_id,
            1,
            effective_from,
            knowledge_time,
            recorded_time,
            rules_sha256,
            new_id(),
            new_id(),
        )
        event = {
            "format": POLICY_EVENT_FORMAT,
            "schema_version": "1",
            "operation": "policy.create",
            "policy_id": policy_id,
            "policy_version_id": version_id,
            "portfolio_id": portfolio_id,
            "name": normalized_name,
            "version_number": 1,
            "effective_from": version.effective_from,
            "known_at": version.known_at,
            "recorded_at": version.recorded_at,
            "created_at": created_time,
            "rules_sha256": rules_sha256,
            "rules": normalized_rules,
        }
        with self.repository.write_transaction():
            artifact_id, _ = self.repository.virtual_artifact(
                "manual://policy-create", self._event_json(event)
            )
            batch_id = self.repository.import_batch(
                artifact_id,
                adapter_name="manual-policy",
                adapter_version="1",
                schema_version="1",
            )
            policy = InvestmentPolicy(
                policy_id,
                portfolio_id,
                normalized_name,
                created_time,
                artifact_id,
                batch_id,
            )
            version = PolicyVersion(
                version.id,
                version.policy_id,
                version.version_number,
                version.effective_from,
                version.known_at,
                version.recorded_at,
                version.rules_sha256,
                artifact_id,
                batch_id,
            )
            self.repository.add_policy(policy, version, rule_objects)
        return self._write_result(policy, version, len(rule_objects))

    def add_version(
        self,
        policy_id: str,
        effective_from: str,
        rules: Sequence[Mapping[str, Any]],
        *,
        known_at: str | None = None,
        recorded_at: str | None = None,
    ) -> dict[str, Any]:
        self.repository.policy(policy_id)
        version_id = new_id()
        version_number = self.repository.next_policy_version_number(policy_id)
        recorded_time = canonical_timestamp(recorded_at or now())
        knowledge_time = canonical_timestamp(known_at or recorded_time)
        normalized_rules, rule_objects, rules_sha256 = self._rules(
            version_id, rules
        )
        version = PolicyVersion(
            version_id,
            policy_id,
            version_number,
            effective_from,
            knowledge_time,
            recorded_time,
            rules_sha256,
            new_id(),
            new_id(),
        )
        event = {
            "format": POLICY_EVENT_FORMAT,
            "schema_version": "1",
            "operation": "policy.add_version",
            "policy_id": policy_id,
            "policy_version_id": version_id,
            "version_number": version_number,
            "effective_from": version.effective_from,
            "known_at": version.known_at,
            "recorded_at": version.recorded_at,
            "rules_sha256": rules_sha256,
            "rules": normalized_rules,
        }
        with self.repository.write_transaction():
            artifact_id, _ = self.repository.virtual_artifact(
                "manual://policy-version", self._event_json(event)
            )
            batch_id = self.repository.import_batch(
                artifact_id,
                adapter_name="manual-policy-version",
                adapter_version="1",
                schema_version="1",
            )
            version = PolicyVersion(
                version.id,
                version.policy_id,
                version.version_number,
                version.effective_from,
                version.known_at,
                version.recorded_at,
                version.rules_sha256,
                artifact_id,
                batch_id,
            )
            self.repository.add_policy_version(version, rule_objects)
        policy = InvestmentPolicy(**dict(self.repository.policy(policy_id)))
        return self._write_result(policy, version, len(rule_objects))

    def list(self, portfolio_id: str | None = None) -> list[dict[str, Any]]:
        return [dict(row) for row in self.repository.policies(portfolio_id)]

    def evaluate(
        self,
        policy_id: str,
        as_of: str,
        *,
        known_as_of: str | None = None,
        price_dataset_name: str | None = None,
        price_dataset_version: str | None = None,
        fx_dataset_name: str | None = None,
        fx_dataset_version: str | None = None,
    ) -> dict[str, Any]:
        effective_cutoff = canonical_timestamp(as_of)
        knowledge_cutoff = canonical_timestamp(known_as_of or as_of)
        policy = dict(self.repository.policy(policy_id))
        version = dict(
            self.repository.policy_version_at(
                policy_id, effective_cutoff, knowledge_cutoff
            )
        )
        rules = self._stored_rules(version["id"])
        valuation = self.portfolios.portfolio_valuation(
            policy["portfolio_id"],
            effective_cutoff,
            known_as_of=knowledge_cutoff,
            price_dataset_name=price_dataset_name,
            price_dataset_version=price_dataset_version,
            fx_dataset_name=fx_dataset_name,
            fx_dataset_version=fx_dataset_version,
        )
        result = evaluate_policy(
            valuation,
            rules,
            policy_version_id=version["id"],
            portfolio_id=policy["portfolio_id"],
            as_of=effective_cutoff,
            known_as_of=knowledge_cutoff,
        )
        return {
            "policy_id": policy_id,
            "policy_name": policy["name"],
            "version_number": version["version_number"],
            **result,
            "valuation": valuation,
        }

    def simulate(
        self,
        policy_id: str,
        as_of: str,
        actions: Sequence[Mapping[str, Any]],
        **options: Any,
    ) -> dict[str, Any]:
        before = self.evaluate(policy_id, as_of, **options)
        instrument_ids = {str(action["instrument_id"]) for action in actions}
        instruments = {
            instrument_id: dict(self.repository.instrument_details(instrument_id))
            for instrument_id in instrument_ids
        }
        simulated_valuation = simulate_base_currency_trades(
            before["valuation"], actions, instruments
        )
        after = evaluate_policy(
            simulated_valuation,
            self._stored_rules(before["policy_version_id"]),
            policy_version_id=before["policy_version_id"],
            portfolio_id=before["portfolio_id"],
            as_of=before["as_of"],
            known_as_of=before["known_as_of"],
        )
        return {
            "policy_id": policy_id,
            "policy_version_id": before["policy_version_id"],
            "as_of": before["as_of"],
            "known_as_of": before["known_as_of"],
            "before": {key: value for key, value in before.items() if key != "valuation"},
            "after": after,
            "simulated_valuation": simulated_valuation,
        }

    def _stored_rules(self, version_id: str) -> list[PolicyRule]:
        return [
            PolicyRule(
                row["id"],
                row["policy_version_id"],
                row["rule_key"],
                row["rule_type"],
                row["severity"],
                row["description"],
                row["subject"],
                row["target"],
                row["lower_bound"],
                row["upper_bound"],
            )
            for row in self.repository.policy_rules(version_id)
        ]

    @staticmethod
    def _rules(
        version_id: str, definitions: Sequence[Mapping[str, Any]]
    ) -> tuple[list[dict[str, Any]], tuple[PolicyRule, ...], str]:
        if not definitions:
            raise ValueError("policy version requires at least one rule")
        normalized: list[dict[str, Any]] = []
        keys: set[str] = set()
        for index, definition in enumerate(definitions):
            unknown = set(definition) - RULE_FIELDS
            if unknown:
                raise ValueError(
                    f"policy rule {index} has unknown fields: {', '.join(sorted(unknown))}"
                )
            rule = PolicyRule(
                _stable_rule_id(version_id, str(definition.get("key", "")).strip()),
                version_id,
                definition.get("key", ""),
                definition.get("type", ""),
                definition.get("severity", "soft"),
                definition.get("description", ""),
                definition.get("subject"),
                definition.get("target"),
                definition.get("lower"),
                definition.get("upper"),
            )
            if rule.rule_key in keys:
                raise ValueError(f"duplicate policy rule key: {rule.rule_key}")
            keys.add(rule.rule_key)
            normalized.append(
                {
                    "id": rule.id,
                    "key": rule.rule_key,
                    "type": rule.rule_type,
                    "severity": rule.severity,
                    "description": rule.description,
                    "subject": rule.subject,
                    "target": None
                    if rule.target is None
                    else canonical_decimal(rule.target),
                    "lower": None
                    if rule.lower_bound is None
                    else canonical_decimal(rule.lower_bound),
                    "upper": None
                    if rule.upper_bound is None
                    else canonical_decimal(rule.upper_bound),
                }
            )
        normalized.sort(key=lambda item: item["key"])
        semantic_rules = [
            {key: item[key] for key in item if key != "id"}
            for item in normalized
        ]
        serialized = json.dumps(semantic_rules, sort_keys=True, separators=(",", ":"))
        return (
            normalized,
            tuple(
                PolicyRule(
                    item["id"],
                    version_id,
                    item["key"],
                    item["type"],
                    item["severity"],
                    item["description"],
                    item["subject"],
                    item["target"],
                    item["lower"],
                    item["upper"],
                )
                for item in normalized
            ),
            hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
        )

    @staticmethod
    def _event_json(event: Mapping[str, Any]) -> str:
        return json.dumps(event, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _write_result(
        policy: InvestmentPolicy, version: PolicyVersion, rule_count: int
    ) -> dict[str, Any]:
        return {
            "policy_id": policy.id,
            "policy_version_id": version.id,
            "version_number": version.version_number,
            "rules_sha256": version.rules_sha256,
            "source_artifact_id": version.source_artifact_id,
            "import_batch_id": version.import_batch_id,
            "rules": rule_count,
        }
