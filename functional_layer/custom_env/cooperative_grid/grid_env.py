"""CooperativeGrid backend: two agents, one heavy door, one goal room.

A PettingZoo `ParallelEnv` (both agents act every step) over a tiny fixed map:

    #########        # wall     . floor     D the heavy door (closed)
    #A.....B#        A/B agent start cells
    ####D####        the door sits in the wall between the corridor and the goal room;
    #.......#        the two HANDLE cells are the corridor cells diagonally flanking it
    #..GGG..#        G goal cells
    #########

Physics (all deterministic, resolved in agent order A then B within a step):

- `LEFT/RIGHT/UP/DOWN` move one cell unless the target is a wall, the closed door, or the
  cell the other agent occupies; a blocked move is a no-op.
- `PULL` opens the door only when BOTH agents pull in the same step, one on each handle
  cell, the door is closed — and the door is not JAMMED. A jammed door does not move.
  A lone pull never moves the door (it is heavy).
- `SHAKE` by an agent standing on a handle cell clears the jam.
- the episode terminates when both agents stand on goal cells; it truncates at `max_steps`.

`jammed_at_start` is the designed hidden condition: it is part of the physical world the
backend reports (`snapshot().door_jammed`) and nothing in the map shows it to a planner
that reasons only about positions and the door being open or closed.

Rendering is MiniGrid-style (`render_mode="rgb_array"` draws with pygame into an off-screen
surface and returns an ndarray; `"human"` additionally shows a window and paces the frames at
`render_fps`). With `render_mode=None` pygame is never imported: headless is the default.
"""
from __future__ import annotations

import os
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, List, Optional, Tuple

import numpy as np
from gymnasium import spaces
from pettingzoo import ParallelEnv

Cell = Tuple[int, int]

LAYOUT: Tuple[str, ...] = (
    "#########",
    "#A.....B#",
    "####D####",
    "#.......#",
    "#..GGG..#",
    "#########",
)

AGENT_NAMES: Tuple[str, ...] = ("A", "B")
DOOR_NAME = "door"

# ── primitive actions ─────────────────────────────────────────────────────────────────
NOOP, LEFT, RIGHT, UP, DOWN, PULL, SHAKE = range(7)
ACTION_NAMES: Tuple[str, ...] = ("noop", "left", "right", "up", "down", "pull", "shake")
MOVES: Dict[int, Cell] = {LEFT: (-1, 0), RIGHT: (1, 0), UP: (0, -1), DOWN: (0, 1)}

# ── observation encoding (MiniGrid-like: one channel per object kind) ─────────────────
OBJ_FLOOR, OBJ_WALL, OBJ_DOOR_CLOSED, OBJ_DOOR_OPEN, OBJ_GOAL, OBJ_AGENT_A, OBJ_AGENT_B = range(7)


@dataclass(frozen=True)
class GridSnapshot:
    """The exportable full physical state (a value; nothing here aliases the simulator)."""
    positions: Tuple[Tuple[str, int, int], ...]     # (agent, x, y) in agent order
    door_cell: Cell
    door_open: bool
    door_jammed: bool                               # the hidden physical condition
    places: Tuple[Tuple[str, Tuple[Cell, ...]], ...]   # named regions: handles and goal
    step_count: int
    terminated: bool
    truncated: bool


