import argparse
import json

from .capabilities import build_core_registry
from .store import Store


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
