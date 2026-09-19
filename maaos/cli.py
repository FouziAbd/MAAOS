"""`python -m maaos ...` — the domain-kit command line (DK3).

    python -m maaos create-domain <name> [--target DIR]   generate a runnable domain skeleton
    python -m maaos validate-domain <name> [--budget N]   author-facing connection check
    python -m maaos list-domains                          the names in domains/registry.py

Names resolve through the static `domains.registry.REGISTRY` and nowhere else: no
directory scanning, no dynamic import (the import guard forbids it in this package). Exit
status: 0 when no check FAILED, 1 otherwise, 2 for a usage error.

`create-domain` writes new files only and prints the registry lines to add by hand.
"""
from __future__ import annotations

import argparse
import pathlib
import sys
from typing import Optional, Sequence

from app.validation import author_frame, validate_named
from maaos.scaffold import ScaffoldError, create_domain


def _registry():
    """`domains.registry.REGISTRY`, or an author-facing message when a registered domain
    cannot be imported (it is half-edited): the CLI must stay usable for every other domain."""
    try:
        from domains.registry import REGISTRY
    except Exception as error:                      # noqa: BLE001 — reported, not raised
        where = author_frame(error)
        raise SystemExit(
            f"domains/registry.py could not be imported: {type(error).__name__}: {error}"
            f"{where}\n  a registered domain is broken or half-edited (its types.py, model.py, "
            f"environment.py and __init__.py must agree); fix it, or temporarily remove its two "
            f"lines from domains/registry.py"
        ) from error
    return REGISTRY


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m maaos", description=(__doc__ or "").splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate-domain", help="check that a registered domain is correctly connected")
    validate.add_argument("name", help="the key in domains/registry.py")
    validate.add_argument("--budget", type=int, default=50,
                          help="executive-step budget for the bounded validation episodes (default 50)")
    sub.add_parser("list-domains", help="print the registered domain names")
    create = sub.add_parser("create-domain", help="generate a runnable domain skeleton (new files only)")
    create.add_argument("name", help="a lowercase Python identifier, e.g. warehouse")
    create.add_argument("--target", default=None,
                        help="write the package here instead of domains/<name>/ (repo-relative)")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "list-domains":
        for name in sorted(_registry()):
            print(name)
        return 0
    if args.command == "create-domain":
        try:
            created = create_domain(
                args.name, registered=_registry(),
                target=pathlib.Path(args.target) if args.target else None,
            )
        except ScaffoldError as error:
            print(f"create-domain: {error}", file=sys.stderr)
            return 1
        print(created.next_steps())
        return 0
    if args.command == "validate-domain":
        if args.budget <= 0:
            print("--budget must be positive", file=sys.stderr)
            return 2
        report = validate_named(args.name, _registry(), executive_budget=args.budget)
        print(report.render())
        return 0 if report.ok else 1
    return 2


__all__ = ["main"]
