"""Domain `cooperative_grid` — the value types (SYMBOLIC-side module: imports stdlib, shared,
kit only).

The world: two agents (`A`, `B`) on a small grid, one heavy door (`door`) between the corridor
and the goal room, and three named PLACES the executive actions talk about —
`handle_left` / `handle_right` (the two cooperative positions flanking the door) and `goal`
(the goal room's goal cells). Every cell that is none of these is "the hall".

    State   the authoritative world as the environment reports it: exact agent cells, the
            door's open/closed state AND its jam (the designed hidden physical condition —
            it is world content, so it lives in `canonical()`; `project()` in model.py is
            what keeps it from the planner), and the place layout
    Call    one grounded high-level action: Goto(agent, place), CooperateOpen(agent, door,
            partner) or ClearJam(agent, door)
    Task    both agents on goal cells

The runtime reads exactly these members — keep their names for METHODS, never for fields:

    State  world_key() same_world(other) identities()       (+ canonical() for the keys)
    Call   skill  cost  key()  canonical()  identities()  __str__()  and value equality (==)
    Task   is_satisfied_by(state)  canonical()
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Dict, FrozenSet, Optional, Tuple

from kit import world_key
from shared.comparison_keys import WorldKey

Cell = Tuple[int, int]

# ── the symbolic vocabulary shared by the model and the environment adapter ──────────
DOOR = "door"
HANDLE_LEFT = "handle_left"
HANDLE_RIGHT = "handle_right"
GOAL = "goal"
HALL = "hall"                          # "at no named place" — not a place one can Goto
HANDLES: Tuple[str, ...] = (HANDLE_LEFT, HANDLE_RIGHT)


class Op(StrEnum):
    """The executive actions (each may run several primitive grid steps in the backend)."""
    GOTO = "Goto"                      # Goto(agent, place)
    COOPERATE_OPEN = "CooperateOpen"   # CooperateOpen(agent, door, partner): both pull
    CLEAR_JAM = "ClearJam"             # ClearJam(agent, door): shake the door (recovery)


@dataclass(frozen=True, slots=True)
class AgentPose:
    name: str
    x: int
    y: int

    @property
    def cell(self) -> Cell:
        return (self.x, self.y)


@dataclass(frozen=True, slots=True)
class Door:
    name: str
    x: int
    y: int
    is_open: bool
    jammed: bool                       # the hidden physical condition


@dataclass(frozen=True, slots=True)
class Place:
    name: str
    cells: Tuple[Cell, ...]


@dataclass(frozen=True, slots=True)
class State:
    """The authoritative world. `canonical()` is the world content; `episode_over` is
    bookkeeping the backend reports (terminated or truncated) and stays outside it."""
    agents: Tuple[AgentPose, ...]
    door: Door
    places: Tuple[Place, ...]
    episode_over: bool = False

    def canonical(self) -> Dict[str, Any]:
        return {
            "agents": [{"name": a.name, "x": a.x, "y": a.y} for a in self.agents],
            "door": {"name": self.door.name, "x": self.door.x, "y": self.door.y,
                     "open": self.door.is_open, "jammed": self.door.jammed},
            "places": {p.name: [list(c) for c in p.cells] for p in self.places},
        }

    def world_key(self) -> WorldKey:
        return world_key(self.canonical())

    def same_world(self, other: "State", /) -> bool:
        return self.canonical() == other.canonical()

    def identities(self) -> FrozenSet[str]:
        return frozenset({a.name for a in self.agents} | {self.door.name}
                         | {p.name for p in self.places})

    # ── helpers over the world content (used by the task and by project()) ────────────
    def agent(self, name: str) -> Optional[AgentPose]:
        for a in self.agents:
            if a.name == name:
                return a
        return None

    def cells_of(self, place: str) -> Tuple[Cell, ...]:
        for p in self.places:
            if p.name == place:
                return p.cells
        return ()

    def place_of(self, agent_name: str) -> str:
        """The named place the agent stands on, or HALL."""
        a = self.agent(agent_name)
        if a is None:
            return HALL
        for p in self.places:
            if a.cell in p.cells:
                return p.name
        return HALL


@dataclass(frozen=True, slots=True)
class Call:
    """One grounded high-level action. `target` is a place for Goto and the door otherwise;
    `partner` is the second agent of CooperateOpen."""
    op: Op
    agent: str
    target: str
    partner: Optional[str] = None

    @property
    def skill(self) -> Op:
        return self.op

    @property
    def cost(self) -> int:
        return 1

    def canonical(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"op": str(self.op), "agent": self.agent, "target": self.target}
        if self.partner is not None:
            data["partner"] = self.partner
        return data

    def key(self) -> str:
        return json.dumps(self.canonical(), sort_keys=True, separators=(",", ":"))

    def identities(self) -> FrozenSet[str]:
        names = {self.agent, self.target}
        if self.partner is not None:
            names.add(self.partner)
        return frozenset(names)

    def __str__(self) -> str:
        if self.partner is not None:
            return f"{self.op}({self.agent}, {self.partner}, {self.target})"
        return f"{self.op}({self.agent}, {self.target})"


@dataclass(frozen=True, slots=True)
class Task:
    """The goal: every agent stands on a goal cell."""
    task_id: str
    description: str

    def is_satisfied_by(self, state: State, /) -> bool:
        return bool(state.agents) and all(state.place_of(a.name) == GOAL for a in state.agents)

    def canonical(self) -> Dict[str, Any]:
        return {"task_id": self.task_id, "description": self.description}


__all__ = ["AgentPose", "Call", "Cell", "DOOR", "Door", "GOAL", "HALL", "HANDLES",
           "HANDLE_LEFT", "HANDLE_RIGHT", "Op", "Place", "State", "Task"]
