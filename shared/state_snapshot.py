"""Canonical typed `StateSnapshot` and its deterministic normalization/serialization contract.

Supervisor requirements:
  :86 — the environment wrapper converts backend state into a normalized typed StateSnapshot.
  :88 — deterministic normalization/serialization is used for equality/hashing/replay/trace
        keys; raw backend serialization is NOT the equality criterion.
  :167 — symbolic state is exact/fully observable after wrapper normalization.

P0_V1_DECISIONS Decision 4 (SPEC-DETERMINED): the snapshot is built EXCLUSIVELY from the
authoritative `core_env.world`. Never from reward-derived belief, never from `core_env.grid`,
never from observations. Evidence that the alternatives are unsound is in
docs/handoff/section18.md §F (multiplexed reward channel) and §L-7 (grid desync).

Key contract
------------
`world_key()` covers agents + boxes + static world ONLY. Episode bookkeeping (step_count,
terminated, truncated) is deliberately EXCLUDED: the symbolic predictor predicts a successor
world, not how many primitive steps the backend needed to get there. `world_key()` is the
repeated-failure/trace bookkeeping key required by supervisor :118.

`replay_key()` additionally covers episode state and is for replay/debugging ONLY.

`__eq__`/`__hash__` delegate to `world_key()`, so `a == b`, `set()` and `dict` membership all use
the same criterion as the explicit call. Without this the generated dataclass equality would
compare `episode` too, and the most natural idiom (`if predicted == observed`) would silently use
the wrong criterion.

ONE OF THE MONITOR'S TWO CRITERIA
---------------------------------
`world_key()` is the **world basis** of a two-basis comparison (P0_V1_DECISIONS Decision 13.6).
Whole-snapshot equality is not the *sole* criterion and must not be used as one: the symbolic model
does not model positions, so a successful `GotoPushPose` changes the world while its symbolic effect
adds only `in_pose`, and a whole-snapshot comparison would report a mismatch on the happy path.

The monitor therefore compares:

  * the **world basis** — a skill's declared deterministic world effect
    (`SkillIR.predicted_world_effects`, grounded by the P2 predictor) against `world_key()`;
  * the **symbolic basis** — `ProjectionContract.monitored_key()` over
    `domain.box_push_v1.project` (see `shared/symbolic_state.py`).

`ExecutionDiscrepancy` carries a separate, correctly typed key pair per basis. `world_key()` is
also the repeated-failure bookkeeping key (:118) and the criterion behind `__eq__`/`__hash__`.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Tuple

from shared.comparison_keys import WorldKey
from shared.ids import AgentId, BoxId, Cell


def _cell(c: Any) -> Cell:
    if not isinstance(c, (tuple, list)) or len(c) != 2:
        raise ValueError(f"cell must be a 2-tuple, got {c!r}")
    x, y = c
    if not isinstance(x, int) or not isinstance(y, int) or isinstance(x, bool) or isinstance(y, bool):
        raise ValueError(f"cell coordinates must be ints, got {c!r}")
    return (x, y)


@dataclass(frozen=True, slots=True)
class AgentSnapshot:
    agent_id: AgentId
    position: Cell
    direction: int                   # 0=RIGHT 1=DOWN 2=LEFT 3=UP (constants.py:31-36)

    def __post_init__(self) -> None:
        object.__setattr__(self, "position", _cell(self.position))
        if self.direction not in (0, 1, 2, 3):
            raise ValueError(f"direction must be 0..3, got {self.direction!r}")

    def canonical(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id.value,
            "position": list(self.position),
            "direction": self.direction,
        }


@dataclass(frozen=True, slots=True)
class BoxSnapshot:
    box_id: BoxId
    position: Cell
    required_agents: int             # 1 = light, 2 = heavy (box_push_env.py:80-81). Static.
    is_target: bool                  # static
    delivered: bool                  # fluent

    def __post_init__(self) -> None:
        object.__setattr__(self, "position", _cell(self.position))
        if self.required_agents < 1:
            raise ValueError("required_agents must be >= 1")

    @property
    def is_heavy(self) -> bool:
        return self.required_agents > 1

    def canonical(self) -> Dict[str, Any]:
        return {
            "box_id": self.box_id.value,
            "position": list(self.position),
            "required_agents": self.required_agents,
            "is_target": self.is_target,
            "delivered": self.delivered,
        }


@dataclass(frozen=True, slots=True)
class StaticWorld:
    """Never mutated after reset. Included in the comparison key so a snapshot is
    self-describing and two snapshots from different instances never compare equal."""
    width: int
    height: int
    walls: Tuple[Cell, ...]
    delivery_zone: Tuple[Cell, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "walls", tuple(sorted(_cell(c) for c in self.walls)))
        object.__setattr__(self, "delivery_zone", tuple(sorted(_cell(c) for c in self.delivery_zone)))
        if self.width <= 0 or self.height <= 0:
            raise ValueError("width/height must be positive")

    def canonical(self) -> Dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "walls": [list(c) for c in self.walls],
            "delivery_zone": [list(c) for c in self.delivery_zone],
        }


@dataclass(frozen=True, slots=True)
class EpisodeSnapshot:
    """Bookkeeping. Excluded from `world_key()` by design — see module docstring."""
    step_count: int = 0
    terminated: bool = False
    truncated: bool = False

    def __post_init__(self) -> None:
        if self.step_count < 0:
            raise ValueError("step_count must be non-negative")

    def canonical(self) -> Dict[str, Any]:
        return {
            "step_count": self.step_count,
            "terminated": self.terminated,
            "truncated": self.truncated,
        }


@dataclass(frozen=True, slots=True, eq=False)
class StateSnapshot:
    """Canonical exact world state. Equality and hashing use `world_key()` (see module docstring)."""
    agents: Tuple[AgentSnapshot, ...]
    boxes: Tuple[BoxSnapshot, ...]
    static: StaticWorld
    episode: EpisodeSnapshot = EpisodeSnapshot()

    def __post_init__(self) -> None:
        agents = tuple(sorted(self.agents, key=lambda a: a.agent_id))
        boxes = tuple(sorted(self.boxes, key=lambda b: b.box_id))
        if len({a.agent_id for a in agents}) != len(agents):
            raise ValueError("duplicate AgentId in StateSnapshot")
        if len({b.box_id for b in boxes}) != len(boxes):
            raise ValueError("duplicate BoxId in StateSnapshot")
        object.__setattr__(self, "agents", agents)
        object.__setattr__(self, "boxes", boxes)

    # ── lookups ────────────────────────────────────────────────────────────────────
    def agent(self, agent_id: AgentId) -> AgentSnapshot:
        for a in self.agents:
            if a.agent_id == agent_id:
                return a
        raise KeyError(f"unknown agent {agent_id}")

    def box(self, box_id: BoxId) -> BoxSnapshot:
        for b in self.boxes:
            if b.box_id == box_id:
                return b
        raise KeyError(f"unknown box {box_id}")

    def has_agent(self, agent_id: AgentId) -> bool:
        return any(a.agent_id == agent_id for a in self.agents)

    def has_box(self, box_id: BoxId) -> bool:
        return any(b.box_id == box_id for b in self.boxes)

    @property
    def all_targets_delivered(self) -> bool:
        targets = [b for b in self.boxes if b.is_target]
        return bool(targets) and all(b.delivered for b in targets)

    # ── canonical form ─────────────────────────────────────────────────────────────
    def canonical_world(self) -> Dict[str, Any]:
        return {
            "agents": [a.canonical() for a in self.agents],
            "boxes": [b.canonical() for b in self.boxes],
            "static": self.static.canonical(),
        }

    def canonical_full(self) -> Dict[str, Any]:
        return {"world": self.canonical_world(), "episode": self.episode.canonical()}

    @staticmethod
    def _dumps(obj: Any) -> str:
        return json.dumps(obj, sort_keys=True, separators=(",", ":"))

    def world_json(self) -> str:
        """Deterministic serialization of the world (no episode bookkeeping)."""
        return self._dumps(self.canonical_world())

    def replay_json(self) -> str:
        """Deterministic serialization including episode bookkeeping (replay/debug)."""
        return self._dumps(self.canonical_full())

    def world_key(self) -> WorldKey:
        """Stable digest used for equality, hashing, and trace/bookkeeping keys (:118).

        Typed `WorldKey` so it cannot be mistaken for — or silently substituted by — a
        `SymbolicKey`; the two are different comparison bases (Decision 13.6).
        """
        return WorldKey(hashlib.sha256(self.world_json().encode("utf-8")).hexdigest())

    def replay_key(self) -> str:
        """Replay/debug digest. NOT a comparison criterion — see the module docstring."""
        return hashlib.sha256(self.replay_json().encode("utf-8")).hexdigest()

    def same_world(self, other: "StateSnapshot") -> bool:
        """Structural world equality — the WORLD basis only (Decision 13.6), not the whole
        monitor criterion. World-level identity for bookkeeping and tests."""
        return self.world_key() == other.world_key()

    # `eq=False` on the dataclass: the generated equality would include `episode`, so the most
    # natural idiom (`predicted == observed`, `set()`, dict keys) would silently use a different
    # criterion from `world_key()`. Delegating keeps every path consistent.
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, StateSnapshot):
            return NotImplemented
        return self.world_key() == other.world_key()

    def __hash__(self) -> int:
        return hash(self.world_key())

    # ── round-trip ─────────────────────────────────────────────────────────────────
    def to_dict(self) -> Dict[str, Any]:
        return self.canonical_full()

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "StateSnapshot":
        world = d["world"]
        ep = d.get("episode", {})
        return cls(
            agents=tuple(
                AgentSnapshot(
                    agent_id=AgentId(a["agent_id"]),
                    position=tuple(a["position"]),
                    direction=a["direction"],
                )
                for a in world["agents"]
            ),
            boxes=tuple(
                BoxSnapshot(
                    box_id=BoxId(b["box_id"]),
                    position=tuple(b["position"]),
                    required_agents=b["required_agents"],
                    is_target=b["is_target"],
                    delivered=b["delivered"],
                )
                for b in world["boxes"]
            ),
            static=StaticWorld(
                width=world["static"]["width"],
                height=world["static"]["height"],
                walls=tuple(tuple(c) for c in world["static"]["walls"]),
                delivery_zone=tuple(tuple(c) for c in world["static"]["delivery_zone"]),
            ),
            episode=EpisodeSnapshot(
                step_count=ep.get("step_count", 0),
                terminated=ep.get("terminated", False),
                truncated=ep.get("truncated", False),
            ),
        )

    def replace_episode(self, episode: EpisodeSnapshot) -> "StateSnapshot":
        return StateSnapshot(self.agents, self.boxes, self.static, episode)

    def with_box(self, box: BoxSnapshot) -> "StateSnapshot":
        boxes = tuple(box if b.box_id == box.box_id else b for b in self.boxes)
        return StateSnapshot(self.agents, boxes, self.static, self.episode)
