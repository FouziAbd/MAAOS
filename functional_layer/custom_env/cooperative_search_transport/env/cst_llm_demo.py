"""
LLM-driven multi-agent demo for CooperativeSearchTransport.

POMDP-correct: agents observe only their local partial view.  Internal state
(position, carrying status) is maintained by DeterministicGridUpdater inside
the middleware belief system — no access to env.core_env.world.

Run from this directory:
    cd functional_layer/custom_env/cooperative_search_transport/env
    /home/fouzi/PettingZooEnv/bin/python3 cst_llm_demo.py
"""

import sys
import os
import time
from typing import Dict, List, Optional, Tuple, Any


class _Tee:
    """Write to both stdout and a log file simultaneously."""
    def __init__(self, filepath):
        self._file = open(filepath, "w", buffering=1)
        self._stdout = sys.__stdout__
    def write(self, data):
        self._stdout.write(data)
        self._file.write(data)
    def flush(self):
        self._stdout.flush()
        self._file.flush()
    def close(self):
        self._file.close()

# ── path setup ────────────────────────────────────────────────────────────────
_ENV_DIR   = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_ENV_DIR, "../../../.."))
sys.path.insert(0, _ENV_DIR)
sys.path.insert(0, _REPO_ROOT)

import dspy
from constants import Actions, Directions, DIRECTION_VECTORS, ACTION_NAMES, DIRECTION_NAMES
from state import EnvConfig
from multi_agent_env import MultiAgentCooperativeSearchTransportEnv
from entity_schema import CST_ENTITY_SCHEMA
from obs_parser import parse_cst_obs

from middleware_layer.middleware_orchestrator import MiddlewareOrchestrator
from model_layer.agent import Agent

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

LLM_MODEL = "ollama_chat/gemma4:e4b"
LLM_BASE  = "http://localhost:11434"

ACTIONS_DETAILS = [
    "0 (TURN_LEFT): Rotate 90° to the left in place",
    "1 (TURN_RIGHT): Rotate 90° to the right in place",
    "2 (MOVE_FORWARD): Move one step forward in the direction you are currently facing",
    "3 (STAY): Stay in place, do nothing",
    "4 (PICK_OR_INTERACT): Use ONLY when a TARGET object is DIRECTLY IN FRONT of you. "
        "Single-agent object → pick it up. Cooperative object → latch on.",
    "5 (DROP): Drop what you are carrying, or disengage from a cooperative hold. "
        "For delivery: use only when standing on a delivery zone cell.",
    "6 (COOPERATE): Hold your cooperative grip while waiting for partner to reposition",
]

_ACTION_SHORT = {
    0: "TURN_LEFT", 1: "TURN_RIGHT", 2: "MOVE_FORWARD",
    3: "STAY", 4: "PICK_OR_INTERACT", 5: "DROP", 6: "COOPERATE",
}

# ═══════════════════════════════════════════════════════════════════════════════
# MINIGRID OBSERVATION ENCODING  (shared with obs_parser — replicated here for
# the directive/summary helpers which only run in this file)
# ═══════════════════════════════════════════════════════════════════════════════

_OBJ_TYPE_IDX = {
    0: "unseen", 1: "empty",  2: "wall", 3: "floor", 4: "door",
    5: "key",    6: "ball",   7: "box",  8: "goal",  9: "lava",  10: "agent",
}
_COLOR_IDX = {0: "red", 1: "green", 2: "blue", 3: "purple", 4: "yellow", 5: "grey"}


def _cell_desc(cell) -> str:
    t, c = int(cell[0]), int(cell[1])
    if t == 0: return "unseen"
    if t == 1: return "empty"
    if t == 2: return "WALL"
    if t == 3 and c == 1: return "DELIVERY_ZONE"
    if t == 3: return "floor"
    if t == 7 and c == 0: return "TARGET_OBJECT"
    if t == 7 and c == 2: return "DECOY_OBJECT"
    if t == 10: return f"AGENT({_COLOR_IDX.get(c, '?')})"
    return f"{_OBJ_TYPE_IDX.get(t,'?')}({_COLOR_IDX.get(c,'?')})"


