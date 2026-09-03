import argparse
import json
from pathlib import Path

from .capabilities import build_core_registry
from .store import Store


def _json_argument(value: str):
    candidate = Path(value)
    if candidate.is_file():
        return json.loads(candidate.read_text(encoding="utf-8"))
    return json.loads(value)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="clausula")
    subparsers = parser.add_subparsers(dest="command", required=True)

    account = subparsers.add_parser("account")
    account_actions = account.add_subparsers(dest="action", required=True)
    create = account_actions.add_parser("create")
    create.add_argument("institution")
    create.add_argument("name")

    ledger = subparsers.add_parser("ledger")
    ledger_actions = ledger.add_subparsers(dest="action", required=True)
    import_csv = ledger_actions.add_parser("import")
    import_csv.add_argument("account")
    import_csv.add_argument("path")
    state = ledger_actions.add_parser("state")
    state.add_argument("account")
    state.add_argument("--as-of")
    transactions = ledger_actions.add_parser("transactions")
    transactions.add_argument("account")
    transactions.add_argument("--as-of")
    cost_basis = ledger_actions.add_parser("cost-basis")
    cost_basis.add_argument("account")
    cost_basis.add_argument("--as-of")

    market = subparsers.add_parser("market")
    market_actions = market.add_subparsers(dest="action", required=True)
    import_prices = market_actions.add_parser("import-prices")
    import_prices.add_argument("path")
    import_prices.add_argument("--dataset", default="daily_prices")
    import_prices.add_argument("--version")
    import_prices.add_argument("--provider", default="local")
    import_fx = market_actions.add_parser("import-fx")
    import_fx.add_argument("path")
    import_fx.add_argument("--dataset", default="daily_fx")
    import_fx.add_argument("--version")
    import_fx.add_argument("--provider", default="local")
    datasets = market_actions.add_parser("datasets")
    datasets.add_argument("--name")

    portfolio = subparsers.add_parser("portfolio")
    portfolio_actions = portfolio.add_subparsers(dest="action", required=True)
    create_portfolio = portfolio_actions.add_parser("create")
    create_portfolio.add_argument("name")
    create_portfolio.add_argument("--base-currency", default="USD")
    membership = portfolio_actions.add_parser("membership")
    membership.add_argument("portfolio")
    membership.add_argument("account")
    membership.add_argument("membership_action", choices=("add", "remove"))
    membership.add_argument("effective_at")
    membership.add_argument("--known-at")
    valuation = portfolio_actions.add_parser("valuation")
    valuation.add_argument("portfolio")
    valuation.add_argument("as_of")
    valuation.add_argument("--known-as-of")
    valuation.add_argument("--price-dataset")
    valuation.add_argument("--price-version")
    valuation.add_argument("--fx-dataset")
    valuation.add_argument("--fx-version")
    performance = portfolio_actions.add_parser("performance")
    performance.add_argument("portfolio")
    performance.add_argument("dates", nargs="+")
    performance.add_argument("--known-as-of")
    performance.add_argument("--price-dataset")
    performance.add_argument("--price-version")
    performance.add_argument("--fx-dataset")
    performance.add_argument("--fx-version")

    policy = subparsers.add_parser("policy")
    policy_actions = policy.add_subparsers(dest="action", required=True)
    policy_create = policy_actions.add_parser("create")
    policy_create.add_argument("portfolio")
    policy_create.add_argument("name")
    policy_create.add_argument("effective_from")
    policy_create.add_argument("--rules", required=True, help="JSON text or a JSON file path")
    policy_create.add_argument("--known-at")
    policy_create.add_argument("--created-at")
    policy_create.add_argument("--recorded-at")
    policy_version = policy_actions.add_parser("add-version")
    policy_version.add_argument("policy")
    policy_version.add_argument("effective_from")
    policy_version.add_argument("--rules", required=True, help="JSON text or a JSON file path")
    policy_version.add_argument("--known-at")
    policy_version.add_argument("--recorded-at")
    policy_list = policy_actions.add_parser("list")
    policy_list.add_argument("--portfolio")
    policy_evaluate = policy_actions.add_parser("evaluate")
    policy_evaluate.add_argument("policy")
    policy_evaluate.add_argument("as_of")
    policy_evaluate.add_argument("--known-as-of")
    policy_evaluate.add_argument("--price-dataset")
    policy_evaluate.add_argument("--price-version")
    policy_evaluate.add_argument("--fx-dataset")
    policy_evaluate.add_argument("--fx-version")
    policy_simulate = policy_actions.add_parser("simulate")
    policy_simulate.add_argument("policy")
    policy_simulate.add_argument("as_of")
    policy_simulate.add_argument("--actions", required=True, help="JSON text or a JSON file path")
    policy_simulate.add_argument("--known-as-of")
    policy_simulate.add_argument("--price-dataset")
    policy_simulate.add_argument("--price-version")
    policy_simulate.add_argument("--fx-dataset")
    policy_simulate.add_argument("--fx-version")

    planning = subparsers.add_parser("planning")
    planning_actions = planning.add_subparsers(dest="action", required=True)
    planning_compare = planning_actions.add_parser("compare")
    planning_compare.add_argument("policy")
    planning_compare.add_argument("as_of")
    planning_compare.add_argument("--scenarios", required=True, help="JSON text or a JSON file path")
    planning_compare.add_argument("--known-as-of")
    planning_compare.add_argument("--price-dataset")
    planning_compare.add_argument("--price-version")
    planning_compare.add_argument("--fx-dataset")
    planning_compare.add_argument("--fx-version")
    planning_create = planning_actions.add_parser("create")
    planning_create.add_argument("policy")
    planning_create.add_argument("name")
    planning_create.add_argument("as_of")
    planning_create.add_argument("--scenarios", required=True, help="JSON text or a JSON file path")
    planning_create.add_argument("--known-as-of")
    planning_create.add_argument("--created-at")
    planning_create.add_argument("--recorded-at")
    planning_create.add_argument("--price-dataset")
    planning_create.add_argument("--price-version")
    planning_create.add_argument("--fx-dataset")
    planning_create.add_argument("--fx-version")
    planning_list = planning_actions.add_parser("list")
    planning_list.add_argument("--portfolio")
    planning_get = planning_actions.add_parser("get")
    planning_get.add_argument("plan")

    decision = subparsers.add_parser("decision")
    decision_actions = decision.add_subparsers(dest="action", required=True)
    decision_create = decision_actions.add_parser("create")
    decision_create.add_argument("portfolio")
    decision_create.add_argument("title")
    decision_create.add_argument("intent", choices=("trade", "non_trade"))
    decision_create.add_argument("as_of")
    decision_create.add_argument("--rationale", required=True)
    decision_create.add_argument("--known-as-of")
    decision_create.add_argument("--policy-version")
    decision_create.add_argument("--plan")
    decision_create.add_argument("--alternatives", default="[]", help="JSON text or a JSON file path")
    decision_create.add_argument("--created-at")
    decision_create.add_argument("--recorded-at")
    decision_list = decision_actions.add_parser("list")
    decision_list.add_argument("--portfolio")
    decision_get = decision_actions.add_parser("get")
    decision_get.add_argument("decision")
    decision_policy = decision_actions.add_parser("link-policy")
    decision_policy.add_argument("decision")
    decision_policy.add_argument("policy_version")
    decision_policy.add_argument("--link-type", default="governs")
    decision_evidence = decision_actions.add_parser("link-evidence")
    decision_evidence.add_argument("decision")
    decision_evidence.add_argument("evidence")
    decision_evidence.add_argument("--kind", default="research")
    decision_evidence.add_argument("--relation", choices=("supports", "contradicts", "context"), default="supports")
    decision_transaction = decision_actions.add_parser("link-transaction")
    decision_transaction.add_argument("decision")
    decision_transaction.add_argument("transaction")
    decision_transaction.add_argument("--relation", default="executed")
    decision_transaction.add_argument("--linked-at")
    decision_review = decision_actions.add_parser("review")
    decision_review.add_argument("decision")
    decision_review.add_argument("review_type", choices=("process", "outcome"))
    decision_review.add_argument("--notes", required=True)
    decision_review.add_argument("--score", type=int)
    decision_review.add_argument("--reviewed-at")

    research = subparsers.add_parser("research")
    research_actions = research.add_subparsers(dest="action", required=True)
    research_ingest = research_actions.add_parser("ingest-text")
    research_ingest.add_argument("path")
    research_ingest.add_argument("title")
    research_ingest.add_argument("source_uri")
    research_ingest.add_argument("--known-at", required=True)
    research_ingest.add_argument("--effective-at")
    research_ingest.add_argument("--media-type", default="text/plain")
    research_document = research_actions.add_parser("document")
    research_document.add_argument("document")
    research_search = research_actions.add_parser("search")
    research_search.add_argument("query")
    research_search.add_argument("--as-of")
    research_search.add_argument("--known-as-of")
    research_claim = research_actions.add_parser("claim")
    research_claim.add_argument("document")
    research_claim.add_argument("claim_key")
    research_claim.add_argument("text")
    research_claim.add_argument("span_start", type=int)
    research_claim.add_argument("span_end", type=int)
    research_claim.add_argument("--known-at", required=True)
    research_evidence = research_actions.add_parser("evidence")
    research_evidence.add_argument("document")
    research_evidence.add_argument("kind")
    research_evidence.add_argument("text")
    research_evidence.add_argument("span_start", type=int)
    research_evidence.add_argument("span_end", type=int)
    research_evidence.add_argument(
        "relation", choices=("supports", "contradicts", "context")
    )
    research_evidence.add_argument("--known-at", required=True)
    research_contradiction = research_actions.add_parser("contradiction")
    research_contradiction.add_argument("claim_a")
    research_contradiction.add_argument("claim_b")
    research_contradiction.add_argument("kind")
    research_contradiction.add_argument("explanation")
    research_contradiction.add_argument("--known-at", required=True)
    research_thesis = research_actions.add_parser("thesis-create")
    research_thesis.add_argument("title")
    research_thesis.add_argument("initial_text")
    research_thesis.add_argument("--known-at", required=True)
    research_revision = research_actions.add_parser("thesis-revise")
    research_revision.add_argument("thesis")
    research_revision.add_argument("text")
    research_revision.add_argument("--known-at", required=True)
    research_get_thesis = research_actions.add_parser("thesis")
    research_get_thesis.add_argument("thesis")
    research_link = research_actions.add_parser("link")
    research_link.add_argument("from_type")
    research_link.add_argument("from_id")
    research_link.add_argument("to_type")
    research_link.add_argument("to_id")
    research_link.add_argument("relation")
    research_link.add_argument("--known-at", required=True)
    research_link.add_argument("--effective-at")
    research_trace = research_actions.add_parser("trace")
    research_trace.add_argument("node_type")
    research_trace.add_argument("node_id")
    research_trace.add_argument("--max-depth", type=int, default=3)

    system = subparsers.add_parser("system")
    system_actions = system.add_subparsers(dest="action", required=True)
    system_actions.add_parser("check")
    export = system_actions.add_parser("export")
    export.add_argument("path")
    backup = system_actions.add_parser("backup")
    backup.add_argument("path")

    capability = subparsers.add_parser("capability")
    capability_actions = capability.add_subparsers(dest="action", required=True)
    capability_actions.add_parser("list")
    describe = capability_actions.add_parser("describe")
    describe.add_argument("name")
    run = capability_actions.add_parser("run")
    run.add_argument("name")
    run.add_argument("--input", default="{}")
    run.add_argument("--permission", action="append", default=[])
    run.add_argument("--confirm", action="store_true")
    run.add_argument("--dry-run", action="store_true")

    args = parser.parse_args(argv)
    registry = build_core_registry(Store())
    if args.command == "account":
        output = registry.execute(
            "account.create",
            {"institution": args.institution, "name": args.name},
            permissions={"ledger:write"},
            confirmed=True,
        )
    elif args.command == "ledger" and args.action == "import":
        output = registry.execute(
            "ledger.import_csv",
            {"account_id": args.account, "path": args.path},
            permissions={"ledger:write"},
            confirmed=True,
        )
    elif args.command == "ledger" and args.action == "state":
        arguments = {"account_id": args.account}
        if args.as_of is not None:
            arguments["as_of"] = args.as_of
        output = registry.execute(
            "ledger.get_state", arguments, permissions={"portfolio:read"}
        )
    elif args.command == "ledger" and args.action == "transactions":
        arguments = {"account_id": args.account}
        if args.as_of is not None:
            arguments["as_of"] = args.as_of
        output = registry.execute(
            "ledger.get_transactions", arguments, permissions={"ledger:read"}
        )
    elif args.command == "ledger" and args.action == "cost-basis":
        arguments = {"account_id": args.account}
        if args.as_of is not None:
            arguments["as_of"] = args.as_of
        output = registry.execute(
            "ledger.get_cost_basis", arguments, permissions={"portfolio:read"}
        )
    elif args.command == "market" and args.action in {"import-prices", "import-fx"}:
        arguments = {
            "path": args.path,
            "dataset_name": args.dataset,
            "provider": args.provider,
        }
        if args.version is not None:
            arguments["version"] = args.version
        output = registry.execute(
            "market.import_prices_csv"
            if args.action == "import-prices"
            else "market.import_fx_csv",
            arguments,
            permissions={"market:write"},
            confirmed=True,
        )
    elif args.command == "market" and args.action == "datasets":
        arguments = {} if args.name is None else {"dataset_name": args.name}
        output = registry.execute(
            "market.list_datasets", arguments, permissions={"market:read"}
        )
    elif args.command == "portfolio" and args.action == "create":
        output = registry.execute(
            "portfolio.create",
            {"name": args.name, "base_currency": args.base_currency},
            permissions={"portfolio:write"},
            confirmed=True,
        )
    elif args.command == "portfolio" and args.action == "membership":
        arguments = {
            "portfolio_id": args.portfolio,
            "account_id": args.account,
            "action": args.membership_action,
            "effective_at": args.effective_at,
        }
        if args.known_at is not None:
            arguments["known_at"] = args.known_at
        output = registry.execute(
            "portfolio.set_membership",
            arguments,
            permissions={"portfolio:write"},
            confirmed=True,
        )
    elif args.command == "portfolio" and args.action in {"valuation", "performance"}:
        arguments = {"portfolio_id": args.portfolio}
        if args.action == "valuation":
            arguments["as_of"] = args.as_of
        else:
            arguments["dates"] = args.dates
        optional = {
            "known_as_of": args.known_as_of,
            "price_dataset_name": args.price_dataset,
            "price_dataset_version": args.price_version,
            "fx_dataset_name": args.fx_dataset,
            "fx_dataset_version": args.fx_version,
        }
        arguments.update({key: value for key, value in optional.items() if value is not None})
        output = registry.execute(
            "portfolio.get_valuation"
            if args.action == "valuation"
            else "portfolio.get_performance",
            arguments,
            permissions={"portfolio:read", "market:read"},
        )
    elif args.command == "policy" and args.action == "create":
        arguments = {
            "portfolio_id": args.portfolio,
            "name": args.name,
            "effective_from": args.effective_from,
            "rules": _json_argument(args.rules),
        }
        for key, value in {
            "known_at": args.known_at,
            "created_at": args.created_at,
            "recorded_at": args.recorded_at,
        }.items():
            if value is not None:
                arguments[key] = value
        output = registry.execute(
            "policy.create", arguments, permissions={"policy:write"}, confirmed=True
        )
    elif args.command == "policy" and args.action == "add-version":
        arguments = {
            "policy_id": args.policy,
            "effective_from": args.effective_from,
            "rules": _json_argument(args.rules),
        }
        for key, value in {"known_at": args.known_at, "recorded_at": args.recorded_at}.items():
            if value is not None:
                arguments[key] = value
        output = registry.execute(
            "policy.add_version", arguments, permissions={"policy:write"}, confirmed=True
        )
    elif args.command == "policy" and args.action == "list":
        arguments = {} if args.portfolio is None else {"portfolio_id": args.portfolio}
        output = registry.execute("policy.list", arguments, permissions={"policy:read"})
    elif args.command == "policy" and args.action in {"evaluate", "simulate"}:
        arguments = {"policy_id": args.policy, "as_of": args.as_of}
        if args.action == "simulate":
            arguments["actions"] = _json_argument(args.actions)
        optional = {
            "known_as_of": args.known_as_of,
            "price_dataset_name": args.price_dataset,
            "price_dataset_version": args.price_version,
            "fx_dataset_name": args.fx_dataset,
            "fx_dataset_version": args.fx_version,
        }
        arguments.update({key: value for key, value in optional.items() if value is not None})
        output = registry.execute(
            "policy.evaluate" if args.action == "evaluate" else "policy.simulate",
            arguments,
            permissions={"policy:read", "portfolio:read", "market:read"},
        )
    elif args.command == "planning" and args.action in {"compare", "create"}:
        arguments = {
            "policy_id": args.policy,
            "as_of": args.as_of,
            "scenarios": _json_argument(args.scenarios),
        }
        if args.action == "create":
            arguments["name"] = args.name
            if args.created_at is not None:
                arguments["created_at"] = args.created_at
            if args.recorded_at is not None:
                arguments["recorded_at"] = args.recorded_at
        optional = {
            "known_as_of": args.known_as_of,
            "price_dataset_name": args.price_dataset,
            "price_dataset_version": args.price_version,
            "fx_dataset_name": args.fx_dataset,
            "fx_dataset_version": args.fx_version,
        }
        arguments.update({key: value for key, value in optional.items() if value is not None})
        output = registry.execute(
            "planning.compare" if args.action == "compare" else "planning.create",
            arguments,
            permissions={
                "planning:read" if args.action == "compare" else "planning:write",
                "policy:read",
                "portfolio:read",
                "market:read",
            },
            confirmed=args.action == "create",
        )
    elif args.command == "planning" and args.action == "list":
        arguments = {} if args.portfolio is None else {"portfolio_id": args.portfolio}
        output = registry.execute("planning.list", arguments, permissions={"planning:read"})
    elif args.command == "planning" and args.action == "get":
        output = registry.execute(
            "planning.get", {"plan_id": args.plan}, permissions={"planning:read"}
        )
    elif args.command == "decision" and args.action == "create":
        arguments = {
            "portfolio_id": args.portfolio,
            "title": args.title,
            "intent": args.intent,
            "rationale": args.rationale,
            "as_of": args.as_of,
            "alternatives": _json_argument(args.alternatives),
        }
        optional = {
            "known_as_of": args.known_as_of,
            "policy_version_id": args.policy_version,
            "plan_id": args.plan,
            "created_at": args.created_at,
            "recorded_at": args.recorded_at,
        }
        arguments.update({key: value for key, value in optional.items() if value is not None})
        output = registry.execute(
            "decision.create", arguments, permissions={"decision:write"}, confirmed=True
        )
    elif args.command == "decision" and args.action == "list":
        arguments = {} if args.portfolio is None else {"portfolio_id": args.portfolio}
        output = registry.execute("decision.list", arguments, permissions={"decision:read"})
    elif args.command == "decision" and args.action == "get":
        output = registry.execute(
            "decision.get", {"decision_id": args.decision}, permissions={"decision:read"}
        )
    elif args.command == "decision" and args.action in {"link-policy", "link-evidence", "link-transaction", "review"}:
        if args.action == "link-policy":
            capability = "decision.link_policy"
            arguments = {"decision_id": args.decision, "policy_version_id": args.policy_version, "link_type": args.link_type}
            permissions = {"decision:write", "policy:read"}
        elif args.action == "link-evidence":
            capability = "decision.link_evidence"
            arguments = {"decision_id": args.decision, "evidence_id": args.evidence, "evidence_kind": args.kind, "relation": args.relation}
            permissions = {"decision:write", "research:read"}
        elif args.action == "link-transaction":
            capability = "decision.link_transaction"
            arguments = {"decision_id": args.decision, "transaction_id": args.transaction, "relation": args.relation}
            if args.linked_at is not None:
                arguments["linked_at"] = args.linked_at
            permissions = {"decision:write", "ledger:read"}
        else:
            capability = "decision.review"
            arguments = {"decision_id": args.decision, "review_type": args.review_type, "notes": args.notes}
            if args.score is not None:
                arguments["score"] = args.score
            if args.reviewed_at is not None:
                arguments["reviewed_at"] = args.reviewed_at
            permissions = {"decision:write"}
        output = registry.execute(capability, arguments, permissions=permissions, confirmed=True)
    elif args.command == "research" and args.action == "ingest-text":
        output = registry.execute(
            "research.ingest_text",
            {
                "path": args.path,
                "title": args.title,
                "source_uri": args.source_uri,
                "known_at": args.known_at,
                "effective_at": args.effective_at,
                "media_type": args.media_type,
            },
            permissions={"research:write"},
            confirmed=True,
        )
    elif args.command == "research" and args.action == "document":
        output = registry.execute(
            "research.get_document",
            {"document_id": args.document},
            permissions={"research:read"},
        )
    elif args.command == "research" and args.action == "search":
        arguments = {"query": args.query}
        if args.as_of is not None:
            arguments["as_of"] = args.as_of
        if args.known_as_of is not None:
            arguments["known_as_of"] = args.known_as_of
        output = registry.execute(
            "research.search", arguments, permissions={"research:read"}
        )
    elif args.command == "research" and args.action == "claim":
        output = registry.execute(
            "research.add_claim",
            {
                "document_id": args.document,
                "claim_key": args.claim_key,
                "text": args.text,
                "span_start": args.span_start,
                "span_end": args.span_end,
                "known_at": args.known_at,
            },
            permissions={"research:write", "research:read"},
            confirmed=True,
        )
    elif args.command == "research" and args.action == "evidence":
        output = registry.execute(
            "research.add_evidence",
            {
                "document_id": args.document,
                "kind": args.kind,
                "text": args.text,
                "span_start": args.span_start,
                "span_end": args.span_end,
                "relation": args.relation,
                "known_at": args.known_at,
                "effective_at": args.effective_at,
            },
            permissions={"research:write"},
            confirmed=True,
        )
    elif args.command == "research" and args.action == "contradiction":
        output = registry.execute(
            "research.add_contradiction",
            {
                "claim_a_id": args.claim_a,
                "claim_b_id": args.claim_b,
                "kind": args.kind,
                "explanation": args.explanation,
                "known_at": args.known_at,
            },
            permissions={"research:write"},
            confirmed=True,
        )
    elif args.command == "research" and args.action == "thesis-create":
        output = registry.execute(
            "research.create_thesis",
            {
                "title": args.title,
                "initial_text": args.initial_text,
                "known_at": args.known_at,
            },
            permissions={"research:write"},
            confirmed=True,
        )
    elif args.command == "research" and args.action == "thesis-revise":
        output = registry.execute(
            "research.revise_thesis",
            {"thesis_id": args.thesis, "text": args.text, "known_at": args.known_at},
            permissions={"research:write"},
            confirmed=True,
        )
    elif args.command == "research" and args.action == "thesis":
        output = registry.execute(
            "research.get_thesis",
            {"thesis_id": args.thesis},
            permissions={"research:read"},
        )
    elif args.command == "research" and args.action == "link":
        output = registry.execute(
            "research.link",
            {
                "from_type": args.from_type,
                "from_id": args.from_id,
                "to_type": args.to_type,
                "to_id": args.to_id,
                "relation": args.relation,
                "known_at": args.known_at,
            },
            permissions={"research:write"},
            confirmed=True,
        )
    elif args.command == "research" and args.action == "trace":
        output = registry.execute(
            "research.trace",
            {
                "node_type": args.node_type,
                "node_id": args.node_id,
                "max_depth": args.max_depth,
            },
            permissions={"research:read"},
        )
    elif args.command == "system" and args.action == "check":
        output = registry.execute(
            "system.check_integrity", permissions={"system:read"}
        )
    elif args.command == "system" and args.action == "export":
        output = registry.execute(
            "system.export",
            {"path": args.path},
            permissions={"system:export"},
            confirmed=True,
        )
    elif args.command == "system" and args.action == "backup":
        output = registry.execute(
            "system.backup",
            {"path": args.path},
            permissions={"system:backup"},
            confirmed=True,
        )
    elif args.command == "capability" and args.action == "list":
        output = registry.describe()
    elif args.command == "capability" and args.action == "describe":
        output = registry.describe(args.name)
    else:
        output = registry.execute(
            args.name,
            json.loads(args.input),
            permissions=args.permission,
            confirmed=args.confirm,
            dry_run=args.dry_run,
        )
    print(json.dumps(output, default=str, sort_keys=True))
    return 0


if __name__ == "__main__":
    main()
