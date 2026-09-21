"""The explicit domain registry — the one file an author edits by hand to register a domain.

    from domains.<name> import DOMAIN as _<NAME>        # beside the other imports
    REGISTRY = MappingProxyType({..., "<name>": _<NAME>})  # one entry per domain

Consumers resolve names here and nowhere else: no directory scanning, no dynamic import,
no plugin discovery (report Phase 4 default assumptions; ADR-R4 rejected registration hooks).
The CLI (reserved: DK3 adds `validate-domain`, DK4 adds `create-domain`) will look names up
here and print — never write — the registration line.
"""
from __future__ import annotations

from types import MappingProxyType
from typing import Any, Mapping

from app.domain_package import DomainPackage

from domains.box_push import DOMAIN as _BOX_PUSH
from domains.cooperative_grid import DOMAIN as _COOPERATIVE_GRID

REGISTRY: Mapping[str, DomainPackage[Any, Any, Any, Any, Any]] = MappingProxyType({
    "box_push": _BOX_PUSH,
    "cooperative_grid": _COOPERATIVE_GRID,
})

__all__ = ["REGISTRY"]