# ═══════════════════════════════════════════════════════════════════════════════
# PRIOR KNOWLEDGE
# ═══════════════════════════════════════════════════════════════════════════════

_PRIOR_OBJECTS: Dict[int, dict] = {
    0: dict(is_target=True,  required_agents=2, init_pos=[2, 9]),
    1: dict(is_target=True,  required_agents=1, init_pos=[6, 5]),
    2: dict(is_target=False, required_agents=1, init_pos=[9, 2]),
    3: dict(is_target=False, required_agents=1, init_pos=[10, 4]),
}

_DELIVERY_ZONE: List[List[int]] = [[1, 1], [2, 1], [1, 2], [2, 2]]

# ── Navigation helpers ────────────────────────────────────────────────────────

def _manhattan(a, b) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _nav_hint_action(pos, direction: int, goal_pos) -> int:
    """Straight-line nav toward goal_pos (no wall awareness)."""
    dx = goal_pos[0] - pos[0]
    dy = goal_pos[1] - pos[1]
    if dx == 0 and dy == 0:
        return 3
    if abs(dx) >= abs(dy) and dx != 0:
        wanted = 0 if dx > 0 else 2
    else:
        wanted = 1 if dy > 0 else 3
    if direction == wanted:
        return 2
    if (direction + 1) % 4 == wanted:
        return 1
    if (direction - 1) % 4 == wanted:
        return 0
    return 1


_DIR_NAMES = {0: "RIGHT", 1: "DOWN", 2: "LEFT", 3: "UP"}


def _primary_direction_blocked(pos, goal_pos, grid_cells: List[List[str]]) -> bool:
    """Return True if the primary axis direction toward goal_pos is wall-blocked."""
    dx = goal_pos[0] - pos[0]
    dy = goal_pos[1] - pos[1]
    if dx == 0 and dy == 0:
        return False
    if abs(dx) >= abs(dy) and dx != 0:
        primary = 0 if dx > 0 else 2
    else:
        primary = 1 if dy > 0 else 3
    dvec = DIRECTION_VECTORS[primary]
    nx, ny = pos[0] + dvec[0], pos[1] + dvec[1]
    if grid_cells and 0 <= nx < len(grid_cells) and 0 <= ny < len(grid_cells[0]):
        return grid_cells[nx][ny] == "wall"
    return False


def _smart_nav_hint(pos, direction: int, goal_pos,
                    grid_cells: List[List[str]]) -> Tuple[int, str]:
    """
    Grid-aware nav hint.
    If the direct-line direction toward goal_pos passes through a known wall cell,
    suggest the perpendicular direction instead so the agent can search for a gap.
    Returns (action_idx, explanation_string).
    """
    dx = goal_pos[0] - pos[0]
    dy = goal_pos[1] - pos[1]
    if dx == 0 and dy == 0:
        return 3, "already at goal — STAY or DROP"

    # Primary direction: larger axis gap first
    if abs(dx) >= abs(dy) and dx != 0:
        primary   = 0 if dx > 0 else 2          # RIGHT / LEFT
        secondary = 1 if dy >= 0 else 3          # DOWN / UP (perpendicular)
    else:
        primary   = 1 if dy > 0 else 3           # DOWN / UP
        secondary = 0 if dx >= 0 else 2          # RIGHT / LEFT (perpendicular)

    def next_cell(d):
        dvec = DIRECTION_VECTORS[d]
        return pos[0] + dvec[0], pos[1] + dvec[1]

    def is_known_wall(d):
        nx, ny = next_cell(d)
        if grid_cells and 0 <= nx < len(grid_cells) and 0 <= ny < len(grid_cells[0]):
            return grid_cells[nx][ny] == "wall"
        return False

    primary_wall   = is_known_wall(primary)
    secondary_wall = is_known_wall(secondary)

    if primary_wall and not secondary_wall:
        wanted = secondary
        note   = (f"wall blocks {_DIR_NAMES[primary]} — "
                  f"go {_DIR_NAMES[secondary]} to search for a gap")
    elif primary_wall and secondary_wall:
        wanted = (primary + 2) % 4
        note   = "both forward directions blocked — turning back"
    else:
        wanted = primary
        note   = f"clear path {_DIR_NAMES[primary]}"

    if direction == wanted:
        action = 2
    elif (direction + 1) % 4 == wanted:
        action = 1
    elif (direction - 1) % 4 == wanted:
        action = 0
    else:
        action = 1

    return action, note


