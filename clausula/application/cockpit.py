from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping, Sequence

from clausula.analytics.policy import evaluate_policy
from clausula.domain import PolicyRule, canonical_decimal, canonical_timestamp, dec

from .ports import CoreRepository
from .portfolio import PortfolioService


def derive_capital_envelope(
    valuation: Mapping[str, Any], policies: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Derive reserve and deployable cash without creating financial facts."""

    base_currency = str(valuation["base_currency"])
    cash = sum(
        (
            dec(line["base_value"])
            for line in valuation.get("allocation", ())
            if line.get("asset_type") == "cash"
        ),
        Decimal(0),
    )
    common = {
        "base_currency": base_currency,
        "cash_base_value": canonical_decimal(cash),
    }
    if valuation.get("complete") is not True:
        return common | {
            "status": "unavailable",
            "required_reserve": None,
            "deployable_cash": None,
            "reserve_gap": None,
            "sources": [],
            "reason": "capital envelope requires a complete portfolio valuation",
        }

    total = dec(valuation["total_value"])
    requirements: list[tuple[Decimal, dict[str, Any]]] = []
    for policy in policies:
        for result in policy.get("results", ()):
            rule_type = result.get("rule_type")
            lower = result.get("lower_bound")
            if lower is None:
                continue
            if rule_type == "min_cash_amount":
                required = dec(lower)
            elif rule_type == "min_cash_weight":
                required = total * dec(lower)
            else:
                continue
            requirements.append(
                (
                    required,
                    {
                        "policy_id": policy.get("policy_id"),
                        "policy_name": policy.get("policy_name"),
                        "policy_version_id": policy.get("policy_version_id"),
                        "rule_id": result.get("rule_id"),
                        "rule_key": result.get("rule_key"),
                        "rule_type": rule_type,
                        "required_reserve": canonical_decimal(required),
                    },
                )
            )

    if not requirements:
        return common | {
            "status": "unconstrained",
            "required_reserve": None,
            "deployable_cash": None,
            "reserve_gap": None,
            "sources": [],
            "reason": "no active minimum-cash policy defines a reserve floor",
        }

    required_reserve = max(value for value, _ in requirements)
    deployable = max(cash - required_reserve, Decimal(0))
    gap = max(required_reserve - cash, Decimal(0))
    return common | {
        "status": "shortfall" if gap > 0 else "funded",
        "required_reserve": canonical_decimal(required_reserve),
        "deployable_cash": canonical_decimal(deployable),
        "reserve_gap": canonical_decimal(gap),
        "sources": [source for _, source in requirements],
    }


def derive_risk_headroom(policies: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return signed distance to each deterministic policy boundary."""

    rows: list[dict[str, Any]] = []
    for policy in policies:
        for result in policy.get("results", ()):
            current_raw = result.get("current_value")
            lower_raw = result.get("lower_bound")
            upper_raw = result.get("upper_bound")
            headroom: Decimal | None = None
            if current_raw is not None:
                current = dec(current_raw)
                candidates: list[Decimal] = []
                if lower_raw is not None:
                    candidates.append(current - dec(lower_raw))
                if upper_raw is not None:
                    candidates.append(dec(upper_raw) - current)
                if candidates:
                    headroom = min(candidates)
            rule_type = str(result.get("rule_type") or "")
            rows.append(
                {
                    "policy_id": policy.get("policy_id"),
                    "policy_name": policy.get("policy_name"),
                    "policy_version_id": policy.get("policy_version_id"),
                    "rule_id": result.get("rule_id"),
                    "rule_key": result.get("rule_key"),
                    "rule_type": rule_type,
                    "severity": result.get("severity"),
                    "status": result.get("status"),
                    "current_value": current_raw,
                    "lower_bound": lower_raw,
                    "upper_bound": upper_raw,
                    "headroom": None if headroom is None else canonical_decimal(headroom),
                    "unit": "base_currency" if rule_type == "min_cash_amount" else "ratio",
                }
            )

    def order_key(row: Mapping[str, Any]) -> tuple[int, Decimal, str, str]:
        value = row.get("headroom")
        return (
            1 if value is None else 0,
            Decimal(0) if value is None else dec(value),
            str(row.get("policy_id") or ""),
            str(row.get("rule_key") or ""),
        )

    return sorted(rows, key=order_key)


class CapitalCockpitService:
    """Build one deterministic read snapshot for the local decision workspace.

    The read model deliberately values the portfolio once, then evaluates every
    applicable policy against that same immutable valuation. This avoids the
    UI-triggered repeated valuation work that would occur if each policy were
    evaluated through an independent capability call.
    """

    def __init__(self, repository: CoreRepository):
        self.repository = repository
        self.portfolios = PortfolioService(repository)

    def snapshot(
        self,
        portfolio_id: str,
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
        portfolio = dict(self.repository.portfolio(portfolio_id))
        valuation = self.portfolios.portfolio_valuation(
            portfolio_id,
            effective_cutoff,
            known_as_of=knowledge_cutoff,
            price_dataset_name=price_dataset_name,
            price_dataset_version=price_dataset_version,
            fx_dataset_name=fx_dataset_name,
            fx_dataset_version=fx_dataset_version,
        )

        policies: list[dict[str, Any]] = []
        for policy_row in self.repository.policies(portfolio_id):
            policy = dict(policy_row)
            try:
                version = dict(
                    self.repository.policy_version_at(
                        policy["id"], effective_cutoff, knowledge_cutoff
                    )
                )
            except KeyError:
                policies.append(
                    {
                        "policy_id": policy["id"],
                        "policy_name": policy["name"],
                        "status": "unavailable",
                        "complete": False,
                        "results": [],
                        "violations": [],
                        "reason": "no policy version exists at this effective/knowledge cutoff",
                    }
                )
                continue
            result = evaluate_policy(
                valuation,
                self._stored_rules(version["id"]),
                policy_version_id=version["id"],
                portfolio_id=portfolio_id,
                as_of=effective_cutoff,
                known_as_of=knowledge_cutoff,
            )
            policies.append(
                {
                    "policy_id": policy["id"],
                    "policy_name": policy["name"],
                    "version_number": version["version_number"],
                    **result,
                }
            )

        return {
            "format": "clausula-capital-cockpit-v1",
            "portfolio": {
                "id": portfolio["id"],
                "name": portfolio["name"],
                "base_currency": portfolio["base_currency"],
            },
            "as_of": effective_cutoff,
            "known_as_of": knowledge_cutoff,
            "valuation": valuation,
            "policies": policies,
            "capital_envelope": derive_capital_envelope(valuation, policies),
            "risk_headroom": derive_risk_headroom(policies),
            "plans": [dict(row) for row in self.repository.plans(portfolio_id)],
            "decisions": [dict(row) for row in self.repository.decisions(portfolio_id)],
        }

    def _stored_rules(self, policy_version_id: str) -> list[PolicyRule]:
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
            for row in self.repository.policy_rules(policy_version_id)
        ]
