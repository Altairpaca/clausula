from __future__ import annotations

from decimal import Decimal
import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from clausula.domain import PolicyRule, canonical_decimal, dec, new_id

from .policy import PolicyEvaluationError, evaluate_policy, simulate_base_currency_trades


def _with_new_cash(valuation: Mapping[str, Any], cash_available: Any) -> dict[str, Any]:
    cash = dec(cash_available)
    if cash < 0:
        raise PolicyEvaluationError("planning cash_available cannot be negative")
    if cash == 0:
        return dict(valuation)
    base_currency = str(valuation["base_currency"]).upper()
    result = dict(valuation)
    allocation = [dict(line) for line in valuation.get("allocation", ())]
    for line in allocation:
        if line["asset_type"] == "cash":
            line["base_value"] = canonical_decimal(dec(line["base_value"]) + cash)
            break
    else:
        allocation.append({"asset_type": "cash", "base_value": canonical_decimal(cash), "weight": None})
    currency_exposure = [dict(line) for line in valuation.get("currency_exposure", ())]
    for line in currency_exposure:
        if str(line["currency"]).upper() == base_currency:
            line["base_value"] = canonical_decimal(dec(line["base_value"]) + cash)
            break
    else:
        currency_exposure.append({"currency": base_currency, "base_value": canonical_decimal(cash)})
    total = dec(valuation["total_value"]) + cash
    for line in allocation:
        line["weight"] = (
            None
            if total == 0
            else canonical_decimal(dec(line["base_value"]) / total)
        )
    result["total_value"] = canonical_decimal(total)
    result["partial_value"] = canonical_decimal(dec(valuation["partial_value"]) + cash)
    result["allocation"] = allocation
    concentration = [dict(line) for line in valuation.get("concentration", ())]
    for line in concentration:
        line["weight"] = (
            None
            if total == 0
            else canonical_decimal(dec(line["base_value"]) / total)
        )
    result["concentration"] = concentration
    result["currency_exposure"] = currency_exposure
    return result


def _constraint_gap(result: Mapping[str, Any]) -> Decimal | None:
    current = result.get("current_value")
    if current is None:
        return None
    current_value = dec(current)
    rule_type = result["rule_type"]
    if rule_type in {"max_single_instrument_weight", "max_asset_type_weight", "max_currency_weight"}:
        return max(Decimal(0), current_value - dec(result["upper_bound"]))
    if rule_type in {"min_cash_weight", "min_cash_amount"}:
        return max(Decimal(0), dec(result["lower_bound"]) - current_value)
    lower = dec(result["lower_bound"])
    upper = dec(result["upper_bound"])
    if current_value < lower:
        return lower - current_value
    return max(Decimal(0), current_value - upper)


def _constraint_explanation(result: Mapping[str, Any], gap: Decimal | None) -> str:
    if result["status"] == "unavailable":
        return "valuation is incomplete; planning cannot establish this constraint"
    if gap is None:
        return f"rule {result['rule_key']} is violated"
    return f"rule {result['rule_key']} is outside its bound by {canonical_decimal(gap)}"


def _result_sha256(result: Mapping[str, Any]) -> str:
    payload = json.dumps(_semantic_value(result), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _semantic_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _semantic_value(item)
            for key, item in value.items()
            if key not in {"id", "result_sha256"} and not key.endswith("_id")
        }
    if isinstance(value, list):
        return [_semantic_value(item) for item in value]
    return value


def _cash_reserve(valuation: Mapping[str, Any], rules: Sequence[PolicyRule]) -> dict[str, Any]:
    total = dec(valuation["total_value"])
    cash = next(
        (
            dec(line["base_value"])
            for line in valuation.get("allocation", ())
            if line["asset_type"] == "cash"
        ),
        Decimal(0),
    )
    weight = Decimal(0) if total == 0 else cash / total
    minimum_amount = max(
        (rule.lower_bound for rule in rules if rule.rule_type == "min_cash_amount"),
        default=Decimal(0),
    )
    minimum_weight = max(
        (rule.lower_bound for rule in rules if rule.rule_type == "min_cash_weight"),
        default=Decimal(0),
    )
    return {
        "projected_amount": canonical_decimal(cash),
        "projected_weight": canonical_decimal(weight),
        "minimum_amount": canonical_decimal(minimum_amount),
        "minimum_weight": canonical_decimal(minimum_weight),
        "amount_gap": canonical_decimal(max(Decimal(0), minimum_amount - cash)),
        "weight_gap": canonical_decimal(max(Decimal(0), minimum_weight - weight)),
    }


def _allocation_gaps(valuation: Mapping[str, Any], rules: Sequence[PolicyRule]) -> list[dict[str, str]]:
    weights = {
        line["asset_type"]: dec(line["weight"])
        for line in valuation.get("allocation", ())
        if line.get("weight") is not None
    }
    return [
        {
            "rule_key": rule.rule_key,
            "asset_type": rule.subject or "",
            "current_weight": canonical_decimal(weights.get(rule.subject or "", Decimal(0))),
            "target_weight": canonical_decimal(rule.target),
            "delta_to_target": canonical_decimal(
                rule.target - weights.get(rule.subject or "", Decimal(0))
            ),
        }
        for rule in rules
        if rule.rule_type == "allocation_band"
    ]


