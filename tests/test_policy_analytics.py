from __future__ import annotations

from clausula.analytics import (
    PolicyEvaluationError,
    evaluate_policy,
    simulate_base_currency_trades,
)
from clausula.domain import PolicyRule, new_id


def rule(version_id, key, rule_type, *, severity="soft", subject=None, target=None, lower=None, upper=None):
    return PolicyRule(
        new_id(),
        version_id,
        key,
        rule_type,
        severity,
        subject=subject,
        target=target,
        lower_bound=lower,
        upper_bound=upper,
    )


def valuation(instrument_id):
    return {
        "portfolio_id": new_id(),
        "as_of": "2025-01-01",
        "known_as_of": "2025-01-01",
        "base_currency": "USD",
        "complete": True,
        "total_value": "1000",
        "partial_value": "1000",
        "allocation": [
            {"asset_type": "cash", "base_value": "300", "weight": "0.3"},
            {"asset_type": "stock", "base_value": "700", "weight": "0.7"},
        ],
        "concentration": [
            {
                "instrument_id": instrument_id,
                "identifier": "ticker:ABC",
                "base_value": "700",
                "weight": "0.7",
            }
        ],
        "currency_exposure": [
            {"currency": "USD", "base_value": "1000", "weight": "1"}
        ],
        "gaps": [],
    }


def test_policy_rules_validate_decimal_semantics():
    version_id = new_id()
    allocation = rule(
        version_id,
        "equity",
        "allocation_band",
        subject="stock",
        target="0.6",
        lower="0.5",
        upper="0.7",
    )
    assert str(allocation.target) == "0.6"

    import pytest

    with pytest.raises(ValueError, match="between 0 and 1"):
        rule(version_id, "bad", "min_cash_weight", lower="1.1")
    with pytest.raises(ValueError, match="binary floating point"):
        rule(version_id, "bad", "min_cash_weight", lower=0.1)


def test_policy_evaluation_is_structured_deterministic_and_fail_closed():
    version_id = new_id()
    portfolio_id = new_id()
    instrument_id = new_id()
    rules = [
        rule(version_id, "equity", "allocation_band", subject="stock", target="0.6", lower="0.5", upper="0.65"),
        rule(version_id, "cash", "min_cash_amount", severity="hard", lower="250"),
        rule(version_id, "currency", "max_currency_weight", subject="USD", upper="0.8"),
        rule(version_id, "single", "max_single_instrument_weight", upper="0.5"),
    ]
    inputs = dict(
        policy_version_id=version_id,
        portfolio_id=portfolio_id,
        as_of="2025-01-01",
        known_as_of="2025-01-01",
    )

    first = evaluate_policy(valuation(instrument_id), rules, **inputs)
    second = evaluate_policy(valuation(instrument_id), rules, **inputs)

    assert first == second
    assert first["status"] == "violation"
    assert [item["rule_key"] for item in first["violations"]] == [
        "currency",
        "equity",
        "single",
    ]
    assert first["violations"][2]["evidence"] == [
        {"kind": "instrument", "subject": "ticker:ABC", "observed_value": "0.7"}
    ]

    incomplete = valuation(instrument_id) | {"complete": False, "total_value": None}
    unavailable = evaluate_policy(incomplete, rules, **inputs)
    assert unavailable["status"] == "unavailable"
    assert all(item["current_value"] is None for item in unavailable["results"])


def test_policy_simulation_reallocates_base_cash_without_mutating_input():
    instrument_id = new_id()
    current = valuation(instrument_id)
    instruments = {
        instrument_id: {
            "scheme": "ticker",
            "identifier": "ABC",
            "asset_type": "stock",
            "currency": "USD",
        }
    }

    simulated = simulate_base_currency_trades(
        current,
        [{"instrument_id": instrument_id, "base_value_delta": "-200", "fee": "2"}],
        instruments,
    )

    assert current["total_value"] == "1000"
    assert simulated["total_value"] == "998"
    assert simulated["simulation"] == {
        "actions": [
            {"instrument_id": instrument_id, "base_value_delta": "-200", "fee": "2"}
        ],
        "total_fees": "2",
        "funding_assumption": "base_currency_cash",
        "ledger_mutated": False,
    }
    assert simulated["allocation"] == [
        {"asset_type": "cash", "base_value": "498", "weight": "0.4989979959919839679358717435"},
        {"asset_type": "stock", "base_value": "500", "weight": "0.5010020040080160320641282565"},
    ]


