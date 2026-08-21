"""The SYNTHETIC NoPlan instance (Decision 12) — clearly labelled, never the frozen instance.

The frozen V1 instance is always solvable under full observability, so `:266`'s required
"`NoPlan` case where the symbolic abstraction has one" is exercised by THIS purpose-built
instance instead: a single-agent universe with the heavy box still pending. `CooperativePush`
requires two distinct agents (`different(a1, a2)` — and the pair is not even GROUNDABLE with one
agent), so `delivered(box_0)` is symbolically unreachable and the planner must return `NoPlan`.

This is a synthetic TEST instance for the `NoPlan → orchestrator` path (:128). It is not part of
the frozen domain, it never touches the backend, and nothing in it may leak into the shipping
initial state.
"""
from __future__ import annotations

from typing import FrozenSet, Tuple

from domain.box_push_v1 import AGENT_0, BOX_HEAVY, DELIVERY_ZONE, DOMAIN_IR
from shared.symbolic_state import GroundedLiteral, SymbolicState

from symbolic.planner import Universe


def noplan_instance() -> Tuple[SymbolicState, FrozenSet[GroundedLiteral], Universe]:
    """(state, goal, universe) for the unsolvable single-agent heavy-box instance."""
    box = str(BOX_HEAVY)
    state = SymbolicState.of((
        GroundedLiteral("discovered", (box,)),
        GroundedLiteral("pending", (box,)),
        GroundedLiteral("heavy", (box,)),
        # deliberately NO `different` facts and only one agent in the universe below
    ))
    goal = frozenset({GroundedLiteral("delivered", (box,))})
    universe = Universe(agents=(AGENT_0,), boxes=(BOX_HEAVY,), zone=DELIVERY_ZONE)
    return state, goal, universe


__all__ = ["noplan_instance", "DOMAIN_IR"]
