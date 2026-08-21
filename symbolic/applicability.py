"""Classical applicability and deterministic effect application over `SymbolicState` literals.

DECLARATIVE ONLY (Decision 6 / supervisor :55): applicability is literal membership against the
frozen `SkillIR` preconditions — no geometry, no reachability, no backend consultation, and
structurally no way to acquire any (this module may not import the predictor, the monitor, the
backend, or `runtime`; guarded statically).

`apply_effects` is the ONE deterministic successor function, shared by the planner (search) and
the symbolic predictor (prediction) so they cannot drift apart.
"""
from __future__ import annotations

from typing import Tuple

from shared.skill_ir import DomainIR, SkillIR
from shared.skills import (
    CallValidation,
    GroundedSkillCall,
    OutsideSymbolicModel,
    SymbolicallyInapplicable,
    ValidatedCall,
)
from shared.symbolic_state import GroundedLiteral, SymbolicState


def ground_literals(ir: SkillIR, call: GroundedSkillCall, predicates) -> Tuple[GroundedLiteral, ...]:
    """Ground lifted predicates through the frozen `SkillIR.bind` — the single sanctioned
    binding path (Decision 11), so the planner, predictor and monitor share one grounding."""
    binding = ir.bind(call)
    return tuple(
        GroundedLiteral(str(p.name), tuple(binding[a] for a in p.args)) for p in predicates
    )


def evaluate(
    domain: DomainIR, state: SymbolicState, call: GroundedSkillCall
) -> CallValidation:
    """Symbolic applicability verdict for a grounded call against a symbolic state.

    Returns exactly one of the frozen validation outcomes:
      - `ValidatedCall`            — every precondition literal holds.
      - `SymbolicallyInapplicable` — some precondition fails (listed). A SYMBOLIC-track result,
        never an infrastructure fault (Decision 7).
      - `OutsideSymbolicModel`     — registry-valid skill with no symbolic model (Explore/Wait,
        Decision 15). Executable, but nothing here can predict it.
    """
    resolved = domain.resolve(call.skill)
    if isinstance(resolved, OutsideSymbolicModel):
        return resolved
    unsatisfied = tuple(
        literal.canonical()
        for literal in ground_literals(resolved, call, resolved.preconditions)
        if not state.holds(literal)
    )
    if unsatisfied:
        return SymbolicallyInapplicable(
            reason=f"{call.skill}: preconditions not satisfied", call=call,
            unsatisfied=unsatisfied,
        )
    return ValidatedCall(call=call)


def apply_effects(
    state: SymbolicState, ir: SkillIR, call: GroundedSkillCall
) -> SymbolicState:
    """The deterministic V1 successor: add positive effect literals, delete negative ones.
    Implicit frame conditions — every unmentioned literal is unchanged (`shared/skill_ir.py`)."""
    literals = set(state.literals)
    binding = ir.bind(call)
    for effect in ir.effects:
        literal = GroundedLiteral(
            str(effect.predicate.name),
            tuple(binding[a] for a in effect.predicate.args),
        )
        if effect.positive:
            literals.add(literal)
        else:
            literals.discard(literal)
    return SymbolicState.of(literals)
