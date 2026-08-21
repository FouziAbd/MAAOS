"""Stable typed identifiers frozen at P0.

Identity, never geometry. Executive skill arguments are identities (`BoxId`, `AgentId`,
`ZoneId`), never grid cells — see P0_V1_DECISIONS Decision 11.

Evidence for stability (docs/handoff/section18.md §D):
  - agent ids "agent_0"/"agent_1" — multi_agent_box_push_env.py:54
  - box ids 0 (HEAVY) / 1 (LIGHT) — box_push_env.py:79-82, stable across steps and resets
  - the render grid carries NO identity (both boxes are identical TargetPackage objects,
    multi_agent_box_push_env.py:351), so identity must come from these ids, never from cells.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

# A grid cell. Used ONLY inside StateSnapshot and backend adapters — never as a skill argument.
Cell = Tuple[int, int]


@dataclass(frozen=True, order=True, slots=True)
class AgentId:
    """Stable agent identity. Ordering is canonical and used to order agent pairs."""
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not self.value:
            raise ValueError("AgentId.value must be a non-empty string")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, order=True, slots=True)
class BoxId:
    """Stable box identity (int key of world.objects)."""
    value: int

    def __post_init__(self) -> None:
        if not isinstance(self.value, int) or isinstance(self.value, bool):
            raise ValueError("BoxId.value must be an int")
        if self.value < 0:
            raise ValueError("BoxId.value must be non-negative")

    def __str__(self) -> str:
        return f"box_{self.value}"

    @classmethod
    def parse(cls, text: str) -> "BoxId":
        """Inverse of `__str__`. Needed so a lifted planner action can be un-lifted to a call."""
        if not isinstance(text, str) or not text.startswith("box_"):
            raise ValueError(f"not a box identity: {text!r}")
        try:
            return cls(int(text[len("box_"):]))
        except ValueError:
            raise ValueError(f"not a box identity: {text!r}") from None


@dataclass(frozen=True, order=True, slots=True)
class ZoneId:
    """Stable delivery-zone identity.

    V1 freezes exactly one zone (`delivery_zone`, the 10 cells of box_push_env.py:39).
    The parameter exists in every push-related signature because the push direction — and
    therefore the pose — is a function of the target zone (_push_dir_toward_goal,
    skill_executor_push.py:39-47). Naming it keeps that dependency explicit instead of hidden.
    """
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not self.value:
            raise ValueError("ZoneId.value must be a non-empty string")

    def __str__(self) -> str:
        return self.value


def canonical_agent_pair(a: AgentId, b: AgentId) -> Tuple[AgentId, AgentId]:
    """Canonically order an agent pair (ascending AgentId).

    CooperativePush takes a pair, not a partner (Decision 1). Canonical ordering gives the
    grounded call a deterministic serialization, which repeated-failure bookkeeping requires
    (SUPERVISOR_P0_P4_CONTRACT.md:118).
    """
    if a == b:
        raise ValueError("CooperativePush requires two distinct agents")
    return (a, b) if a <= b else (b, a)
