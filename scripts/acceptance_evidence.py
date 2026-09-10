from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from clausula.acceptance import (
    ACCEPTANCE_EVIDENCE_FORMAT,
    ACCEPTANCE_SET_FORMAT,
    AcceptanceEvidenceError,
    combine_acceptance_evidence,
    verify_acceptance_evidence,
    verify_acceptance_set,
)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AcceptanceEvidenceError(f"{path}: evidence document must be a JSON object")
    return value


def _verification(document: dict[str, Any]) -> dict[str, Any]:
    if document.get("format") == ACCEPTANCE_EVIDENCE_FORMAT:
        return verify_acceptance_evidence(document)
    if document.get("format") == ACCEPTANCE_SET_FORMAT:
        return verify_acceptance_set(document)
    return {"valid": False, "errors": ["unsupported acceptance evidence format"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify or combine sanitized Clausula local-acceptance evidence."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    verify_parser = subparsers.add_parser("verify", help="Verify evidence digests/contracts.")
    verify_parser.add_argument("paths", nargs="+", type=Path)

    combine_parser = subparsers.add_parser(
        "combine", help="Combine evidence reports bound to one repository commit."
    )
    combine_parser.add_argument("paths", nargs="+", type=Path)
    combine_parser.add_argument("--output", type=Path, default=None)

    args = parser.parse_args(argv)
    try:
        if args.command == "verify":
            valid = True
            results = []
            for path in args.paths:
                document = _load(path)
                verification = _verification(document)
                results.append({"path": str(path), **verification})
                valid = valid and verification["valid"]
            print(json.dumps(results, sort_keys=True, indent=2))
            return 0 if valid else 2

        reports = [_load(path) for path in args.paths]
        combined = combine_acceptance_evidence(reports)
        rendered = json.dumps(combined, sort_keys=True, indent=2) + "\n"
        if args.output is None:
            sys.stdout.write(rendered)
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        return 0
    except (AcceptanceEvidenceError, OSError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
