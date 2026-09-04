from clausula.application.cockpit import derive_capital_envelope, derive_risk_headroom


def test_capital_envelope_uses_conservative_active_cash_floor() -> None:
    valuation = {
        "base_currency": "CNY",
        "complete": True,
        "total_value": "1000",
        "allocation": [
            {"asset_type": "cash", "base_value": "300", "weight": "0.3"},
            {"asset_type": "stock", "base_value": "700", "weight": "0.7"},
        ],
    }
    policies = [
        {
            "policy_id": "household-policy",
            "policy_name": "Household capital",
            "policy_version_id": "version-1",
            "results": [
                {
                    "rule_id": "cash-amount",
                    "rule_key": "reserve-cny",
                    "rule_type": "min_cash_amount",
                    "lower_bound": "200",
                    "upper_bound": None,
                    "current_value": "300",
                    "status": "compliant",
                    "severity": "hard",
                },
                {
                    "rule_id": "cash-weight",
                    "rule_key": "reserve-weight",
                    "rule_type": "min_cash_weight",
                    "lower_bound": "0.25",
                    "upper_bound": None,
                    "current_value": "0.3",
                    "status": "compliant",
                    "severity": "hard",
                },
            ],
        }
    ]

    envelope = derive_capital_envelope(valuation, policies)

    assert envelope["status"] == "funded"
    assert envelope["cash_base_value"] == "300"
    assert envelope["required_reserve"] == "250"
    assert envelope["deployable_cash"] == "50"
    assert envelope["reserve_gap"] == "0"
    assert len(envelope["sources"]) == 2


def test_capital_envelope_fails_closed_when_valuation_is_incomplete() -> None:
    envelope = derive_capital_envelope(
        {
            "base_currency": "USD",
            "complete": False,
            "total_value": None,
            "partial_value": "100",
            "allocation": [{"asset_type": "cash", "base_value": "100"}],
        },
        [],
    )

    assert envelope["status"] == "unavailable"
    assert envelope["cash_base_value"] == "100"
    assert envelope["required_reserve"] is None
    assert envelope["deployable_cash"] is None


def test_capital_envelope_does_not_treat_unconstrained_cash_as_deployable() -> None:
    envelope = derive_capital_envelope(
        {
            "base_currency": "USD",
            "complete": True,
            "total_value": "500",
            "allocation": [{"asset_type": "cash", "base_value": "500"}],
        },
        [],
    )

    assert envelope["status"] == "unconstrained"
    assert envelope["deployable_cash"] is None
    assert envelope["required_reserve"] is None


def test_risk_headroom_is_signed_and_sorted_by_boundary_pressure() -> None:
    policies = [
        {
            "policy_id": "risk",
            "policy_name": "Risk policy",
            "policy_version_id": "v1",
            "results": [
                {
                    "rule_id": "position",
                    "rule_key": "single-position-cap",
                    "rule_type": "max_single_position_weight",
                    "severity": "hard",
                    "status": "violation",
                    "current_value": "0.35",
                    "lower_bound": None,
                    "upper_bound": "0.30",
                },
                {
                    "rule_id": "cash",
                    "rule_key": "cash-floor",
                    "rule_type": "min_cash_weight",
                    "severity": "hard",
                    "status": "compliant",
                    "current_value": "0.30",
                    "lower_bound": "0.25",
                    "upper_bound": None,
                },
                {
                    "rule_id": "band",
                    "rule_key": "equity-band",
                    "rule_type": "allocation_band",
                    "severity": "soft",
                    "status": "compliant",
                    "current_value": "0.20",
                    "lower_bound": "0.10",
                    "upper_bound": "0.30",
                },
            ],
        }
    ]

    rows = derive_risk_headroom(policies)

    assert [row["rule_key"] for row in rows] == [
        "single-position-cap",
        "cash-floor",
        "equity-band",
    ]
    assert [row["headroom"] for row in rows] == ["-0.05", "0.05", "0.1"]
