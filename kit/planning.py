"""Breadth-first symbolic planning (DK2) — extracted from `symbolic/planner.py::plan`
(BoxPush; the R5 probe plans in closed form, so this helper is "extracted from BoxPush",
not an intersection — recorded in `docs/decisions/DK1_DOMAIN_PACKAGE.md` §"DK2 — kit
extraction record").

It reproduces the frozen planner's result categories one for one, which is exactly where
a domain author is likely to get the typed planner contract wrong:

    goal already satisfied           -> PlanFound(())                 (`planner.py:104-105`)
    no candidate call at all         -> NoPlan                        (`:106-108`)
    node budget exceeded             -> PlannerFailure(timed_out=True) (`:117-121`)
    frontier exhausted, no goal      -> NoPlan                        (`:136-139`)
    any exception during the search  -> PlannerFailure                (`:140-141`)

`NoPlan` is a SEMANTIC answer; `PlannerFailure` follows the infrastructure-fault path.

The search sees the author's SYMBOLIC state only: the signature has no authoritative state
and no environment. `candidates` is the grounded call universe the caller enumerated from
identities — it must be DETERMINISTICALLY ORDERED (the frozen planner sorts its grounded
calls; the plan found depends on expansion order); `applicable` and `apply` are the author's
symbolic transition. Visited states are keyed by `symbolic_key()` (kit `SymbolicKeyed`).
"""
from __future__ import annotations

from collections import deque
from typing import Callable, Iterable, Optional, TypeVar

from kit.protocols import SymbolicKeyed
from shared.planner_result import NoPlan, PlanFound, PlannerFailure, PlannerResult
from shared.skills import ValidatedCall
from shared.value_contracts import RuntimeCall
from shared.versioning import ModelVersion

SymbolicStateT = TypeVar("SymbolicStateT", bound=SymbolicKeyed)
CallT = TypeVar("CallT", bound=RuntimeCall)

#: The frozen planner's default budget (`symbolic/planner.py::_NODE_BUDGET`).
NODE_BUDGET = 100_000


def bfs_plan(
    start: SymbolicStateT,
    *,
    is_goal: Callable[[SymbolicStateT], bool],
    candidates: Iterable[CallT],
    applicable: Callable[[SymbolicStateT, CallT], object],
    apply: Callable[[SymbolicStateT, CallT], SymbolicStateT],
    model_version: Optional[ModelVersion] = None,
    node_budget: int = NODE_BUDGET,
) -> PlannerResult:
    """Breadth-first search from `start` to any state satisfying `is_goal`."""
    try:
        if is_goal(start):
            return PlanFound(plan=(), model_version=model_version)
        grounded = tuple(candidates)
        if not grounded:
            return NoPlan(
                reason="no candidate symbolic action for these identities",
                model_version=model_version,
            )
        frontier: deque = deque([(start, ())])
        visited = {start.symbolic_key()}
        expanded = 0
        while frontier:
            current, prefix = frontier.popleft()
            expanded += 1
            if expanded > node_budget:
                return PlannerFailure(
                    error=f"node budget {node_budget} exceeded after {len(visited)} states",
                    timed_out=True,
                )
            for call in grounded:
                if not isinstance(applicable(current, call), ValidatedCall):
                    continue
                successor = apply(current, call)
                key = successor.symbolic_key()
                if key in visited:
                    continue
                steps = prefix + (call,)
                if is_goal(successor):
                    return PlanFound(plan=steps, model_version=model_version)
                visited.add(key)
                frontier.append((successor, steps))
        return NoPlan(
            reason=f"search space exhausted: {len(visited)} reachable symbolic states, "
                   f"none satisfies the goal",
            model_version=model_version,
        )
    except Exception as error:                              # any computation failure is typed
        return PlannerFailure(error=f"{type(error).__name__}: {error}")


__all__ = ["NODE_BUDGET", "bfs_plan"]