class CooperativeGridEnv(ParallelEnv):
    """Two agents must open a heavy door together, then both reach the goal room."""

    metadata = {"render_modes": ["human", "rgb_array"], "name": "cooperative_grid_v0",
                "render_fps": 3}

    def __init__(self, render_mode: Optional[str] = None, *, jammed_at_start: bool = True,
                 max_steps: int = 200, render_fps: Optional[int] = None,
                 tile_size: int = 64) -> None:
        if render_mode not in (None, "human", "rgb_array"):
            raise ValueError(f"unknown render_mode {render_mode!r}")
        self.render_mode = render_mode
        self.jammed_at_start = jammed_at_start
        self.max_steps = max_steps
        self.render_fps = render_fps or self.metadata["render_fps"]
        self.tile_size = tile_size
        self.possible_agents: List[str] = list(AGENT_NAMES)
        self.agents: List[str] = []

        self.height = len(LAYOUT)
        self.width = len(LAYOUT[0])
        self.walls: frozenset = frozenset()
        self.goal_cells: Tuple[Cell, ...] = ()
        self.door_cell: Cell = (0, 0)
        self.start: Dict[str, Cell] = {}
        walls, goals, starts = set(), [], {}
        for y, row in enumerate(LAYOUT):
            for x, ch in enumerate(row):
                if ch == "#":
                    walls.add((x, y))
                elif ch == "D":
                    self.door_cell = (x, y)
                elif ch == "G":
                    goals.append((x, y))
                elif ch in AGENT_NAMES:
                    starts[ch] = (x, y)
        self.walls = frozenset(walls)
        self.goal_cells = tuple(goals)
        self.start = starts
        dx, dy = self.door_cell
        # the handle cells: corridor cells diagonally flanking the door (left and right)
        self.handle_cells: Dict[str, Cell] = {"handle_left": (dx - 1, dy - 1),
                                              "handle_right": (dx + 1, dy - 1)}
        self.places: Tuple[Tuple[str, Tuple[Cell, ...]], ...] = (
            ("handle_left", (self.handle_cells["handle_left"],)),
            ("handle_right", (self.handle_cells["handle_right"],)),
            ("goal", self.goal_cells),
        )

        self._pos: Dict[str, Cell] = {}
        self._facing: Dict[str, Cell] = {}
        self._door_open = False
        self._door_jammed = False
        self._step_count = 0
        self._terminated = False
        self._truncated = False
        self._caption = ""
        self._effect = ""          # the last physical event, shown by the renderer
        self._flash = 0            # frames of door "shake" animation left
        self._window: Any = None
        self._clock: Any = None
        self._font: Any = None
        self.observation_spaces = {
            a: spaces.Box(0, 255, shape=(self.height, self.width, 3), dtype=np.uint8)
            for a in self.possible_agents}
        self.action_spaces = {a: spaces.Discrete(len(ACTION_NAMES)) for a in self.possible_agents}

    # ── PettingZoo API ────────────────────────────────────────────────────────────────
    def observation_space(self, agent: str) -> spaces.Space:
        return self.observation_spaces[agent]

    def action_space(self, agent: str) -> spaces.Space:
        return self.action_spaces[agent]

    def reset(self, seed: Optional[int] = None, options: Optional[dict] = None):
        self.agents = list(self.possible_agents)
        self._pos = dict(self.start)
        self._facing = {"A": (1, 0), "B": (-1, 0)}
        self._door_open = False
        self._door_jammed = self.jammed_at_start
        self._step_count = 0
        self._terminated = False
        self._truncated = False
        self._caption = ""
        self._effect = "reset"
        self._flash = 0
        if self.render_mode == "human":
            self.render()
        return self._observations(), {a: {} for a in self.agents}

    def step(self, actions: Dict[str, int]):
        if not self.agents:
            raise RuntimeError("step() after the episode ended; call reset()")
        self._step_count += 1
        events: List[str] = []
        # movement, resolved in agent order
        for agent in self.possible_agents:
            action = int(actions.get(agent, NOOP))
            if action in MOVES:
                mx, my = MOVES[action]
                x, y = self._pos[agent]
                target = (x + mx, y + my)
                self._facing[agent] = (mx, my)
                if self._free(target, agent):
                    self._pos[agent] = target
                    events.append(f"{agent} {ACTION_NAMES[action]}")
                else:
                    events.append(f"{agent} blocked")
        pulling = [a for a in self.possible_agents if int(actions.get(a, NOOP)) == PULL]
        shaking = [a for a in self.possible_agents if int(actions.get(a, NOOP)) == SHAKE]
        for agent in shaking:
            if self._on_handle(agent) and not self._door_open:
                self._flash = 3
                if self._door_jammed:
                    self._door_jammed = False
                    events.append(f"{agent} shake: jam cleared")
                else:
                    events.append(f"{agent} shake")
            else:
                events.append(f"{agent} shake: nothing to shake")
        if pulling:
            on_handles = {a: self._on_handle(a) for a in pulling}
            if self._door_open:
                events.append("pull: door already open")
            elif len(pulling) < 2 or not all(on_handles.values()):
                events.append("pull: too heavy for one agent")
            elif self._door_jammed:
                self._flash = 2
                events.append("pull: the door did not move")
            else:
                self._door_open = True
                events.append("pull: DOOR OPEN")
        self._terminated = all(self._pos[a] in self.goal_cells for a in self.possible_agents)
        self._truncated = not self._terminated and self._step_count >= self.max_steps
        rewards = {a: (1.0 if self._terminated else 0.0) for a in self.agents}
        terminations = {a: self._terminated for a in self.agents}
        truncations = {a: self._truncated for a in self.agents}
        infos = {a: {"events": tuple(events)} for a in self.agents}
        observations = self._observations()
        self._effect = "; ".join(events)
        if self._terminated or self._truncated:
            self.agents = []
        if self.render_mode == "human":
            self.render()
        return observations, rewards, terminations, truncations, infos

    def render(self):
        if self.render_mode is None:
            return None
        frame = self._draw()
        if self.render_mode == "human":
            self._show(frame)
        return frame

    def close(self) -> None:
        if self._window is not None:
            import pygame
            pygame.display.quit()
            pygame.quit()
            self._window = None
            self._clock = None
            self._font = None

    # ── backend services for a skill layer (not part of the PettingZoo API) ───────────
    def snapshot(self) -> GridSnapshot:
        """A fresh value of the full physical state, including the hidden jam."""
        return GridSnapshot(
            positions=tuple((a, *self._pos[a]) for a in self.possible_agents),
            door_cell=self.door_cell, door_open=self._door_open, door_jammed=self._door_jammed,
            places=self.places, step_count=self._step_count,
            terminated=self._terminated, truncated=self._truncated,
        )

    def route(self, agent: str, targets: Tuple[Cell, ...]) -> Optional[List[int]]:
        """Shortest sequence of MOVE actions taking `agent` to one of `targets` through the
        cells it can currently traverse (no walls, no closed door, not the other agent's
        cell); `None` when no such path exists. Backend geometry — never the planner's."""
        start = self._pos[agent]
        if start in targets:
            return []
        prev: Dict[Cell, Tuple[Cell, int]] = {}
        queue: Deque[Cell] = deque([start])
        seen = {start}
        while queue:
            cell = queue.popleft()
            for action, (mx, my) in MOVES.items():
                nxt = (cell[0] + mx, cell[1] + my)
                if nxt in seen or not self._free(nxt, agent):
                    continue
                seen.add(nxt)
                prev[nxt] = (cell, action)
                if nxt in targets:
                    path: List[int] = []
                    cur = nxt
                    while cur != start:
                        cur, act = prev[cur]
                        path.append(act)
                    path.reverse()
                    return path
                queue.append(nxt)
        return None

    def annotate(self, caption: str) -> None:
        """A caption for the renderer (the high-level action under way); no physical effect."""
        self._caption = caption

    @property
    def door_open(self) -> bool:
        return self._door_open

    @property
    def door_jammed(self) -> bool:
        return self._door_jammed

    def position(self, agent: str) -> Cell:
        return self._pos[agent]

    # ── internals ─────────────────────────────────────────────────────────────────────
    def _free(self, cell: Cell, mover: str) -> bool:
        x, y = cell
        if not (0 <= x < self.width and 0 <= y < self.height) or cell in self.walls:
            return False
        if cell == self.door_cell and not self._door_open:
            return False
        return all(self._pos[a] != cell for a in self.possible_agents if a != mover)

    def _on_handle(self, agent: str) -> bool:
        return self._pos[agent] in self.handle_cells.values()

    def _observations(self) -> Dict[str, np.ndarray]:
        grid = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        for (x, y) in self.walls:
            grid[y, x, 0] = OBJ_WALL
        for (x, y) in self.goal_cells:
            grid[y, x, 0] = OBJ_GOAL
        dx, dy = self.door_cell
        grid[dy, dx, 0] = OBJ_DOOR_OPEN if self._door_open else OBJ_DOOR_CLOSED
        for i, agent in enumerate(self.possible_agents):
            x, y = self._pos[agent]
            grid[y, x, 1] = OBJ_AGENT_A + i
            fx, fy = self._facing[agent]
            grid[y, x, 2] = [(1, 0), (0, 1), (-1, 0), (0, -1)].index((fx, fy))
        return {a: grid.copy() for a in self.agents}

    # ── rendering (pygame, imported only here) ────────────────────────────────────────
    def _draw(self) -> np.ndarray:
        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        import pygame

        ts = self.tile_size
        banner = ts // 2 + 8
        surface = pygame.Surface((self.width * ts, self.height * ts + banner))
        surface.fill((0, 0, 0))
        if self._font is None:
            pygame.font.init()
            self._font = pygame.font.SysFont(None, max(14, ts // 3))
        floor, wall, goal = (40, 40, 40), (100, 100, 100), (0, 140, 0)
        for y in range(self.height):
            for x in range(self.width):
                rect = pygame.Rect(x * ts, y * ts, ts, ts)
                cell = (x, y)
                color = wall if cell in self.walls else (goal if cell in self.goal_cells else floor)
                pygame.draw.rect(surface, color, rect)
                pygame.draw.rect(surface, (20, 20, 20), rect, 1)
        # the door: closed = a yellow slab with a dark bar; open = a yellow frame
        dx, dy = self.door_cell
        rect = pygame.Rect(dx * ts, dy * ts, ts, ts)
        yellow = (230, 200, 0)
        if self._door_open:
            pygame.draw.rect(surface, floor, rect)
            pygame.draw.rect(surface, yellow, rect, max(2, ts // 10))
        else:
            jitter = (ts // 12) if (self._flash % 2 == 1) else 0
            pygame.draw.rect(surface, yellow, rect.inflate(-jitter, -jitter))
            pygame.draw.rect(surface, (120, 100, 0), rect.inflate(-ts // 2, -ts // 8))
            if self._door_jammed:      # the hidden condition, visible to the human only
                pygame.draw.polygon(surface, (220, 30, 30), [
                    (rect.left + ts // 6, rect.bottom - ts // 6),
                    (rect.left + ts // 2, rect.bottom - ts // 2),
                    (rect.left + ts // 2 + ts // 3, rect.bottom - ts // 6)])
        if self._flash > 0:
            self._flash -= 1
        # the handle cells: a faint outline so the cooperative positions are visible
        for hx, hy in self.handle_cells.values():
            pygame.draw.rect(surface, (90, 90, 160), pygame.Rect(hx * ts, hy * ts, ts, ts), 3)
        # the agents: MiniGrid triangles pointing where they last moved, labelled A / B
        colors = {"A": (220, 60, 60), "B": (60, 120, 220)}
        for agent in self.possible_agents:
            x, y = self._pos[agent]
            fx, fy = self._facing[agent]
            cx, cy = x * ts + ts / 2, y * ts + ts / 2
            r = ts * 0.36
            tip = (cx + fx * r, cy + fy * r)
            base = (cx - fx * r * 0.7, cy - fy * r * 0.7)
            px, py = -fy, fx
            left = (base[0] + px * r * 0.7, base[1] + py * r * 0.7)
            right = (base[0] - px * r * 0.7, base[1] - py * r * 0.7)
            pygame.draw.polygon(surface, colors[agent], [tip, left, right])
            label = self._font.render(agent, True, (255, 255, 255))
            surface.blit(label, label.get_rect(center=(cx, cy)))
        # the banner: the high-level action and the last physical event
        text = self._caption if self._caption else ""
        if self._effect:
            text = f"{text}   |   {self._effect}" if text else self._effect
        line = self._font.render(text[:90], True, (240, 240, 240))
        surface.blit(line, (8, self.height * ts + 6))
        return np.transpose(np.array(pygame.surfarray.pixels3d(surface)), (1, 0, 2)).copy()

    def _show(self, frame: np.ndarray) -> None:
        import pygame
        h, w = frame.shape[:2]
        if self._window is None:
            pygame.init()
            pygame.display.set_caption("CooperativeGrid — MAAOS domain")
            self._window = pygame.display.set_mode((w, h))
            self._clock = pygame.time.Clock()
        pygame.event.pump()
        pygame.surfarray.blit_array(self._window, np.transpose(frame, (1, 0, 2)))
        pygame.display.flip()
        self._clock.tick(self.render_fps)


__all__ = ["ACTION_NAMES", "AGENT_NAMES", "CooperativeGridEnv", "DOOR_NAME", "DOWN",
           "GridSnapshot", "LAYOUT", "LEFT", "NOOP", "PULL", "RIGHT", "SHAKE", "UP"]
