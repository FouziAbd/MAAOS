from __future__ import annotations

from copy import deepcopy
from typing import Dict, List, Optional, Tuple

from minigrid.core.grid import Grid
from minigrid.core.mission import MissionSpace
from minigrid.core.world_object import Wall
from minigrid.minigrid_env import MiniGridEnv

from constants import Directions, Actions, DIRECTION_VECTORS
from objects import AgentMarker, DecoyPackage, DeliveryTile, TargetPackage
from state import EnvCoreConfig, ObjectState, WorldState, AgentState, StaticWorld, EpisodeState

class CooperativeSearchTransportMiniGridEnv(MiniGridEnv):
    """
    MiniGrid core environment for Cooperative Search and Transport.

    This is the single-world / core layout layer.
    Multi-agent control will be handled in multi_agent_env.py.
    """
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
            raise ValueError("For v1, MiniGrid core assumes a square grid (width == height).")

        self.agent_start_pos = agent_start_pos
        self.agent_start_dir = int(agent_start_dir)
        self.agent = AgentState(
            agent_id="agent_0",
            position=agent_start_pos,
            direction=agent_start_dir,
        )

        self.static_walls: List[Tuple[int, int]] = []
        self.delivery_zone: List[Tuple[int, int]] = []
        self.initial_object_states: Dict[int, ObjectState] = {}
        self.initial_agent_starts: List[Tuple[int, int]] = []

        mission_space = MissionSpace(mission_func=self._gen_mission)

        super().__init__(
            mission_space=mission_space,
            grid_size=self.config.width,
            max_steps=self.config.max_steps,
            #see_through_walls=True,
            agent_view_size=self.config.agent_view_size,
            render_mode=self.config.render_mode,
            **kwargs,
        )

    @staticmethod
    def _gen_mission() -> str:
        return "deliver all target packages to the delivery zone"

    def _get_initial_object_states(self) -> Dict[int, ObjectState]:
        # v1 fixed objects
        return {
            0: ObjectState(
                object_id=0,
                position=(2, 9),
                is_target=True,
                required_agents=2,
            ),
            1: ObjectState(
                object_id=1,
                position=(6, 5),
                is_target=True,
                required_agents=1,
            ),
            2: ObjectState(
                object_id=2,
                position=(9, 2),
                is_target=False,
                required_agents=1,
            ),
            3: ObjectState(
                object_id=3,
                position=(10, 4),
                is_target=False,
                required_agents=1,
            ),
        }

    def _build_base_grid(self, width: int, height: int) -> Grid:
        grid = Grid(width, height)

        # Outer border
        grid.wall_rect(0, 0, width, height)

        walls: List[Tuple[int, int]] = []

        # Track outer walls
        for x in range(width):
            walls.append((x, 0))
            walls.append((x, height - 1))
        for y in range(height):
            walls.append((0, y))
            walls.append((width - 1, y))

        # Internal walls to create simple rooms/corridors
        for y in range(1, height - 1):
            if y not in (3, 8):
                grid.set(4, y, Wall())
                walls.append((4, y))

        for y in range(1, height - 1):
            if y not in (6,):
                grid.set(8, y, Wall())
                walls.append((8, y))

        delivery_zone = [(1, 1), (2, 1), (1, 2), (2, 2)]
        for x, y in delivery_zone:
            grid.set(x, y, DeliveryTile())

        self.static_walls = walls
        self.delivery_zone = delivery_zone
        return grid

    def _put_object_from_state(self, obj_state: ObjectState):
        obj = TargetPackage() if obj_state.is_target else DecoyPackage()
        x, y = obj_state.position
        self.put_obj(obj, x, y)

    def _gen_grid(self, width: int, height: int):
        self.grid = self._build_base_grid(width, height)

        self.initial_object_states = self._get_initial_object_states()
        #self.initial_agent_starts = self._get_agent_start_positions()

        for obj_state in self.initial_object_states.values():
            self._put_object_from_state(obj_state)

        # Single official MiniGrid agent, mainly for debugging / rendering
        self.agent_pos = self.agent_start_pos
        self.agent_dir = self.agent_start_dir
        self.mission = self._gen_mission()

    def reset(self, *, seed=None, options=None):
        obs, info = super().reset(seed=seed)

        # Build the initial world state
        self.world = WorldState(
            agents={},
            objects=self._get_initial_object_states(),
            static = StaticWorld(
                walls=list(self.static_walls),
                delivery_zone=list(self.delivery_zone),
            ),
            episode = EpisodeState()
        )

        # Add agents to world state
        if self.agent_start_pos is not None:
            self.agent_pos = self.agent_start_pos
            self.agent_dir = self.agent_start_dir

        self.agent = AgentState(
            agent_id="agent_0",
            position=self.agent_start_pos,
            direction=self.agent_start_dir,
        )
        return obs, info

    """def build_render_grid(
        self,
        world: WorldState,
        primary_agent_id: Optional[str],
    ) -> Grid:
        ""
        Build a fresh MiniGrid Grid from the current multi-agent world state.
        Used by the PettingZoo wrapper for rendering.
        ""
        grid = self._build_base_grid(self.config.width, self.config.height)

        # Objects
        for obj in world.objects.values():
            if obj.delivered or obj.carried_by is not None:
                continue
            x, y = obj.position
            grid.set(x, y, TargetPackage() if obj.is_target else DecoyPackage())

        # Other agents as markers
        marker_colors = ["purple", "yellow", "grey", "red", "blue", "green"]
        marker_idx = 0
        for agent_id, agent in world.agents.items():
            if agent_id == primary_agent_id:
                continue
            x, y = agent.position
            color = marker_colors[marker_idx % len(marker_colors)]
            marker_idx += 1
            grid.set(x, y, AgentMarker(color=color))

        return grid"""

    def get_initial_world_objects(self) -> Dict[int, ObjectState]:
        return deepcopy(self.initial_object_states)

    def get_initial_agent_starts(self) -> List[Tuple[int, int]]:
        return list(self.initial_agent_starts)

    def step(self, action: int):
        self.world.episode.step_count += 1
        reward = -0.01
        terminated = False
        truncated = False
        info = {}

        # Get the position in front of the agent
        fwd_pos = self.front_pos
        fwd_cell = self.grid.get(*fwd_pos)

        # Rotate left
        if action == Actions.TURN_LEFT:
            self._turn_left()
            self.agent.last_action = Actions.TURN_LEFT
        # Rotate right
        elif action == Actions.TURN_RIGHT:
            self._turn_right()
            self.agent.last_action = Actions.TURN_RIGHT
        # Move forward
        elif action == Actions.MOVE_FORWARD:
            moved = self._move_forward()
            if not moved:
                reward -= 0.1  # Penalty for failed move
            self.agent.last_action = Actions.MOVE_FORWARD
        # Stay
        elif action == Actions.STAY:
            self.agent.last_action = Actions.STAY
        # Pick up or interact
        elif action == Actions.PICK_OR_INTERACT:
            success = self._handle_pick_or_interact()
            if not success:
                reward -= 0.1  # Penalty for failed pickup/interaction
            else:
                reward += 0.1  # Reward for successful pickup/interaction
            self.agent.last_action = Actions.PICK_OR_INTERACT
        # Drop
        elif action == Actions.DROP:    
            drop_reward = self._handle_drop()
            reward += drop_reward
            self.agent.last_action = Actions.DROP
        
        if self._all_targets_delivered():
            self.world.episode.terminated = True
            terminated = True
            reward += 10.0  # Bonus for completing the task
        
        if self.world.episode.step_count >= self.config.max_steps:
            self.world.episode.truncated = True
            truncated = True
        
        obs = self.gen_obs()


        return obs, reward, terminated, truncated, info

    def _turn_left(self):
        self.agent_dir  = (int(self.agent_dir) - 1) % 4

    def _turn_right(self):
        self.agent_dir = (int(self.agent_dir) + 1) % 4

    def _move_forward(self) -> bool:
        dx, dy = DIRECTION_VECTORS[Directions(self.agent_dir)]
        x, y = self.agent_pos
        next_pos = (x + dx, y + dy)

        if not self._is_free_for_agent(next_pos):
            return False

        self.agent_pos = next_pos
        return True

    def _is_free_for_agent(self, pos: Tuple[int, int]) -> bool:
        x, y = pos

        if not (0 <= x < self.config.width and 0 <= y < self.config.height):
            return False

        if pos in self.world.static.walls:
            return False


        # do not step onto undelivered, uncarried objects
        for obj in self.world.objects.values():
            if obj.delivered or obj.carried_by is not None:
                continue
            if obj.position == pos:
                return False

        return True
    
    def _handle_pick_or_interact(self) -> bool:
        fwd_pos = self.front_pos
        for obj in self.world.objects.values():
            if obj.delivered or obj.carried_by is not None:
                continue
            if obj.position == fwd_pos:
                # Pick up the object
                obj.carried_by = self.agent.agent_id
                self.agent.carrying_object_id = obj.object_id
                return True
        return False

    def _handle_drop(self):
        if self.agent.carrying_object_id is None:
            return 0.0
        
        obj = self.world.objects[self.agent.carrying_object_id]
        obj.position = self.agent.position
        obj.carried_by = None
        self.agent.carrying_object_id = None
        if obj.is_target and obj.position in self.world.static.delivery_zone:
            obj.delivered = True
            self.world.episode.delivered_target_count += 1
            return 20.0  # Reward for successful delivery
        return 0.0

    def _all_targets_delivered(self) -> bool:
        targets = [obj for obj in self.world.objects.values() if obj.is_target]
        return all(obj.delivered for obj in targets)