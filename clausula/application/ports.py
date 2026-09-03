from __future__ import annotations

from pathlib import Path
from typing import Any, ContextManager, Iterable, Mapping, Protocol, runtime_checkable

from clausula.domain import (
    CorporateAction,
    DatasetVersion,
    FxRate,
    FxConversion,
    InstrumentIdentifier,
    MarketPrice,
    InvestmentPolicy,
    CandidateAction,
    Decision,
    DecisionAlternative,
    DecisionEvidenceLink,
    DecisionPolicyLink,
    DecisionReview,
    DecisionReviewSchedule,
    DecisionStatement,
    DecisionTransactionLink,
    Plan,
    PlanScenario,
    ProjectedState,
    PolicyRule,
    PolicyVersion,
    Portfolio,
    PortfolioMembershipEvent,
    SecurityTransfer,
    Transaction,
    UnresolvedConstraint,
    ResearchClaim,
    ResearchContradiction,
    ResearchDocument,
    ResearchEvidence,
    ResearchLink,
    ResearchThesis,
    ThesisRevision,
    Recommendation,
    RecommendationAlternative,
)


@runtime_checkable
class LedgerRepository(Protocol):
    """Persistence operations required by the canonical Ledger service."""

    def create_account(self, institution: str, name: str) -> str: ...

    def require_account(self, account_id: str) -> Mapping[str, Any]: ...

    def instrument(
        self,
        identifier: InstrumentIdentifier,
        name: str = "",
        asset_type: str = "stock",
        currency: str = "USD",
    ) -> str: ...

    def instrument_details(self, instrument_id: str) -> Mapping[str, Any]: ...


    def artifact(self, path: str | Path) -> tuple[str, str]: ...

    def virtual_artifact(self, uri: str, content: str) -> tuple[str, str]: ...

    def import_batch(
        self,
        artifact_id: str,
        *,
        adapter_name: str = "manual",
        adapter_version: str = "1",
        schema_version: str = "1",
    ) -> str: ...

    def add_import(
        self,
        batch_id: str,
        artifact_id: str,
        entries: Iterable[tuple[Transaction, str]],
        *,
        adapter_name: str,
        adapter_version: str,
        schema_version: str,
    ) -> int: ...

    def add_transaction(self, transaction: Transaction, external_id: str | None = None) -> bool: ...

    def add_transfer(
        self,
        transfer_id: str,
        source_transaction: Transaction,
        destination_transaction: Transaction,
    ) -> None: ...

    def add_fx_conversion(self, transaction: Transaction, conversion: FxConversion) -> None: ...

    def add_security_transfer(
        self,
        transfer: SecurityTransfer,
        source_transaction: Transaction,
        destination_transaction: Transaction,
    ) -> None: ...

    def add_corporate_action(
        self, transaction: Transaction, action: CorporateAction
    ) -> None: ...

    def transactions(
        self,
        account_id: str,
        as_of: str | None = None,
        known_as_of: str | None = None,
    ) -> list[Mapping[str, Any]]: ...

    def transaction(self, transaction_id: str) -> Mapping[str, Any] | None: ...

    def legs(self, transaction_id: str) -> list[Mapping[str, Any]]: ...

    def transaction_metadata(self, transaction_id: str) -> Mapping[str, Any]: ...

    def corporate_action_transaction(self, action_id: str) -> str: ...

    def record_reconciliation(
        self,
        *,
        account_id: str,
        effective_at: str,
        known_at: str,
        source_artifact_id: str,
        import_batch_id: str,
        observed: dict,
        derived: dict,
        differences: list[dict],
    ) -> str: ...


