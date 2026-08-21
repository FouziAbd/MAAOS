"""The V1 predictor — BOTH comparison bases (Decision 13.6), MONITOR-SIDE ONLY (clause 9).

This module is structurally out of reach of applicability and planning: a static guard forbids
`symbolic/applicability.py`, `symbolic/belief.py` and `symbolic/planner.py` from importing it.
That is the boundary that keeps effect prediction from becoming a feasibility oracle — a
predictor consulted before choosing IS the oracle Decision 6 forbids, however innocent each part.

BOUNDED INPUTS (clause 9, statically guarded): agent positions, agent directions, box positions,
box `delivered`/`required_agents`, and the zone cells. NEVER `StaticWorld.walls`, never other
agents' occupancy, never grid bounds. A predictor that needs to know what is in the way has
stopped predicting an effect and started testing feasibility.

The world-effect arithmetic grounds the declarations frozen in
`domain/box_push_v1.py::predicted_world_effects`. `push_dir` and the pose/landing cells are
TRANSCRIBED arithmetic (the backend's `_push_dir_toward_goal` / `PushSkill` loop semantics,
verified by drift tests) — transcribed, not imported: this package may not import the backend,
and the numbers are declared success semantics, not consultation.

`first_zone_cell_along` is PARTIAL (§19 D-2): when the push ray never crosses the zone (the
agent-facing `D` of `Push` can point away), there IS no predicted terminal cell and this module
emits NO world-basis prediction — never a guessed one. The symbolic basis and the authoritative
outcome still apply.
"""
from __future__ import annotations

from typing import Optional, Tuple

from shared.ids import ZoneId
from shared.skill_ir import DomainIR
from shared.skills import GroundedSkillCall, OutsideSymbolicModel, SkillName
from shared.state_snapshot import AgentSnapshot, BoxSnapshot, StateSnapshot
from shared.symbolic_state import SymbolicState

from symbolic.applicability import apply_effects

#: constants.py:31-36 — RIGHT(0)=(+1,0) DOWN(1)=(0,+1) LEFT(2)=(-1,0) UP(3)=(0,-1). Transcribed;
#: pinned against the backend by tests (this package cannot import `constants`).
_DIRECTION_VECTORS = {0: (1, 0), 1: (0, 1), 2: (-1, 0), 3: (0, -1)}


