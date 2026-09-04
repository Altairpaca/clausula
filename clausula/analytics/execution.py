from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping, Sequence

from clausula.domain import canonical_decimal, dec


NUMERIC_ACTION_CONSTRAINTS = {"min_trade_value", "max_trade_value"}


def _applies(constraint: Mapping[str, Any], action: Mapping[str, Any]) -> bool:
    subject = constraint.get("subject")
    return subject in (None, "", action.get("instrument_id"))


def _side(action: Mapping[str, Any]) -> str | None:
    explicit = str(action.get("side") or "").strip().lower()
    if explicit in {"buy", "sell"}:
        return explicit
    if action.get("base_value_delta") is None:
        return None
    value = dec(action["base_value_delta"])
    if value > 0:
        return "buy"
    if value < 0:
        return "sell"
    return None


def _result(
    constraint: Mapping[str, Any],
    status: str,
    reason: str,
    evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "constraint_key": constraint["key"],
        "constraint_type": constraint["type"],
        "subject": constraint.get("subject"),
        "status": status,
        "reason": reason,
        "evidence": dict(evidence or {}),
    }


def _numeric_action_result(
    constraint: Mapping[str, Any], actions: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    applicable = [action for action in actions if _applies(constraint, action)]
    missing = [action for action in applicable if action.get("base_value_delta") is None]
    if missing:
        return _result(
            constraint,
            "unavailable",
            "base_value_delta is required to evaluate trade-value constraints",
            {"missing_actions": len(missing)},
        )
    threshold = dec(constraint["value"])
    values = [abs(dec(action["base_value_delta"])) for action in applicable]
    if constraint["type"] == "min_trade_value":
        violations = [value for value in values if value < threshold and value != 0]
        relation = ">="
    else:
        violations = [value for value in values if value > threshold]
        relation = "<="
    if violations:
        return _result(
            constraint,
            "violation",
            f"one or more trade values must be {relation} {canonical_decimal(threshold)}",
            {
                "threshold": canonical_decimal(threshold),
                "violating_values": [canonical_decimal(value) for value in violations],
            },
        )
    return _result(
        constraint,
        "compliant",
        "trade values satisfy the execution bound",
        {"threshold": canonical_decimal(threshold)},
    )


def evaluate_execution_contract(
    constraints: Sequence[Mapping[str, Any]],
    actions: Sequence[Mapping[str, Any]],
    *,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate execution feasibility without inferring missing market facts."""

    context = dict(context or {})
    results: list[dict[str, Any]] = []
    for constraint in constraints:
        kind = constraint["type"]
        if kind == "allowed_instruments":
            allowed = set(constraint["values"])
            missing = [
                str(action.get("instrument_id"))
                for action in actions
                if str(action.get("instrument_id")) not in allowed
            ]
            results.append(
                _result(
                    constraint,
                    "violation" if missing else "compliant",
                    "proposed instrument is outside the execution universe"
                    if missing
                    else "all proposed instruments are allowed",
                    {"blocked_instruments": missing},
                )
            )
        elif kind == "allowed_sides":
            allowed = set(constraint["values"])
            sides = [_side(action) for action in actions]
            if any(side is None for side in sides):
                results.append(
                    _result(
                        constraint,
                        "unavailable",
                        "side or non-zero base_value_delta is required",
                    )
                )
            else:
                blocked = [side for side in sides if side not in allowed]
                results.append(
                    _result(
                        constraint,
                        "violation" if blocked else "compliant",
                        "one or more action sides are not allowed"
                        if blocked
                        else "all action sides are allowed",
                        {"blocked_sides": blocked},
                    )
                )
        elif kind in NUMERIC_ACTION_CONSTRAINTS:
            results.append(_numeric_action_result(constraint, actions))
        elif kind == "max_total_turnover":
            if any(action.get("base_value_delta") is None for action in actions):
                results.append(
                    _result(
                        constraint,
                        "unavailable",
                        "base_value_delta is required to calculate total turnover",
                    )
                )
            else:
                turnover = sum(
                    (abs(dec(action["base_value_delta"])) for action in actions),
                    Decimal(0),
                )
                limit = dec(constraint["value"])
                results.append(
                    _result(
                        constraint,
                        "violation" if turnover > limit else "compliant",
                        "total turnover exceeds the contract limit"
                        if turnover > limit
                        else "total turnover is within the contract limit",
                        {
                            "turnover": canonical_decimal(turnover),
                            "limit": canonical_decimal(limit),
                        },
                    )
                )
        elif kind == "require_settled_cash":
            if context.get("settled_cash_base") is None:
                results.append(
                    _result(
                        constraint,
                        "unavailable",
                        "settled_cash_base is required for cash-availability evaluation",
                    )
                )
            elif any(action.get("base_value_delta") is None for action in actions):
                results.append(
                    _result(
                        constraint,
                        "unavailable",
                        "base_value_delta is required for cash-availability evaluation",
                    )
                )
            else:
                required = sum(
                    (
                        dec(action["base_value_delta"])
                        + dec(action.get("fee", "0"))
                        + dec(action.get("tax_estimate", "0"))
                        for action in actions
                        if dec(action["base_value_delta"]) > 0
                    ),
                    Decimal(0),
                )
                available = dec(context["settled_cash_base"])
                results.append(
                    _result(
                        constraint,
                        "violation" if required > available else "compliant",
                        "proposed buys exceed settled cash"
                        if required > available
                        else "settled cash covers proposed buys",
                        {
                            "required": canonical_decimal(required),
                            "available": canonical_decimal(available),
                        },
                    )
                )
        elif kind == "minimum_lot":
            lot = dec(constraint["value"])
            applicable = [action for action in actions if _applies(constraint, action)]
            if any(action.get("quantity") is None for action in applicable):
                results.append(
                    _result(
                        constraint,
                        "unavailable",
                        "quantity is required to evaluate minimum-lot rules",
                    )
                )
            else:
                violating = [
                    canonical_decimal(abs(dec(action["quantity"])))
                    for action in applicable
                    if abs(dec(action["quantity"])) % lot != 0
                ]
                results.append(
                    _result(
                        constraint,
                        "violation" if violating else "compliant",
                        "one or more quantities are not an integer multiple of the lot"
                        if violating
                        else "all quantities satisfy the lot rule",
                        {
                            "lot": canonical_decimal(lot),
                            "violating_quantities": violating,
                        },
                    )
                )
        elif kind == "price_tick":
            tick = dec(constraint["value"])
            applicable = [action for action in actions if _applies(constraint, action)]
            prices = [action.get("limit_price", action.get("price")) for action in applicable]
            if any(price is None for price in prices):
                results.append(
                    _result(
                        constraint,
                        "unavailable",
                        "price or limit_price is required to evaluate price-tick rules",
                    )
                )
            else:
                violating = [
                    canonical_decimal(dec(price))
                    for price in prices
                    if dec(price) % tick != 0
                ]
                results.append(
                    _result(
                        constraint,
                        "violation" if violating else "compliant",
                        "one or more prices do not align to the tick"
                        if violating
                        else "all prices align to the tick",
                        {
                            "tick": canonical_decimal(tick),
                            "violating_prices": violating,
                        },
                    )
                )
        elif kind == "sell_delay_days":
            required_days = int(constraint["value"])
            applicable = [
                action
                for action in actions
                if _applies(constraint, action) and _side(action) == "sell"
            ]
            if any(action.get("holding_age_days") is None for action in applicable):
                results.append(
                    _result(
                        constraint,
                        "unavailable",
                        "holding_age_days is required for sell-delay evaluation",
                    )
                )
            else:
                blocked = [
                    int(action["holding_age_days"])
                    for action in applicable
                    if int(action["holding_age_days"]) < required_days
                ]
                results.append(
                    _result(
                        constraint,
                        "violation" if blocked else "compliant",
                        "one or more sells violate the minimum holding delay"
                        if blocked
                        else "sell-delay rule is satisfied",
                        {"required_days": required_days, "blocked_ages": blocked},
                    )
                )
        elif kind == "trading_window":
            local_time = str(context.get("local_time") or "")
            if not local_time:
                results.append(
                    _result(
                        constraint,
                        "unavailable",
                        "local_time is required to evaluate the trading window",
                    )
                )
            else:
                start = constraint["start"]
                end = constraint["end"]
                inside = (
                    start <= local_time <= end
                    if start <= end
                    else local_time >= start or local_time <= end
                )
                results.append(
                    _result(
                        constraint,
                        "compliant" if inside else "violation",
                        "current local time is inside the execution window"
                        if inside
                        else "current local time is outside the execution window",
                        {"local_time": local_time, "start": start, "end": end},
                    )
                )
        else:
            results.append(
                _result(
                    constraint,
                    "unavailable",
                    f"unsupported execution constraint type: {kind}",
                )
            )

    statuses = {result["status"] for result in results}
    if "violation" in statuses:
        status = "blocked"
    elif "unavailable" in statuses:
        status = "conditional"
    else:
        status = "executable"
    return {
        "status": status,
        "complete": "unavailable" not in statuses,
        "results": results,
        "violations": [row for row in results if row["status"] == "violation"],
        "missing_facts": [row for row in results if row["status"] == "unavailable"],
    }