# ── Grid display helpers ──────────────────────────────────────────────────────

def _obj_grid_pos(grid_cells: List[List[str]], oid: int, is_target: bool) -> Optional[List[int]]:
    """Return [x,y] of object_N from the belief grid, or None."""
    kind = "target" if is_target else "decoy"
    lbl  = f"{kind}_{oid}"
    for x, col in enumerate(grid_cells):
        for y, cell in enumerate(col):
            if cell == lbl:
                return [x, y]
    return None


def _grid_explored(grid_cells: List[List[str]]) -> int:
    """Count cells that are no longer 'unknown'."""
    return sum(1 for col in grid_cells for cell in col if cell != "unknown")


def _render_grid_ascii(grid_cells: List[List[str]], self_pos: List[int]) -> str:
    """
    Render a compact 12×12 ASCII map of the belief grid.
    Symbols:
      ?  unknown    .  empty    #  wall    D  delivery_zone
      0/1  target   d  decoy    A  other agent   @  self
    Columns = x (0 left), rows = y (0 top).
    """
    W = len(grid_cells)
    H = len(grid_cells[0]) if W > 0 else 0
    header = "   " + "".join(str(x % 10) for x in range(W))
    rows = [header]
    for y in range(H):
        row_chars = []
        for x in range(W):
            if [x, y] == list(self_pos):
                row_chars.append("@")
            else:
                cell = grid_cells[x][y]
                if cell == "unknown":         row_chars.append("?")
                elif cell == "empty":         row_chars.append(".")
                elif cell == "wall":          row_chars.append("#")
                elif cell == "delivery_zone": row_chars.append("D")
                elif cell.startswith("target_"):
                    row_chars.append(cell.split("_")[1])  # "0" or "1"
                elif cell.startswith("decoy_"):  row_chars.append("d")
                elif cell == "agent":             row_chars.append("A")
                else:                             row_chars.append("?")
        rows.append(f"{y:2d} " + "".join(row_chars))
    return "\n".join(rows)


_AGENT_STARTS: Dict[str, Tuple[List[int], int]] = {
    "agent_0": ([10, 10], int(Directions.LEFT)),
    "agent_1": ([10,  9], int(Directions.LEFT)),
}


def _build_initial_entities(agent_id: str) -> dict:
    """Build prior-knowledge entity dict for one agent including the full grid."""
    start_pos, start_dir = _AGENT_STARTS[agent_id]

    # ── Initialize 12×12 belief grid ──────────────────────────────────────────
    grid: List[List[str]] = [["unknown"] * 12 for _ in range(12)]

    # Mark delivery zone cells (prior knowledge)
    for cx, cy in _DELIVERY_ZONE:
        grid[cx][cy] = "delivery_zone"

    # Mark all object starting positions (prior knowledge)
    for oid, info in _PRIOR_OBJECTS.items():
        x, y = info["init_pos"]
        kind = "target" if info["is_target"] else "decoy"
        grid[x][y] = f"{kind}_{oid}"

    # ── Build entity dict ──────────────────────────────────────────────────────
    entities: dict = {
        "self": {
            "direction":            start_dir,
            "position":             list(start_pos),
            "carrying_object_id":   None,
            "engaged_object_ids":   [],
            "delivered_object_ids": [],
        },
        "grid": {
            "cells": grid,
        },
    }
    for oid, info in _PRIOR_OBJECTS.items():
        entities[f"object_{oid}"] = {
            "is_target":       info["is_target"],
            "required_agents": info["required_agents"],
            "status":          "available",
        }
    return entities


