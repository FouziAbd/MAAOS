"""The V1 classical planner: deterministic breadth-first search over the frozen skill IR.

Returns EXACTLY one of the frozen trio (`.claude/rules/symbolic-model.md`):

    PlanFound(plan)      — a sequence of `GroundedSkillCall`s, i.e. the SAME executive vocabulary
                           the executor consumes (supervisor P2 deliverable; nothing to translate)
    NoPlan(reason)       — the search space is exhausted: a legitimate SYMBOLIC result
    PlannerFailure(...)  — the computation failed (budget/exception): infrastructure material,
                           converted to a fault by the runtime path, never here

DECLARATIVE ONLY: expansion is `evaluate` + `apply_effects` over literals. No geometry, no
reachability, no distances, no backend — the plan may be optimistic, and a symbolically valid
step failing in the backend is the designed `ExecutionDiscrepancy` signal, not a planner bug.

Determinism: grounding and expansion order are fully sorted, so the same (state, goal) always
yields the same plan — the recorded `.soln` artifact is reproducible byte-for-byte.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from itertools import permutations
from typing import FrozenSet, Optional, Tuple

from shared.ids import AgentId, BoxId, ZoneId
from shared.planner_result import NoPlan, PlanFound, PlannerFailure, PlannerResult
from shared.skill_ir import DomainIR
from shared.skills import GroundedSkillCall, ParameterType, ValidatedCall
from shared.symbolic_state import GroundedLiteral, SymbolicState
from shared.versioning import ModelVersion

from symbolic.applicability import apply_effects, evaluate

#: Search budget: expanded-node cap. The frozen instance's reachable space is tiny (tens of
#: states); the cap exists so a degenerate future instance yields a typed PlannerFailure
#: (timed_out) instead of a hang. It is a COMPUTATION budget, never a feasibility judgement.
_NODE_BUDGET = 100_000


@dataclass(frozen=True)
class Universe:
    """The grounding universe: which identities exist. Explicit, never inferred from literals —
    the synthetic NoPlan instance (Decision 12) exists precisely because a one-agent universe
    makes `CooperativePush` ungroundable."""
    agents: Tuple[AgentId, ...]
    boxes: Tuple[BoxId, ...]
    zone: ZoneId

    @classmethod
    def from_snapshot(cls, snapshot, zone: ZoneId) -> "Universe":
        return cls(
            agents=tuple(sorted((a.agent_id for a in snapshot.agents), key=lambda x: x.value)),
            boxes=tuple(sorted((b.box_id for b in snapshot.boxes), key=lambda x: x.value)),
            zone=zone,
        )


def ground_calls(domain: DomainIR, universe: Universe) -> Tuple[GroundedSkillCall, ...]:
    """Every grounded call of every symbolic-action-set skill, deterministically ordered.

    Agent-pair skills ground over ordered pairs and collapse through `GroundedSkillCall`'s
    canonical pair ordering (the same collapse `SkillIR.unbind` performs for a planner emitting
    both `(a0,a1)` and `(a1,a0)` — `different` is symmetric)."""
    calls = []
    seen = set()
    for ir in domain.skills:
        signature = ir.signature
        agent_slots = [p for p in signature.parameters
                       if p.type in (ParameterType.AGENT, ParameterType.AGENT_PAIR)]
        needs_pair = any(p.type is ParameterType.AGENT_PAIR for p in agent_slots)
        needs_box = any(p.type is ParameterType.BOX for p in signature.parameters)
        if needs_pair:
            agent_choices = list(permutations(universe.agents, 2))
        else:
            agent_choices = [(a,) for a in universe.agents]
        box_choices = list(universe.boxes) if needs_box else [None]
        for agents in agent_choices:
            for box in box_choices:
                call = GroundedSkillCall(
                    skill=signature.name, agents=tuple(agents), box=box, zone=universe.zone,
                )
                if call.key() not in seen:
                    seen.add(call.key())
                    calls.append(call)
    calls.sort(key=lambda c: (str(c.skill), c.key()))
    return tuple(calls)


def _goal_satisfied(state: SymbolicState, goal: FrozenSet[GroundedLiteral]) -> bool:
    return all(state.holds(literal) for literal in goal)


def plan(
    domain: DomainIR,
    state: SymbolicState,
    goal: FrozenSet[GroundedLiteral],
    universe: Universe,
    model_version: Optional[ModelVersion] = None,
    node_budget: int = _NODE_BUDGET,
) -> PlannerResult:
    """Breadth-first search from `state` to any state satisfying `goal`."""
    try:
        goal = frozenset(goal)
        if _goal_satisfied(state, goal):
            return PlanFound(plan=(), model_version=model_version)
        grounded = ground_calls(domain, universe)
        if not grounded and goal:
            return NoPlan(reason="no groundable symbolic action in this universe")

        start = frozenset(state.literals)
        frontier = deque([(start, ())])
        visited = {start}
        expanded = 0
        while frontier:
            literals, prefix = frontier.popleft()
            expanded += 1
            if expanded > node_budget:
                return PlannerFailure(
                    error=f"node budget {node_budget} exceeded after {len(visited)} states",
                    timed_out=True,
                )
            current = SymbolicState(literals)
            for call in grounded:
                verdict = evaluate(domain, current, call)
                if not isinstance(verdict, ValidatedCall):
                    continue
                successor = apply_effects(current, domain.skill(call.skill), call)
                key = frozenset(successor.literals)
                if key in visited:
                    continue
                steps = prefix + (call,)
                if _goal_satisfied(successor, goal):
                    return PlanFound(plan=steps, model_version=model_version)
                visited.add(key)
                frontier.append((key, steps))
        return NoPlan(
            reason=f"search space exhausted: {len(visited)} reachable symbolic states, "
                   f"none satisfies the goal"
        )
    except Exception as error:                           # any computation failure is typed
        return PlannerFailure(error=f"{type(error).__name__}: {error}")
