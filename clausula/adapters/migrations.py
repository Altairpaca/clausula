from __future__ import annotations

from dataclasses import dataclass
import hashlib
import sqlite3
from typing import Callable, Iterable


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


MIGRATION_METADATA_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations(
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS schema_migrations_reject_update
BEFORE UPDATE ON schema_migrations
BEGIN SELECT RAISE(ABORT, 'schema_migrations is append-only'); END;
CREATE TRIGGER IF NOT EXISTS schema_migrations_reject_delete
BEFORE DELETE ON schema_migrations
BEGIN SELECT RAISE(ABORT, 'schema_migrations is append-only'); END;
"""


MIGRATIONS = (
    Migration(
        2,
        "tamper_evident_audit_log",
        """
CREATE TABLE audit_events(
    sequence INTEGER PRIMARY KEY,
    id TEXT NOT NULL UNIQUE,
    occurred_at TEXT NOT NULL,
    actor_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    previous_hash TEXT NOT NULL,
    event_hash TEXT NOT NULL UNIQUE
);
CREATE INDEX audit_events_object ON audit_events(object_type, object_id, sequence);
CREATE TRIGGER audit_events_reject_update
BEFORE UPDATE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;
CREATE TRIGGER audit_events_reject_delete
BEFORE DELETE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;
""",
    ),
    Migration(
        3,
        "ledger_lots_fx_corporate_actions",
        """
CREATE TABLE fx_conversions(
    transaction_id TEXT PRIMARY KEY REFERENCES transactions(id),
    from_currency TEXT NOT NULL,
    to_currency TEXT NOT NULL,
    from_amount TEXT NOT NULL,
    to_amount TEXT NOT NULL,
    rate TEXT NOT NULL,
    fee TEXT NOT NULL,
    fee_currency TEXT
);
CREATE TABLE transaction_order(
    transaction_id TEXT PRIMARY KEY REFERENCES transactions(id),
    source_sequence INTEGER NOT NULL CHECK(source_sequence >= 0)
);
CREATE TABLE security_transfers(
    id TEXT PRIMARY KEY,
    source_transaction_id TEXT NOT NULL REFERENCES transactions(id),
    destination_transaction_id TEXT NOT NULL REFERENCES transactions(id),
    instrument_id TEXT NOT NULL REFERENCES instruments(id),
    quantity TEXT NOT NULL,
    carried_basis TEXT NOT NULL,
    currency TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    UNIQUE(source_transaction_id, destination_transaction_id)
);
CREATE TABLE security_transfer_allocations(
    id TEXT PRIMARY KEY,
    security_transfer_id TEXT NOT NULL REFERENCES security_transfers(id),
    sequence INTEGER NOT NULL,
    source_transaction_id TEXT NOT NULL REFERENCES transactions(id),
    acquired_at TEXT NOT NULL,
    quantity TEXT NOT NULL,
    basis TEXT NOT NULL,
    currency TEXT NOT NULL,
    UNIQUE(security_transfer_id, sequence)
);
CREATE TABLE corporate_actions(
    id TEXT PRIMARY KEY,
    transaction_id TEXT NOT NULL UNIQUE REFERENCES transactions(id),
    instrument_id TEXT NOT NULL REFERENCES instruments(id),
    action_type TEXT NOT NULL,
    numerator TEXT NOT NULL,
    denominator TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);
CREATE TABLE reconciliation_observations(
    id TEXT PRIMARY KEY,
    reconciliation_id TEXT NOT NULL REFERENCES reconciliation_records(id),
    kind TEXT NOT NULL,
    instrument_id TEXT REFERENCES instruments(id),
    currency TEXT,
    value TEXT NOT NULL,
    CHECK(kind IN ('cash','position')),
    CHECK((kind='cash' AND currency IS NOT NULL AND instrument_id IS NULL) OR
          (kind='position' AND currency IS NULL AND instrument_id IS NOT NULL))
);
CREATE INDEX reconciliation_observations_record
ON reconciliation_observations(reconciliation_id, kind);
CREATE TRIGGER fx_conversions_reject_update BEFORE UPDATE ON fx_conversions
BEGIN SELECT RAISE(ABORT, 'fx_conversions is append-only'); END;
CREATE TRIGGER transaction_order_reject_update BEFORE UPDATE ON transaction_order
BEGIN SELECT RAISE(ABORT, 'transaction_order is append-only'); END;
CREATE TRIGGER transaction_order_reject_delete BEFORE DELETE ON transaction_order
BEGIN SELECT RAISE(ABORT, 'transaction_order is append-only'); END;
CREATE TRIGGER fx_conversions_reject_delete BEFORE DELETE ON fx_conversions
BEGIN SELECT RAISE(ABORT, 'fx_conversions is append-only'); END;
CREATE TRIGGER security_transfers_reject_update BEFORE UPDATE ON security_transfers
BEGIN SELECT RAISE(ABORT, 'security_transfers is append-only'); END;
CREATE TRIGGER security_transfers_reject_delete BEFORE DELETE ON security_transfers
BEGIN SELECT RAISE(ABORT, 'security_transfers is append-only'); END;
CREATE TRIGGER security_transfer_allocations_reject_update BEFORE UPDATE ON security_transfer_allocations
BEGIN SELECT RAISE(ABORT, 'security_transfer_allocations is append-only'); END;
CREATE TRIGGER security_transfer_allocations_reject_delete BEFORE DELETE ON security_transfer_allocations
BEGIN SELECT RAISE(ABORT, 'security_transfer_allocations is append-only'); END;
CREATE TRIGGER corporate_actions_reject_update BEFORE UPDATE ON corporate_actions
BEGIN SELECT RAISE(ABORT, 'corporate_actions is append-only'); END;
CREATE TRIGGER corporate_actions_reject_delete BEFORE DELETE ON corporate_actions
BEGIN SELECT RAISE(ABORT, 'corporate_actions is append-only'); END;
CREATE TRIGGER reconciliation_observations_reject_update BEFORE UPDATE ON reconciliation_observations
BEGIN SELECT RAISE(ABORT, 'reconciliation_observations is append-only'); END;
CREATE TRIGGER reconciliation_observations_reject_delete BEFORE DELETE ON reconciliation_observations
BEGIN SELECT RAISE(ABORT, 'reconciliation_observations is append-only'); END;
""",
    ),
    Migration(
        4,
        "market_snapshots_and_dataset_versions",
        """
CREATE TABLE market_datasets(
    id TEXT PRIMARY KEY,
    dataset_name TEXT NOT NULL,
    version TEXT NOT NULL,
    provider TEXT NOT NULL,
    adapter_name TEXT NOT NULL,
    adapter_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    source_artifact_id TEXT NOT NULL REFERENCES artifacts(id),
    import_batch_id TEXT NOT NULL REFERENCES imports(id),
    manifest_sha256 TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    UNIQUE(dataset_name, version)
);
CREATE TABLE market_prices(
    id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL REFERENCES market_datasets(id),
    instrument_id TEXT NOT NULL REFERENCES instruments(id),
    observed_at TEXT NOT NULL,
    known_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    close TEXT NOT NULL,
    currency TEXT NOT NULL,
    quality TEXT NOT NULL,
    UNIQUE(dataset_id, instrument_id, observed_at)
);
CREATE TABLE market_fx_rates(
    id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL REFERENCES market_datasets(id),
    observed_at TEXT NOT NULL,
    known_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    from_currency TEXT NOT NULL,
    to_currency TEXT NOT NULL,
    rate TEXT NOT NULL,
    quality TEXT NOT NULL,
    UNIQUE(dataset_id, observed_at, from_currency, to_currency)
);
CREATE INDEX market_prices_lookup ON market_prices(instrument_id, observed_at, known_at);
CREATE INDEX market_fx_lookup ON market_fx_rates(from_currency, to_currency, observed_at, known_at);
CREATE TRIGGER market_datasets_reject_update BEFORE UPDATE ON market_datasets
BEGIN SELECT RAISE(ABORT, 'market_datasets is append-only'); END;
CREATE TRIGGER market_datasets_reject_delete BEFORE DELETE ON market_datasets
BEGIN SELECT RAISE(ABORT, 'market_datasets is append-only'); END;
CREATE TRIGGER market_prices_reject_update BEFORE UPDATE ON market_prices
BEGIN SELECT RAISE(ABORT, 'market_prices is append-only'); END;
CREATE TRIGGER market_prices_reject_delete BEFORE DELETE ON market_prices
BEGIN SELECT RAISE(ABORT, 'market_prices is append-only'); END;
CREATE TRIGGER market_fx_rates_reject_update BEFORE UPDATE ON market_fx_rates
BEGIN SELECT RAISE(ABORT, 'market_fx_rates is append-only'); END;
CREATE TRIGGER market_fx_rates_reject_delete BEFORE DELETE ON market_fx_rates
BEGIN SELECT RAISE(ABORT, 'market_fx_rates is append-only'); END;
""",
    ),
    Migration(
        5,
        "portfolio_membership_events",
        """
CREATE TABLE portfolios(
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    base_currency TEXT NOT NULL,
    created_at TEXT NOT NULL,
    source_artifact_id TEXT NOT NULL REFERENCES artifacts(id),
    import_batch_id TEXT NOT NULL REFERENCES imports(id)
);
CREATE TABLE portfolio_membership_events(
    id TEXT PRIMARY KEY,
    portfolio_id TEXT NOT NULL REFERENCES portfolios(id),
    account_id TEXT NOT NULL REFERENCES accounts(id),
    action TEXT NOT NULL CHECK(action IN ('add','remove')),
    effective_at TEXT NOT NULL,
    known_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    source_artifact_id TEXT NOT NULL REFERENCES artifacts(id),
    import_batch_id TEXT NOT NULL REFERENCES imports(id)
);
CREATE INDEX portfolio_membership_as_of
ON portfolio_membership_events(portfolio_id, account_id, effective_at, known_at, recorded_at);
CREATE TRIGGER portfolios_reject_update BEFORE UPDATE ON portfolios
BEGIN SELECT RAISE(ABORT, 'portfolios is append-only'); END;
CREATE TRIGGER portfolios_reject_delete BEFORE DELETE ON portfolios
BEGIN SELECT RAISE(ABORT, 'portfolios is append-only'); END;
CREATE TRIGGER portfolio_membership_events_reject_update BEFORE UPDATE ON portfolio_membership_events
BEGIN SELECT RAISE(ABORT, 'portfolio_membership_events is append-only'); END;
CREATE TRIGGER portfolio_membership_events_reject_delete BEFORE DELETE ON portfolio_membership_events
BEGIN SELECT RAISE(ABORT, 'portfolio_membership_events is append-only'); END;
""",
    ),
    Migration(
        6,
        "versioned_investment_policy",
        """
CREATE TABLE investment_policies(
    id TEXT PRIMARY KEY,
    portfolio_id TEXT NOT NULL REFERENCES portfolios(id),
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    source_artifact_id TEXT NOT NULL REFERENCES artifacts(id),
    import_batch_id TEXT NOT NULL REFERENCES imports(id)
);
CREATE TABLE policy_versions(
    id TEXT PRIMARY KEY,
    policy_id TEXT NOT NULL REFERENCES investment_policies(id),
    version_number INTEGER NOT NULL CHECK(version_number > 0),
    effective_from TEXT NOT NULL,
    known_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    rules_sha256 TEXT NOT NULL,
    source_artifact_id TEXT NOT NULL REFERENCES artifacts(id),
    import_batch_id TEXT NOT NULL REFERENCES imports(id),
    UNIQUE(policy_id, version_number)
);
CREATE TABLE policy_rules(
    id TEXT PRIMARY KEY,
    policy_version_id TEXT NOT NULL REFERENCES policy_versions(id),
    rule_key TEXT NOT NULL,
    rule_type TEXT NOT NULL,
    severity TEXT NOT NULL CHECK(severity IN ('hard','soft')),
    description TEXT NOT NULL,
    subject TEXT,
    target TEXT,
    lower_bound TEXT,
    upper_bound TEXT,
    UNIQUE(policy_version_id, rule_key)
);
CREATE INDEX policy_versions_as_of
ON policy_versions(policy_id, effective_from, known_at, version_number);
CREATE TRIGGER investment_policies_reject_update BEFORE UPDATE ON investment_policies
BEGIN SELECT RAISE(ABORT, 'investment_policies is append-only'); END;
CREATE TRIGGER investment_policies_reject_delete BEFORE DELETE ON investment_policies
BEGIN SELECT RAISE(ABORT, 'investment_policies is append-only'); END;
CREATE TRIGGER policy_versions_reject_update BEFORE UPDATE ON policy_versions
BEGIN SELECT RAISE(ABORT, 'policy_versions is append-only'); END;
CREATE TRIGGER policy_versions_reject_delete BEFORE DELETE ON policy_versions
BEGIN SELECT RAISE(ABORT, 'policy_versions is append-only'); END;
CREATE TRIGGER policy_rules_reject_update BEFORE UPDATE ON policy_rules
BEGIN SELECT RAISE(ABORT, 'policy_rules is append-only'); END;
CREATE TRIGGER policy_rules_reject_delete BEFORE DELETE ON policy_rules
BEGIN SELECT RAISE(ABORT, 'policy_rules is append-only'); END;
""",
    ),
    Migration(
        7,
        "deterministic_planning_artifacts",
        """
CREATE TABLE plans(
    id TEXT PRIMARY KEY,
    portfolio_id TEXT NOT NULL REFERENCES portfolios(id),
    policy_id TEXT NOT NULL REFERENCES investment_policies(id),
    policy_version_id TEXT NOT NULL REFERENCES policy_versions(id),
    name TEXT NOT NULL,
    as_of TEXT NOT NULL,
    known_as_of TEXT NOT NULL,
    created_at TEXT NOT NULL,
    source_artifact_id TEXT NOT NULL REFERENCES artifacts(id),
    import_batch_id TEXT NOT NULL REFERENCES imports(id)
);
CREATE TABLE plan_scenarios(
    id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL REFERENCES plans(id),
    scenario_key TEXT NOT NULL,
    description TEXT NOT NULL,
    cash_available TEXT NOT NULL,
    total_fees TEXT NOT NULL,
    total_tax_estimate TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('feasible','violates_policy','unavailable','rejected')),
    projected_total TEXT,
    result_sha256 TEXT NOT NULL,
    result_json TEXT NOT NULL,
    UNIQUE(plan_id, scenario_key)
);
CREATE TABLE plan_actions(
    id TEXT PRIMARY KEY,
    scenario_id TEXT NOT NULL REFERENCES plan_scenarios(id),
    sequence INTEGER NOT NULL CHECK(sequence >= 0),
    instrument_id TEXT NOT NULL REFERENCES instruments(id),
    base_value_delta TEXT NOT NULL,
    fee TEXT NOT NULL,
    tax_estimate TEXT NOT NULL,
    UNIQUE(scenario_id, sequence)
);
CREATE TABLE plan_projected_states(
    id TEXT PRIMARY KEY,
    scenario_id TEXT NOT NULL UNIQUE REFERENCES plan_scenarios(id),
    complete INTEGER NOT NULL CHECK(complete IN (0,1)),
    total_value TEXT,
    valuation_sha256 TEXT NOT NULL
);
CREATE TABLE plan_constraints(
    id TEXT PRIMARY KEY,
    scenario_id TEXT NOT NULL REFERENCES plan_scenarios(id),
    rule_id TEXT REFERENCES policy_rules(id),
    rule_key TEXT NOT NULL,
    severity TEXT NOT NULL CHECK(severity IN ('hard','soft')),
    status TEXT NOT NULL CHECK(status IN ('violation','unavailable')),
    kind TEXT NOT NULL,
    gap TEXT,
    explanation TEXT NOT NULL
);
CREATE INDEX plans_temporal ON plans(portfolio_id, as_of, known_as_of, created_at);
CREATE TRIGGER plans_reject_update BEFORE UPDATE ON plans
BEGIN SELECT RAISE(ABORT, 'plans is append-only'); END;
CREATE TRIGGER plans_reject_delete BEFORE DELETE ON plans
BEGIN SELECT RAISE(ABORT, 'plans is append-only'); END;
CREATE TRIGGER plan_scenarios_reject_update BEFORE UPDATE ON plan_scenarios
BEGIN SELECT RAISE(ABORT, 'plan_scenarios is append-only'); END;
CREATE TRIGGER plan_scenarios_reject_delete BEFORE DELETE ON plan_scenarios
BEGIN SELECT RAISE(ABORT, 'plan_scenarios is append-only'); END;
CREATE TRIGGER plan_actions_reject_update BEFORE UPDATE ON plan_actions
BEGIN SELECT RAISE(ABORT, 'plan_actions is append-only'); END;
CREATE TRIGGER plan_actions_reject_delete BEFORE DELETE ON plan_actions
BEGIN SELECT RAISE(ABORT, 'plan_actions is append-only'); END;
CREATE TRIGGER plan_projected_states_reject_update BEFORE UPDATE ON plan_projected_states
BEGIN SELECT RAISE(ABORT, 'plan_projected_states is append-only'); END;
CREATE TRIGGER plan_projected_states_reject_delete BEFORE DELETE ON plan_projected_states
BEGIN SELECT RAISE(ABORT, 'plan_projected_states is append-only'); END;
CREATE TRIGGER plan_constraints_reject_update BEFORE UPDATE ON plan_constraints
BEGIN SELECT RAISE(ABORT, 'plan_constraints is append-only'); END;
CREATE TRIGGER plan_constraints_reject_delete BEFORE DELETE ON plan_constraints
BEGIN SELECT RAISE(ABORT, 'plan_constraints is append-only'); END;
""",
    ),
    Migration(
        8,
        "decision_memory_links_and_reviews",
        """