_PRIOR_KNOWLEDGE_TEMPLATE = """\
Grid: 12×12. x increases RIGHT, y increases DOWNWARD (UP = y-1, DOWN = y+1).
Delivery zone (far left): (1,1) (2,1) (1,2) (2,2).
Object locations at episode start:
  obj_0: TARGET at [2, 9] — requires 2 agents (cooperative carry)
  obj_1: TARGET at [6, 5] — requires 1 agent (solo carry)
  obj_2: DECOY  at [9, 2] — ignore
  obj_3: DECOY  at [10, 4] — ignore
Agent starting positions: agent_0 at [10,10] facing LEFT, agent_1 at [10,9] facing LEFT.
Walls divide the grid into rooms. Wall gap positions are unknown — discover by exploring.
Belief grid provided each step: @ = you, D = delivery zone, 0/1 = targets, d = decoy,
  # = wall, . = empty, ? = not yet explored.
"""

# ═══════════════════════════════════════════════════════════════════════════════
# AGENT DESCRIPTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def get_scenario_description(agent_id: str) -> str:
    return f"""\
You are {agent_id} in a Cooperative Search and Transport task on a 12×12 grid.
You see only a 3×3 area around you. Your position and carrying state come from your belief history.

GRID (y increases DOWNWARD: moving UP decreases y, moving DOWN increases y):
  You start on the right side of a 12×12 grid.
  The delivery zone is on the far left: (1,1) (2,1) (1,2) (2,2).
  There are walls dividing the grid into rooms. Each wall has one or more gaps.
  You must explore to find the gaps — they are not known in advance.

OBJECTS (known from prior knowledge — see OBJECT STATUS for current positions):
  obj_0: TARGET at [2, 9] — needs 2 agents (cooperative carry)
  obj_1: TARGET at [6, 5] — needs 1 agent (solo carry)
  obj_2: DECOY  at [9, 2] — ignore
  obj_3: DECOY  at [10, 4] — ignore

BELIEF GRID: a 12×12 map is shown each step.  Cells update as you explore.
  @ = your position    D = delivery zone    0/1 = target objects
  d = decoy            # = wall             . = empty    ? = unexplored

ACTION SEMANTICS:
  0 TURN_LEFT:       Rotate 90° left (does not move)
  1 TURN_RIGHT:      Rotate 90° right (does not move)
  2 MOVE_FORWARD:    Move 1 step in current facing direction
  3 STAY:            Do nothing
  4 PICK_OR_INTERACT: Pick up or latch onto the object DIRECTLY IN FRONT
  5 DROP:            Release carried object; if on delivery zone, delivers it
  6 COOPERATE:       Hold cooperative grip while waiting for your partner

REWARD SIGNALS:
  -0.01 per step: action succeeded (including turns and stays)
  -0.11 per step: MOVE_FORWARD failed — you did NOT move (obstacle in front)
  positive reward: successful pickup, latch, or delivery

NAVIGATION GUIDELINES:
  - Don't MOVE_FORWARD when front_blocked=True — it will fail and waste a step.
  - If on_delivery_zone=True and carrying an object → DROP it (action 5).
  - If a TARGET_OBJECT is directly in front → PICK_OR_INTERACT (action 4).
  - Use NAV_HINT as your navigation guide. It accounts for known walls in the belief grid.
    If NAV_HINT says "wall blocks X — go Y to search for a gap", trust it.
  - If you have been at the same position for several steps and keep turning, you are
    stuck against a wall. Move perpendicular to the wall to find the gap — don't keep
    alternating TURN_LEFT and TURN_RIGHT in place.
  - Use the BELIEF GRID to reason spatially: # cells are walls, ? cells are unexplored.
    If you see a column of # in the grid, move along it until you find a gap (. or empty).
"""


def get_goal_description(agent_id: str) -> str:
    return (
        "Deliver both TARGET objects to the delivery zone at (1,1)-(2,2) on the far left. "
        "obj_1 at [6,5] can be carried alone. "
        "obj_0 at [2,9] needs both agents to carry together (cooperative). "
        "Walls divide the grid — find their gaps by exploring."
    )