def test_each_policy_rule_honors_inclusive_boundaries_and_missing_subject_zero():
    version_id = new_id()
    portfolio_id = new_id()
    instrument_id = new_id()
    current = valuation(instrument_id)
    rules = [
        rule(version_id, "band", "allocation_band", subject="stock", target="0.7", lower="0.7", upper="0.7"),
        rule(version_id, "single", "max_single_instrument_weight", upper="0.7"),
        rule(version_id, "asset", "max_asset_type_weight", subject="stock", upper="0.7"),
        rule(version_id, "cash-weight", "min_cash_weight", lower="0.3"),
        rule(version_id, "cash-amount", "min_cash_amount", lower="300"),
        rule(version_id, "currency", "max_currency_weight", subject="EUR", upper="0"),
    ]
    result = evaluate_policy(
        current,
        rules,
        policy_version_id=version_id,
        portfolio_id=portfolio_id,
        as_of="2025-01-01",
        known_as_of="2025-01-01",
    )
    assert result["status"] == "compliant"
    assert all(item["status"] == "compliant" for item in result["results"])

    outside = current | {
        "allocation": [
            {"asset_type": "cash", "base_value": "299", "weight": "0.299"},
            {"asset_type": "stock", "base_value": "701", "weight": "0.701"},
        ],
        "total_value": "1000",
        "concentration": [
            {
                "instrument_id": instrument_id,
                "identifier": "ticker:ABC",
                "base_value": "701",
                "weight": "0.701",
            }
        ],
    }
    outside_result = evaluate_policy(
        outside,
        rules,
        policy_version_id=version_id,
        portfolio_id=portfolio_id,
        as_of="2025-01-01",
        known_as_of="2025-01-01",
    )
    assert {item["rule_key"] for item in outside_result["violations"]} >= {
        "band",
        "single",
        "asset",
        "cash-weight",
        "cash-amount",
    }


def test_policy_simulation_rejects_unsafe_or_unavailable_inputs():
    instrument_id = new_id()
    current = valuation(instrument_id)
    instruments = {
        instrument_id: {
            "scheme": "ticker",
            "identifier": "ABC",
            "asset_type": "stock",
            "currency": "USD",
        }
    }
    import pytest

    with pytest.raises(PolicyEvaluationError, match="negative base cash"):
        simulate_base_currency_trades(
            current, [{"instrument_id": instrument_id, "base_value_delta": "400"}], instruments
        )
    with pytest.raises(PolicyEvaluationError, match="short position"):
        simulate_base_currency_trades(
            current, [{"instrument_id": instrument_id, "base_value_delta": "-800"}], instruments
        )
    with pytest.raises(PolicyEvaluationError, match="invalid simulation action"):
        simulate_base_currency_trades(
            current, [{"instrument_id": new_id(), "base_value_delta": "1"}], instruments
        )
    with pytest.raises(Exception, match="binary floating point"):
        simulate_base_currency_trades(
            current, [{"instrument_id": instrument_id, "base_value_delta": 1.0}], instruments
        )
    with pytest.raises(PolicyEvaluationError, match="complete valuation"):
        simulate_base_currency_trades(
            current | {"complete": False},
            [{"instrument_id": instrument_id, "base_value_delta": "1"}],
            instruments,
        )
    with pytest.raises(PolicyEvaluationError, match="at least one action"):
        simulate_base_currency_trades(current, [], instruments)
