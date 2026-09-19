"""Content-addressed keys for domain value types (DK2).

Extracted from the two existing implementations, which compute their keys identically:
`shared/state_snapshot.py::StateSnapshot.world_key` (sha256 of the canonical JSON, sorted
keys, compact separators) and `tests/probe_counter.py::_digest`. A domain author writes
`canonical()` once and derives both keys from it:

    def world_key(self) -> WorldKey:       return world_key(self.canonical())
    def symbolic_key(self) -> SymbolicKey: return symbolic_key(self.canonical())

Keying discipline (from `shared/value_contracts.py::RuntimeState`): the payload must be the
WORLD content only — episode bookkeeping (tick counters, step counts) is excluded so two
attempts from the same situation share a key.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from shared.comparison_keys import SymbolicKey, WorldKey


def digest(payload: Mapping[str, Any]) -> str:
    """sha256 hex of the canonical JSON form of `payload` (sorted keys, compact)."""
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def world_key(payload: Mapping[str, Any]) -> WorldKey:
    """The authoritative-state key (Decision 13 world basis)."""
    return WorldKey(digest(payload))


def symbolic_key(payload: Mapping[str, Any]) -> SymbolicKey:
    """The symbolic-projection key (Decision 13 symbolic basis)."""
    return SymbolicKey(digest(payload))


__all__ = ["digest", "symbolic_key", "world_key"]
