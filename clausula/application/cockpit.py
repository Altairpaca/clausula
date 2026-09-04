from __future__ import annotations

from typing import Any

from clausula.analytics.policy import evaluate_policy
from clausula.domain import PolicyRule, canonical_timestamp

from .ports import CoreRepository
from .portfolio import PortfolioService


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
