from __future__ import annotations

from decimal import Decimal
import hashlib
import json
from typing import Any, Iterable, Mapping, Sequence
import uuid

from clausula.domain import (
    PolicyEvaluation,
    PolicyEvidence,
    PolicyRule,
    PolicyRuleResult,
    canonical_decimal,
    canonical_timestamp,
    dec,
)


class PolicyEvaluationError(ValueError):
    pass


def _weight_map(lines: Iterable[Mapping[str, Any]], key: str) -> dict[str, Decimal]:
    return {
        str(line[key]): dec(line.get("weight") or "0")
        for line in lines
        if line.get("weight") is not None
    }


def _rule_result(
    rule: PolicyRule,
    current: Decimal | None,
    status: str,
    evidence: tuple[PolicyEvidence, ...] = (),
) -> PolicyRuleResult:
    return PolicyRuleResult(
        rule.id,
        rule.rule_key,
        rule.rule_type,
        rule.severity,
        status,
        current,
        rule.target,
        rule.lower_bound,
        rule.upper_bound,
        evidence,
    )


def _evaluate_rule(
    valuation: Mapping[str, Any], rule: PolicyRule
) -> PolicyRuleResult:
    complete = valuation.get("complete") is True
    if not complete:
        return _rule_result(rule, None, "unavailable")

    allocation = _weight_map(valuation.get("allocation", ()), "asset_type")
    total_value = dec(valuation["total_value"])
    currencies = {
        str(line["currency"]): (
            Decimal(0)
            if total_value == 0
            else dec(line["base_value"]) / total_value
        )
        for line in valuation.get("currency_exposure", ())
    }
    concentration = [
        line
        for line in valuation.get("concentration", ())
        if line.get("weight") is not None
    ]
    current: Decimal
    evidence: tuple[PolicyEvidence, ...]
    if rule.rule_type == "allocation_band":
        current = allocation.get(rule.subject or "", Decimal(0))
        status = (
            "compliant"
            if rule.lower_bound <= current <= rule.upper_bound
            else "violation"
        )
        evidence = (PolicyEvidence("allocation", rule.subject or "", current),)
    elif rule.rule_type == "max_asset_type_weight":
        current = allocation.get(rule.subject or "", Decimal(0))
        status = "compliant" if current <= rule.upper_bound else "violation"
        evidence = (PolicyEvidence("allocation", rule.subject or "", current),)
    elif rule.rule_type == "min_cash_weight":
        current = allocation.get("cash", Decimal(0))
        status = "compliant" if current >= rule.lower_bound else "violation"
        evidence = (PolicyEvidence("allocation", "cash", current),)
    elif rule.rule_type == "min_cash_amount":
        current = next(
            (
                dec(line["base_value"])
                for line in valuation.get("allocation", ())
                if line["asset_type"] == "cash"
            ),
            Decimal(0),
        )
        status = "compliant" if current >= rule.lower_bound else "violation"
        evidence = (PolicyEvidence("cash_amount", valuation["base_currency"], current),)
    elif rule.rule_type == "max_currency_weight":
        current = currencies.get(rule.subject or "", Decimal(0))
        status = "compliant" if current <= rule.upper_bound else "violation"
        evidence = (PolicyEvidence("currency", rule.subject or "", current),)
    else:
        largest = max(concentration, key=lambda line: dec(line["weight"]), default=None)
        current = Decimal(0) if largest is None else dec(largest["weight"])
        status = "compliant" if current <= rule.upper_bound else "violation"
        evidence = () if largest is None else (
            PolicyEvidence("instrument", largest["identifier"], current),
        )
    return _rule_result(rule, current, status, evidence)


