from __future__ import annotations

import argparse
import json

from clausula.application.ledger_import import parse_csv_import


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate and preview a Clausula ledger CSV without opening a Store."
    )
    parser.add_argument("csv", help="path to the ledger CSV")
    parser.add_argument(
        "--recorded-at",
        help="optional ISO-8601 knowledge cutoff used for deterministic preview fixtures",
    )
    args = parser.parse_args()

    plan = parse_csv_import(args.csv, recorded_at=args.recorded_at)
    print(json.dumps(plan.as_dict(), ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if plan.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