def get_observation_spec() -> str:
    return (
        "Partial observation: local view (small grid around you) encoded as cell types, "
        "your facing direction, and your internal state (what you are carrying/holding)."
    )


# ═══════════════════════════════════════════════════════════════════════════════
# OBSERVATION SUMMARY  (informative facts only — LLM decides the action)
# ═══════════════════════════════════════════════════════════════════════════════

def _room_name(x: int) -> str:
    if x >= 8:   return "RIGHT"
    if x >= 4:   return "MIDDLE"
    return "LEFT"


def _interpret_reward(action: Optional[int], reward: Optional[float]) -> str:
    """Translate a raw reward into a human-readable outcome."""
    if reward is None:
        return "unknown"
    if action == Actions.MOVE_FORWARD:
        return "moved OK" if reward > -0.06 else "BLOCKED — did not move"
    if action == Actions.PICK_OR_INTERACT:
        return "pickup/latch succeeded" if reward > 0 else "pickup failed (nothing in front?)"
    if action == Actions.DROP:
        return "delivered!" if reward > 0.5 else "dropped/disengaged"
    return f"reward={reward:+.2f}"


def summarize_cst_obs(obs: dict, entities: dict, step: int = 0,
                      recent_history: Optional[List[dict]] = None) -> str:
    """
    Informative summary of current belief state.
    No SUGGESTED_ACTION — the LLM planner decides what to do.
    """
    self_e     = entities.get("self", {})
    direction  = self_e.get("direction", 2)
    carrying   = self_e.get("carrying_object_id")
    engaged    = self_e.get("engaged_object_ids", [])
    delivered  = self_e.get("delivered_object_ids", [])
    pos        = self_e.get("position", [0, 0])
    dir_name   = DIRECTION_NAMES.get(direction, str(direction))
    grid_cells = entities.get("grid", {}).get("cells", [])

    image     = obs.get("image")
    VIEW_SIZE = len(image) if image is not None else 3

    # ── local view ─────────────────────────────────────────────────────────
    cells: dict = {}
    if image is not None:
        mid = VIEW_SIZE // 2
        for r in range(VIEW_SIZE):
            for c in range(VIEW_SIZE):
                # first index = lateral, second index = depth
                ahead  = (VIEW_SIZE - 1) - c
                side   = r - mid
                label  = _cell_desc(image[r][c])
                side_s = ("L" if side < 0 else "R" if side > 0 else "C")
                cells[f"{ahead}_{side_s}"] = label

    front = cells.get("1_C", "unknown")

    view_parts = []
    for ahead in range(VIEW_SIZE - 1, -1, -1):
        row = []
        for side_s in (["L", "C", "R"] if VIEW_SIZE >= 3 else ["C"]):
            k = f"{ahead}_{side_s}"
            v = cells.get(k, "?")
            tag = "[YOU]" if ahead == 0 and side_s == "C" else v
            row.append(tag)
        prefix = f"  {ahead} step{'s' if ahead != 1 else ''} ahead:" if ahead > 0 else "  Your cell:"
        view_parts.append(f"{prefix} {' | '.join(row)}")

    # ── last action outcome ────────────────────────────────────────────────
    last_outcome = "none yet"
    if recent_history:
        last = recent_history[-1]
        a, r = last.get("action"), last.get("reward")
        name = _ACTION_SHORT.get(a, str(a))
        last_outcome = f"{name} → {_interpret_reward(a, r)}"

    # ── inventory ──────────────────────────────────────────────────────────
    if carrying is not None:
        obj_e = entities.get(f"object_{carrying}", {})
        inv = f"carrying obj_{carrying} ({'TARGET' if obj_e.get('is_target') else 'DECOY'})"
    elif engaged:
        obj_e_eng  = entities.get(f"object_{engaged[0]}", {})
        req_eng    = obj_e_eng.get("required_agents", 1)
        gpos_eng   = _obj_grid_pos(grid_cells, engaged[0], obj_e_eng.get("is_target", True))
        if req_eng > 1 and gpos_eng is not None:
            inv = (f"PARTIAL LATCH on obj_{engaged[0]} at {gpos_eng} "
                   f"(needs {req_eng} agents — partner has NOT yet latched)")
        else:
            inv = f"FULL cooperative hold on obj_{engaged[0]}"
    else:
        inv = "empty hands"

    # ── object status (positions from the belief grid) ─────────────────────
    obj_lines = []
    for oid in range(len(_PRIOR_OBJECTS)):
        obj_e  = entities.get(f"object_{oid}", {})
        kind   = "TARGET" if obj_e.get("is_target") else "DECOY"
        req    = obj_e.get("required_agents", 1)
        status = obj_e.get("status", "available")
        gpos   = _obj_grid_pos(grid_cells, oid, obj_e.get("is_target", False))
        dist   = _manhattan(pos, gpos) if gpos else "?"
        if status == "delivered" or oid in delivered:
            obj_lines.append(f"  obj_{oid} [{kind}]: DELIVERED")
        elif oid == carrying:
            obj_lines.append(f"  obj_{oid} [{kind}]: YOU ARE CARRYING IT")
        elif oid in engaged:
            gpos_e = _obj_grid_pos(grid_cells, oid, obj_e.get("is_target", True))
            if req > 1 and gpos_e is not None:
                obj_lines.append(
                    f"  obj_{oid} [{kind}]: PARTIAL LATCH — you latched (1 of {req} agents), "
                    f"object still at {gpos_e}. Partner must also PICK_OR_INTERACT on it!"
                )
            else:
                obj_lines.append(
                    f"  obj_{oid} [{kind}]: FULL cooperative hold — object is jointly carried"
                )
        elif gpos:
            obj_lines.append(
                f"  obj_{oid} [{kind}, needs {req} agent(s)]: "
                f"at {gpos}, ~{dist} steps from you"
            )
        else:
            obj_lines.append(f"  obj_{oid} [{kind}, needs {req} agent(s)]: not on grid")

    # ── precomputed signals ────────────────────────────────────────────────
    on_delivery_zone = list(pos) in [list(c) for c in _DELIVERY_ZONE]
    front_blocked    = (front == "WALL" or front.startswith("AGENT"))

    # NAV_HINT — differentiates partial latch (wait for partner) vs full hold (deliver)
    nav_hint_str = "none"
    if carrying is not None:
        # Solo carrying: navigate to delivery zone
        goal      = min(_DELIVERY_ZONE, key=lambda c: _manhattan(pos, c))
        act, note = _smart_nav_hint(pos, direction, goal, grid_cells)
        nav_hint_str = f"{_ACTION_SHORT.get(act, str(act))} [{note}] → goal: delivery zone {goal}"
    elif engaged:
        obj_e_eng = entities.get(f"object_{engaged[0]}", {})
        req_eng   = obj_e_eng.get("required_agents", 1)
        gpos_eng  = _obj_grid_pos(grid_cells, engaged[0], obj_e_eng.get("is_target", True))
        if req_eng > 1 and gpos_eng is not None:
            # Partial latch: object still on grid — partner has NOT yet latched.
            # Stay near the object and COOPERATE so the partner can also latch.
            nav_hint_str = (
                f"COOPERATE [PARTIAL LATCH on obj_{engaged[0]} at {gpos_eng}. "
                f"Object needs {req_eng} agents. Your partner must also face it and "
                f"PICK_OR_INTERACT to complete the hold. Stay in place and COOPERATE!]"
            )
        else:
            # Full cooperative hold: both agents engaged, object off-grid — navigate together
            goal      = min(_DELIVERY_ZONE, key=lambda c: _manhattan(pos, c))
            act, note = _smart_nav_hint(pos, direction, goal, grid_cells)
            nav_hint_str = (
                f"{_ACTION_SHORT.get(act, str(act))} [FULL hold on obj_{engaged[0]} — "
                f"both agents engaged. Navigate to delivery zone {goal} in sync. {note}]"
            )
    else:
        best_goal, best_dist_val, best_blocked = None, float("inf"), True
        for oid in range(len(_PRIOR_OBJECTS)):
            obj_e = entities.get(f"object_{oid}", {})
            if not obj_e.get("is_target", False):
                continue
            if obj_e.get("status") in ("delivered", "carried_by_self"):
                continue
            gpos_t = _obj_grid_pos(grid_cells, oid, True)
            if gpos_t:
                d       = _manhattan(pos, gpos_t)
                blocked = _primary_direction_blocked(pos, gpos_t, grid_cells)
                # Prefer closer target; on tie prefer the one with unblocked primary direction
                if d < best_dist_val or (d == best_dist_val and best_blocked and not blocked):
                    best_dist_val, best_goal, best_blocked = d, gpos_t, blocked
        if best_goal:
            act, note    = _smart_nav_hint(pos, direction, best_goal, grid_cells)
            nav_hint_str = (
                f"{_ACTION_SHORT.get(act, str(act))} [{note}] → goal: target at {best_goal} "
                f"(~{best_dist_val} steps)"
            )
        else:
            nav_hint_str = "explore — no undelivered target on grid"

    # ── grid summary ───────────────────────────────────────────────────────
    explored    = _grid_explored(grid_cells) if grid_cells else 0
    grid_ascii  = _render_grid_ascii(grid_cells, pos) if grid_cells else "(no grid)"

    lines = [
        f"STEP {step} | pos={pos} | facing={dir_name} | room={_room_name(pos[0])}",
        f"IN FRONT: {front}",
        f"front_blocked={front_blocked}",
        f"on_delivery_zone={on_delivery_zone}",
        f"INVENTORY: {inv}",
        f"LAST ACTION: {last_outcome}",
        f"NAV_HINT: {nav_hint_str}",
        "",
        "OBJECT STATUS:",
        *obj_lines,
        "",
        f"BELIEF GRID ({explored}/144 cells explored):",
        "(legend: @=you  D=delivery_zone  0/1=target  d=decoy  #=wall  .=empty  ?=unknown)",
        grid_ascii,
        "",
        "LOCAL VIEW (rows = steps ahead, cols = left|center|right):",
        *view_parts,
    ]
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# BELIEF STATE LOGGER
# ═══════════════════════════════════════════════════════════════════════════════