def _evaluation_id(
    policy_version_id: str,
    portfolio_id: str,
    as_of: str,
    known_as_of: str,
    results: Sequence[PolicyRuleResult],
) -> str:
    payload = json.dumps(
        {
            "policy_version_id": policy_version_id,
            "portfolio_id": portfolio_id,
            "as_of": canonical_timestamp(as_of),
            "known_as_of": canonical_timestamp(known_as_of),
            "results": [
                {
                    "rule_id": item.rule_id,
                    "status": item.status,
                    "current": None
                    if item.current_value is None
                    else canonical_decimal(item.current_value),
                }
                for item in results
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"clausula:policy-evaluation:{digest}"))


def evaluate_policy(
    valuation: Mapping[str, Any],
    rules: Iterable[PolicyRule],
    *,
    policy_version_id: str,
    portfolio_id: str,
    as_of: str,
    known_as_of: str,
) -> dict[str, Any]:
    ordered_rules = sorted(rules, key=lambda item: (item.rule_key, item.id))
    results = tuple(_evaluate_rule(valuation, rule) for rule in ordered_rules)
    statuses = {item.status for item in results}
    if "unavailable" in statuses:
        status = "unavailable"
    elif "violation" in statuses:
        status = "violation"
    else:
        status = "compliant"
    evaluation = PolicyEvaluation(
        _evaluation_id(
            policy_version_id, portfolio_id, as_of, known_as_of, results
        ),
        policy_version_id,
        portfolio_id,
        as_of,
        known_as_of,
        status,
        results,
    )
    return {
        "evaluation_id": evaluation.id,
        "policy_version_id": evaluation.policy_version_id,
        "portfolio_id": evaluation.portfolio_id,
        "as_of": evaluation.as_of,
        "known_as_of": evaluation.known_as_of,
        "status": evaluation.status,
        "complete": evaluation.status != "unavailable",
        "results": [_serialize_result(item) for item in evaluation.results],
        "violations": [
            _serialize_result(item)
            for item in evaluation.results
            if item.status == "violation"
        ],
    }


def _serialize_result(result: PolicyRuleResult) -> dict[str, Any]:
    return {
        "rule_id": result.rule_id,
        "rule_key": result.rule_key,
        "rule_type": result.rule_type,
        "severity": result.severity,
        "status": result.status,
        "current_value": None
        if result.current_value is None
        else canonical_decimal(result.current_value),
        "target": None if result.target is None else canonical_decimal(result.target),
        "lower_bound": None
        if result.lower_bound is None
        else canonical_decimal(result.lower_bound),
        "upper_bound": None
        if result.upper_bound is None
        else canonical_decimal(result.upper_bound),
        "evidence": [
            {
                "kind": item.kind,
                "subject": item.subject,
                "observed_value": canonical_decimal(item.observed_value),
            }
            for item in result.evidence
        ],
    }


def simulate_base_currency_trades(
    valuation: Mapping[str, Any],
    actions: Sequence[Mapping[str, Any]],
    instruments: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    if valuation.get("complete") is not True:
        raise PolicyEvaluationError("policy simulation requires a complete valuation")
    base_currency = str(valuation["base_currency"]).upper()
    total = dec(valuation["total_value"])
    allocation = {
        line["asset_type"]: dec(line["base_value"])
        for line in valuation.get("allocation", ())
    }
    currencies = {
        line["currency"]: dec(line["base_value"])
        for line in valuation.get("currency_exposure", ())
    }
    concentration = {
        line["instrument_id"]: {
            "instrument_id": line["instrument_id"],
            "identifier": line["identifier"],
            "base_value": dec(line["base_value"]),
        }
        for line in valuation.get("concentration", ())
    }
    cash = allocation.get("cash", Decimal(0))
    normalized_actions = []
    total_fees = Decimal(0)
    total_taxes = Decimal(0)
    has_tax_estimate = False
    for index, raw_action in enumerate(actions):
        try:
            instrument_id = str(raw_action["instrument_id"])
            instrument = instruments[instrument_id]
        except (KeyError, TypeError, ValueError) as exc:
            raise PolicyEvaluationError(f"invalid simulation action {index}") from exc
        try:
            delta = dec(raw_action["base_value_delta"])
            fee = dec(raw_action.get("fee", "0"))
            tax = dec(raw_action.get("tax_estimate", "0"))
        except (KeyError, TypeError, ValueError) as exc:
            raise PolicyEvaluationError(str(exc)) from exc
        if delta == 0:
            raise PolicyEvaluationError("simulation action delta cannot be zero")
        if fee < 0:
            raise PolicyEvaluationError("simulation fee cannot be negative")
        if tax < 0:
            raise PolicyEvaluationError("simulation tax estimate cannot be negative")
        current = concentration.get(
            instrument_id,
            {
                "instrument_id": instrument_id,
                "identifier": f"{instrument['scheme']}:{instrument['identifier']}",
                "base_value": Decimal(0),
            },
        )
        new_instrument_value = current["base_value"] + delta
        new_cash = cash - delta - fee - tax
        if new_instrument_value < 0:
            raise PolicyEvaluationError("simulation cannot create a short position")
        if new_cash < 0:
            raise PolicyEvaluationError("simulation cannot create negative base cash")
        current["base_value"] = new_instrument_value
        concentration[instrument_id] = current
        asset_type = instrument["asset_type"]
        allocation[asset_type] = allocation.get(asset_type, Decimal(0)) + delta
        cash = new_cash
        allocation["cash"] = cash
        instrument_currency = instrument["currency"].upper()
        currencies[instrument_currency] = currencies.get(
            instrument_currency, Decimal(0)
        ) + delta
        currencies[base_currency] = currencies.get(base_currency, Decimal(0)) - delta - fee - tax
        total -= fee + tax
        total_fees += fee
        total_taxes += tax
        normalized_action = {
            "instrument_id": instrument_id,
            "base_value_delta": canonical_decimal(delta),
            "fee": canonical_decimal(fee),
        }
        if "tax_estimate" in raw_action:
            has_tax_estimate = True
            normalized_action["tax_estimate"] = canonical_decimal(tax)
        normalized_actions.append(normalized_action)
    if total < 0:
        raise PolicyEvaluationError("simulation cannot create negative total value")

    def weight(value: Decimal) -> str | None:
        return None if total == 0 else canonical_decimal(value / total)

    return {
        **{
            key: value
            for key, value in valuation.items()
            if key not in {"allocation", "concentration", "currency_exposure"}
        },
        "total_value": canonical_decimal(total),
        "partial_value": canonical_decimal(total),
        "allocation": [
            {
                "asset_type": key,
                "base_value": canonical_decimal(value),
                "weight": weight(value),
            }
            for key, value in sorted(allocation.items())
            if value != 0
        ],
        "concentration": sorted(
            (
                {
                    "instrument_id": item["instrument_id"],
                    "identifier": item["identifier"],
                    "base_value": canonical_decimal(item["base_value"]),
                    "weight": weight(item["base_value"]),
                }
                for item in concentration.values()
                if item["base_value"] != 0
            ),
            key=lambda item: (-dec(item["base_value"]), item["instrument_id"]),
        ),
        "currency_exposure": [
            {"currency": key, "base_value": canonical_decimal(value), "weight": weight(value)}
            for key, value in sorted(currencies.items())
            if value != 0
        ],
        "simulation": {
            "actions": normalized_actions,
            "total_fees": canonical_decimal(total_fees),
            **(
                {"total_tax_estimate": canonical_decimal(total_taxes)}
                if has_tax_estimate
                else {}
            ),
            "funding_assumption": "base_currency_cash",
            "ledger_mutated": False,
        },
    }
