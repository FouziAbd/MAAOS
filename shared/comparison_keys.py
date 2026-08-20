"""Distinct types for the monitor's two comparison keys (P0_V1_DECISIONS Decision 13.6).

Both keys are sha256 hex, so as plain `str` they are indistinguishable — and "a symbolic key is
never written into a `*_world_key` field" was enforced by nothing but a docstring. An adversarial
review flagged that a P1/P2 monitor could reintroduce exactly the confusion Decision 13 exists to
prevent, with every test still green.

These subclass `str`, so equality, hashing, dict keys and `json.dumps` behave identically and no
existing comparison changes. What they add is an `isinstance` check the contract types can enforce.
"""
from __future__ import annotations


class ComparisonKey(str):
    """Base for a digest that identifies a state under ONE comparison basis."""
    __slots__ = ()


class WorldKey(ComparisonKey):
    """Digest of the canonical WORLD state — `StateSnapshot.world_key()`."""
    __slots__ = ()


class SymbolicKey(ComparisonKey):
    """Digest of a monitored SYMBOLIC projection — `ProjectionContract.monitored_key()`."""
    __slots__ = ()
