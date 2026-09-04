from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Mapping, Sequence

from clausula.analytics.execution import evaluate_execution_contract
from clausula.domain import canonical_decimal, canonical_timestamp, dec, new_id, now


EXECUTION_CONTRACT_FORMAT = "clausula-execution-contract-v1"
NUMERIC_TYPES = {
    "min_trade_value",
    "max_trade_value",
    "max_total_turnover",
    "minimum_lot",
    "price_tick",
}
ALLOWED_TYPES = {
    "allowed_instruments",
    "allowed_sides",
    *NUMERIC_TYPES,
    "require_settled_cash",
    "sell_delay_days",
    "trading_window",
}


class ExecutionContractError(ValueError):
    pass


def _required_text(value: Any, field: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ExecutionContractError(f"execution contract {field} cannot be empty")
    return result


def _clock(value: Any, field: str) -> str:
    text = _required_text(value, field)
    try:
        datetime.strptime(text, "%H:%M")
    except ValueError as exc:
        raise ExecutionContractError(f"{field} must use HH:MM") from exc
    return text


def normalize_constraints(
    definitions: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if not definitions:
        raise ExecutionContractError("execution contract requires at least one constraint")
    result: list[dict[str, Any]] = []
    keys: set[str] = set()
    for index, definition in enumerate(definitions):
        key = _required_text(definition.get("key"), f"constraint {index} key")
        if key in keys:
            raise ExecutionContractError(f"duplicate execution constraint key: {key}")
        keys.add(key)
        kind = _required_text(definition.get("type"), f"constraint {index} type").lower()
        if kind not in ALLOWED_TYPES:
            raise ExecutionContractError(f"unsupported execution constraint type: {kind}")
        normalized: dict[str, Any] = {"key": key, "type": kind}
        subject = str(definition.get("subject") or "").strip()
        if subject:
            normalized["subject"] = subject
        if kind in {"allowed_instruments", "allowed_sides"}:
            values = [
                str(item).strip()
                for item in definition.get("values", ())
                if str(item).strip()
            ]
            if not values:
                raise ExecutionContractError(f"{kind} requires non-empty values")
            if kind == "allowed_sides":
                values = [item.lower() for item in values]
                invalid = set(values) - {"buy", "sell"}
                if invalid:
                    raise ExecutionContractError(
                        f"allowed_sides contains invalid values: {', '.join(sorted(invalid))}"
                    )
            normalized["values"] = sorted(set(values))
        elif kind in NUMERIC_TYPES:
            if definition.get("value") is None:
                raise ExecutionContractError(f"{kind} requires value")
            value = dec(definition["value"])
            if value <= 0:
                raise ExecutionContractError(f"{kind} value must be positive")
            normalized["value"] = canonical_decimal(value)
        elif kind == "sell_delay_days":
            try:
                days = int(definition.get("value"))
            except (TypeError, ValueError) as exc:
                raise ExecutionContractError("sell_delay_days requires integer value") from exc
            if days < 0:
                raise ExecutionContractError("sell_delay_days cannot be negative")
            normalized["value"] = days
        elif kind == "trading_window":
            normalized["start"] = _clock(
                definition.get("start"), "trading_window start"
            )
            normalized["end"] = _clock(
                definition.get("end"), "trading_window end"
            )
        result.append(normalized)
    return sorted(result, key=lambda row: row["key"])


class ExecutionService:
    """Version and evaluate deterministic portfolio execution constraints."""

    def __init__(self, repository):
        self.repository = repository

    def _versions(
        self,
        *,
        portfolio_id: str | None = None,
        contract_id: str | None = None,
    ) -> list[dict[str, Any]]:
        loader = getattr(self.repository, "execution_contract_versions", None)
        if loader is None:
            raise ExecutionContractError("repository does not support execution contracts")
        return [
            dict(row)
            for row in loader(portfolio_id=portfolio_id, contract_id=contract_id)
        ]

    def create(
        self,
        portfolio_id: str,
        name: str,
        effective_from: str,
        constraints: Sequence[Mapping[str, Any]],
        *,
        known_at: str | None = None,
        recorded_at: str | None = None,
    ) -> dict[str, Any]:
        self.repository.portfolio(portfolio_id)
        if self._versions(portfolio_id=portfolio_id):
            raise ExecutionContractError(
                "portfolio already has an execution contract identity; append a version instead"
            )
        return self._append(
            contract_id=new_id(),
            portfolio_id=portfolio_id,
            name=_required_text(name, "name"),
            version_number=1,
            effective_from=effective_from,
            constraints=constraints,
            known_at=known_at,
            recorded_at=recorded_at,
        )

    def add_version(
        self,
        contract_id: str,
        effective_from: str,
        constraints: Sequence[Mapping[str, Any]],
        *,
        known_at: str | None = None,
        recorded_at: str | None = None,
    ) -> dict[str, Any]:
        versions = self._versions(contract_id=contract_id)
        if not versions:
            raise KeyError(f"unknown execution contract: {contract_id}")
        latest = max(versions, key=lambda row: int(row["version_number"]))
        return self._append(
            contract_id=contract_id,
            portfolio_id=latest["portfolio_id"],
            name=latest["name"],
            version_number=int(latest["version_number"]) + 1,
            effective_from=effective_from,
            constraints=constraints,
            known_at=known_at,
            recorded_at=recorded_at,
        )

    def _append(
        self,
        *,
        contract_id: str,
        portfolio_id: str,
        name: str,
        version_number: int,
        effective_from: str,
        constraints: Sequence[Mapping[str, Any]],
        known_at: str | None,
        recorded_at: str | None,
    ) -> dict[str, Any]:
        recorded_time = canonical_timestamp(recorded_at or now())
        knowledge_time = canonical_timestamp(known_at or recorded_time)
        effective_time = canonical_timestamp(effective_from)
        if knowledge_time > recorded_time:
            raise ExecutionContractError("known_at cannot be after recorded_at")
        normalized = normalize_constraints(constraints)
        provenance = json.dumps(
            {
                "format": EXECUTION_CONTRACT_FORMAT,
                "contract_id": contract_id,
                "portfolio_id": portfolio_id,
                "name": name,
                "version_number": version_number,
                "effective_from": effective_time,
                "known_at": knowledge_time,
                "recorded_at": recorded_time,
                "constraints": normalized,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        artifact_id, _ = self.repository.virtual_artifact(
            "manual://execution-contract", provenance
        )
        batch_id = self.repository.import_batch(
            artifact_id,
            adapter_name="manual-execution-contract",
            adapter_version="1",
            schema_version="1",
        )
        writer = getattr(self.repository, "add_execution_contract_version", None)
        if writer is None:
            raise ExecutionContractError("repository does not support execution contracts")
        return dict(
            writer(
                contract_id,
                {
                    "format": EXECUTION_CONTRACT_FORMAT,
                    "portfolio_id": portfolio_id,
                    "name": name,
                    "version_number": version_number,
                    "effective_from": effective_time,
                    "known_at": knowledge_time,
                    "recorded_at": recorded_time,
                    "constraints": normalized,
                    "source_artifact_id": artifact_id,
                    "import_batch_id": batch_id,
                },
            )
        )

    def list(self, portfolio_id: str | None = None) -> list[dict[str, Any]]:
        return self._versions(portfolio_id=portfolio_id)

    def active(
        self,
        portfolio_id: str,
        as_of: str,
        *,
        known_as_of: str | None = None,
    ) -> dict[str, Any] | None:
        loader = getattr(self.repository, "execution_contract_version_at", None)
        if loader is None:
            raise ExecutionContractError("repository does not support execution contracts")
        row = loader(portfolio_id, as_of, known_as_of)
        return None if row is None else dict(row)

    def evaluate(
        self,
        portfolio_id: str,
        as_of: str,
        actions: Sequence[Mapping[str, Any]],
        *,
        known_as_of: str | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        effective_cutoff = canonical_timestamp(as_of)
        knowledge_cutoff = canonical_timestamp(known_as_of or as_of)
        contract = self.active(
            portfolio_id, effective_cutoff, known_as_of=knowledge_cutoff
        )
        if contract is None:
            return {
                "portfolio_id": portfolio_id,
                "as_of": effective_cutoff,
                "known_as_of": knowledge_cutoff,
                "contract": None,
                "status": "conditional",
                "complete": False,
                "results": [],
                "violations": [],
                "missing_facts": [
                    {
                        "constraint_key": "execution_contract",
                        "constraint_type": "contract",
                        "status": "unavailable",
                        "reason": "no execution contract is active at this cutoff",
                        "evidence": {},
                    }
                ],
            }
        evaluated = evaluate_execution_contract(
            contract["constraints"], actions, context=context
        )
        return {
            "portfolio_id": portfolio_id,
            "as_of": effective_cutoff,
            "known_as_of": knowledge_cutoff,
            "contract": contract,
            **evaluated,
        }

    def evaluate_plan(
        self,
        plan_id: str,
        *,
        context_by_scenario: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        plan = dict(self.repository.plan(plan_id))
        contexts = dict(context_by_scenario or {})
        scenarios = []
        for scenario in self.repository.plan_scenarios(plan_id):
            scenario_id = scenario["id"]
            actions = [dict(row) for row in self.repository.plan_actions(scenario_id)]
            evaluation = self.evaluate(
                plan["portfolio_id"],
                plan["as_of"],
                actions,
                known_as_of=plan["known_as_of"],
                context=contexts.get(scenario_id, {}),
            )
            scenarios.append(
                {
                    "scenario_id": scenario_id,
                    "scenario_key": scenario["scenario_key"],
                    "execution": evaluation,
                }
            )
        statuses = {row["execution"]["status"] for row in scenarios}
        if "executable" in statuses:
            overall = "has_executable_scenario"
        elif "conditional" in statuses:
            overall = "conditional"
        else:
            overall = "blocked"
        return {
            "plan_id": plan_id,
            "portfolio_id": plan["portfolio_id"],
            "status": overall,
            "scenarios": scenarios,
        }