@runtime_checkable
class CoreRepository(LedgerRepository, Protocol):
    def write_transaction(self) -> ContextManager[None]: ...

    def integrity_check(self) -> str: ...

    def verify_audit_chain(self) -> dict[str, Any]: ...

    def record_adapter_invocation(
        self,
        *,
        adapter: str,
        actor_type: str,
        actor_id: str,
        capability: str,
        side_effect: str,
        confirmed: bool,
        succeeded: bool,
    ) -> str: ...

    def export(self, destination: str | Path) -> str: ...

    def backup_bundle(self, destination: str | Path) -> dict[str, Any]: ...

    def rebuild_catalog(self) -> Mapping[str, Any]: ...

    def imported_transaction_mapping(
        self, account_id: str, artifact_id: str
    ) -> Mapping[str, str]: ...

    def add_market_dataset(
        self,
        dataset: DatasetVersion,
        prices: Iterable[MarketPrice],
        fx_rates: Iterable[FxRate],
    ) -> Mapping[str, Any]: ...

    def market_price(
        self,
        instrument_id: str,
        as_of: str,
        known_as_of: str | None = None,
        dataset_name: str | None = None,
        dataset_version: str | None = None,
    ) -> Mapping[str, Any] | None: ...

    def market_fx_rate(
        self,
        from_currency: str,
        to_currency: str,
        as_of: str,
        known_as_of: str | None = None,
        dataset_name: str | None = None,
        dataset_version: str | None = None,
    ) -> Mapping[str, Any] | None: ...

    def market_datasets(self, dataset_name: str | None = None) -> list[Mapping[str, Any]]: ...

    def add_portfolio(self, portfolio: Portfolio) -> None: ...

    def portfolio(self, portfolio_id: str) -> Mapping[str, Any]: ...

    def add_portfolio_membership(self, event: PortfolioMembershipEvent) -> None: ...

    def portfolio_accounts(
        self, portfolio_id: str, as_of: str, known_as_of: str | None = None
    ) -> list[str]: ...

    def add_policy(
        self,
        policy: InvestmentPolicy,
        version: PolicyVersion,
        rules: Iterable[PolicyRule],
    ) -> None: ...

    def add_policy_version(
        self, version: PolicyVersion, rules: Iterable[PolicyRule]
    ) -> None: ...

    def policy(self, policy_id: str) -> Mapping[str, Any]: ...

    def policies(
        self, portfolio_id: str | None = None
    ) -> list[Mapping[str, Any]]: ...

    def next_policy_version_number(self, policy_id: str) -> int: ...

    def policy_version_at(
        self, policy_id: str, as_of: str, known_as_of: str | None = None
    ) -> Mapping[str, Any]: ...

    def policy_versions(self, policy_id: str) -> list[Mapping[str, Any]]: ...

    def policy_rules(self, policy_version_id: str) -> list[Mapping[str, Any]]: ...

    def policy_version(self, policy_version_id: str) -> Mapping[str, Any]: ...

    def add_plan(
        self,
        plan: Plan,
        scenarios: Iterable[PlanScenario],
        actions: Iterable[CandidateAction],
        constraints: Iterable[UnresolvedConstraint],
        projected_states: Iterable[ProjectedState],
        results: Mapping[str, Mapping[str, Any]],
    ) -> None: ...

    def plan(self, plan_id: str) -> Mapping[str, Any]: ...

    def plans(self, portfolio_id: str | None = None) -> list[Mapping[str, Any]]: ...

    def plan_scenarios(self, plan_id: str) -> list[Mapping[str, Any]]: ...

    def plan_actions(self, scenario_id: str) -> list[Mapping[str, Any]]: ...

    def plan_constraints(self, scenario_id: str) -> list[Mapping[str, Any]]: ...

    def plan_projected_state(self, scenario_id: str) -> Mapping[str, Any]: ...

    def add_decision(
        self, decision: Decision, alternatives: Iterable[DecisionAlternative],
        statements: Iterable[DecisionStatement] = (),
        review_schedules: Iterable[DecisionReviewSchedule] = (),
    ) -> None: ...

    def decision(self, decision_id: str) -> Mapping[str, Any]: ...

    def decisions(self, portfolio_id: str | None = None) -> list[Mapping[str, Any]]: ...

    def decision_alternatives(self, decision_id: str) -> list[Mapping[str, Any]]: ...

    def add_decision_policy_link(self, link: DecisionPolicyLink) -> None: ...

    def add_decision_evidence_link(self, link: DecisionEvidenceLink) -> None: ...

    def add_decision_transaction_link(self, link: DecisionTransactionLink) -> None: ...

    def add_decision_review(self, review: DecisionReview) -> None: ...

    def decision_links(self, decision_id: str) -> Mapping[str, list[Mapping[str, Any]]]: ...

    def add_research_document(self, document: ResearchDocument) -> None: ...

    def research_document(self, document_id: str) -> Mapping[str, Any]: ...

    def research_documents(self, query: str | None = None) -> list[Mapping[str, Any]]: ...

    def add_research_claim(self, claim: ResearchClaim) -> None: ...

    def research_claim(self, claim_id: str) -> Mapping[str, Any]: ...

    def research_claims(self, document_id: str) -> list[Mapping[str, Any]]: ...

    def all_research_claims(self) -> list[Mapping[str, Any]]: ...

    def add_research_evidence(self, evidence: ResearchEvidence) -> None: ...

    def research_evidence(self, document_id: str) -> list[Mapping[str, Any]]: ...

    def all_research_evidence(self) -> list[Mapping[str, Any]]: ...

    def add_research_contradiction(
        self, contradiction: ResearchContradiction
    ) -> None: ...

    def research_contradictions(
        self, claim_id: str
    ) -> list[Mapping[str, Any]]: ...

    def add_research_thesis(
        self, thesis: ResearchThesis, revision: ThesisRevision
    ) -> None: ...

    def add_thesis_revision(self, revision: ThesisRevision) -> None: ...

    def research_thesis(self, thesis_id: str) -> Mapping[str, Any]: ...

    def research_theses(self) -> list[Mapping[str, Any]]: ...

    def thesis_revisions(self, thesis_id: str) -> list[Mapping[str, Any]]: ...

    def add_research_link(self, link: ResearchLink) -> None: ...

    def research_links(
        self, node_type: str, node_id: str
    ) -> list[Mapping[str, Any]]: ...

    def add_recommendation(
        self,
        recommendation: Recommendation,
        alternatives: Iterable[RecommendationAlternative],
    ) -> None: ...

    def recommendation(self, recommendation_id: str) -> Mapping[str, Any]: ...

    def recommendation_alternatives(
        self, recommendation_id: str
    ) -> list[Mapping[str, Any]]: ...

    def transition_recommendation(self, recommendation_id: str, status: str) -> None: ...