def compare_plan_scenarios(
    valuation: Mapping[str, Any],
    rules: Sequence[PolicyRule],
    scenarios: Sequence[Mapping[str, Any]],
    instruments: Mapping[str, Mapping[str, Any]],
    *,
    policy_version_id: str,
    portfolio_id: str,
    as_of: str,
    known_as_of: str,
) -> dict[str, Any]:
    if not scenarios:
        raise ValueError("planning requires at least one scenario")
    seen: set[str] = set()
    evaluated: list[dict[str, Any]] = []
    for index, scenario in enumerate(scenarios):
        try:
            key = str(scenario["key"]).strip()
            actions = scenario.get("actions", ())
            cash_available = dec(scenario.get("cash_available", "0"))
        except (KeyError, TypeError, ValueError) as exc:
            raise PolicyEvaluationError(f"invalid planning scenario {index}") from exc
        if not key or key in seen:
            raise ValueError("planning scenario keys must be non-empty and unique")
        seen.add(key)
        if not isinstance(actions, list):
            raise PolicyEvaluationError(f"planning scenario {key} actions must be an array")
        base = _with_new_cash(valuation, cash_available)
        if base.get("complete") is not True:
            raise PolicyEvaluationError("policy simulation requires a complete valuation")
        if actions:
            simulated = simulate_base_currency_trades(base, actions, instruments)
        else:
            simulated = {
                **base,
                "simulation": {
                    "actions": [],
                    "total_fees": "0",
                    "total_tax_estimate": "0",
                    "funding_assumption": "base_currency_cash",
                    "ledger_mutated": False,
                },
            }
        evaluation = evaluate_policy(
            simulated,
            rules,
            policy_version_id=policy_version_id,
            portfolio_id=portfolio_id,
            as_of=as_of,
            known_as_of=known_as_of,
        )
        constraints = []
        for rule_result in evaluation["results"]:
            if rule_result["status"] not in {"violation", "unavailable"}:
                continue
            gap = _constraint_gap(rule_result)
            constraints.append(
                {
                    "rule_id": rule_result["rule_id"],
                    "rule_key": rule_result["rule_key"],
                    "severity": rule_result["severity"],
                    "status": rule_result["status"],
                    "kind": "missing_valuation" if rule_result["status"] == "unavailable" else "policy_bound",
                    "gap": None if gap is None else canonical_decimal(gap),
                    "explanation": _constraint_explanation(rule_result, gap),
                }
            )
        status = (
            "unavailable"
            if evaluation["status"] == "unavailable"
            else "violates_policy"
            if evaluation["status"] == "violation"
            else "feasible"
        )
        normalized_actions = simulated["simulation"]["actions"]
        result = {
            "scenario_key": key,
            "description": str(scenario.get("description", "")).strip(),
            "cash_available": canonical_decimal(cash_available),
            "status": status,
            "total_fees": simulated["simulation"]["total_fees"],
            "total_tax_estimate": simulated["simulation"].get("total_tax_estimate", "0"),
            "projected_total": simulated["total_value"],
            "actions": normalized_actions,
            "evaluation": evaluation,
            "simulated_valuation": simulated,
            "unresolved_constraints": constraints,
            "cash_reserve": _cash_reserve(simulated, rules),
            "allocation_gaps": _allocation_gaps(simulated, rules),
        }
        result["result_sha256"] = _result_sha256(result)
        result["score"] = {
            "hard_constraints": sum(item["severity"] == "hard" for item in constraints),
            "constraints": len(constraints),
            "fees": simulated["simulation"]["total_fees"],
            "tax_estimate": simulated["simulation"].get("total_tax_estimate", "0"),
        }
        evaluated.append(result)

    def rank(item: Mapping[str, Any]) -> tuple[Any, ...]:
        status_rank = {"feasible": 0, "violates_policy": 1, "unavailable": 2}[item["status"]]
        return (
            status_rank,
            item["score"]["hard_constraints"],
            item["score"]["constraints"],
            dec(item["score"]["fees"]) + dec(item["score"]["tax_estimate"]),
            item["scenario_key"],
        )

    ordered = sorted(evaluated, key=rank)
    return {
        "policy_version_id": policy_version_id,
        "portfolio_id": portfolio_id,
        "as_of": as_of,
        "known_as_of": known_as_of,
        "valuation": dict(valuation),
        "scenarios": ordered,
        "recommended_scenario": ordered[0]["scenario_key"] if ordered else None,
        "selection_method": "feasibility_then_hard_constraints_then_total_constraints_then_fees_then_key",
        "ledger_mutated": False,
    }
