"""Domain `lamp` — the value types (SYMBOLIC-side module: imports stdlib, shared, kit only).

Three frozen dataclasses the runtime handles without interpreting:

    State   the authoritative world (what the environment reports) — `canonical()` lists the
            WORLD content only (never episode bookkeeping), and everything else derives from it
    Call    one grounded executive action, naming the objects it acts on
    Task    the goal, as a pure test over a State

`identities()` on State and Call is what grounding checks: a call naming an identity the
state lacks is rejected before execution (never a feasibility test).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Dict, FrozenSet, Tuple

from kit import world_key
from shared.comparison_keys import WorldKey


class Op(StrEnum):
    """The executive actions. TODO(author): rename/extend."""
    TURN_ON = "TurnOn"
    TURN_OFF = "TurnOff"
    NUDGE = "Nudge"          # frees a stuck switch; no symbolic effect (recovery advice only)


@dataclass(frozen=True, slots=True)
class State:
    """TODO(author): the authoritative world. Keep it a frozen dataclass; put the world
    content in `canonical()` and episode bookkeeping (tick counters) OUTSIDE it."""
    lamps: Tuple[str, ...]
    lit: FrozenSet[str] = frozenset()
    tick: int = 0                                  # episode bookkeeping, not world content

    def canonical(self) -> Dict[str, Any]:
        return {"lamps": list(self.lamps), "lit": sorted(self.lit)}

    def world_key(self) -> WorldKey:
        return world_key(self.canonical())

    def same_world(self, other: "State", /) -> bool:
        return self.canonical() == other.canonical()

    def identities(self) -> FrozenSet[str]:
        return frozenset(self.lamps)


@dataclass(frozen=True, slots=True)
class Call:
    """TODO(author): one grounded action and its parameters."""
    op: Op
    lamp_id: str

    @property
    def skill(self) -> Op:
        return self.op

    @property
    def cost(self) -> int:
        return 1

    def canonical(self) -> Dict[str, Any]:
        return {"op": str(self.op), "lamp": self.lamp_id}

    def key(self) -> str:
        return json.dumps(self.canonical(), sort_keys=True, separators=(",", ":"))

    def identities(self) -> FrozenSet[str]:
        return frozenset({self.lamp_id})

    def __str__(self) -> str:
        return f"{self.op}({self.lamp_id})"


@dataclass(frozen=True, slots=True)
class Task:
    """TODO(author): the goal as a pure test over the authoritative state."""
    task_id: str
    description: str
    lamps: Tuple[str, ...]

    def is_satisfied_by(self, state: State, /) -> bool:
        return set(self.lamps) <= state.lit

    def canonical(self) -> Dict[str, Any]:
        return {"task_id": self.task_id, "description": self.description, "lamps": list(self.lamps)}


__all__ = ["Call", "Op", "State", "Task"]