CREATE TABLE decisions(
    id TEXT PRIMARY KEY,
    portfolio_id TEXT NOT NULL REFERENCES portfolios(id),
    title TEXT NOT NULL,
    intent TEXT NOT NULL CHECK(intent IN ('trade','non_trade')),
    rationale TEXT NOT NULL,
    as_of TEXT NOT NULL,
    known_as_of TEXT NOT NULL,
    created_at TEXT NOT NULL,
    policy_version_id TEXT REFERENCES policy_versions(id),
    plan_id TEXT REFERENCES plans(id),
    source_artifact_id TEXT NOT NULL REFERENCES artifacts(id),
    import_batch_id TEXT NOT NULL REFERENCES imports(id)
);
CREATE TABLE decision_alternatives(
    id TEXT PRIMARY KEY,
    decision_id TEXT NOT NULL REFERENCES decisions(id),
    alternative_key TEXT NOT NULL,
    description TEXT NOT NULL,
    selected INTEGER NOT NULL CHECK(selected IN (0,1)),
    UNIQUE(decision_id, alternative_key)
);
CREATE TABLE decision_policy_links(
    id TEXT PRIMARY KEY,
    decision_id TEXT NOT NULL REFERENCES decisions(id),
    policy_version_id TEXT NOT NULL REFERENCES policy_versions(id),
    link_type TEXT NOT NULL,
    UNIQUE(decision_id, policy_version_id, link_type)
);
CREATE TABLE decision_evidence_links(
    id TEXT PRIMARY KEY,
    decision_id TEXT NOT NULL REFERENCES decisions(id),
    evidence_id TEXT NOT NULL,
    evidence_kind TEXT NOT NULL,
    relation TEXT NOT NULL CHECK(relation IN ('supports','contradicts','context')),
    UNIQUE(decision_id, evidence_id, relation)
);
CREATE TABLE decision_transaction_links(
    id TEXT PRIMARY KEY,
    decision_id TEXT NOT NULL REFERENCES decisions(id),
    transaction_id TEXT NOT NULL REFERENCES transactions(id),
    relation TEXT NOT NULL,
    linked_at TEXT NOT NULL,
    UNIQUE(decision_id, transaction_id, relation)
);
CREATE TABLE decision_reviews(
    id TEXT PRIMARY KEY,
    decision_id TEXT NOT NULL REFERENCES decisions(id),
    review_type TEXT NOT NULL CHECK(review_type IN ('process','outcome')),
    score INTEGER CHECK(score IS NULL OR score BETWEEN 1 AND 5),
    notes TEXT NOT NULL,
    reviewed_at TEXT NOT NULL
);
CREATE TABLE decision_statements(
    id TEXT PRIMARY KEY,
    decision_id TEXT NOT NULL REFERENCES decisions(id),
    kind TEXT NOT NULL CHECK(kind IN ('assumption','expected_outcome','invalidation_condition')),
    statement_key TEXT NOT NULL,
    text TEXT NOT NULL,
    UNIQUE(decision_id, kind, statement_key)
);
CREATE TABLE decision_review_schedules(
    id TEXT PRIMARY KEY,
    decision_id TEXT NOT NULL REFERENCES decisions(id),
    review_type TEXT NOT NULL CHECK(review_type IN ('process','outcome')),
    due_at TEXT NOT NULL,
    UNIQUE(decision_id, review_type, due_at)
);
CREATE INDEX decisions_temporal ON decisions(portfolio_id, as_of, known_as_of, created_at);
CREATE TRIGGER decisions_reject_update BEFORE UPDATE ON decisions
BEGIN SELECT RAISE(ABORT, 'decisions is append-only'); END;
CREATE TRIGGER decisions_reject_delete BEFORE DELETE ON decisions
BEGIN SELECT RAISE(ABORT, 'decisions is append-only'); END;
CREATE TRIGGER decision_alternatives_reject_update BEFORE UPDATE ON decision_alternatives
BEGIN SELECT RAISE(ABORT, 'decision_alternatives is append-only'); END;
CREATE TRIGGER decision_alternatives_reject_delete BEFORE DELETE ON decision_alternatives
BEGIN SELECT RAISE(ABORT, 'decision_alternatives is append-only'); END;
CREATE TRIGGER decision_policy_links_reject_update BEFORE UPDATE ON decision_policy_links
BEGIN SELECT RAISE(ABORT, 'decision_policy_links is append-only'); END;
CREATE TRIGGER decision_policy_links_reject_delete BEFORE DELETE ON decision_policy_links
BEGIN SELECT RAISE(ABORT, 'decision_policy_links is append-only'); END;
CREATE TRIGGER decision_evidence_links_reject_update BEFORE UPDATE ON decision_evidence_links
BEGIN SELECT RAISE(ABORT, 'decision_evidence_links is append-only'); END;
CREATE TRIGGER decision_evidence_links_reject_delete BEFORE DELETE ON decision_evidence_links
BEGIN SELECT RAISE(ABORT, 'decision_evidence_links is append-only'); END;
CREATE TRIGGER decision_transaction_links_reject_update BEFORE UPDATE ON decision_transaction_links
BEGIN SELECT RAISE(ABORT, 'decision_transaction_links is append-only'); END;
CREATE TRIGGER decision_transaction_links_reject_delete BEFORE DELETE ON decision_transaction_links
BEGIN SELECT RAISE(ABORT, 'decision_transaction_links is append-only'); END;
CREATE TRIGGER decision_reviews_reject_update BEFORE UPDATE ON decision_reviews
BEGIN SELECT RAISE(ABORT, 'decision_reviews is append-only'); END;
CREATE TRIGGER decision_reviews_reject_delete BEFORE DELETE ON decision_reviews
BEGIN SELECT RAISE(ABORT, 'decision_reviews is append-only'); END;
CREATE TRIGGER decision_statements_reject_update BEFORE UPDATE ON decision_statements
BEGIN SELECT RAISE(ABORT, 'decision_statements is append-only'); END;
CREATE TRIGGER decision_statements_reject_delete BEFORE DELETE ON decision_statements
BEGIN SELECT RAISE(ABORT, 'decision_statements is append-only'); END;
CREATE TRIGGER decision_review_schedules_reject_update BEFORE UPDATE ON decision_review_schedules
BEGIN SELECT RAISE(ABORT, 'decision_review_schedules is append-only'); END;
CREATE TRIGGER decision_review_schedules_reject_delete BEFORE DELETE ON decision_review_schedules
BEGIN SELECT RAISE(ABORT, 'decision_review_schedules is append-only'); END;
""",
    ),
    Migration(
        9,
        "research_evidence_graph",
        """