def _print_belief_state(agent_id: str, entities: dict, step: int) -> None:
    """Print a full belief state snapshot for one agent to stdout (→ log file)."""
    self_e     = entities.get("self", {})
    grid_cells = entities.get("grid", {}).get("cells", [])
    pos        = self_e.get("position", "?")
    direction  = self_e.get("direction", "?")
    dir_name   = DIRECTION_NAMES.get(direction, str(direction))
    carrying   = self_e.get("carrying_object_id")
    engaged    = self_e.get("engaged_object_ids", [])
    delivered  = self_e.get("delivered_object_ids", [])
    explored   = _grid_explored(grid_cells)

    sep = "  " + "-" * 50
    print(sep)
    print(f"  [BELIEF {agent_id} @ step {step}]")
    print(f"    pos={pos}  facing={dir_name}  carrying={carrying}  "
          f"engaged={engaged}  delivered={delivered}")
    for oid in range(len(_PRIOR_OBJECTS)):
        obj_e  = entities.get(f"object_{oid}", {})
        kind   = "TARGET" if obj_e.get("is_target") else "DECOY"
        status = obj_e.get("status", "?")
        gpos   = _obj_grid_pos(grid_cells, oid, obj_e.get("is_target", False))
        print(f"    obj_{oid}[{kind}]  status={status}  grid_pos={gpos}")
    print(f"    Grid ({explored}/144 explored)  "
          f"legend: @=self D=delivery 0/1=target d=decoy #=wall .=empty ?=unknown")
    grid_pos = pos if isinstance(pos, list) else [0, 0]
    for line in _render_grid_ascii(grid_cells, grid_pos).split("\n"):
        print(f"    {line}")
    print(sep)


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN LOOP
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    _log = _Tee(os.path.join(_ENV_DIR, "cst_demo_log.txt"))
    sys.stdout = _log

    config = EnvConfig(
        width=12, height=12,
        num_agents=2, num_objects=4, num_target_objects=2,
        max_steps=200, agent_view_size=3,
        render_mode="human", seed=42,
    )

    env = MultiAgentCooperativeSearchTransportEnv(config=config)
    observations, _ = env.reset(seed=42)

    print("\n" + "=" * 70)
    print("COOPERATIVE SEARCH & TRANSPORT  —  LLM AGENTS  (POMDP)")
    print("=" * 70)

    lm = dspy.LM(model=LLM_MODEL, api_base=LLM_BASE, api_key="ollama", cache=False)
    dspy.configure(lm=lm)

    controllers:  Dict[str, Agent] = {}
    middlewares:  Dict[str, MiddlewareOrchestrator] = {}

    env.render()
    time.sleep(0.5)

    step = 0
    while env.agents:
        step += 1
        actions = {}

        for agent_id in env.agents:
            if agent_id not in controllers:
                initial_ents = _build_initial_entities(agent_id)
                mw = MiddlewareOrchestrator(
                    env=env,
                    agent_id=agent_id,
                    LLM_model=lm,
                    scenario_description=get_scenario_description(agent_id),
                    goal_description=get_goal_description(agent_id),
                    action_space=ACTIONS_DETAILS,
                    environment_name="CooperativeSearchTransport",
                    observation_spec=get_observation_spec(),
                    # ── belief system ──────────────────────────────────────
                    entity_schema=CST_ENTITY_SCHEMA,
                    initial_entities=initial_ents,
                    obs_parser_fn=parse_cst_obs,
                    prior_knowledge=_PRIOR_KNOWLEDGE_TEMPLATE,
                    history_window=6,
                    belief_updater_kwargs={"grid_width": 12, "grid_height": 12},
                )
                middlewares[agent_id] = mw
                controllers[agent_id] = Agent(
                    agent_id=agent_id,
                    scenario_description=get_scenario_description(agent_id),
                    goal_description=get_goal_description(agent_id),
                    action_space=ACTIONS_DETAILS,
                    LLM_model=lm,
                    middleware=mw,
                )
                print(f"[init] controller ready for {agent_id}")

            # Get current entity state for tactical summary
            mw       = middlewares[agent_id]
            entities = mw.belief_manager.updater.get_all_entities()
            tactical = summarize_cst_obs(
                observations[agent_id], entities, step,
                recent_history=mw.belief_manager.history_as_json,
            )

            raw = controllers[agent_id].choose_action_with_tactical_info(
                observations[agent_id], tactical
            )
            actions[agent_id] = max(0, min(6, int(raw)))

        observations, rewards, terminations, truncations, _ = env.step(actions)
        env.render()

        # Update each agent's belief from the step outcome (POMDP dead-reckoning)
        for agent_id in sorted(actions):
            if agent_id in middlewares:
                middlewares[agent_id].update_belief(
                    actions[agent_id],
                    rewards.get(agent_id, -0.01),
                    observations.get(agent_id, {}),
                )
                entities_after = middlewares[agent_id].belief_manager.updater.get_all_entities()
                _print_belief_state(agent_id, entities_after, step)

        act_str = "  ".join(
            f"{aid}={ACTION_NAMES.get(actions[aid], actions[aid])}"
            for aid in sorted(actions)
        )
        rew_str = "  ".join(
            f"{aid}={rewards[aid]:+.2f}" for aid in sorted(rewards)
        )
        print(f"Step {step:3d} | {act_str} | {rew_str}")

        if all(terminations.values()):
            print("\n✓  SUCCESS — all targets delivered!")
            break
        if all(truncations.values()):
            print("\n✗  Episode truncated (max steps reached)")
            break

        time.sleep(0.1)

    env.close()
    print("\nEpisode finished.")
    sys.stdout = sys.__stdout__
    _log.close()


if __name__ == "__main__":
    main()
