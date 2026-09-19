"""Domain `lamp` — the symbolic model (SYMBOLIC-side module: imports stdlib, shared, kit,
and sibling modules only; NEVER `environment`, `app`, `runtime`, or a backend).

The model is deliberately OPTIMISTIC: `applicable` and `plan` decide from the symbolic
state alone. A call the model admits may still fail in the environment — that failure is
typed evidence the runtime reports, never a reason to consult the environment here.

What you write (the kit derives plan/ground/evaluate/predict/monitor from it):

    project(state)         authoritative -> symbolic state (leave geometry/detail behind)
    apply(sym, call)       the deterministic INTENDED effect
    applicable(sym, call)  the typed verdict: ValidatedCall or SymbolicallyInapplicable
    plan(sym, identities)  PlanFound / NoPlan / PlannerFailure — `bfs_plan` does the search
    apply_world(state, call)  optional: the intended effect on the AUTHORITATIVE state, so
                           the monitor can also compare what the world did
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, FrozenSet

from kit import bfs_plan, symbolic_key
from shared.comparison_keys import SymbolicKey
from shared.planner_result import PlannerResult
from shared.skills import CallValidation, SymbolicallyInapplicable, ValidatedCall
from shared.versioning import ModelVersion

from .types import Call, Op, State

MODEL_VERSION = ModelVersion(revision=0, label="lamp-v0")   # TODO(author): bump on change


@dataclass(frozen=True, slots=True)
class SymbolicState:
    """TODO(author): the symbolic view the planner reasons over."""
    lit: FrozenSet[str]

    def canonical(self) -> Dict[str, Any]:
        return {"lit": sorted(self.lit)}

    def symbolic_key(self) -> SymbolicKey:
        return symbolic_key(self.canonical())


class Model:
    """The `kit.SymbolicModel` for this domain."""

    @property
    def model_version(self) -> ModelVersion:
        return MODEL_VERSION

    def project(self, state: State, /) -> SymbolicState:
        # TODO(author): derive the symbolic state from the authoritative one — `stuck` is
        # deliberately dropped here: the model stays optimistic about every switch
        return SymbolicState(lit=state.lit)

    def apply(self, sym: SymbolicState, call: Call, /) -> SymbolicState:
        # TODO(author): the deterministic intended effect of each action
        if call.op is Op.TURN_ON:
            return SymbolicState(lit=sym.lit | {call.lamp_id})
        if call.op is Op.TURN_OFF:
            return SymbolicState(lit=sym.lit - {call.lamp_id})
        return sym                                  # Nudge: no symbolic effect

    def applicable(self, sym: SymbolicState, call: Call, /) -> CallValidation:
        # TODO(author): preconditions over the SYMBOLIC state only (optimistic by design):
        # the model does not know a switch can be stuck — that is the environment's truth
        if call.op is Op.TURN_ON and call.lamp_id in sym.lit:
            return SymbolicallyInapplicable(reason=f"{call}: already lit", call=call,
                                            unsatisfied=("not lit",))
        if call.op is Op.TURN_OFF and call.lamp_id not in sym.lit:
            return SymbolicallyInapplicable(reason=f"{call}: already dark", call=call,
                                            unsatisfied=("lit",))
        return ValidatedCall(call=call)

    def plan(self, sym: SymbolicState, identities: FrozenSet[str], /) -> PlannerResult:
        # TODO(author): the goal test and the candidate calls (enumerated from identities)
        candidates = [Call(op, lamp) for lamp in sorted(identities) for op in (Op.TURN_ON, Op.TURN_OFF)]
        return bfs_plan(
            sym, is_goal=lambda s: identities <= s.lit, candidates=candidates,
            applicable=self.applicable, apply=self.apply, model_version=MODEL_VERSION,
        )

    def apply_world(self, state: State, call: Call, /) -> State:
        # TODO(author): the intended effect on the authoritative state (optional but
        # recommended: it lets the monitor compare the world basis too)
        stuck = state.stuck - {call.lamp_id} if call.op is Op.NUDGE else state.stuck
        return State(state.lamps, lit=self.apply(self.project(state), call).lit, stuck=stuck,
                     tick=state.tick)


MODEL = Model()

__all__ = ["MODEL", "MODEL_VERSION", "Model", "SymbolicState"]
