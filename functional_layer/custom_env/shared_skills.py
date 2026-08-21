"""
Env-agnostic skill scaffolding shared across the custom grid environments
(CooperativeSearchTransport, BoxPush).

This module holds the pieces that are NOT specific to any one task — MiniGrid cell
decoding, grid navigation (BFS / frontier exploration), and the BaseSkill lifecycle
plus the generic explore/wait skills. Env-specific skills (carry vs. push) and the
per-env skill factories live in each env's own skill_executor module and import the
primitives from here, so no env depends on another.

Constants (Actions / DIRECTION_VECTORS) are the canonical shared definitions kept in
the CST env's constants.py; this module bootstraps that onto sys.path so it can be
imported from any working directory.
"""
import sys
import os

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_CST_ENV  = os.path.join(_THIS_DIR, "cooperative_search_transport", "env")
if _CST_ENV not in sys.path:
    sys.path.insert(0, _CST_ENV)

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


# ── Generic skills ────────────────────────────────────────────────────────────

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


class WaitSkill(BaseSkill):
    """Stay in place; completes immediately."""

    def __init__(self, agent_id: str):
        super().__init__(agent_id)
        self.done  = True
        self.label = "done"

    def step(self, obs: dict, entities: dict) -> int:
        return int(Actions.STAY)
