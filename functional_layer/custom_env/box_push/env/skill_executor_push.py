"""
Box-Push skills — granular, single-purpose, composed by the centralized LLM.

    explore         -> found_target | found_decoy | explored        (reused from CST)
    goto_push_pose  -> in_position | none_known | blocked
    push            -> pushed | delivered | too_heavy | blocked      (single-agent / light)
    cooperate_push  -> moved | delivered | waiting_partner | blocked  (heavy, 2 agents)
    wait            -> done                                           (reused from CST)

Navigation/exploration helpers and ExploreSkill/WaitSkill/BaseSkill are imported from
the CST skill_executor (identical logic — no need to duplicate).
"""
import sys
import os

_THIS_DIR  = os.path.dirname(os.path.abspath(__file__))
_CST_ENV   = os.path.abspath(os.path.join(_THIS_DIR, "../../cooperative_search_transport/env"))
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "../../../.."))
for _p in (_REPO_ROOT, _CST_ENV, _THIS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from typing import Optional, List, Tuple
from collections import deque
from constants import Actions, Directions, DIRECTION_VECTORS

# Reuse CST scaffolding verbatim.
from skill_executor import (
    BaseSkill, ExploreSkill, WaitSkill,
    _bfs_next_action, _frontier_explore, _nearest_target_cell,
    _get_front_cell, _manhattan, _dir_to_action,
)
from box_push_env import GOAL_ZONE

_BLOCKING = ("wall", "agent")  # treated as obstacles for box destinations


def _push_dir_toward_goal(box) -> int:
    """Direction (Directions int) to push `box` toward the nearest goal cell."""
    gx, gy = min(GOAL_ZONE, key=lambda c: _manhattan(box, c))
    dx, dy = gx - box[0], gy - box[1]
    if abs(dx) >= abs(dy) and dx != 0:
        return int(Directions.RIGHT) if dx > 0 else int(Directions.LEFT)
    if dy != 0:
        return int(Directions.DOWN) if dy > 0 else int(Directions.UP)
    return int(Directions.LEFT)


def _cell_label(grid, x, y) -> str:
    if 0 <= x < len(grid) and 0 <= y < len(grid[0]):
        return grid[x][y]
    return "wall"


def _nav_blocked(cell: str) -> bool:
    """Cells impassable for navigation. Unlike CST, BOXES are obstacles here — only
    PushSkill/cooperate_push may move into a box; plain navigation must route around
    them, otherwise the agent bulldozes boxes (e.g. into walls) while repositioning."""
    return cell in ("wall", "agent") or cell.startswith("target")


def _bfs_avoid_boxes(pos, goal, direction: int, grid) -> int:
    """BFS toward `goal` treating walls/agents/boxes as obstacles ('unknown' passable).
    Returns the first primitive action; TURN_RIGHT to re-scan if no path is found."""
    start = (int(pos[0]), int(pos[1]))
    goal  = (int(goal[0]), int(goal[1]))
    if start == goal:
        return int(Actions.STAY)
    W = len(grid)
    H = len(grid[0]) if W > 0 else 0
    q: deque = deque()
    seen = {start}
    for d, (dx, dy) in DIRECTION_VECTORS.items():
        nx, ny = start[0] + dx, start[1] + dy
        if 0 <= nx < W and 0 <= ny < H and not _nav_blocked(grid[nx][ny]):
            q.append(((nx, ny), int(d)))
            seen.add((nx, ny))
    while q:
        (x, y), first_dir = q.popleft()
        if (x, y) == goal:
            return _dir_to_action(direction, first_dir)
        for d, (dx, dy) in DIRECTION_VECTORS.items():
            nx, ny = x + dx, y + dy
            if 0 <= nx < W and 0 <= ny < H and (nx, ny) not in seen and not _nav_blocked(grid[nx][ny]):
                seen.add((nx, ny))
                q.append(((nx, ny), first_dir))
    return int(Actions.TURN_RIGHT)


_GOAL_SET = {tuple(c) for c in GOAL_ZONE}


def _is_goal(cell) -> bool:
    return tuple(cell) in _GOAL_SET


def _nearest_undelivered_target(grid, pos):
    """Nearest discovered target cell NOT already sitting on the goal (those are done)."""
    best, best_d = None, float("inf")
    for x, col in enumerate(grid):
        for y, cell in enumerate(col):
            if cell.startswith("target") and (x, y) not in _GOAL_SET:
                d = _manhattan(pos, (x, y))
                if d < best_d:
                    best_d, best = d, [x, y]
    return best


# ── goto_push_pose ──────────────────────────────────────────────────────────────

class GotoPushPoseSkill(BaseSkill):
    """Navigate BEHIND the LLM-chosen target box (side away from goal), facing the push dir.

    `box` is the [x, y] cell the planner wants this agent to handle. When omitted, falls
    back to the nearest undelivered target so the skill is still usable without an arg.
    """

    _MAX_STEPS   = 40   # backstop: bail well before the 150 default
    _NO_PROGRESS = 8    # bail if we reach no NEW cell for this many steps (frozen/oscillating)

    def __init__(self, agent_id: str, box: Optional[Tuple[int, int]] = None):
        super().__init__(agent_id)
        self._box_arg = tuple(box) if box is not None else None
        self._seen_pos: set = set()
        self._stale = 0

    def _resolve_box(self, grid, pos):
        # Trust the planner's box if it is still a known, undelivered target.
        if self._box_arg is not None:
            bx, by = self._box_arg
            if (0 <= bx < len(grid) and 0 <= by < len(grid[0])
                    and grid[bx][by].startswith("target")
                    and (bx, by) not in _GOAL_SET):
                return [bx, by]
        return _nearest_undelivered_target(grid, pos)

    def step(self, obs: dict, entities: dict) -> int:
        if self.done:
            return int(Actions.STAY)
        self_e = entities.get("self", {})
        pos    = self_e.get("position", [0, 0])
        grid   = entities.get("grid", {}).get("cells", [])
        box    = self._resolve_box(grid, pos)
        if box is None:
            return self._finish("none_known")

        push_dir = _push_dir_toward_goal(box)
        dx, dy   = DIRECTION_VECTORS[Directions(push_dir)]
        behind   = [box[0] - dx, box[1] - dy]

        if list(pos) == behind:
            if int(self_e.get("direction", 2)) == push_dir:
                return self._finish("in_position")
            return _dir_to_action(int(self_e.get("direction", 2)), push_dir)

        # Bail fast if we reach no NEW cell for a while. The shared map records agents as
        # 'empty', so a stationary partner blocking the route (or sitting on the only push
        # pose) freezes BFS silently — the agent keeps re-issuing a move into the partner and
        # never advances. Legitimate detours keep reaching new cells, so they don't trip this.
        key = (int(pos[0]), int(pos[1]))
        if key not in self._seen_pos:
            self._seen_pos.add(key)
            self._stale = 0
        else:
            self._stale += 1
            if self._stale >= self._NO_PROGRESS:
                return self._finish("blocked")

        self._steps += 1
        if self._timeout():
            self.label = "blocked"
            return int(Actions.STAY)
        unstuck = self._check_stuck(pos)
        if unstuck is not None:
            return unstuck
        return _bfs_avoid_boxes(pos, behind, int(self_e.get("direction", 2)), grid)


# ── push (single agent / light box) ──────────────────────────────────────────────

class PushSkill(BaseSkill):
    """Push the box in front, cell-by-cell, toward an LLM-supplied destination.

    A real multi-step skill (not a single action): it keeps issuing MOVE_FORWARD,
    re-checking the belief after each push, until the box reaches `dest` (→ pushed),
    lands on the goal (→ delivered), or a push fails (→ too_heavy / blocked). When
    `dest` is omitted it pushes straight ahead until the box is delivered or stops.
    """
    _MAX_STEPS = 30

    def __init__(self, agent_id: str, dest: Optional[Tuple[int, int]] = None):
        super().__init__(agent_id)
        self._dest = tuple(dest) if dest is not None else None
        self._issued = False
        self._expect_pos: Optional[Tuple[int, int]] = None  # where we'll stand if the push works
        self._land:       Optional[Tuple[int, int]] = None  # where the box will land

    def step(self, obs: dict, entities: dict) -> int:
        if self.done:
            return int(Actions.STAY)
        self_e = entities.get("self", {})
        pos    = self_e.get("position", [0, 0])
        d      = int(self_e.get("direction", 2))
        grid   = entities.get("grid", {}).get("cells", [])
        dx, dy = DIRECTION_VECTORS[Directions(d)]

        # Evaluate the push we issued last primitive step.
        if self._issued:
            self._issued = False
            if list(pos) == list(self._expect_pos):       # advanced → box slid one cell
                if _is_goal(self._land):
                    return self._finish("delivered")
                if self._dest is not None and tuple(self._land) == self._dest:
                    return self._finish("pushed")
                # else: keep pushing toward dest (fall through to issue the next push)
            else:                                          # agent didn't move → push failed
                beyond = _cell_label(grid, self._land[0], self._land[1])
                if beyond in _BLOCKING or beyond.startswith("target"):
                    return self._finish("blocked")
                return self._finish("too_heavy")

        # Issue the next push if a box is still in front.
        if _get_front_cell(obs) != "TARGET_OBJECT":
            return self._finish("blocked")  # nothing (more) to push in front
        self._steps += 1
        if self._timeout():
            self.label = "pushed"           # progress made, just out of budget this cycle
            return int(Actions.STAY)
        self._expect_pos = (pos[0] + dx, pos[1] + dy)
        self._land       = (pos[0] + 2 * dx, pos[1] + 2 * dy)
        self._issued = True
        return int(Actions.MOVE_FORWARD)


# ── cooperate_push (heavy box, 2 agents) ──────────────────────────────────────────

class CooperativePushSkill(BaseSkill):
    """
    Push a HEAVY box to the goal with two agents in TANDEM (in-line). The agents line up
    directly behind the box along the push axis — A1 at B-D, A2 at B-2D (B = box, D = push
    direction) — both facing D. When both are in their slots, a joint MOVE_FORWARD slides
    box + both agents one cell (env's tandem rule). A real multi-step skill: after each
    joint move the formation is preserved (A1 lands on the new B-D, A2 on the new B-2D),
    so it keeps pushing until the box is delivered / blocked / out of budget. Handles its
    own positioning from the partner's belief. Must be assigned to BOTH agents in the same
    cycle.
    """

    _WAIT_LIMIT = 10   # give up waiting if the partner stops converging on its slot

    def __init__(self, agent_id: str, partner_id: str,
                 box: Optional[Tuple[int, int]] = None):
        super().__init__(agent_id)
        self.partner_id = partner_id
        self._box_arg = tuple(box) if box is not None else None
        self._issued = False
        self._start_pos: Optional[List[int]] = None
        self._dest: Optional[Tuple[int, int]] = None
        self._wait = 0
        self._best_pd: Optional[float] = None   # partner's best distance to its slot

    def _resolve_box(self, grid, pos):
        if self._box_arg is not None:
            bx, by = self._box_arg
            if (0 <= bx < len(grid) and 0 <= by < len(grid[0])
                    and grid[bx][by].startswith("target")
                    and (bx, by) not in _GOAL_SET):
                return [bx, by]
        return _nearest_undelivered_target(grid, pos)

    def _assign_slots(self, box, push_dir, pos, partner_pos):
        """Tandem slots: A1 = B-D (front, against the box), A2 = B-2D (rear). Assign
        deterministically — whoever is closer to the front slot is A1; ties by agent_id —
        so both agents agree without negotiation. Returns (my_slot, partner_slot)."""
        bx, by = box
        dx, dy = DIRECTION_VECTORS[Directions(push_dir)]
        a1 = (bx - dx, by - dy)
        a2 = (bx - 2 * dx, by - 2 * dy)
        d_self = _manhattan(pos, a1)
        d_part = _manhattan(partner_pos, a1) if partner_pos is not None else float("inf")
        i_am_a1 = d_self < d_part or (d_self == d_part and self.agent_id < self.partner_id)
        return (a1, a2) if i_am_a1 else (a2, a1)

    def step(self, obs: dict, entities: dict, partner_entities: Optional[dict] = None) -> int:
        if self.done:
            return int(Actions.STAY)
        self_e = entities.get("self", {})
        pos    = self_e.get("position", [0, 0])
        d      = int(self_e.get("direction", 2))
        grid   = entities.get("grid", {}).get("cells", [])
        box    = self._resolve_box(grid, pos)
        if box is None:
            return self._finish("none_known")

        push_dir = _push_dir_toward_goal(box)
        dx, dy   = DIRECTION_VECTORS[Directions(push_dir)]
        dest     = (box[0] + dx, box[1] + dy)
        if _cell_label(grid, dest[0], dest[1]) in _BLOCKING:
            return self._finish("blocked")   # box's destination (B+D) is walled/occupied

        my_slot, partner_slot = self._assign_slots(box, push_dir, pos, partner_pos=
                                (partner_entities or {}).get("self", {}).get("position"))
        # The tandem runway behind the box must be clear floor.
        for sx, sy in (my_slot, partner_slot):
            lbl = _cell_label(grid, sx, sy)
            if lbl == "wall" or lbl.startswith("target"):
                return self._finish("blocked")

        p_self = (partner_entities or {}).get("self", {})
        partner_pos = p_self.get("position")
        partner_dir = p_self.get("direction")

        ready         = list(pos) == list(my_slot) and d == push_dir
        partner_ready = (partner_pos is not None
                         and tuple(partner_pos) == tuple(partner_slot)
                         and partner_dir is not None and int(partner_dir) == push_dir)

        # Push evaluation (after we issued a joint MOVE_FORWARD)
        if self._issued:
            self._issued = False
            if list(pos) != list(self._start_pos):       # advanced → joint push moved the box
                if _is_goal(self._dest):
                    return self._finish("delivered")
                # Keep pushing toward the goal: the tandem formation is preserved, so the
                # ready/partner_ready checks below will re-issue the next joint move.

        self._steps += 1
        if self._timeout():
            self.label = "waiting_partner"
            return int(Actions.STAY)

        if ready and partner_ready:
            self._wait, self._best_pd = 0, None
            self._issued = True
            self._start_pos = list(pos)
            self._dest = dest
            return int(Actions.MOVE_FORWARD)

        if ready and not partner_ready:
            # I'm in my slot; hold — but only while the partner is actually converging on
            # its slot. If it stops getting closer for a while (e.g. the planner put it on
            # a different skill), give up fast instead of burning the whole budget.
            pd = _manhattan(partner_pos, partner_slot) if partner_pos is not None else float("inf")
            if self._best_pd is None or pd < self._best_pd:
                self._best_pd, self._wait = pd, 0
            else:
                self._wait += 1
                if self._wait >= self._WAIT_LIMIT:
                    return self._finish("waiting_partner")
            return int(Actions.STAY)

        self._wait, self._best_pd = 0, None
        # Not in my slot yet → navigate to it. Route partner-aware: the shared map shows
        # agents as 'empty', so treat the partner's current cell as an obstacle, otherwise
        # we walk into the partner (who sits in the tandem line) and freeze.
        if list(pos) == list(my_slot):
            return _dir_to_action(d, push_dir)  # at the slot, just face the push direction
        nav_grid = grid
        if partner_pos is not None:
            nav_grid = [col[:] for col in grid]
            px, py = int(partner_pos[0]), int(partner_pos[1])
            if 0 <= px < len(nav_grid) and 0 <= py < len(nav_grid[0]):
                nav_grid[px][py] = "agent"
        unstuck = self._check_stuck(pos)
        if unstuck is not None:
            return unstuck
        return _bfs_avoid_boxes(pos, list(my_slot), d, nav_grid)


# ── Factory ───────────────────────────────────────────────────────────────────

def make_skill(agent_id: str, skill_name: str,
               arg: Optional[Tuple[int, int]] = None,
               partner_id: Optional[str] = None) -> BaseSkill:
    """`arg` is the LLM-supplied (x, y): the box cell for goto_push_pose/cooperate_push,
    the destination cell for push. None falls back to nearest-target behaviour."""
    if skill_name == "explore":
        return ExploreSkill(agent_id)
    if skill_name == "goto_push_pose":
        return GotoPushPoseSkill(agent_id, arg)
    if skill_name == "push":
        return PushSkill(agent_id, arg)
    if skill_name == "cooperate_push":
        return CooperativePushSkill(agent_id, partner_id or "", arg)
    return WaitSkill(agent_id)