CREATE TABLE research_documents(
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    media_type TEXT NOT NULL,
    source_uri TEXT NOT NULL,
    text TEXT NOT NULL,
    text_sha256 TEXT NOT NULL,
    effective_at TEXT NOT NULL,
    known_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    source_artifact_id TEXT NOT NULL REFERENCES artifacts(id),
    import_batch_id TEXT NOT NULL REFERENCES imports(id)
);
CREATE TABLE research_claims(
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES research_documents(id),
    claim_key TEXT NOT NULL,
    text TEXT NOT NULL,
    span_start INTEGER NOT NULL CHECK(span_start >= 0),
    span_end INTEGER NOT NULL CHECK(span_end > span_start),
    generated_by TEXT NOT NULL,
    confidence TEXT,
    effective_at TEXT NOT NULL,
    known_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    source_artifact_id TEXT NOT NULL REFERENCES artifacts(id),
    import_batch_id TEXT NOT NULL REFERENCES imports(id),
    UNIQUE(document_id, claim_key)
);
CREATE TABLE research_evidence(
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES research_documents(id),
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    span_start INTEGER NOT NULL CHECK(span_start >= 0),
    span_end INTEGER NOT NULL CHECK(span_end > span_start),
    relation TEXT NOT NULL CHECK(relation IN ('supports','contradicts','context')),
    generated_by TEXT NOT NULL,
    confidence TEXT,
    effective_at TEXT NOT NULL,
    known_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    source_artifact_id TEXT NOT NULL REFERENCES artifacts(id),
    import_batch_id TEXT NOT NULL REFERENCES imports(id)
);
CREATE TABLE research_contradictions(
    id TEXT PRIMARY KEY,
    claim_a_id TEXT NOT NULL REFERENCES research_claims(id),
    claim_b_id TEXT NOT NULL REFERENCES research_claims(id),
    kind TEXT NOT NULL,
    explanation TEXT NOT NULL,
    known_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    source_artifact_id TEXT NOT NULL REFERENCES artifacts(id),
    import_batch_id TEXT NOT NULL REFERENCES imports(id),
    UNIQUE(claim_a_id, claim_b_id, kind)
);
CREATE TABLE research_theses(
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    source_artifact_id TEXT NOT NULL REFERENCES artifacts(id),
    import_batch_id TEXT NOT NULL REFERENCES imports(id)
);
CREATE TABLE thesis_revisions(
    id TEXT PRIMARY KEY,
    thesis_id TEXT NOT NULL REFERENCES research_theses(id),
    revision_number INTEGER NOT NULL CHECK(revision_number > 0),
    text TEXT NOT NULL,
    known_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    source_artifact_id TEXT NOT NULL REFERENCES artifacts(id),
    import_batch_id TEXT NOT NULL REFERENCES imports(id),
    UNIQUE(thesis_id, revision_number)
);
CREATE TABLE research_links(
    id TEXT PRIMARY KEY,
    from_type TEXT NOT NULL,
    from_id TEXT NOT NULL,
    to_type TEXT NOT NULL,
    to_id TEXT NOT NULL,
    relation TEXT NOT NULL,
    created_at TEXT NOT NULL,
    source_artifact_id TEXT NOT NULL REFERENCES artifacts(id),
    import_batch_id TEXT NOT NULL REFERENCES imports(id),
    UNIQUE(from_type, from_id, to_type, to_id, relation)
);
CREATE INDEX research_documents_search ON research_documents(title, source_uri);
CREATE INDEX research_claims_document ON research_claims(document_id, claim_key);
CREATE INDEX research_evidence_document ON research_evidence(document_id, id);
CREATE INDEX research_contradictions_claims
ON research_contradictions(claim_a_id, claim_b_id);
CREATE INDEX thesis_revisions_order ON thesis_revisions(thesis_id, revision_number);
CREATE INDEX research_links_from ON research_links(from_type, from_id);
CREATE INDEX research_links_to ON research_links(to_type, to_id);
CREATE TRIGGER research_documents_reject_update BEFORE UPDATE ON research_documents
BEGIN SELECT RAISE(ABORT, 'research_documents is append-only'); END;
CREATE TRIGGER research_documents_reject_delete BEFORE DELETE ON research_documents
BEGIN SELECT RAISE(ABORT, 'research_documents is append-only'); END;
CREATE TRIGGER research_claims_reject_update BEFORE UPDATE ON research_claims
BEGIN SELECT RAISE(ABORT, 'research_claims is append-only'); END;
CREATE TRIGGER research_claims_reject_delete BEFORE DELETE ON research_claims
BEGIN SELECT RAISE(ABORT, 'research_claims is append-only'); END;
CREATE TRIGGER research_evidence_reject_update BEFORE UPDATE ON research_evidence
BEGIN SELECT RAISE(ABORT, 'research_evidence is append-only'); END;
CREATE TRIGGER research_evidence_reject_delete BEFORE DELETE ON research_evidence
BEGIN SELECT RAISE(ABORT, 'research_evidence is append-only'); END;
CREATE TRIGGER research_contradictions_reject_update BEFORE UPDATE ON research_contradictions
BEGIN SELECT RAISE(ABORT, 'research_contradictions is append-only'); END;
CREATE TRIGGER research_contradictions_reject_delete BEFORE DELETE ON research_contradictions
BEGIN SELECT RAISE(ABORT, 'research_contradictions is append-only'); END;
CREATE TRIGGER research_theses_reject_update BEFORE UPDATE ON research_theses
BEGIN SELECT RAISE(ABORT, 'research_theses is append-only'); END;
CREATE TRIGGER research_theses_reject_delete BEFORE DELETE ON research_theses
BEGIN SELECT RAISE(ABORT, 'research_theses is append-only'); END;
CREATE TRIGGER thesis_revisions_reject_update BEFORE UPDATE ON thesis_revisions
BEGIN SELECT RAISE(ABORT, 'thesis_revisions is append-only'); END;
CREATE TRIGGER thesis_revisions_reject_delete BEFORE DELETE ON thesis_revisions
BEGIN SELECT RAISE(ABORT, 'thesis_revisions is append-only'); END;
CREATE TRIGGER research_links_reject_update BEFORE UPDATE ON research_links
BEGIN SELECT RAISE(ABORT, 'research_links is append-only'); END;
CREATE TRIGGER research_links_reject_delete BEFORE DELETE ON research_links
BEGIN SELECT RAISE(ABORT, 'research_links is append-only'); END;
""",
    ),
    Migration(
        10,
        "research_temporal_links",
        """
