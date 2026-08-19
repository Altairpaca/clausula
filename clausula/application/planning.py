from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from clausula.analytics import compare_plan_scenarios
from clausula.domain import (
    CandidateAction,
    Plan,
    PlanScenario,
    ProjectedState,
    UnresolvedConstraint,
    canonical_decimal,
    canonical_timestamp,
    dec,
    new_id,
    now,
)

from .portfolio import PortfolioService
from .policy import PolicyService
from .ports import CoreRepository


PLANNING_EVENT_FORMAT = "clausula-planning-event-v1"
SCENARIO_FIELDS = {"key", "description", "cash_available", "actions"}
ACTION_FIELDS = {"instrument_id", "base_value_delta", "fee", "tax_estimate"}


class PlanningError(ValueError):
    pass


class PlanningService:
    def __init__(self, repository: CoreRepository):
        self.repository = repository
        self.policies = PolicyService(repository)
        self.portfolios = PortfolioService(repository)

    def compare(
        self,
        policy_id: str,
        as_of: str,
        scenarios: Sequence[Mapping[str, Any]],
        *,
        known_as_of: str | None = None,
        price_dataset_name: str | None = None,
        price_dataset_version: str | None = None,
        fx_dataset_name: str | None = None,
        fx_dataset_version: str | None = None,
    ) -> dict[str, Any]:
        policy = dict(self.repository.policy(policy_id))
        effective_cutoff = canonical_timestamp(as_of)
        knowledge_cutoff = canonical_timestamp(known_as_of or as_of)
        version = dict(
            self.repository.policy_version_at(
                policy_id, effective_cutoff, knowledge_cutoff
            )
        )
        valuation = self.portfolios.portfolio_valuation(
            policy["portfolio_id"],
            effective_cutoff,
            known_as_of=knowledge_cutoff,
            price_dataset_name=price_dataset_name,
            price_dataset_version=price_dataset_version,
            fx_dataset_name=fx_dataset_name,
            fx_dataset_version=fx_dataset_version,
        )
        normalized = self._normalize_scenarios(scenarios)
        instrument_ids = {
            action["instrument_id"]
            for scenario in normalized
            for action in scenario["actions"]
        }
        instruments = {
            instrument_id: dict(self.repository.instrument_details(instrument_id))
            for instrument_id in instrument_ids
        }
        rules = self.policies._stored_rules(version["id"])
        result = compare_plan_scenarios(
            valuation,
            rules,
            normalized,
            instruments,
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
        }

    def create(
        self,
        policy_id: str,
        name: str,
        as_of: str,
        scenarios: Sequence[Mapping[str, Any]],
        *,
        known_as_of: str | None = None,
        created_at: str | None = None,
        recorded_at: str | None = None,
        price_dataset_name: str | None = None,
        price_dataset_version: str | None = None,
        fx_dataset_name: str | None = None,
        fx_dataset_version: str | None = None,
    ) -> dict[str, Any]:
        normalized_name = str(name).strip()
        if not normalized_name:
            raise PlanningError("plan name is required")
        normalized = self._normalize_scenarios(scenarios)
        comparison = self.compare(
            policy_id,
            as_of,
            normalized,
            known_as_of=known_as_of,
            price_dataset_name=price_dataset_name,
            price_dataset_version=price_dataset_version,
            fx_dataset_name=fx_dataset_name,
            fx_dataset_version=fx_dataset_version,
        )
        policy = dict(self.repository.policy(policy_id))
        plan_id = new_id()
        created_time = canonical_timestamp(created_at or now())
        recorded_time = canonical_timestamp(recorded_at or created_time)
        effective_cutoff = canonical_timestamp(as_of)
        knowledge_cutoff = canonical_timestamp(known_as_of or as_of)
        scenario_ids = {item["scenario_key"]: new_id() for item in comparison["scenarios"]}
        event = {
            "format": PLANNING_EVENT_FORMAT,
            "schema_version": "1",
            "operation": "planning.create",
            "plan_id": plan_id,
            "portfolio_id": policy["portfolio_id"],
            "policy_id": policy_id,
            "policy_version_id": comparison["policy_version_id"],
            "name": normalized_name,
            "as_of": effective_cutoff,
            "known_as_of": knowledge_cutoff,
            "created_at": created_time,
            "recorded_at": recorded_time,
            "price_dataset_name": price_dataset_name,
            "price_dataset_version": price_dataset_version,
            "fx_dataset_name": fx_dataset_name,
            "fx_dataset_version": fx_dataset_version,
            "scenarios": normalized,
            "comparison_sha256": self._comparison_sha256(comparison),
        }
        plan_result = self._build_persisted_rows(
            plan_id, comparison, normalized, scenario_ids
        )
        with self.repository.write_transaction():
            artifact_id, _ = self.repository.virtual_artifact(
                "manual://planning-create", self._event_json(event)
            )
            batch_id = self.repository.import_batch(
                artifact_id,
                adapter_name="manual-planning",
                adapter_version="1",
                schema_version="1",
            )
            plan = Plan(
                plan_id,
                policy["portfolio_id"],
                policy_id,
                comparison["policy_version_id"],
                normalized_name,
                effective_cutoff,
                knowledge_cutoff,
                created_time,
                artifact_id,
                batch_id,
            )
            self.repository.add_plan(plan, *plan_result)
        return {
            **self.get(plan_id),
            "comparison_sha256": event["comparison_sha256"],
        }

    def list(self, portfolio_id: str | None = None) -> list[dict[str, Any]]:
        return [dict(row) for row in self.repository.plans(portfolio_id)]

    def get(self, plan_id: str) -> dict[str, Any]:
        plan = dict(self.repository.plan(plan_id))
        scenarios = []
        for row in self.repository.plan_scenarios(plan_id):
            scenario = dict(row)
            result = json.loads(scenario.pop("result_json"))
            scenario["result"] = result
            scenario["actions"] = [dict(item) for item in self.repository.plan_actions(row["id"])]
            scenario["unresolved_constraints"] = [
                dict(item) for item in self.repository.plan_constraints(row["id"])
            ]
            scenario["projected_state"] = dict(
                self.repository.plan_projected_state(row["id"])
            )
            scenarios.append(scenario)
        return {"plan": plan, "scenarios": scenarios, "ledger_mutated": False}

    @staticmethod
    def _normalize_scenarios(
        scenarios: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        if not isinstance(scenarios, list) or not scenarios:
            raise PlanningError("planning requires a non-empty scenarios array")
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, raw in enumerate(scenarios):
            if not isinstance(raw, Mapping):
                raise PlanningError(f"planning scenario {index} must be an object")
            unknown = set(raw) - SCENARIO_FIELDS
            if unknown:
                raise PlanningError(
                    f"planning scenario {index} has unknown fields: {', '.join(sorted(unknown))}"
                )
            key = str(raw.get("key", "")).strip()
            if not key or key in seen:
                raise PlanningError("planning scenario keys must be non-empty and unique")
            seen.add(key)
            actions = raw.get("actions", [])
            if not isinstance(actions, list):
                raise PlanningError(f"planning scenario {key} actions must be an array")
            normalized_actions = []
            for action_index, raw_action in enumerate(actions):
                if not isinstance(raw_action, Mapping):
                    raise PlanningError(
                        f"planning action {key}[{action_index}] must be an object"
                    )
                unknown = set(raw_action) - ACTION_FIELDS
                if unknown:
                    raise PlanningError(
                        f"planning action {key}[{action_index}] has unknown fields: {', '.join(sorted(unknown))}"
                    )
                try:
                    instrument_id = str(raw_action["instrument_id"])
                    delta = dec(raw_action["base_value_delta"])
                    fee = dec(raw_action.get("fee", "0"))
                    tax = dec(raw_action.get("tax_estimate", "0"))
                except (KeyError, TypeError, ValueError) as exc:
                    raise PlanningError(
                        f"invalid planning action {key}[{action_index}]"
                    ) from exc
                if delta == 0:
                    raise PlanningError("candidate action delta cannot be zero")
                if fee < 0 or tax < 0:
                    raise PlanningError("candidate action fee and tax estimate cannot be negative")
                normalized_actions.append(
                    {
                        "instrument_id": instrument_id,
                        "base_value_delta": canonical_decimal(delta),
                        "fee": canonical_decimal(fee),
                        "tax_estimate": canonical_decimal(tax),
                    }
                )
            normalized.append(
                {
                    "key": key,
                    "description": str(raw.get("description", "")).strip(),
                    "cash_available": canonical_decimal(raw.get("cash_available", "0")),
                    "actions": normalized_actions,
                }
            )
        return normalized

    @staticmethod
    def _build_persisted_rows(
        plan_id: str,
        comparison: Mapping[str, Any],
        normalized: Sequence[Mapping[str, Any]],
        scenario_ids: Mapping[str, str],
    ) -> tuple[
        list[PlanScenario],
        list[CandidateAction],
        list[UnresolvedConstraint],
        list[ProjectedState],
        dict[str, dict[str, Any]],
    ]:
        inputs = {item["key"]: item for item in normalized}
        scenarios: list[PlanScenario] = []
        actions: list[CandidateAction] = []
        constraints: list[UnresolvedConstraint] = []
        projected_states: list[ProjectedState] = []
        results: dict[str, dict[str, Any]] = {}
        for item in comparison["scenarios"]:
            scenario_id = scenario_ids[item["scenario_key"]]
            scenarios.append(
                PlanScenario(
                    scenario_id,
                    plan_id,
                    item["scenario_key"],
                    item["description"],
                    item["cash_available"],
                    item["total_fees"],
                    item["total_tax_estimate"],
                    item["status"],
                    item["projected_total"],
                    item["result_sha256"],
                )
            )
            for sequence, action in enumerate(inputs[item["scenario_key"]]["actions"]):
                actions.append(
                    CandidateAction(
                        new_id(),
                        scenario_id,
                        sequence,
                        action["instrument_id"],
                        action["base_value_delta"],
                        action["fee"],
                        action["tax_estimate"],
                    )
                )
            for constraint in item["unresolved_constraints"]:
                constraints.append(
                    UnresolvedConstraint(
                        new_id(),
                        scenario_id,
                        constraint["rule_id"],
                        constraint["rule_key"],
                        constraint["severity"],
                        constraint["status"],
                        constraint["kind"],
                        constraint["gap"],
                        constraint["explanation"],
                    )
                )
            valuation_payload = json.dumps(
                PlanningService._semantic_value(item["simulated_valuation"]),
                sort_keys=True,
                separators=(",", ":"),
            )
            projected_states.append(
                ProjectedState(
                    new_id(),
                    scenario_id,
                    item["simulated_valuation"]["complete"],
                    item["simulated_valuation"]["total_value"],
                    hashlib.sha256(valuation_payload.encode("utf-8")).hexdigest(),
                )
            )
            results[scenario_id] = dict(item)
        return scenarios, actions, constraints, projected_states, results

    @staticmethod
    def _comparison_sha256(comparison: Mapping[str, Any]) -> str:
        payload = json.dumps(
            PlanningService._semantic_value(comparison["scenarios"]),
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _semantic_value(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {
                key: PlanningService._semantic_value(item)
                for key, item in value.items()
                if key not in {"id", "result_sha256"} and not key.endswith("_id")
            }
        if isinstance(value, list):
            return [PlanningService._semantic_value(item) for item in value]
        return value

    @staticmethod
    def _event_json(event: Mapping[str, Any]) -> str:
        return json.dumps(event, sort_keys=True, separators=(",", ":"))
