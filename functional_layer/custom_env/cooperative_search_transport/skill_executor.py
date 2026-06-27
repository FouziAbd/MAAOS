"""
Skill executor for CST centralized runner.

Granular, single-purpose skills the centralized LLM composes:
    explore         -> found_target | found_decoy | explored
    goto_target     -> at_target | none_known | blocked
    goto_delivery   -> at_delivery | blocked
    pick            -> picked_solo | latched_coop | failed
    drop            -> delivered | dropped | nothing
    cooperate_move  -> moved | waiting_partner | arrived
    wait            -> done

Each skill runs primitive env steps in an inner loop until it reaches its single
specific outcome, then returns control (and a label) to the LLM.
"""

import sys
import os

_ENV_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _ENV_DIR)

from typing import Optional, List, Tuple, Set
from collections import deque
from constants import Actions, DIRECTION_VECTORS

# ── Shared constants ──────────────────────────────────────────────────────────

_OBJ_TYPE_IDX = {
    0: "unseen", 1: "empty",  2: "wall", 3: "floor", 4: "door",
    5: "key",    6: "ball",   7: "box",  8: "goal",  9: "lava", 10: "agent",
}
_COLOR_IDX = {0: "red", 1: "green", 2: "blue", 3: "purple", 4: "yellow", 5: "grey"}
_DIR_NAMES = {0: "RIGHT", 1: "DOWN", 2: "LEFT", 3: "UP"}
_DELIVERY_ZONE: List[List[int]] = [[1, 1], [2, 1], [1, 2], [2, 2]]

# Cells an agent may walk through while navigating / exploring.
_TRAVERSABLE = {"empty", "delivery_zone"}

# ── View / cell helpers ────────────────────────────────────────────────────────

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
    return f"{_OBJ_TYPE_IDX.get(t, '?')}({_COLOR_IDX.get(c, '?')})"