ALTER TABLE research_links ADD COLUMN effective_at TEXT NOT NULL DEFAULT '1970-01-01T00:00:00+00:00';
ALTER TABLE research_links ADD COLUMN known_at TEXT NOT NULL DEFAULT '1970-01-01T00:00:00+00:00';
""",
    ),
    Migration(
        11,
        "recommendation_lifecycle",
        """
CREATE TABLE recommendations(
    id TEXT PRIMARY KEY,
    portfolio_id TEXT NOT NULL REFERENCES portfolios(id),
    subject TEXT NOT NULL,
    recommendation_type TEXT NOT NULL,
    rationale TEXT NOT NULL,
    origin TEXT NOT NULL CHECK(origin IN ('rule','agent')),
    as_of TEXT NOT NULL,
    known_as_of TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    source_artifact_id TEXT NOT NULL REFERENCES artifacts(id),
    import_batch_id TEXT NOT NULL REFERENCES imports(id)
);
CREATE TABLE recommendation_alternatives(
    id TEXT PRIMARY KEY,
    recommendation_id TEXT NOT NULL REFERENCES recommendations(id),
    alternative_key TEXT NOT NULL,
    description TEXT NOT NULL,
    selected INTEGER NOT NULL CHECK(selected IN (0,1)),
    UNIQUE(recommendation_id, alternative_key)
);
CREATE TABLE recommendation_transitions(
    id TEXT PRIMARY KEY,
    recommendation_id TEXT NOT NULL REFERENCES recommendations(id),
    status TEXT NOT NULL CHECK(status IN ('reviewed','accepted','rejected','expired')),
    transitioned_at TEXT NOT NULL,
    source_artifact_id TEXT NOT NULL REFERENCES artifacts(id),
    import_batch_id TEXT NOT NULL REFERENCES imports(id),
    UNIQUE(recommendation_id, status)
);
CREATE INDEX recommendations_portfolio ON recommendations(portfolio_id, created_at, id);
CREATE INDEX recommendation_transitions_lookup
ON recommendation_transitions(recommendation_id, transitioned_at, id);
CREATE TRIGGER recommendations_reject_update BEFORE UPDATE ON recommendations
BEGIN SELECT RAISE(ABORT, 'recommendations is append-only'); END;
CREATE TRIGGER recommendations_reject_delete BEFORE DELETE ON recommendations
BEGIN SELECT RAISE(ABORT, 'recommendations is append-only'); END;
CREATE TRIGGER recommendation_alternatives_reject_update BEFORE UPDATE ON recommendation_alternatives
BEGIN SELECT RAISE(ABORT, 'recommendation_alternatives is append-only'); END;
CREATE TRIGGER recommendation_alternatives_reject_delete BEFORE DELETE ON recommendation_alternatives
BEGIN SELECT RAISE(ABORT, 'recommendation_alternatives is append-only'); END;
CREATE TRIGGER recommendation_transitions_reject_update BEFORE UPDATE ON recommendation_transitions
BEGIN SELECT RAISE(ABORT, 'recommendation_transitions is append-only'); END;
CREATE TRIGGER recommendation_transitions_reject_delete BEFORE DELETE ON recommendation_transitions
BEGIN SELECT RAISE(ABORT, 'recommendation_transitions is append-only'); END;
""",
    ),
)


LATEST_SCHEMA_VERSION = max(migration.version for migration in MIGRATIONS)


def _statements(script: str) -> Iterable[str]:
    pending = ""
    for line in script.splitlines(keepends=True):
        pending += line
        if sqlite3.complete_statement(pending):
            statement = pending.strip()
            if statement:
                yield statement
            pending = ""
    if pending.strip():
        raise MigrationError("incomplete SQL migration statement")


def _execute_script(connection: sqlite3.Connection, script: str) -> None:
    for statement in _statements(script):
        connection.execute(statement)


def migrate(
    connection: sqlite3.Connection,
    *,
    baseline_sql: str,
    apply_baseline: Callable[[], None],
    now: Callable[[], str],
) -> int:
    current = connection.execute("PRAGMA user_version").fetchone()[0]
    if current > LATEST_SCHEMA_VERSION:
        raise MigrationError(
            f"database schema {current} is newer than supported schema {LATEST_SCHEMA_VERSION}"
        )

    baseline_checksum = hashlib.sha256(baseline_sql.encode("utf-8")).hexdigest()
    if current == 0:
        with connection:
            apply_baseline()
            connection.execute("PRAGMA user_version = 1")
        current = 1
    elif current == 1:
        # Version 1 predates the migration ledger. Re-applying its idempotent
        # bootstrap fills the side tables introduced during the prototype.
        with connection:
            apply_baseline()

    with connection:
        _execute_script(connection, MIGRATION_METADATA_SQL)
        connection.execute(
            """INSERT OR IGNORE INTO schema_migrations(version,name,checksum,applied_at)
               VALUES(1,'kernel_baseline',?,?)""",
            (baseline_checksum, now()),
        )

    expected = {1: ("kernel_baseline", baseline_checksum)} | {
        migration.version: (migration.name, migration.checksum) for migration in MIGRATIONS
    }
    rows = connection.execute(
        "SELECT version,name,checksum FROM schema_migrations ORDER BY version"
    ).fetchall()
    for version, name, checksum in rows:
        contract = expected.get(version)
        if contract is None:
            raise MigrationError(f"database contains unknown migration {version}: {name}")
        if contract != (name, checksum):
            raise MigrationError(f"migration checksum mismatch for version {version}: {name}")

    for migration in MIGRATIONS:
        if migration.version <= current:
            continue
        try:
            with connection:
                _execute_script(connection, migration.sql)
                connection.execute(
                    "INSERT INTO schema_migrations(version,name,checksum,applied_at) VALUES(?,?,?,?)",
                    (migration.version, migration.name, migration.checksum, now()),
                )
                connection.execute(f"PRAGMA user_version = {migration.version}")
        except sqlite3.DatabaseError as exc:
            raise MigrationError(
                f"failed to apply migration {migration.version}: {migration.name}"
            ) from exc
        current = migration.version

    return current
