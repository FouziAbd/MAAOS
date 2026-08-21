"""
PettingZoo ParallelEnv wrapper for the Box-Push domain.

Interaction model = PUSHING (no carrying). There is NO dedicated cooperate action —
cooperation is emergent from MOVE_FORWARD; only TURN_LEFT/TURN_RIGHT/MOVE_FORWARD/STAY
are used (action space is Discrete(4)). Coordination lives in the skill/LLM layer.
  - A LIGHT box (required_agents == 1) slides one cell when a single agent does
    MOVE_FORWARD into it and the cell beyond is free; the pusher follows.
  - A HEAVY box (required_agents == 2) does NOT move for a lone pusher (the agent is
    blocked — this is the "discover it's heavy" signal). It moves only when two agents
    are lined up in TANDEM directly behind it: one at B-D and one at B-2D (B = box,
    D = push direction), BOTH facing D and both choosing MOVE_FORWARD, with B+D free.
    The box and both pushers then translate one cell in D together.
  - A target box whose position lands in the goal zone is delivered (by position).
"""
from __future__ import annotations

import sys
import os
from typing import Any, Dict, List, Optional, Tuple

from gymnasium import spaces
from pettingzoo import ParallelEnv

_THIS_DIR  = os.path.dirname(os.path.abspath(__file__))
_CST_ENV   = os.path.abspath(os.path.join(_THIS_DIR, "../../cooperative_search_transport/env"))
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "../../../.."))
for _p in (_REPO_ROOT, _CST_ENV, _THIS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from objects import AgentMarker, TargetPackage
from constants import Actions, DIRECTION_VECTORS, Directions
from state import AgentState, EnvConfig, WorldState
from box_push_env import BoxPushMiniGridEnv

_MOVE_FAIL_PENALTY = 0.1
_LIGHT_PUSH_REWARD = 0.1
_JOINT_PUSH_REWARD = 0.2
_DELIVERY_REWARD   = 20.0
_COMPLETE_BONUS    = 10.0


class MultiAgentBoxPushEnv(ParallelEnv):
    metadata = {"name": "box_push_parallel_v1", "render_modes": ["human", "rgb_array", "text"]}

    def __init__(self, config: Optional[EnvConfig] = None):
        self.config = config or EnvConfig()
        self.config.validate()

        self.core_env = BoxPushMiniGridEnv(config=self.config)
        self.core_env._gen_grid = self._gen_grid

        self.possible_agents = [f"agent_{i}" for i in range(self.config.num_agents)]
        self.agents = list(self.possible_agents)

        def custom_get_frame(*args, **kwargs):
            tile_size = kwargs.get("tile_size", 32)
            if len(args) > 1:
                tile_size = args[1]
            for agent in self.possible_agents:
                if agent in self.agent_positions:
                    self.core_env.grid.set(*self.agent_positions[agent], None)
            img = self.core_env.grid.render(tile_size, agent_pos=(-1, -1), agent_dir=0, highlight_mask=None)
            for agent in self.possible_agents:
                if agent in self.agent_positions:
                    pos = self.agent_positions[agent]
                    ag_obj = self.agent_objects[agent]
                    ymin, ymax = pos[1] * tile_size, (pos[1] + 1) * tile_size
                    xmin, xmax = pos[0] * tile_size, (pos[0] + 1) * tile_size
                    ag_obj.render(img[ymin:ymax, xmin:xmax, :])
            for agent in self.possible_agents:
                if agent in self.agent_positions:
                    self.core_env.grid.set(*self.agent_positions[agent], self.agent_objects[agent])
            return img

        self.core_env.get_frame = custom_get_frame
        self.core_env.world = WorldState()
        self.core_env.world.agents = self.agents

    # ── Spaces ──────────────────────────────────────────────────────────────────
    def action_space(self, agent: str):
        # Only TURN_LEFT=0, TURN_RIGHT=1, MOVE_FORWARD=2, STAY=3 are used. No
        # PICK/DROP/COOPERATE — heavy-box cooperation is emergent from MOVE_FORWARD.
        return spaces.Discrete(4)

    def observation_space(self, agent: str):
        return self.core_env.observation_space

    def _get_agent_start_positions(self) -> List[Tuple[int, int]]:
        return [(10, 10), (10, 9), (9, 10), (9, 9)]

    # ── Grid generation / reset ──────────────────────────────────────────────────
    def _gen_grid(self, width, height):
        self.core_env.grid = self.core_env._build_base_grid(width, height)
        self.core_env.agent_pos = (-1, -1)
        self.core_env.agent_dir = 0
        self.agent_positions: Dict[str, Tuple[int, int]] = {}
        self.agent_dirs: Dict[str, int] = {}
        self.agent_objects: Dict[str, AgentMarker] = {}

        self.core_env.initial_object_states = self.core_env._get_initial_object_states()
        for obj_state in self.core_env.initial_object_states.values():
            self.core_env._put_object_from_state(obj_state)

        colors = ["green", "red", "blue", "purple", "yellow", "grey"]
        for idx, agent_id in enumerate(self.possible_agents):
            pos = self._get_agent_start_positions()[idx]
            self.agent_positions[agent_id] = pos
            self.agent_dirs[agent_id] = Directions.LEFT
            marker = AgentMarker(color=colors[idx % len(colors)], dir=self.agent_dirs[agent_id])
            self.agent_objects[agent_id] = marker
            self.core_env.grid.set(*pos, marker)

        self.core_env.agent_pos = (10, 10)
        self.core_env.agent_dir = int(Directions.LEFT)

    def reset(self, seed: Optional[int] = None, options: Optional[dict] = None):
        self.agents = list(self.possible_agents)
        self.core_env.reset(seed=seed, options=options)

        for agent in self.agents:
            self.core_env.grid.set(*self.agent_positions[agent], self.agent_objects[agent])

        observations = {}
        for agent in self.agents:
            pos = self.agent_positions[agent]
            self.core_env.agent_pos = pos
            self.core_env.agent_dir = self.agent_dirs[agent]
            self.core_env.grid.set(*pos, None)
            observations[agent] = self.core_env.gen_obs()
            self.core_env.grid.set(*pos, self.agent_objects[agent])
            self.core_env.world.agents[agent] = AgentState(
                agent_id=agent, position=pos, direction=self.agent_dirs[agent])

        self.core_env.agent_pos = (-1, -1)
        return observations, {agent: {} for agent in self.agents}

    # ── Step ──────────────────────────────────────────────────────────────────────
    def step(self, actions: Dict[str, int]):
        self.core_env.world.episode.step_count += 1
        rewards = {aid: -0.01 for aid in self.agents}
        terminations = {aid: False for aid in self.agents}
        truncations = {aid: False for aid in self.agents}
        infos = {aid: {} for aid in self.agents}

        joint = {aid: int(actions.get(aid, Actions.STAY)) for aid in self.agents}

        # 1) Turns
        for aid in self.agents:
            a = self.core_env.world.agents[aid]
            a.last_action = joint[aid]
            if joint[aid] == Actions.TURN_LEFT:
                self._turn_left(a)
            elif joint[aid] == Actions.TURN_RIGHT:
                self._turn_right(a)

        # 2) Moves / pushes
        self._resolve_pushes(joint, rewards)

        # 3) Delivery by position
        self._check_delivery(rewards)

        # 4) Termination
        if self._all_targets_delivered():
            self.core_env.world.episode.terminated = True
            terminations = {aid: True for aid in self.agents}
            for aid in self.agents:
                rewards[aid] += _COMPLETE_BONUS
        if self.core_env.world.episode.step_count >= self.config.max_steps:
            self.core_env.world.episode.truncated = True
            truncations = {aid: True for aid in self.agents}

        observations = self._get_all_observations()
        return observations, rewards, terminations, truncations, infos

    # ── Push resolution ────────────────────────────────────────────────────────────
    def _resolve_pushes(self, joint: Dict[str, int], rewards: Dict[str, float]):
        world = self.core_env.world
        movers = [aid for aid in self.agents if joint[aid] == Actions.MOVE_FORWARD]
        handled: set = set()

        # Phase A — heavy TANDEM pushes. The box at B moves one cell in direction D only
        # when one mover (A1) is directly behind it at B-D facing D, and a second mover
        # (A2) is directly behind A1 at B-2D facing D. Box+A1+A2 translate one cell in D.
        for obj in world.objects.values():
            if obj.delivered or obj.required_agents < 2:
                continue
            pair = self._find_tandem(obj, movers, handled)
            if pair is None:
                continue
            d, a1, a2 = pair
            dx, dy = DIRECTION_VECTORS[Directions(d)]
            bx, by = obj.position
            new_box = (bx + dx, by + dy)
            new_pos = {a1: (world.agents[a1].position[0] + dx, world.agents[a1].position[1] + dy),
                       a2: (world.agents[a2].position[0] + dx, world.agents[a2].position[1] + dy)}
            if not self._tandem_feasible(new_box, obj):
                continue
            for aid in (a1, a2):
                self.core_env.grid.set(*world.agents[aid].position, None)
            for aid in (a1, a2):
                np = new_pos[aid]
                world.agents[aid].position = np
                self.agent_positions[aid] = np
                self.core_env.grid.set(*np, self.agent_objects[aid])
                rewards[aid] += _JOINT_PUSH_REWARD
                handled.add(aid)
            self._set_box_position(obj, new_box)

        # Phase B — individual movers: plain move or light push
        for aid in movers:
            if aid in handled:
                continue
            a = world.agents[aid]
            dx, dy = DIRECTION_VECTORS[Directions(int(a.direction))]
            front = (a.position[0] + dx, a.position[1] + dy)
            box = self._box_at(front)
            if box is None:
                if not self._move_forward(a):
                    rewards[aid] -= _MOVE_FAIL_PENALTY
            elif box.required_agents > 1:
                rewards[aid] -= _MOVE_FAIL_PENALTY  # lone push of a heavy box → no move
            else:
                dest = (front[0] + dx, front[1] + dy)
                if self._cell_free_for_box(dest, box):
                    self._set_box_position(box, dest)
                    self.core_env.grid.set(*a.position, None)
                    a.position = front
                    self.agent_positions[aid] = front
                    self.core_env.grid.set(*front, self.agent_objects[aid])
                    rewards[aid] += _LIGHT_PUSH_REWARD
                else:
                    rewards[aid] -= _MOVE_FAIL_PENALTY

    def _check_delivery(self, rewards: Dict[str, float]):
        world = self.core_env.world
        zone = set(world.static.delivery_zone)
        for obj in world.objects.values():
            if obj.delivered or not obj.is_target:
                continue
            if tuple(obj.position) in zone:
                obj.delivered = True
                world.episode.delivered_target_count += 1
                pushers = [aid for aid in self.agents
                           if self._manhattan(world.agents[aid].position, obj.position) == 1]
                for aid in (pushers or self.agents):
                    rewards[aid] += _DELIVERY_REWARD

    # ── Movement helpers ────────────────────────────────────────────────────────
    def _turn_left(self, a: AgentState):
        a.direction = (int(a.direction) - 1) % 4
        self.agent_objects[a.agent_id].dir = a.direction
        self.agent_dirs[a.agent_id] = a.direction

    def _turn_right(self, a: AgentState):
        a.direction = (int(a.direction) + 1) % 4
        self.agent_objects[a.agent_id].dir = a.direction
        self.agent_dirs[a.agent_id] = a.direction

    def _move_forward(self, a: AgentState) -> bool:
        dx, dy = DIRECTION_VECTORS[Directions(a.direction)]
        next_pos = (a.position[0] + dx, a.position[1] + dy)
        if not self._is_free_for_agent(next_pos, a.agent_id):
            return False
        self.core_env.grid.set(*a.position, None)
        a.position = next_pos
        self.agent_positions[a.agent_id] = next_pos
        self.core_env.grid.set(*next_pos, self.agent_objects[a.agent_id])
        return True

    def _is_free_for_agent(self, pos: Tuple[int, int], moving_agent_id: str) -> bool:
        x, y = pos
        if not (0 <= x < self.config.width and 0 <= y < self.config.height):
            return False
        if pos in self.core_env.world.static.walls:
            return False
        for other_id, other in self.core_env.world.agents.items():
            if other_id != moving_agent_id and tuple(other.position) == tuple(pos):
                return False
        for obj in self.core_env.world.objects.values():
            if obj.delivered:
                continue
            if tuple(obj.position) == tuple(pos):
                return False
        return True

    def _box_at(self, pos):
        for obj in self.core_env.world.objects.values():
            if obj.delivered:
                continue
            if tuple(obj.position) == tuple(pos):
                return obj
        return None

    def _cell_free_for_box(self, pos: Tuple[int, int], ignore_box) -> bool:
        x, y = pos
        if not (0 <= x < self.config.width and 0 <= y < self.config.height):
            return False
        if pos in self.core_env.world.static.walls:
            return False
        for agent in self.core_env.world.agents.values():
            if tuple(agent.position) == tuple(pos):
                return False
        for obj in self.core_env.world.objects.values():
            if obj.object_id == ignore_box.object_id or obj.delivered:
                continue
            if tuple(obj.position) == tuple(pos):
                return False
        return True

    def _find_tandem(self, obj, movers: List[str], handled: set):
        """Return (D, a1, a2) if two movers are lined up in tandem behind `obj`:
        a1 at B-D facing D, a2 at B-2D facing D (same D). Else None."""
        world = self.core_env.world
        bx, by = obj.position
        avail = [aid for aid in movers if aid not in handled]
        for a1 in avail:
            d = int(world.agents[a1].direction)
            dx, dy = DIRECTION_VECTORS[Directions(d)]
            if tuple(world.agents[a1].position) != (bx - dx, by - dy):
                continue  # a1 must be directly behind the box (B-D)
            for a2 in avail:
                if a2 == a1 or int(world.agents[a2].direction) != d:
                    continue
                if tuple(world.agents[a2].position) == (bx - 2 * dx, by - 2 * dy):
                    return d, a1, a2  # a2 directly behind a1 (B-2D), same facing
        return None

    def _tandem_feasible(self, new_box: Tuple[int, int], obj) -> bool:
        """The only cell that must be free for a tandem push is the box's destination
        B+D; A1/A2 move into cells vacated by the box and A1 respectively."""
        x, y = new_box
        if not (0 <= x < self.config.width and 0 <= y < self.config.height):
            return False
        if new_box in self.core_env.world.static.walls:
            return False
        for agent in self.core_env.world.agents.values():
            if tuple(agent.position) == tuple(new_box):
                return False
        for other in self.core_env.world.objects.values():
            if other.object_id == obj.object_id or other.delivered:
                continue
            if tuple(other.position) == tuple(new_box):
                return False
        return True

    def _set_box_position(self, obj, new_pos):
        self.core_env.grid.set(*obj.position, None)
        obj.position = (int(new_pos[0]), int(new_pos[1]))
        self.core_env.grid.set(*obj.position, TargetPackage())

    # ── Observation ────────────────────────────────────────────────────────────────
    def _get_all_observations(self) -> Dict[str, Dict[str, Any]]:
        return {aid: self._get_observation_for_agent(aid) for aid in self.agents}

    def _get_observation_for_agent(self, agent_id: str) -> Dict[str, Any]:
        pos = self.agent_positions[agent_id]
        self.core_env.agent_pos = pos
        self.core_env.agent_dir = self.agent_dirs[agent_id]
        self.core_env.grid.set(*pos, None)
        obs = self.core_env.gen_obs()
        self.core_env.grid.set(*pos, self.agent_objects[agent_id])
        return obs

    # ── Misc ────────────────────────────────────────────────────────────────────
    def _manhattan(self, a, b) -> int:
        return abs(a[0] - b[0]) + abs(a[1] - b[1])

    def _all_targets_delivered(self) -> bool:
        targets = [o for o in self.core_env.world.objects.values() if o.is_target]
        return bool(targets) and all(o.delivered for o in targets)

    def render(self):
        self.core_env.render()

    def close(self):
        self.core_env.close()
