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
