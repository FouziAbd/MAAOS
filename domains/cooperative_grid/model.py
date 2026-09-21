"""Domain `cooperative_grid` — the symbolic model (SYMBOLIC-side module: imports stdlib,
shared, kit, and sibling modules only; NEVER `environment`, `app`, `runtime`, or a backend).

The model is deliberately OPTIMISTIC. It reasons over symbolic poses only:

    at[agent]   one of handle_left / handle_right / goal / hall     (no coordinates)
    door_open   whether the heavy door is open

It does NOT know whether the door is jammed — `project()` drops `State.door.jammed` — so
`CooperateOpen` is applicable whenever both agents stand at the two handles and the door is
closed. When the door is jammed the environment refuses the pull; the runtime reports that as
an ExecutionDiscrepancy. Nothing here consults the environment, the grid, or a path.

    project(state)         authoritative -> symbolic (cells become place names; the jam is gone)
    apply(sym, call)       the deterministic INTENDED effect
    applicable(sym, call)  preconditions over the symbolic state only
    plan(sym, identities)  breadth-first search over the calls enumerated from the state

`apply_world` is not declared: a place is a REGION (three goal cells) and the model does not
know which cell the backend will pick, so the monitor compares the symbolic basis only.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, List, Tuple

from kit import bfs_plan, symbolic_key
from shared.comparison_keys import SymbolicKey
from shared.planner_result import PlannerResult
from shared.skills import CallValidation, SymbolicallyInapplicable, ValidatedCall
from shared.versioning import ModelVersion

from .types import GOAL, HALL, HANDLES, Call, Op, State

MODEL_VERSION = ModelVersion(revision=1, label="cooperative_grid-v1")


@dataclass(frozen=True, slots=True)
class SymbolicState:
    """The symbolic view the planner reasons over: who is at which named place, and whether
    the door is open. Object kinds travel with the state so `plan` can type its candidates."""
    agents: Tuple[str, ...]                # sorted agent names
    places: Tuple[str, ...]                # sorted place names one can Goto
    door: str
    at: Tuple[Tuple[str, str], ...]        # (agent, place-or-HALL), sorted by agent
    door_open: bool

    def canonical(self) -> Dict[str, Any]:
        return {"at": dict(self.at), "door_open": self.door_open,
                "agents": list(self.agents), "places": list(self.places), "door": self.door}

    def symbolic_key(self) -> SymbolicKey:
        return symbolic_key(self.canonical())

    def where(self, agent: str) -> str:
        return dict(self.at).get(agent, HALL)

    def moved(self, agent: str, place: str) -> "SymbolicState":
        at = tuple(sorted(((a, place if a == agent else p) for a, p in self.at)))
        return SymbolicState(self.agents, self.places, self.door, at, self.door_open)


def _reject(call: Call, reason: str, *unsatisfied: str) -> SymbolicallyInapplicable:
    return SymbolicallyInapplicable(reason=f"{call}: {reason}", call=call,
                                    unsatisfied=tuple(unsatisfied))


class Model:
    """The `kit.SymbolicModel` for this domain."""

    @property
    def model_version(self) -> ModelVersion:
        return MODEL_VERSION

    def project(self, state: State, /) -> SymbolicState:
        # cells -> place names; the door's jam is deliberately left behind
        agents = tuple(sorted(a.name for a in state.agents))
        places = tuple(sorted(p.name for p in state.places))
        at = tuple(sorted((a.name, state.place_of(a.name)) for a in state.agents))
        return SymbolicState(agents=agents, places=places, door=state.door.name, at=at,
                             door_open=state.door.is_open)

    def apply(self, sym: SymbolicState, call: Call, /) -> SymbolicState:
        if call.op is Op.GOTO:
            return sym.moved(call.agent, call.target)
        if call.op is Op.COOPERATE_OPEN:
            return SymbolicState(sym.agents, sym.places, sym.door, sym.at, door_open=True)
        return sym                                     # ClearJam: no symbolic effect

    def applicable(self, sym: SymbolicState, call: Call, /) -> CallValidation:
        if call.agent not in sym.agents:
            return _reject(call, f"{call.agent} is not an agent", "agent(agent)")
        if call.op is Op.GOTO:
            if call.partner is not None:
                return _reject(call, "Goto takes no partner", "no partner")
            if call.target not in sym.places:
                return _reject(call, f"{call.target} is not a place", "place(target)")
            if sym.where(call.agent) == call.target:
                return _reject(call, "already there", "not at(agent, target)")
            if call.target == GOAL and not sym.door_open:
                return _reject(call, "the door is closed", "door_open")
            if call.target in HANDLES and any(
                p == call.target and a != call.agent for a, p in sym.at
            ):
                return _reject(call, f"{call.target} is taken", "free(target)")
            return ValidatedCall(call=call)
        if call.target != sym.door:
            return _reject(call, f"{call.target} is not the door", "door(target)")
        if sym.door_open:
            return _reject(call, "the door is already open", "not door_open")
        if call.op is Op.COOPERATE_OPEN:
            if call.partner is None or call.partner == call.agent:
                return _reject(call, "needs a distinct partner", "partner")
            if call.partner not in sym.agents:
                return _reject(call, f"{call.partner} is not an agent", "agent(partner)")
            if {sym.where(call.agent), sym.where(call.partner)} != set(HANDLES):
                return _reject(call, "both handles must be held", "at(agent, handle_left)",
                               "at(partner, handle_right)")
            return ValidatedCall(call=call)
        # ClearJam: the agent shakes the door from a handle; no symbolic effect
        if call.partner is not None:
            return _reject(call, "ClearJam takes no partner", "no partner")
        if sym.where(call.agent) not in HANDLES:
            return _reject(call, "must stand at a handle", "at(agent, handle)")
        return ValidatedCall(call=call)

    def plan(self, sym: SymbolicState, identities: FrozenSet[str], /) -> PlannerResult:
        agents = [a for a in sym.agents if a in identities]
        places = [p for p in sym.places if p in identities]
        candidates: List[Call] = [Call(Op.GOTO, a, p) for a in agents for p in places]
        if sym.door in identities:
            candidates += [Call(Op.COOPERATE_OPEN, a, sym.door, partner=b)
                           for i, a in enumerate(agents) for b in agents[i + 1:]]
            candidates += [Call(Op.CLEAR_JAM, a, sym.door) for a in agents]
        return bfs_plan(
            sym, is_goal=lambda s: bool(s.at) and all(p == GOAL for _, p in s.at),
            candidates=candidates, applicable=self.applicable, apply=self.apply,
            model_version=MODEL_VERSION,
        )


MODEL = Model()

__all__ = ["MODEL", "MODEL_VERSION", "Model", "SymbolicState"]