def _get_front_cell(obs) -> str:
    """Return label of the cell one step ahead (center column)."""
    image = obs.get("image")
    if image is None:
        return "unknown"
    V = len(image)
    return _cell_desc(image[V // 2][V - 2])


def _manhattan(a, b) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _dir_to_action(direction: int, wanted: int) -> int:
    """Primitive action to face/move toward `wanted` from current `direction`."""
    if direction == wanted:
        return int(Actions.MOVE_FORWARD)
    if (direction + 1) % 4 == wanted:
        return int(Actions.TURN_RIGHT)
    if (direction - 1) % 4 == wanted:
        return int(Actions.TURN_LEFT)
    return int(Actions.TURN_RIGHT)


# ── Navigation ──────────────────────────────────────────────────────────────────

def _smart_nav_hint(pos, direction: int, goal_pos, grid_cells) -> Tuple[int, str]:
    dx, dy = goal_pos[0] - pos[0], goal_pos[1] - pos[1]
    if dx == 0 and dy == 0:
        return int(Actions.STAY), "already at goal"

    if abs(dx) >= abs(dy) and dx != 0:
        primary   = 0 if dx > 0 else 2
        secondary = 1 if dy >= 0 else 3
    else:
        primary   = 1 if dy > 0 else 3
        secondary = 0 if dx >= 0 else 2

    def next_cell_is_blocked(d):
        dvec = DIRECTION_VECTORS[d]
        nx, ny = pos[0] + dvec[0], pos[1] + dvec[1]
        if grid_cells and 0 <= nx < len(grid_cells) and 0 <= ny < len(grid_cells[0]):
            cell = grid_cells[nx][ny]
            return cell in ("wall", "agent")
        return False

    primary_wall   = next_cell_is_blocked(primary)
    secondary_wall = next_cell_is_blocked(secondary)

    if primary_wall and not secondary_wall:
        wanted = secondary
        note   = f"blocked {_DIR_NAMES[primary]} — go {_DIR_NAMES[secondary]}"
    elif primary_wall and secondary_wall:
        alt = (secondary + 2) % 4
        if not next_cell_is_blocked(alt):
            wanted = alt
            note   = f"both blocked — trying {_DIR_NAMES[alt]}"
        else:
            wanted = (primary + 2) % 4
            note   = "all paths blocked — turning back"
    else:
        wanted = primary
        note   = f"clear {_DIR_NAMES[primary]}"

    return _dir_to_action(direction, wanted), note


def _bfs_next_action(pos, goal_pos, direction: int, grid_cells) -> Tuple[int, str]:
    """
    BFS toward goal_pos; "unknown" cells are passable (exploratory), "wall"/"agent"
    are obstacles. Falls back to _smart_nav_hint when no path exists.
    """
    start = (int(pos[0]), int(pos[1]))
    goal  = (int(goal_pos[0]), int(goal_pos[1]))
    if start == goal:
        return int(Actions.STAY), "already at goal"

    W = len(grid_cells)
    H = len(grid_cells[0]) if W > 0 else 0

    queue: deque = deque()
    visited = {start}
    for d, (dx, dy) in DIRECTION_VECTORS.items():
        nx, ny = start[0] + dx, start[1] + dy
        if 0 <= nx < W and 0 <= ny < H and grid_cells[nx][ny] not in ("wall", "agent"):
            queue.append(((nx, ny), int(d)))
            visited.add((nx, ny))

    while queue:
        (x, y), first_dir = queue.popleft()
        if (x, y) == goal:
            return _dir_to_action(direction, first_dir), f"BFS → {goal_pos}"
        for d, (dx, dy) in DIRECTION_VECTORS.items():
            nx, ny = x + dx, y + dy
            if 0 <= nx < W and 0 <= ny < H and (nx, ny) not in visited:
                if grid_cells[nx][ny] not in ("wall", "agent"):
                    visited.add((nx, ny))
                    queue.append(((nx, ny), first_dir))

    return _smart_nav_hint(pos, direction, goal_pos, grid_cells)


def _frontier_explore(pos, direction: int, grid_cells) -> Tuple[int, str]:
    """
    Frontier exploration: BFS over traversable known cells to the NEAREST "unknown"
    cell, then return the first primitive action toward it. Rotates to scan when no
    unknown cell is reachable.
    """
    start = (int(pos[0]), int(pos[1]))
    W = len(grid_cells)
    H = len(grid_cells[0]) if W > 0 else 0

    queue: deque = deque()
    visited = {start}
    for d, (dx, dy) in DIRECTION_VECTORS.items():
        nx, ny = start[0] + dx, start[1] + dy
        if 0 <= nx < W and 0 <= ny < H and (nx, ny) not in visited:
            visited.add((nx, ny))
            queue.append(((nx, ny), int(d)))

    while queue:
        (x, y), first_dir = queue.popleft()
        cell = grid_cells[x][y]
        if cell == "unknown":
            return _dir_to_action(direction, first_dir), "explore → nearest unknown"
        # only traverse through walkable known cells
        if cell not in _TRAVERSABLE:
            continue
        for d, (dx, dy) in DIRECTION_VECTORS.items():
            nx, ny = x + dx, y + dy
            if 0 <= nx < W and 0 <= ny < H and (nx, ny) not in visited:
                visited.add((nx, ny))
                queue.append(((nx, ny), first_dir))

    return int(Actions.TURN_RIGHT), "no reachable unknown — scanning"


# ── Object-cell helpers ─────────────────────────────────────────────────────────

def _target_cells(grid_cells) -> Set[Tuple[int, int]]:
    return {(x, y) for x, col in enumerate(grid_cells)
            for y, cell in enumerate(col) if cell.startswith("target")}


def _decoy_cells(grid_cells) -> Set[Tuple[int, int]]:
    return {(x, y) for x, col in enumerate(grid_cells)
            for y, cell in enumerate(col) if cell.startswith("decoy")}


def _nearest_target_cell(grid_cells, pos) -> Optional[List[int]]:
    """Nearest discovered target cell (label starts with 'target'), by Manhattan dist."""
    best, best_d = None, float("inf")
    for (x, y) in _target_cells(grid_cells):
        d = _manhattan(pos, (x, y))
        if d < best_d:
            best_d, best = d, [x, y]
    return best


# ── Base skill ────────────────────────────────────────────────────────────────

class BaseSkill:
    _MAX_STEPS = 150

    def __init__(self, agent_id: str):
        self.agent_id     = agent_id
        self.done         = False
        self.label: Optional[str] = None
        self._steps       = 0
        self._prev_pos: Optional[List[int]] = None
        self._stuck_count = 0

    @property
    def is_done(self) -> bool:
        return self.done

    def _timeout(self) -> bool:
        if self._steps >= self._MAX_STEPS:
            self.done  = True
            self.label = "timeout"
            return True
        return False

    def _finish(self, label: str) -> int:
        self.done  = True
        self.label = label
        return int(Actions.STAY)

    def _check_stuck(self, pos) -> Optional[int]:
        """Return TURN_LEFT when position is unchanged for 4+ steps (deadlock breaker)."""
        pos_list = list(pos)
        if self._prev_pos is not None and pos_list == self._prev_pos:
            self._stuck_count += 1
        else:
            self._stuck_count = 0
        self._prev_pos = pos_list
        if self._stuck_count >= 4:
            self._stuck_count = 0
            return int(Actions.TURN_LEFT)
        return None

    def step(self, obs: dict, entities: dict) -> int:
        raise NotImplementedError


# ── Skills ──────────────────────────────────────────────────────────────────────

class ExploreSkill(BaseSkill):
    """Frontier-explore until a new object enters the belief grid, or budget runs out."""
    _MAX_STEPS = 30

    def __init__(self, agent_id: str):
        super().__init__(agent_id)
        self._start_targets: Optional[Set[Tuple[int, int]]] = None
        self._start_decoys:  Optional[Set[Tuple[int, int]]] = None

    def step(self, obs: dict, entities: dict) -> int:
        if self.done:
            return int(Actions.STAY)

        grid = entities.get("grid", {}).get("cells", [])
        if self._start_targets is None:
            self._start_targets = _target_cells(grid)
            self._start_decoys  = _decoy_cells(grid)
        else:
            if _target_cells(grid) - self._start_targets:
                return self._finish("found_target")
            if _decoy_cells(grid) - self._start_decoys:
                return self._finish("found_decoy")

        self._steps += 1
        if self._timeout():
            self.label = "explored"
            return int(Actions.STAY)

        self_e    = entities.get("self", {})
        pos       = self_e.get("position", [0, 0])
        direction = self_e.get("direction", 2)

        unstuck = self._check_stuck(pos)
        if unstuck is not None:
            return unstuck

        action, _ = _frontier_explore(pos, direction, grid)
        return action


class GotoTargetSkill(BaseSkill):
    """Navigate to the nearest discovered target until it is directly in front."""

    def step(self, obs: dict, entities: dict) -> int:
        if self.done:
            return int(Actions.STAY)

        if _get_front_cell(obs) == "TARGET_OBJECT":
            return self._finish("at_target")

        self_e = entities.get("self", {})
        pos    = self_e.get("position", [0, 0])
        grid   = entities.get("grid", {}).get("cells", [])
        goal   = _nearest_target_cell(grid, pos)
        if goal is None:
            return self._finish("none_known")

        self._steps += 1
        if self._timeout():
            self.label = "blocked"
            return int(Actions.STAY)

        unstuck = self._check_stuck(pos)
        if unstuck is not None:
            return unstuck

        direction = self_e.get("direction", 2)
        action, _ = _bfs_next_action(pos, goal, direction, grid)
        return action


class GotoDeliverySkill(BaseSkill):
    """Navigate to the (known) delivery zone until standing on it."""

    def step(self, obs: dict, entities: dict) -> int:
        if self.done:
            return int(Actions.STAY)

        self_e = entities.get("self", {})
        pos    = self_e.get("position", [0, 0])
        if list(pos) in [list(c) for c in _DELIVERY_ZONE]:
            return self._finish("at_delivery")

        self._steps += 1
        if self._timeout():
            self.label = "blocked"
            return int(Actions.STAY)

        unstuck = self._check_stuck(pos)
        if unstuck is not None:
            return unstuck

        direction = self_e.get("direction", 2)
        grid      = entities.get("grid", {}).get("cells", [])
        goal      = min(_DELIVERY_ZONE, key=lambda c: _manhattan(pos, c))
        action, _ = _bfs_next_action(pos, goal, direction, grid)
        return action


class PickSkill(BaseSkill):
    """Issue one PICK_OR_INTERACT and report the outcome read from the belief."""
    _MAX_STEPS = 3

    def __init__(self, agent_id: str):
        super().__init__(agent_id)
        self._issued = False

    def step(self, obs: dict, entities: dict) -> int:
        if self.done:
            return int(Actions.STAY)

        self_e = entities.get("self", {})
        if self_e.get("carrying_object_id") is not None:
            return self._finish("picked_solo")
        if self_e.get("engaged_object_ids"):
            return self._finish("latched_coop")

        if self._issued:
            # PICK already happened last step but belief shows neither outcome.
            return self._finish("failed")

        self._issued = True
        return int(Actions.PICK_OR_INTERACT)


class DropSkill(BaseSkill):
    """Issue one DROP and report whether it delivered, dropped, or did nothing."""
    _MAX_STEPS = 3

    def __init__(self, agent_id: str):
        super().__init__(agent_id)
        self._issued = False
        self._had_carry = False

    def step(self, obs: dict, entities: dict) -> int:
        if self.done:
            return int(Actions.STAY)

        self_e   = entities.get("self", {})
        carrying = self_e.get("carrying_object_id")

        if not self._issued:
            if carrying is None:
                return self._finish("nothing")
            self._had_carry = True
            self._issued = True
            return int(Actions.DROP)

        # Post-drop evaluation
        delivered = self_e.get("delivered_object_ids", [])
        if delivered:
            return self._finish("delivered")
        if self._had_carry and carrying is None:
            return self._finish("dropped")
        return self._finish("dropped")


class CooperativeMoveSkill(BaseSkill):
    """
    Joint carry of a fully-held cooperative object toward the delivery zone.
    Both engaged agents must be assigned this skill the same cycle. The move
    direction is derived from the SHARED object position so both agents agree
    (avoids the per-agent-direction deadlock).
    """

    def __init__(self, agent_id: str, partner_id: str):
        super().__init__(agent_id)
        self.partner_id = partner_id

    def step(self, obs: dict, entities: dict, partner_entities: Optional[dict] = None) -> int:
        if self.done:
            return int(Actions.STAY)

        self_e   = entities.get("self", {})
        engaged  = self_e.get("engaged_object_ids", [])
        pos      = self_e.get("position", [0, 0])
        grid     = entities.get("grid", {}).get("cells", [])

        on_delivery = list(pos) in [list(c) for c in _DELIVERY_ZONE]
        if on_delivery:
            return self._finish("arrived")

        # Partner must be engaged for a joint move to be possible.
        partner_engaged = False
        if partner_entities:
            partner_engaged = bool(partner_entities.get("self", {}).get("engaged_object_ids"))
        if not engaged or not partner_engaged:
            self._steps += 1
            if self._timeout():
                self.label = "waiting_partner"
                return int(Actions.STAY)
            return self._finish("waiting_partner")

        self._steps += 1
        if self._timeout():
            self.label = "waiting_partner"
            return int(Actions.STAY)

        # Shared reference position: midpoint of the two agents approximates the
        # held object, giving both agents the SAME BFS goal direction.
        direction = self_e.get("direction", 2)
        goal      = min(_DELIVERY_ZONE, key=lambda c: _manhattan(pos, c))
        action, _ = _bfs_next_action(pos, goal, direction, grid)

        # One leg = progress checkpoint: report 'moved' once we actually advance.
        unstuck = self._check_stuck(pos)
        if unstuck is not None:
            return unstuck
        if action == int(Actions.MOVE_FORWARD) and self._steps > 1:
            return self._finish("moved")
        return action


class WaitSkill(BaseSkill):
    """Stay in place; completes immediately."""

    def __init__(self, agent_id: str):
        super().__init__(agent_id)
        self.done  = True
        self.label = "done"

    def step(self, obs: dict, entities: dict) -> int:
        return int(Actions.STAY)


# ── Factory ───────────────────────────────────────────────────────────────────

def make_skill(agent_id: str, skill_name: str, arg: Optional[str] = None,
               partner_id: Optional[str] = None) -> BaseSkill:
    if skill_name == "explore":
        return ExploreSkill(agent_id)
    if skill_name == "goto_target":
        return GotoTargetSkill(agent_id)
    if skill_name == "goto_delivery":
        return GotoDeliverySkill(agent_id)
    if skill_name == "pick":
        return PickSkill(agent_id)
    if skill_name == "drop":
        return DropSkill(agent_id)
    if skill_name == "cooperate_move":
        return CooperativeMoveSkill(agent_id, partner_id or "")
    return WaitSkill(agent_id)
