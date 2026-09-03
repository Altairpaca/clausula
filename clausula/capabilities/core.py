from __future__ import annotations

from pathlib import Path
from typing import Any

from clausula.application import (
    CoreRepository,
    LedgerService,
    MarketService,
    PlanningService,
    DecisionService,
    PolicyService,
    PortfolioService,
    ResearchService,
    RecommendationService,
)

from .registry import CapabilityRegistry, CapabilitySpec, SideEffect, object_schema


STRING = {"type": "string"}
NULLABLE_STRING = {"type": ["string", "null"]}
STRING_MAP = {"type": "object", "additionalProperties": {"type": "string"}}
RULE_VALUE = {"type": ["string", "null"]}


def _policy_rule_schema() -> dict[str, Any]:
    return object_schema(
        {
            "key": STRING,
            "type": STRING,
            "severity": STRING,
            "description": STRING,
            "subject": RULE_VALUE,
            "target": RULE_VALUE,
            "lower": RULE_VALUE,
            "upper": RULE_VALUE,
        },
        required=("key", "type"),
    )


def _policy_rules_schema() -> dict[str, Any]:
    return {"type": "array", "items": _policy_rule_schema()}


def _simulation_actions_schema() -> dict[str, Any]:
    return {
        "type": "array",
        "items": object_schema(
            {
                "instrument_id": STRING,
                "base_value_delta": STRING,
                "fee": STRING,
                "tax_estimate": STRING,
            },
            required=("instrument_id", "base_value_delta"),
        ),
    }


def _planning_scenarios_schema() -> dict[str, Any]:
    return {
        "type": "array",
        "items": object_schema(
            {
                "key": STRING,
                "description": STRING,
                "cash_available": STRING,
                "actions": _simulation_actions_schema(),
            },
            required=("key", "actions"),
        ),
    }


def _decision_alternatives_schema() -> dict[str, Any]:
    return {
        "type": "array",
        "items": object_schema(
            {"key": STRING, "description": STRING, "selected": {"type": "boolean"}},
            required=("key", "description"),
        ),
    }


DECISION_STATEMENTS = {"type": "array", "items": object_schema({"key": STRING, "text": STRING}, required=("key", "text"))}
REVIEW_SCHEDULE = {"type": "array", "items": object_schema({"review_type": {"type": "string", "enum": ["process", "outcome"]}, "due_at": STRING}, required=("review_type", "due_at"))}


def _state_schema() -> dict[str, Any]:
    return object_schema(
        {
            "account_id": STRING,
            "as_of": STRING,
            "cash": NULLABLE_STRING,
            "cash_currency": NULLABLE_STRING,
            "cash_by_currency": STRING_MAP,
            "positions": STRING_MAP,
        },
        required=(
            "account_id",
            "as_of",
            "cash",
            "cash_currency",
            "cash_by_currency",
            "positions",
        ),
    )


