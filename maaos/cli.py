"""`python -m maaos ...` — the domain-kit command line (DK3).

    python -m maaos validate-domain <name> [--budget N]   author-facing connection check
    python -m maaos list-domains                          the names in domains/registry.py

Names resolve through the static `domains.registry.REGISTRY` and nowhere else: no
directory scanning, no dynamic import (the import guard forbids it in this package). Exit
status: 0 when no check FAILED, 1 otherwise, 2 for a usage error.

`create-domain` arrives in DK4.
"""
from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

from app.validation import validate_named
from domains.registry import REGISTRY


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m maaos", description=(__doc__ or "").splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate-domain", help="check that a registered domain is correctly connected")
    validate.add_argument("name", help="the key in domains/registry.py")
    validate.add_argument("--budget", type=int, default=50,
                          help="executive-step budget for the bounded validation episodes (default 50)")
    sub.add_parser("list-domains", help="print the registered domain names")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "list-domains":
        for name in sorted(REGISTRY):
            print(name)
        return 0
    if args.command == "validate-domain":
        if args.budget <= 0:
            print("--budget must be positive", file=sys.stderr)
            return 2
        report = validate_named(args.name, REGISTRY, executive_budget=args.budget)
        print(report.render())
        return 0 if report.ok else 1
    return 2


__all__ = ["main"]
