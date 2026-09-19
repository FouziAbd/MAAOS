"""Kit-local structural protocols (DK2) — what the kit's defaults need from a domain's own
value types, over and above the runtime's `shared/value_contracts.py` protocols.

These are deliberately NOT added to `shared/value_contracts.py`: that module's member set
is what EVERY domain must supply for the runtime, and widening it needs a runtime
requirement. The kit's defaults are optional, so their extra members live here.

    Identified      identities() -> frozenset[str]     the objects a state HAS / a call NAMES
                    (both existing domains check grounding by identity membership:
                    `box_push_v1_adapter.py::_resolve_identities`, `app/box_push_v1.py::
                    BoxPushDomainServices.ground`, `tests/probe_counter.py` env + services)
    SymbolicKeyed   symbolic_key() -> SymbolicKey       the symbolic-basis key of a symbolic
                    state (`ProjectionContract.monitored_key` for BoxPush, `CounterSymbolicState.
                    symbolic_key` for the probe)

`ground_by_identity` is the ONE grounding check, written once and used by both the
environment base and the derived services (§1.4 of the plan: today it is written twice per
domain). It is identity membership ONLY — never a feasibility test.
"""
from __future__ import annotations

from typing import FrozenSet, Optional, Protocol, runtime_checkable

from shared.comparison_keys import SymbolicKey
from shared.skills import UngroundedCall
from shared.value_contracts import RuntimeCall, RuntimeState


@runtime_checkable
class Identified(Protocol):
    """A value that names identities: a state names the objects that exist, a call names
    the objects it acts on."""

    def identities(self) -> FrozenSet[str]:
        ...


@runtime_checkable
class SymbolicKeyed(Protocol):
    """A symbolic state with a content-addressed symbolic-basis key."""

    def symbolic_key(self) -> SymbolicKey:
        ...


class IdentifiedState(RuntimeState, Identified, Protocol):
    """An authoritative state usable by the kit: the runtime protocol plus `identities()`."""


class IdentifiedCall(RuntimeCall, Identified, Protocol):
    """A grounded call usable by the kit: the runtime protocol plus `identities()`."""


def ground_by_identity[CallT: IdentifiedCall](
    state: IdentifiedState, call: CallT, /
) -> Optional[UngroundedCall[CallT]]:
    """The typed rejection when the call names an identity the state lacks, else None.

    Identity membership only: this function must never grow a reachability, occupancy or
    feasibility test (P0 Decision 6; `box_push_v1_adapter.py::_resolve_identities`
    docstring: "NEVER a feasibility gate").
    """
    missing = call.identities() - state.identities()
    if missing:
        return UngroundedCall(
            reason=f"unknown identity {', '.join(sorted(missing))} in {call}", call=call
        )
    return None


__all__ = [
    "Identified",
    "IdentifiedCall",
    "IdentifiedState",
    "SymbolicKeyed",
    "ground_by_identity",
]