def build_core_registry(repository: CoreRepository) -> CapabilityRegistry:
    service = LedgerService(repository)
    market = MarketService(repository)
    portfolios = PortfolioService(repository)
    policies = PolicyService(repository)
    planning = PlanningService(repository)
    decisions = DecisionService(repository)
    research = ResearchService(repository)
    recommendations = RecommendationService(repository)
    registry = CapabilityRegistry()
    registry.register(
        CapabilitySpec(
            "account.create",
            "Create a canonical investment account.",
            object_schema(
                {"institution": STRING, "name": STRING},
                required=("institution", "name"),
            ),
            object_schema({"account_id": STRING}, required=("account_id",)),
            "write",
            True,
            SideEffect.LOCAL_WRITE,
            ("ledger:write",),
            True,
            "Creates an append-only audit event.",
        ),
        lambda institution, name: {"account_id": service.create_account(institution, name)},
    )
    registry.register(
        CapabilitySpec(
            "ledger.import_csv",
            "Import validated CSV investment facts with immutable provenance.",
            object_schema(
                {"account_id": STRING, "path": STRING},
                required=("account_id", "path"),
            ),
            object_schema(
                {
                    "artifact_id": STRING,
                    "sha256": STRING,
                    "import_batch_id": STRING,
                    "transactions": {"type": "integer"},
                },
                required=("artifact_id", "sha256", "import_batch_id", "transactions"),
            ),
            "write",
            True,
            SideEffect.LOCAL_WRITE,
            ("ledger:write",),
            True,
            "Every fact links to a source artifact and import batch.",
        ),
        lambda account_id, path: service.import_csv(account_id, Path(path)),
    )
    registry.register(
        CapabilitySpec(
            "ledger.get_state",
            "Replay account cash and positions at a strict knowledge cutoff.",
            object_schema(
                {"account_id": STRING, "as_of": NULLABLE_STRING},
                required=("account_id",),
            ),
            _state_schema(),
            "read",
            True,
            SideEffect.LOCAL_READ,
            ("portfolio:read",),
            False,
            "Excludes facts whose effective_at or known_at exceeds the cutoff.",
        ),
        lambda account_id, as_of=None: service.state(account_id, as_of),
    )
    registry.register(
        CapabilitySpec(
            "ledger.get_transactions",
            "Return transactions and their legs at a strict knowledge cutoff.",
            object_schema(
                {"account_id": STRING, "as_of": NULLABLE_STRING},
                required=("account_id",),
            ),
            {"type": "array", "items": {"type": "object"}},
            "read",
            True,
            SideEffect.LOCAL_READ,
            ("ledger:read",),
            False,
            "Returns source artifact, import batch, and temporal fields.",
        ),
        lambda account_id, as_of=None: service.transactions(account_id, as_of),
    )
    registry.register(
        CapabilitySpec(
            "ledger.get_cost_basis",
            "Replay FIFO lots and realized gains without market-price assumptions.",
            object_schema(
                {"account_id": STRING, "as_of": NULLABLE_STRING},
                required=("account_id",),
            ),
            {"type": "object"},
            "read",
            True,
            SideEffect.LOCAL_READ,
            ("portfolio:read",),
            False,
            "Every open lot and realized match links to source transaction provenance.",
        ),
        lambda account_id, as_of=None: service.cost_basis(account_id, as_of),
    )
    registry.register(
        CapabilitySpec(
            "ledger.record_fx_conversion",
            "Record a balanced two-currency FX conversion with explicit rate and fee.",
            object_schema(
                {
                    "account_id": STRING,
                    "from_currency": STRING,
                    "to_currency": STRING,
                    "from_amount": STRING,
                    "to_amount": STRING,
                    "effective_at": STRING,
                    "fee": STRING,
                    "fee_currency": NULLABLE_STRING,
                },
                required=(
                    "account_id",
                    "from_currency",
                    "to_currency",
                    "from_amount",
                    "to_amount",
                    "effective_at",
                ),
            ),
            object_schema({"transaction_id": STRING}, required=("transaction_id",)),
            "write",
            True,
            SideEffect.LOCAL_WRITE,
            ("ledger:write",),
            True,
            "Creates a provenance artifact, import batch, balanced transaction, and audit events.",
        ),
        lambda account_id, from_currency, to_currency, from_amount, to_amount, effective_at, fee="0", fee_currency=None: {
            "transaction_id": service.record_fx_conversion(
                account_id,
                from_currency,
                to_currency,
                from_amount,
                to_amount,
                effective_at,
                fee=fee,
                fee_currency=fee_currency,
            )
        },
    )
    registry.register(
        CapabilitySpec(
            "market.import_prices_csv",
            "Import a versioned daily price dataset with temporal provenance and quality flags.",
            object_schema(
                {
                    "path": STRING,
                    "dataset_name": STRING,
                    "version": NULLABLE_STRING,
                    "provider": STRING,
                },
                required=("path",),
            ),
            {"type": "object"},
            "write",
            True,
            SideEffect.LOCAL_WRITE,
            ("market:write",),
            True,
            "Stores raw source, dataset manifest, import batch, observations, and audit event.",
        ),
        lambda path, dataset_name="daily_prices", version=None, provider="local": market.import_prices_csv(
            path, dataset_name=dataset_name, version=version, provider=provider
        ),
    )
    registry.register(
        CapabilitySpec(
            "market.import_fx_csv",
            "Import a versioned daily FX dataset with temporal provenance and quality flags.",
            object_schema(
                {
                    "path": STRING,
                    "dataset_name": STRING,
                    "version": NULLABLE_STRING,
                    "provider": STRING,
                },
                required=("path",),
            ),
            {"type": "object"},
            "write",
            True,
            SideEffect.LOCAL_WRITE,
            ("market:write",),
            True,
            "Stores raw source, dataset manifest, import batch, observations, and audit event.",
        ),
        lambda path, dataset_name="daily_fx", version=None, provider="local": market.import_fx_csv(
            path, dataset_name=dataset_name, version=version, provider=provider
        ),
    )
    registry.register(
        CapabilitySpec(
            "market.list_datasets",
            "List immutable market dataset versions and manifests.",
            object_schema({"dataset_name": NULLABLE_STRING}),
            {"type": "array", "items": {"type": "object"}},
            "read",
            True,
            SideEffect.LOCAL_READ,
            ("market:read",),
            False,
            "Returns source, import, manifest, provider, and version provenance.",
        ),
        lambda dataset_name=None: [
            dict(row) for row in repository.market_datasets(dataset_name)
        ],
    )
    registry.register(
        CapabilitySpec(
            "portfolio.create",
            "Create a cross-account portfolio with a base currency.",
            object_schema(
                {"name": STRING, "base_currency": STRING}, required=("name",)
            ),
            object_schema({"portfolio_id": STRING}, required=("portfolio_id",)),
            "write",
            True,
            SideEffect.LOCAL_WRITE,
            ("portfolio:write",),
            True,
            "Creates an append-only portfolio and audit event.",
        ),
        lambda name, base_currency="USD": {
            "portfolio_id": portfolios.create(name, base_currency)
        },
    )
    registry.register(
        CapabilitySpec(
            "portfolio.set_membership",
            "Append an effective and knowledge-dated account membership event.",
            object_schema(
                {
                    "portfolio_id": STRING,
                    "account_id": STRING,
                    "action": {"type": "string", "enum": ["add", "remove"]},
                    "effective_at": STRING,
                    "known_at": NULLABLE_STRING,
                },
                required=("portfolio_id", "account_id", "action", "effective_at"),
            ),
            object_schema({"membership_event_id": STRING}, required=("membership_event_id",)),
            "write",
            True,
            SideEffect.LOCAL_WRITE,
            ("portfolio:write",),
            True,
            "Creates an append-only membership event and audit event.",
        ),
        lambda portfolio_id, account_id, action, effective_at, known_at=None: {
            "membership_event_id": portfolios.set_membership(
                portfolio_id,
                account_id,
                action,
                effective_at,
                known_at=known_at,
            )
        },
    )
    registry.register(
        CapabilitySpec(
            "portfolio.get_valuation",
            "Value a cross-account portfolio with strict market and knowledge cutoffs.",
            object_schema(
                {
                    "portfolio_id": STRING,
                    "as_of": STRING,
                    "known_as_of": NULLABLE_STRING,
                    "price_dataset_name": NULLABLE_STRING,
                    "price_dataset_version": NULLABLE_STRING,
                    "fx_dataset_name": NULLABLE_STRING,
                    "fx_dataset_version": NULLABLE_STRING,
                },
                required=("portfolio_id", "as_of"),
            ),
            {"type": "object"},
            "read",
            True,
            SideEffect.LOCAL_READ,
            ("portfolio:read", "market:read"),
            False,
            "Returns all price/FX dataset references and structured valuation gaps.",
        ),
        lambda portfolio_id, as_of, known_as_of=None, price_dataset_name=None, price_dataset_version=None, fx_dataset_name=None, fx_dataset_version=None: portfolios.portfolio_valuation(
            portfolio_id,
            as_of,
            known_as_of=known_as_of,
            price_dataset_name=price_dataset_name,
            price_dataset_version=price_dataset_version,
            fx_dataset_name=fx_dataset_name,
            fx_dataset_version=fx_dataset_version,
        ),
    )
    registry.register(
        CapabilitySpec(
            "portfolio.get_performance",
            "Compute Decimal TWR, XIRR, drawdown, flows, and valuation series.",
            object_schema(
                {
                    "portfolio_id": STRING,
                    "dates": {"type": "array", "items": STRING},
                    "known_as_of": NULLABLE_STRING,
                    "price_dataset_name": NULLABLE_STRING,
                    "price_dataset_version": NULLABLE_STRING,
                    "fx_dataset_name": NULLABLE_STRING,
                    "fx_dataset_version": NULLABLE_STRING,
                },
                required=("portfolio_id", "dates"),
            ),
            {"type": "object"},
            "read",
            True,
            SideEffect.LOCAL_READ,
            ("portfolio:read", "market:read"),
            False,
            "Uses point-in-time facts by default and reports external-flow timing semantics.",
        ),
        lambda portfolio_id, dates, known_as_of=None, price_dataset_name=None, price_dataset_version=None, fx_dataset_name=None, fx_dataset_version=None: portfolios.performance(
            portfolio_id,
            dates,
            known_as_of=known_as_of,
            price_dataset_name=price_dataset_name,
            price_dataset_version=price_dataset_version,
            fx_dataset_name=fx_dataset_name,
            fx_dataset_version=fx_dataset_version,
        ),
    )
    registry.register(
        CapabilitySpec(
            "policy.create",
            "Create an append-only versioned investment policy for a portfolio.",
            object_schema(
                {
                    "portfolio_id": STRING,
                    "name": STRING,
                    "effective_from": STRING,
                    "known_at": NULLABLE_STRING,
                    "created_at": NULLABLE_STRING,
                    "recorded_at": NULLABLE_STRING,
                    "rules": _policy_rules_schema(),
                },
                required=("portfolio_id", "name", "effective_from", "rules"),
            ),
            {"type": "object"},
            "write",
            True,
            SideEffect.LOCAL_WRITE,
            ("policy:write",),
            True,
            "Stores normalized rules, immutable source provenance, and an audit event.",
        ),
        lambda portfolio_id, name, effective_from, rules, known_at=None, created_at=None, recorded_at=None: policies.create(
            portfolio_id,
            name,
            effective_from,
            rules,
            known_at=known_at,
            created_at=created_at,
            recorded_at=recorded_at,
        ),
    )
    registry.register(
        CapabilitySpec(
            "policy.add_version",
            "Append an immutable policy version with temporal provenance.",
            object_schema(
                {
                    "policy_id": STRING,
                    "effective_from": STRING,
                    "known_at": NULLABLE_STRING,
                    "recorded_at": NULLABLE_STRING,
                    "rules": _policy_rules_schema(),
                },
                required=("policy_id", "effective_from", "rules"),
            ),
            {"type": "object"},
            "write",
            True,
            SideEffect.LOCAL_WRITE,
            ("policy:write",),
            True,
            "Version rows and rules are append-only and carry source provenance.",
        ),
        lambda policy_id, effective_from, rules, known_at=None, recorded_at=None: policies.add_version(
            policy_id,
            effective_from,
            rules,
            known_at=known_at,
            recorded_at=recorded_at,
        ),
    )
    registry.register(
        CapabilitySpec(
            "policy.list",
            "List canonical investment policies, optionally scoped to a portfolio.",
            object_schema({"portfolio_id": NULLABLE_STRING}),
            {"type": "array", "items": {"type": "object"}},
            "read",
            True,
            SideEffect.LOCAL_READ,
            ("policy:read",),
            False,
            "Returns stable policy identity and provenance columns.",
        ),
        lambda portfolio_id=None: policies.list(portfolio_id),
    )
    registry.register(
        CapabilitySpec(
            "policy.evaluate",
            "Evaluate the selected policy version against deterministic portfolio valuation.",
            object_schema(
                {
                    "policy_id": STRING,
                    "as_of": STRING,
                    "known_as_of": NULLABLE_STRING,
                    "price_dataset_name": NULLABLE_STRING,
                    "price_dataset_version": NULLABLE_STRING,
                    "fx_dataset_name": NULLABLE_STRING,
                    "fx_dataset_version": NULLABLE_STRING,
                },
                required=("policy_id", "as_of"),
            ),
            {"type": "object"},
            "read",
            True,
            SideEffect.LOCAL_READ,
            ("policy:read", "portfolio:read", "market:read"),
            False,
            "Uses effective and known cutoffs and fails closed on incomplete valuation.",
        ),
        lambda policy_id, as_of, known_as_of=None, price_dataset_name=None, price_dataset_version=None, fx_dataset_name=None, fx_dataset_version=None: policies.evaluate(
            policy_id,
            as_of,
            known_as_of=known_as_of,
            price_dataset_name=price_dataset_name,
            price_dataset_version=price_dataset_version,
            fx_dataset_name=fx_dataset_name,
            fx_dataset_version=fx_dataset_version,
        ),
    )
    registry.register(
        CapabilitySpec(
            "policy.simulate",
            "Evaluate a base-currency-cash what-if without mutating the Ledger.",
            object_schema(
                {
                    "policy_id": STRING,
                    "as_of": STRING,
                    "actions": _simulation_actions_schema(),
                    "known_as_of": NULLABLE_STRING,
                    "price_dataset_name": NULLABLE_STRING,
                    "price_dataset_version": NULLABLE_STRING,
                    "fx_dataset_name": NULLABLE_STRING,
                    "fx_dataset_version": NULLABLE_STRING,
                },
                required=("policy_id", "as_of", "actions"),
            ),
            {"type": "object"},
            "read",
            True,
            SideEffect.LOCAL_READ,
            ("policy:read", "portfolio:read", "market:read"),
            False,
            "Returns a deterministic hypothetical valuation and policy result only.",
        ),
        lambda policy_id, as_of, actions, known_as_of=None, price_dataset_name=None, price_dataset_version=None, fx_dataset_name=None, fx_dataset_version=None: policies.simulate(
            policy_id,
            as_of,
            actions,
            known_as_of=known_as_of,
            price_dataset_name=price_dataset_name,
            price_dataset_version=price_dataset_version,
            fx_dataset_name=fx_dataset_name,
            fx_dataset_version=fx_dataset_version,
        ),
    )
    planning_options = {
        "known_as_of": NULLABLE_STRING,
        "price_dataset_name": NULLABLE_STRING,
        "price_dataset_version": NULLABLE_STRING,
        "fx_dataset_name": NULLABLE_STRING,
        "fx_dataset_version": NULLABLE_STRING,
    }
    registry.register(
        CapabilitySpec(
            "planning.compare",
            "Compare deterministic cash-allocation scenarios without persisting a Plan.",
            object_schema(
                {
                    "policy_id": STRING,
                    "as_of": STRING,
                    "scenarios": _planning_scenarios_schema(),
                    **planning_options,
                },
                required=("policy_id", "as_of", "scenarios"),
            ),
            {"type": "object"},
            "read",
            True,
            SideEffect.LOCAL_READ,
            ("planning:read", "policy:read", "portfolio:read", "market:read"),
            False,
            "Ranks candidates by feasibility, unresolved constraints, fees, and stable key.",
        ),
        lambda policy_id, as_of, scenarios, known_as_of=None, price_dataset_name=None, price_dataset_version=None, fx_dataset_name=None, fx_dataset_version=None: planning.compare(
            policy_id,
            as_of,
            scenarios,
            known_as_of=known_as_of,
            price_dataset_name=price_dataset_name,
            price_dataset_version=price_dataset_version,
            fx_dataset_name=fx_dataset_name,
            fx_dataset_version=fx_dataset_version,
        ),
    )
    registry.register(
        CapabilitySpec(
            "planning.create",
            "Persist an immutable deterministic Plan and its projected states.",
            object_schema(
                {
                    "policy_id": STRING,
                    "name": STRING,
                    "as_of": STRING,
                    "scenarios": _planning_scenarios_schema(),
                    "created_at": NULLABLE_STRING,
                    "recorded_at": NULLABLE_STRING,
                    **planning_options,
                },
                required=("policy_id", "name", "as_of", "scenarios"),
            ),
            {"type": "object"},
            "write",
            True,
            SideEffect.LOCAL_WRITE,
            ("planning:write", "policy:read", "portfolio:read", "market:read"),
            True,
            "Stores source/import provenance, scenarios, actions, projected states, constraints, and audit.",
        ),
        lambda policy_id, name, as_of, scenarios, known_as_of=None, created_at=None, recorded_at=None, price_dataset_name=None, price_dataset_version=None, fx_dataset_name=None, fx_dataset_version=None: planning.create(
            policy_id,
            name,
            as_of,
            scenarios,
            known_as_of=known_as_of,
            created_at=created_at,
            recorded_at=recorded_at,
            price_dataset_name=price_dataset_name,
            price_dataset_version=price_dataset_version,
            fx_dataset_name=fx_dataset_name,
            fx_dataset_version=fx_dataset_version,
        ),
    )
    registry.register(
        CapabilitySpec(
            "planning.list",
            "List immutable Plans, optionally scoped to one Portfolio.",
            object_schema({"portfolio_id": NULLABLE_STRING}),
            {"type": "array", "items": {"type": "object"}},
            "read",
            True,
            SideEffect.LOCAL_READ,
            ("planning:read",),
            False,
            "Returns Plan identities, temporal cutoffs, policy references, and provenance.",
        ),
        lambda portfolio_id=None: planning.list(portfolio_id),
    )
    registry.register(
        CapabilitySpec(
            "planning.get",
            "Read a Plan with scenarios, actions, projected states, and unresolved constraints.",
            object_schema({"plan_id": STRING}, required=("plan_id",)),
            {"type": "object"},
            "read",
            True,
            SideEffect.LOCAL_READ,
            ("planning:read",),
            False,
            "Returns persisted deterministic results and does not recompute or mutate the Ledger.",
        ),
        lambda plan_id: planning.get(plan_id),
    )
    registry.register(
        CapabilitySpec(
            "decision.create",
            "Create an immutable trade or non-trade Decision with alternatives and historical context.",
            object_schema(
                {
                    "portfolio_id": STRING,
                    "title": STRING,
                    "intent": {"type": "string", "enum": ["trade", "non_trade"]},
                    "rationale": STRING,
                    "as_of": STRING,
                    "known_as_of": NULLABLE_STRING,
                    "policy_version_id": NULLABLE_STRING,
                    "plan_id": NULLABLE_STRING,
                    "alternatives": _decision_alternatives_schema(),
                    "assumptions": DECISION_STATEMENTS,
                    "expected_outcomes": DECISION_STATEMENTS,
                    "invalidation_conditions": DECISION_STATEMENTS,
                    "review_schedule": REVIEW_SCHEDULE,
                    "created_at": NULLABLE_STRING,
                    "recorded_at": NULLABLE_STRING,
                },
                required=("portfolio_id", "title", "intent", "rationale", "as_of"),
            ),
            {"type": "object"},
            "write",
            True,
            SideEffect.LOCAL_WRITE,
            ("decision:write",),
            True,
            "Stores rationale and alternatives with immutable provenance and audit.",
        ),
        lambda portfolio_id, title, intent, rationale, as_of, known_as_of=None, policy_version_id=None, plan_id=None, alternatives=(), assumptions=(), expected_outcomes=(), invalidation_conditions=(), review_schedule=(), created_at=None, recorded_at=None: decisions.create(
            portfolio_id,
            title,
            intent,
            rationale,
            as_of,
            known_as_of=known_as_of,
            policy_version_id=policy_version_id,
            plan_id=plan_id,
            alternatives=alternatives,
            assumptions=assumptions,
            expected_outcomes=expected_outcomes,
            invalidation_conditions=invalidation_conditions,
            review_schedule=review_schedule,
            created_at=created_at,
            recorded_at=recorded_at,
        ),
    )
    registry.register(
        CapabilitySpec(
            "decision.list",
            "List immutable Decisions for an optional Portfolio.",
            object_schema({"portfolio_id": NULLABLE_STRING}),
            {"type": "array", "items": {"type": "object"}},
            "read",
            True,
            SideEffect.LOCAL_READ,
            ("decision:read",),
            False,
            "Returns decision intent, temporal context, and policy/plan references.",
        ),
        lambda portfolio_id=None: decisions.list(portfolio_id),
    )
    registry.register(
        CapabilitySpec(
            "decision.get",
            "Read a Decision and all append-only links and reviews.",
            object_schema({"decision_id": STRING}, required=("decision_id",)),
            {"type": "object"},
            "read",
            True,
            SideEffect.LOCAL_READ,
            ("decision:read",),
            False,
            "Separates process and outcome reviews and never rewrites rationale.",
        ),
        lambda decision_id: decisions.get(decision_id),
    )
    registry.register(
        CapabilitySpec(
            "decision.link_policy",
            "Append a PolicyVersion link to a Decision.",
            object_schema(
                {"decision_id": STRING, "policy_version_id": STRING, "link_type": STRING},
                required=("decision_id", "policy_version_id"),
            ),
            object_schema({"link_id": STRING}, required=("link_id",)),
            "write",
            True,
            SideEffect.LOCAL_WRITE,
            ("decision:write", "policy:read"),
            True,
            "Links policy context append-only with provenance and audit.",
        ),
        lambda decision_id, policy_version_id, link_type="governs": {
            "link_id": decisions.link_policy(decision_id, policy_version_id, link_type)
        },
    )
    registry.register(
        CapabilitySpec(
            "decision.link_evidence",
            "Append supporting, contradicting, or contextual evidence to a Decision.",
            object_schema(
                {
                    "decision_id": STRING,
                    "evidence_id": STRING,
                    "evidence_kind": STRING,
                    "relation": {"type": "string", "enum": ["supports", "contradicts", "context"]},
                },
                required=("decision_id", "evidence_id"),
            ),
            object_schema({"link_id": STRING}, required=("link_id",)),
            "write",
            True,
            SideEffect.LOCAL_WRITE,
            ("decision:write", "research:read"),
            True,
            "Evidence is linked without pretending it is canonical financial truth.",
        ),
        lambda decision_id, evidence_id, evidence_kind="research", relation="supports": {
            "link_id": decisions.link_evidence(decision_id, evidence_id, evidence_kind, relation)
        },
    )
    registry.register(
        CapabilitySpec(
            "decision.link_transaction",
            "Append the later actual transaction link without rewriting a Decision.",
            object_schema(
                {"decision_id": STRING, "transaction_id": STRING, "relation": STRING, "linked_at": NULLABLE_STRING},
                required=("decision_id", "transaction_id"),
            ),
            object_schema({"link_id": STRING}, required=("link_id",)),
            "write",
            True,
            SideEffect.LOCAL_WRITE,
            ("decision:write", "ledger:read"),
            True,
            "Links executed facts append-only; it never creates or edits a Transaction.",
        ),
        lambda decision_id, transaction_id, relation="executed", linked_at=None: {
            "link_id": decisions.link_transaction(decision_id, transaction_id, relation, linked_at)
        },
    )
    registry.register(
        CapabilitySpec(
            "decision.review",
            "Append a process-quality or outcome-quality Decision review.",
            object_schema(
                {
                    "decision_id": STRING,
                    "review_type": {"type": "string", "enum": ["process", "outcome"]},
                    "score": {"type": ["integer", "null"]},
                    "notes": STRING,
                    "reviewed_at": NULLABLE_STRING,
                },
                required=("decision_id", "review_type", "notes"),
            ),
            object_schema({"review_id": STRING}, required=("review_id",)),
            "write",
            True,
            SideEffect.LOCAL_WRITE,
            ("decision:write",),
            True,
            "Process and outcome quality remain separate immutable records.",
        ),
        lambda decision_id, review_type, notes, score=None, reviewed_at=None: {
            "review_id": decisions.review(decision_id, review_type, score, notes, reviewed_at=reviewed_at)
        },
    )
    registry.register(
        CapabilitySpec(
            "research.ingest_text",
            "Capture an immutable local text document with source provenance.",
            object_schema(
                {
                    "path": STRING,
                    "title": STRING,
                    "source_uri": STRING,
                    "known_at": STRING,
                    "effective_at": NULLABLE_STRING,
                    "recorded_at": NULLABLE_STRING,
                    "media_type": STRING,
                },
                required=("path", "title", "source_uri", "known_at"),
            ),
            {"type": "object"},
            "write",
            True,
            SideEffect.LOCAL_WRITE,
            ("research:write",),
            True,
            "Stores source bytes, provenance, immutable text, and an audit event.",
        ),
        lambda path, title, source_uri, known_at, effective_at=None, recorded_at=None, media_type="text/plain": research.ingest_text(
            path,
            title=title,
            source_uri=source_uri,
            known_at=known_at,
            effective_at=effective_at,
            recorded_at=recorded_at,
            media_type=media_type,
        ),
    )
    registry.register(
        CapabilitySpec(
            "research.get_document",
            "Read a research document and its claims, evidence, and links.",
            object_schema({"document_id": STRING}, required=("document_id",)),
            {"type": "object"},
            "read",
            True,
            SideEffect.LOCAL_READ,
            ("research:read",),
            False,
            "Returns immutable document text and source provenance.",
        ),
        lambda document_id: research.get_document(document_id),
    )
    registry.register(
        CapabilitySpec(
            "research.add_claim",
            "Append a source-spanned research claim.",
            object_schema(
                {
                    "document_id": STRING,
                    "claim_key": STRING,
                    "text": STRING,
                    "span_start": {"type": "integer"},
                    "span_end": {"type": "integer"},
                    "known_at": STRING,
                    "generated_by": STRING,
                    "confidence": NULLABLE_STRING,
                },
                required=("document_id", "claim_key", "text", "span_start", "span_end", "known_at"),
            ),
            {"type": "object"},
            "write",
            True,
            SideEffect.LOCAL_WRITE,
            ("research:write", "research:read"),
            True,
            "Preserves source span and explicit knowledge time.",
        ),
        lambda document_id, claim_key, text, span_start, span_end, known_at, generated_by="human", confidence=None: research.create_claim(
            document_id,
            claim_key=claim_key,
            text=text,
            span_start=span_start,
            span_end=span_end,
            known_at=known_at,
            generated_by=generated_by,
            confidence=confidence,
        ),
    )
    registry.register(
        CapabilitySpec(
            "research.search",
            "Search immutable research documents by deterministic substring matching.",
            object_schema(
                {
                    "query": STRING,
                    "as_of": NULLABLE_STRING,
                    "known_as_of": NULLABLE_STRING,
                },
                required=("query",),
            ),
            {"type": "object"},
            "read",
            True,
            SideEffect.LOCAL_READ,
            ("research:read",),
            False,
            "Search ordering is deterministic and does not use vector ranking.",
        ),
        lambda query, as_of=None, known_as_of=None: research.search(
            query, as_of=as_of, known_as_of=known_as_of
        ),
    )
    registry.register(
        CapabilitySpec(
            "research.add_evidence",
            "Append source evidence with a deterministic relation.",
            object_schema(
                {
                    "document_id": STRING,
                    "kind": STRING,
                    "text": STRING,
                    "span_start": {"type": "integer"},
                    "span_end": {"type": "integer"},
                    "relation": {"type": "string", "enum": ["supports", "contradicts", "context"]},
                    "known_at": STRING,
                    "generated_by": STRING,
                    "confidence": NULLABLE_STRING,
                },
                required=("document_id", "kind", "text", "span_start", "span_end", "relation", "known_at"),
            ),
            {"type": "object"},
            "write",
            True,
            SideEffect.LOCAL_WRITE,
            ("research:write",),
            True,
            "Preserves source span, relation, confidence, and knowledge time.",
        ),
        lambda document_id, kind, text, span_start, span_end, relation, known_at, generated_by="human", confidence=None: research.create_evidence(
            document_id,
            kind=kind,
            text=text,
            span_start=span_start,
            span_end=span_end,
            relation=relation,
            known_at=known_at,
            generated_by=generated_by,
            confidence=confidence,
        ),
    )
    registry.register(
        CapabilitySpec(
            "research.add_contradiction",
            "Record a contradiction while keeping both claims valid.",
            object_schema(
                {
                    "claim_a_id": STRING,
                    "claim_b_id": STRING,
                    "kind": STRING,
                    "explanation": STRING,
                    "known_at": STRING,
                },
                required=("claim_a_id", "claim_b_id", "kind", "explanation", "known_at"),
            ),
            {"type": "object"},
            "write",
            True,
            SideEffect.LOCAL_WRITE,
            ("research:write",),
            True,
            "Contradictions are append-only evidence relationships.",
        ),
        lambda claim_a_id, claim_b_id, kind, explanation, known_at: research.create_contradiction(
            claim_a_id,
            claim_b_id,
            kind=kind,
            explanation=explanation,
            known_at=known_at,
        ),
    )
    registry.register(
        CapabilitySpec(
            "research.create_thesis",
            "Create an immutable thesis with its first revision.",
            object_schema(
                {"title": STRING, "initial_text": STRING, "known_at": STRING},
                required=("title", "initial_text", "known_at"),
            ),
            {"type": "object"},
            "write",
            True,
            SideEffect.LOCAL_WRITE,
            ("research:write",),
            True,
            "Thesis revision one is created atomically and cannot be overwritten.",
        ),
        lambda title, initial_text, known_at: research.create_thesis(
            title=title, initial_text=initial_text, known_at=known_at
        ),
    )
    registry.register(
        CapabilitySpec(
            "research.revise_thesis",
            "Append a new immutable thesis revision.",
            object_schema(
                {"thesis_id": STRING, "text": STRING, "known_at": STRING},
                required=("thesis_id", "text", "known_at"),
            ),
            {"type": "object"},
            "write",
            True,
            SideEffect.LOCAL_WRITE,
            ("research:write",),
            True,
            "Revision numbers are sequential and prior text remains unchanged.",
        ),
        lambda thesis_id, text, known_at: research.revise_thesis(
            thesis_id, text=text, known_at=known_at
        ),
    )
    registry.register(
        CapabilitySpec(
            "research.get_thesis",
            "Read a thesis, revisions, and graph links.",
            object_schema({"thesis_id": STRING}, required=("thesis_id",)),
            {"type": "object"},
            "read",
            True,
            SideEffect.LOCAL_READ,
            ("research:read",),
            False,
            "Returns full immutable revision history.",
        ),
        lambda thesis_id: research.get_thesis(thesis_id),
    )
    registry.register(
        CapabilitySpec(
            "research.link",
            "Append a typed relationship between research and canonical nodes.",
            object_schema(
                {
                    "from_type": STRING,
                    "from_id": STRING,
                    "to_type": STRING,
                    "to_id": STRING,
                    "relation": STRING,
                    "effective_at": NULLABLE_STRING,
                    "known_at": STRING,
                },
                required=("from_type", "from_id", "to_type", "to_id", "relation", "known_at"),
            ),
            object_schema({"link_id": STRING}, required=("link_id",)),
            "write",
            True,
            SideEffect.LOCAL_WRITE,
            ("research:write",),
            True,
            "Endpoint existence is validated before the append-only link is written.",
        ),
        lambda from_type, from_id, to_type, to_id, relation, known_at, effective_at=None: {
            "link_id": research.link(
                from_type,
                from_id,
                to_type,
                to_id,
                relation=relation,
                known_at=known_at,
                effective_at=effective_at,
            )
        },
    )
    registry.register(
        CapabilitySpec(
            "research.trace",
            "Trace deterministic bidirectional research graph neighbors.",
            object_schema(
                {"node_type": STRING, "node_id": STRING, "max_depth": {"type": "integer"}},
                required=("node_type", "node_id"),
            ),
            {"type": "object"},
            "read",
            True,
            SideEffect.LOCAL_READ,
            ("research:read",),
            False,
            "Returns stable node and link records without vector ranking.",
        ),
        lambda node_type, node_id, max_depth=3: research.trace(
            node_type, node_id, max_depth=max_depth
        ),
    )
    registry.register(
        CapabilitySpec(
            "recommendation.create",
            "Create a structured recommendation draft without creating a transaction.",
            object_schema(
                {
                    "portfolio_id": STRING,
                    "subject": STRING,
                    "recommendation_type": STRING,
                    "rationale": STRING,
                    "as_of": STRING,
                    "known_as_of": STRING,
                    "origin": {"type": "string", "enum": ["rule", "agent"]},
                    "alternatives": {"type": "array"},
                },
                required=(
                    "portfolio_id",
                    "subject",
                    "recommendation_type",
                    "rationale",
                    "as_of",
                    "known_as_of",
                ),
            ),
            {"type": "object"},
            "write",
            True,
            SideEffect.LOCAL_WRITE,
            ("recommendation:create",),
            True,
            "Creates a DRAFT recommendation with facts and alternatives as structured data.",
        ),
        lambda portfolio_id, subject, recommendation_type, rationale, as_of, known_as_of, origin="rule", alternatives=(): recommendations.create(
            portfolio_id=portfolio_id,
            subject=subject,
            recommendation_type=recommendation_type,
            rationale=rationale,
            as_of=as_of,
            known_as_of=known_as_of,
            origin=origin,
            alternatives=alternatives,
        ),
    )
    registry.register(
        CapabilitySpec(
            "recommendation.get",
            "Read a recommendation draft and immutable alternatives.",
            object_schema({"recommendation_id": STRING}, required=("recommendation_id",)),
            {"type": "object"},
            "read",
            True,
            SideEffect.LOCAL_READ,
            ("recommendation:read",),
            False,
            "Returns the current derived lifecycle status and original payload.",
        ),
        lambda recommendation_id: recommendations.get(recommendation_id),
    )
    registry.register(
        CapabilitySpec(
            "recommendation.transition",
            "Append a valid recommendation lifecycle transition.",
            object_schema(
                {
                    "recommendation_id": STRING,
                    "status": {
                        "type": "string",
                        "enum": ["reviewed", "accepted", "rejected", "expired"],
                    },
                },
                required=("recommendation_id", "status"),
            ),
            {"type": "object"},
            "write",
            True,
            SideEffect.LOCAL_WRITE,
            ("recommendation:write",),
            True,
            "Lifecycle transitions are append-only and never create transactions.",
        ),
        lambda recommendation_id, status: recommendations.transition(
            recommendation_id, status
        ),
    )

    system_methods = {
        "system.check_integrity": (
            "Check SQLite integrity and the audit hash chain.",
            lambda: {
                "database": repository.integrity_check(),
                "audit": repository.verify_audit_chain(),
            },
            object_schema(
                {"database": STRING, "audit": {"type": "object"}},
                required=("database", "audit"),
            ),
        ),
        "system.export": (
            "Write a stable canonical JSONL export.",
            None,
            object_schema({"path": STRING}, required=("path",)),
        ),
        "system.backup": (
            "Create a verified database, raw artifact, and export backup bundle.",
            None,
            {"type": "object"},
        ),
    }
    description, handler, output_schema = system_methods["system.check_integrity"]
    registry.register(
        CapabilitySpec(
            "system.check_integrity",
            description,
            object_schema(),
            output_schema,
            "read",
            True,
            SideEffect.LOCAL_READ,
            ("system:read",),
            False,
            "Verifies database pages and the append-only audit chain.",
        ),
        handler,
    )
    if hasattr(repository, "export"):
        registry.register(
            CapabilitySpec(
                "system.export",
                system_methods["system.export"][0],
                object_schema({"path": STRING}, required=("path",)),
                system_methods["system.export"][2],
                "write",
                True,
                SideEffect.LOCAL_WRITE,
                ("system:export",),
                True,
                "Exports canonical rows without modifying financial truth.",
            ),
            lambda path: {"path": repository.export(path)},
        )
    if hasattr(repository, "backup_bundle"):
        registry.register(
            CapabilitySpec(
                "system.backup",
                system_methods["system.backup"][0],
                object_schema({"path": STRING}, required=("path",)),
                system_methods["system.backup"][2],
                "write",
                True,
                SideEffect.LOCAL_WRITE,
                ("system:backup",),
                True,
                "Manifest hashes database, raw artifacts, export, and audit head.",
            ),
            lambda path: repository.backup_bundle(path),
        )
    return registry
