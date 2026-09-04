"""V1 task format (SUPERVISOR_P0_P4_CONTRACT.md:184 — representative task examples).

The backend has only a mission string, "push all target boxes onto the goal zone"
(box_push_env.py:75-76); there is no structured task object. P0 defines one.

V1 input is text/typed data only (:169). `description` is the text form the NL track interprets;
`goal_delivered` is the typed form the symbolic track plans against. Both are carried so the
translator has a source and a target, and so a coverage residual can be computed between them.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Tuple

from shared.ids import BoxId, ZoneId
from shared.state_snapshot import StateSnapshot


@dataclass(frozen=True, slots=True)
class Task:
    task_id: str
    description: str
    goal_delivered: Tuple[BoxId, ...]
    zone: ZoneId

    def __post_init__(self) -> None:
        if not self.task_id:
            raise ValueError("Task requires a task_id")
        object.__setattr__(self, "goal_delivered", tuple(sorted(set(self.goal_delivered))))
        if not self.goal_delivered:
            raise ValueError("Task requires at least one box in goal_delivered")

    def is_satisfied_by(self, state: StateSnapshot) -> bool:
        """Pure symbolic goal test over the canonical snapshot. No backend access."""
        return all(state.box(b).delivered for b in self.goal_delivered)

    def canonical(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "description": self.description,
            "goal_delivered": [b.value for b in self.goal_delivered],
            "zone": self.zone.value,
        }
