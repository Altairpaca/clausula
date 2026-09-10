from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from clausula.adapters.schema_preflight import inspect_database_schema
from clausula.adapters.sqlite import SCHEMA


def default_home() -> Path:
    return Path(os.environ.get("CLAUSULA_HOME", Path.home() / ".clausula"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect Clausula schema compatibility without opening the writable Store."
    )
    parser.add_argument(
        "--home",
        type=Path,
        default=None,
        help="CLAUSULA_HOME containing clausula.db (defaults to environment/~/.clausula).",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=None,
        help="Inspect an explicit SQLite database path instead of <home>/clausula.db.",
    )
    args = parser.parse_args(argv)
    home = (args.home or default_home()).expanduser()
    database = args.database.expanduser() if args.database is not None else home / "clausula.db"

    report = inspect_database_schema(database, baseline_sql=SCHEMA)
    print(json.dumps(report.as_dict(), sort_keys=True, indent=2))
    return 0 if report.compatible else 2


if __name__ == "__main__":
    raise SystemExit(main())
