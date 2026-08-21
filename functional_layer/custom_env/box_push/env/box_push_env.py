"""
MiniGrid core environment for the Box-Push domain.

Single-world / core layout layer (multi-agent control lives in
multi_agent_box_push_env.py). Compared with CooperativeSearchTransport this uses a
SIMPLER, OPEN arena so boxes can actually be pushed to the goal (a walled maze makes
box-pushing Sokoban-hard).

Layout (12×12):
  - outer wall only (no internal dividers)
  - GOAL zone = left column x=1, rows y=1..10 (green DeliveryTile)
  - box_0: HEAVY target (req 2 agents) — red
  - box_1: LIGHT target (req 1 agent)  — red
  - agents start on the right, facing LEFT (toward the goal)

Reuses CST's objects/state/constants via sibling import.
"""
import sys
import os
from copy import deepcopy
from typing import Dict, List, Optional, Tuple

_THIS_DIR  = os.path.dirname(os.path.abspath(__file__))
_CST_ENV   = os.path.abspath(os.path.join(_THIS_DIR, "../../cooperative_search_transport/env"))
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "../../../.."))
for _p in (_REPO_ROOT, _CST_ENV, _THIS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from minigrid.core.grid import Grid
from minigrid.core.mission import MissionSpace
from minigrid.minigrid_env import MiniGridEnv

from constants import Directions, Actions, DIRECTION_VECTORS
from objects import AgentMarker, DeliveryTile, TargetPackage
from state import EnvCoreConfig, EnvConfig, ObjectState, WorldState, AgentState, StaticWorld, EpisodeState

# Goal zone: left column.
GOAL_ZONE: List[Tuple[int, int]] = [(1, y) for y in range(1, 11)]


class BoxPushMiniGridEnv(MiniGridEnv):
    def __init__(
        self,
        config: Optional[EnvCoreConfig] = None,
        agent_start_pos: Tuple[int, int] = (10, 10),
        agent_start_dir: int = Directions.LEFT,
        **kwargs,
    ):
        self.config = config or EnvConfig()
        self.config.validate()
        if self.config.width != self.config.height:
            raise ValueError("Box-Push core assumes a square grid (width == height).")

        self.agent_start_pos = agent_start_pos
        self.agent_start_dir = int(agent_start_dir)
        self.agent = AgentState(agent_id="agent_0",
                                position=agent_start_pos, direction=agent_start_dir)

        self.static_walls: List[Tuple[int, int]] = []
        self.delivery_zone: List[Tuple[int, int]] = []
        self.initial_object_states: Dict[int, ObjectState] = {}

        mission_space = MissionSpace(mission_func=self._gen_mission)
        super().__init__(
            mission_space=mission_space,
            grid_size=self.config.width,
            max_steps=self.config.max_steps,
            agent_view_size=self.config.agent_view_size,
            render_mode=self.config.render_mode,
            **kwargs,
        )

    @staticmethod
    def _gen_mission() -> str:
        return "push all target boxes onto the goal zone"

    def _get_initial_object_states(self) -> Dict[int, ObjectState]:
        return {
            0: ObjectState(object_id=0, position=(6, 6), is_target=True, required_agents=2),  # HEAVY
            1: ObjectState(object_id=1, position=(8, 4), is_target=True, required_agents=1),  # LIGHT
        }

    def _build_base_grid(self, width: int, height: int) -> Grid:
        grid = Grid(width, height)
        grid.wall_rect(0, 0, width, height)

        walls: List[Tuple[int, int]] = []
        for x in range(width):
            walls.append((x, 0)); walls.append((x, height - 1))
        for y in range(height):
            walls.append((0, y)); walls.append((width - 1, y))

        # Open arena — no internal dividers.

        for x, y in GOAL_ZONE:
            grid.set(x, y, DeliveryTile())

        self.static_walls = walls
        self.delivery_zone = list(GOAL_ZONE)
        return grid

    def _put_object_from_state(self, obj_state: ObjectState):
        # Every box is now a target (no decoys).
        x, y = obj_state.position
        self.put_obj(TargetPackage(), x, y)

    def _gen_grid(self, width: int, height: int):
        self.grid = self._build_base_grid(width, height)
        self.initial_object_states = self._get_initial_object_states()
        for obj_state in self.initial_object_states.values():
            self._put_object_from_state(obj_state)
        self.agent_pos = self.agent_start_pos
        self.agent_dir = self.agent_start_dir
        self.mission = self._gen_mission()

    def reset(self, *, seed=None, options=None):
        obs, info = super().reset(seed=seed)
        self.world = WorldState(
            agents={},
            objects=self._get_initial_object_states(),
            static=StaticWorld(walls=list(self.static_walls),
                               delivery_zone=list(self.delivery_zone)),
            episode=EpisodeState(),
        )
        if self.agent_start_pos is not None:
            self.agent_pos = self.agent_start_pos
            self.agent_dir = self.agent_start_dir
        self.agent = AgentState(agent_id="agent_0",
                                position=self.agent_start_pos, direction=self.agent_start_dir)
        return obs, info

    def get_initial_world_objects(self) -> Dict[int, ObjectState]:
        return deepcopy(self.initial_object_states)