def _manhattan(a: Tuple[int, int], b: Tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def push_dir(box: Tuple[int, int], zone_cells: Tuple[Tuple[int, int], ...]) -> int:
    """`push_dir(box, zone)` from the frozen effect declarations: the direction toward the
    Manhattan-nearest zone cell, horizontal preferred on ties. Transcription of
    `skill_executor_push._push_dir_toward_goal` (:39-47), drift-pinned in tests."""
    gx, gy = min(zone_cells, key=lambda c: _manhattan(box, c))
    dx, dy = gx - box[0], gy - box[1]
    if abs(dx) >= abs(dy) and dx != 0:
        return 0 if dx > 0 else 2
    if dy != 0:
        return 1 if dy > 0 else 3
    return 2


def first_zone_cell_along(
    box: Tuple[int, int], direction: int, zone_cells: Tuple[Tuple[int, int], ...]
) -> Optional[Tuple[int, int]]:
    """The first zone cell on the ray from `box` along `direction` — or None (§19 D-2).

    Computed directly over the zone cells (which ARE 'the zone', a bounded input): a zone cell is
    on the ray iff its offset from the box is a positive multiple of the direction vector. No
    grid bounds, no walls, no occupancy — whether the ray is CLEAR is feasibility and stays out.
    """
    dx, dy = _DIRECTION_VECTORS[direction]
    candidates = []
    for cx, cy in zone_cells:
        ox, oy = cx - box[0], cy - box[1]
        if dx == 0 and ox != 0:
            continue
        if dy == 0 and oy != 0:
            continue
        step = ox * dx + oy * dy            # signed distance along D (the other axis is 0)
        if step > 0:
            candidates.append((step, (cx, cy)))
    if not candidates:
        return None
    return min(candidates)[1]


def predict_symbolic(
    domain: DomainIR, state: SymbolicState, call: GroundedSkillCall
) -> Optional[SymbolicState]:
    """The SYMBOLIC basis: the deterministic IR successor, or None for a skill outside the
    symbolic model (Decision 15 — no prediction may exist for Explore/Wait)."""
    resolved = domain.resolve(call.skill)
    if isinstance(resolved, OutsideSymbolicModel):
        return None
    return apply_effects(state, resolved, call)


def predict_world_candidates(
    snapshot: StateSnapshot, call: GroundedSkillCall, zone: ZoneId
) -> Tuple[StateSnapshot, ...]:
    """The WORLD basis: the admissible successful terminal snapshots, grounding the frozen
    `predicted_world_effects`. Usually one candidate; TWO for `CooperativePush`, whose terminal
    slots are declared as a SET (`_assign_slots` re-derives front/rear roles every step, so the
    role assignment is not predictable from the pre-state); EMPTY when no prediction exists
    (outside the symbolic model, or the push ray misses the zone — §19 D-2)."""
    if call.zone is not None and call.zone != zone:
        # Decision 11: the zone parameter carries IDENTITY. A call grounded on a different zone
        # than the one being predicted against is a wiring error upstream (pre-flight validates
        # zone identity), never something to silently predict around.
        raise ValueError(
            f"zone identity mismatch: call names {call.zone.value!r}, predicting against "
            f"{zone.value!r}"
        )
    zone_cells = snapshot.static.delivery_zone

    if call.skill is SkillName.GOTO_PUSH_POSE:
        box = snapshot.box(call.box)
        direction = push_dir(box.position, zone_cells)
        dx, dy = _DIRECTION_VECTORS[direction]
        pose = (box.position[0] - dx, box.position[1] - dy)
        return (_with_agent(snapshot, call.agents[0].value, pose, direction),)

    if call.skill is SkillName.PUSH:
        agent = snapshot.agent(call.agents[0])
        direction = agent.direction          # Push's D is the AGENT'S FACING (frozen effects)
        box = snapshot.box(call.box)
        landing = first_zone_cell_along(box.position, direction, zone_cells)
        if landing is None:
            return ()                        # ray misses the zone: NO world-basis prediction
        dx, dy = _DIRECTION_VECTORS[direction]
        predicted = _with_box(snapshot, call.box, landing, delivered=True)
        predicted = _with_agent(
            predicted, call.agents[0].value, (landing[0] - dx, landing[1] - dy), direction
        )
        return (predicted,)

    if call.skill is SkillName.COOPERATIVE_PUSH:
        box = snapshot.box(call.box)
        direction = push_dir(box.position, zone_cells)   # coop's D comes from the box and zone
        landing = first_zone_cell_along(box.position, direction, zone_cells)
        if landing is None:
            return ()
        dx, dy = _DIRECTION_VECTORS[direction]
        front = (landing[0] - dx, landing[1] - dy)
        rear = (landing[0] - 2 * dx, landing[1] - 2 * dy)
        base = _with_box(snapshot, call.box, landing, delivered=True)
        first, second = call.agents[0].value, call.agents[1].value
        return (
            _with_agent(_with_agent(base, first, front, direction), second, rear, direction),
            _with_agent(_with_agent(base, first, rear, direction), second, front, direction),
        )

    return ()                                # Explore / Wait: outside the symbolic model


# ── snapshot surgery (frame: everything unmentioned is unchanged) ─────────────────

def _with_agent(
    snapshot: StateSnapshot, agent_id: str, position: Tuple[int, int], direction: int
) -> StateSnapshot:
    return StateSnapshot(
        agents=tuple(
            AgentSnapshot(a.agent_id, position, direction) if a.agent_id.value == agent_id else a
            for a in snapshot.agents
        ),
        boxes=snapshot.boxes,
        static=snapshot.static,
        episode=snapshot.episode,
    )


def _with_box(snapshot: StateSnapshot, box_id, position, delivered: bool) -> StateSnapshot:
    return StateSnapshot(
        agents=snapshot.agents,
        boxes=tuple(
            BoxSnapshot(b.box_id, position, b.required_agents, b.is_target, delivered)
            if b.box_id == box_id else b
            for b in snapshot.boxes
        ),
        static=snapshot.static,
        episode=snapshot.episode,
    )
