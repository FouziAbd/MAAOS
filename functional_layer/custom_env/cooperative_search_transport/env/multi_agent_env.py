from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from gymnasium import spaces
from pettingzoo import ParallelEnv
from objects import AgentMarker
from constants import Actions, CellType, DIRECTION_VECTORS, Directions
from cooperative_search_transport_env import CooperativeSearchTransportMiniGridEnv
from state import AgentState, EnvConfig, EpisodeState, StaticWorld, WorldState


class MultiAgentCooperativeSearchTransportEnv(ParallelEnv):
    metadata = {
        "name": "cooperative_search_transport_parallel_v1",
        "render_modes": ["human", "rgb_array", "text"],
    }

    def __init__(self, config: Optional[EnvConfig] = None):
        self.config = config or EnvConfig()
        self.config.validate()

        self.core_env = CooperativeSearchTransportMiniGridEnv(config=self.config)
        self.core_env._gen_grid = self._gen_grid ##??


        self.possible_agents = [f"agent_{i}" for i in range(self.config.num_agents)]
        self.agents = list(self.possible_agents)

        # Override get_frame to decouple agent rendering from grid logic
        def custom_get_frame(*args, **kwargs):
            tile_size = kwargs.get('tile_size', 32)
            if len(args) > 1:
                tile_size = args[1]
            
            # FIRST: Remove all agents from grid so they don't render twice
            for agent in self.possible_agents:
                if agent in self.agent_positions:
                    pos = self.agent_positions[agent]
                    self.core_env.grid.set(*pos, None)
            
            # SECOND: Render grid without agents
            img = self.core_env.grid.render(tile_size, agent_pos=(-1, -1), agent_dir=0, highlight_mask=None)

            # THIRD: Manually render agents at their current positions
            for agent in self.possible_agents:
                if agent in self.agent_positions:
                    pos = self.agent_positions[agent]
                    ag_obj = self.agent_objects[agent]
                    
                    ymin = pos[1] * tile_size
                    ymax = (pos[1] + 1) * tile_size
                    xmin = pos[0] * tile_size
                    xmax = (pos[0] + 1) * tile_size
                    
                    tile_img = img[ymin:ymax, xmin:xmax, :]
                    ag_obj.render(tile_img)
            
            # FOURTH: Put agents back in grid for next render
            for agent in self.possible_agents:
                if agent in self.agent_positions:
                    pos = self.agent_positions[agent]
                    self.core_env.grid.set(*pos, self.agent_objects[agent])
            
            return img

        self.core_env.get_frame = custom_get_frame

        self.core_env.world = WorldState()
        self.core_env.world.agents = self.agents

    def action_space(self, agent: str):
        # 0: left, 1: right, 2: forward
        return spaces.Discrete(3)

    def observation_space(self, agent: str):
        return self.core_env.observation_space

    def _get_agent_start_positions(self) -> List[Tuple[int, int]]:
        # Safe fixed starting cells for up to several agents
        return [
            (10, 10),
            (10, 9),
            (9, 10),
            (9, 9),
            (10, 8),
            (9, 8),
            #(8, 10),
            #(8, 9),
        ]

    def _gen_grid(self, width, height):
        self.core_env.grid = self.core_env._build_base_grid(width, height)
        self.core_env.agent_pos = (-1, -1)
        self.core_env.agent_dir = 0
        self.agent_positions = {}
        self.agent_dirs = {}
        self.agent_objects = {}

        self.core_env.initial_object_states = self.core_env._get_initial_object_states()
        for obj_state in self.core_env.initial_object_states.values():
            self.core_env._put_object_from_state(obj_state)
        colors = ["green", "red", "blue", "purple", "yellow", "grey"]

        for id in range(len(self.possible_agents)):
            agent_id = self.possible_agents[id]
            pos = self._get_agent_start_positions()[id]
            self.agent_positions[agent_id] = pos
            self.agent_dirs[agent_id] = Directions.LEFT
            marker = AgentMarker(color=colors[id % len(colors)], dir=self.agent_dirs[agent_id])
            self.agent_objects[agent_id] = marker
            self.core_env.grid.set(*pos, marker)
        
        self.core_env.agent_pos = (10, 10) # Dummy for MiniGrid assertions
        self.core_env.agent_dir = int(Directions.LEFT)


    def reset(self, seed: Optional[int] = None, options: Optional[dict] = None):
        self.agents = list(self.possible_agents)

        # Reset the core MiniGrid world so static layout exists
        self.core_env.reset(seed=seed, options=options)

        # Place agents in grid for initial render and correct obs
        for agent in self.agents:
            pos = self.agent_positions[agent]
            self.core_env.grid.set(*pos, self.agent_objects[agent])

        observations = {}
        for agent in self.agents:
            pos = self.agent_positions[agent]
            self.core_env.agent_pos = pos
            self.core_env.agent_dir = self.agent_dirs[agent]
            
            # Temporarily hide agent from grid so it doesn't observe itself as an obstacle
            self.core_env.grid.set(*pos, None)
            observations[agent] = self.core_env.gen_obs()
            self.core_env.grid.set(*pos, self.agent_objects[agent])
            self.core_env.world.agents[agent] = AgentState(
                agent_id=agent,
                position=pos,
                direction=self.agent_dirs[agent],
            )
            
        self.core_env.agent_pos = (-1, -1) # Reset back to dummy invisible space 
        
        return observations, {agent: {} for agent in self.agents}


    def step(self, actions: Dict[str, int]):
        self.core_env.world.episode.step_count += 1

        rewards = {agent_id: -0.01 for agent_id in self.agents}
        terminations = {agent_id: False for agent_id in self.agents}
        truncations = {agent_id: False for agent_id in self.agents}
        infos = {agent_id: {} for agent_id in self.agents}

        # Default missing actions to STAY
        joint_actions = {
            agent_id: int(actions.get(agent_id, Actions.STAY))
            for agent_id in self.agents
        }

        # Reset cooperation flags
        for agent in self.core_env.world.agents.values():
            agent.cooperating = False

        # 1) Turn / move / mark cooperate
        for agent_id in self.agents:
            action = joint_actions[agent_id]
            agent = self.core_env.world.agents[agent_id]
            agent.last_action = action

            if action == Actions.TURN_LEFT:
                self._turn_left(agent)
            elif action == Actions.TURN_RIGHT:
                self._turn_right(agent)
            elif action == Actions.MOVE_FORWARD:
                # Jointly-held agents move as a group in phase 3 — skip individual move
                if self._is_agent_in_joint_hold(agent_id):
                    pass
                else:
                    moved = self._move_forward(agent)
                    if not moved:
                        rewards[agent_id] -= 0.1
            elif action == Actions.COOPERATE:
                agent.cooperating = True
            elif action == Actions.STAY:
                pass

        # 2) Single-agent pickup / drop
        for agent_id in self.agents:
            action = joint_actions[agent_id]
            if action == Actions.PICK_OR_INTERACT:
                self._handle_pick_or_interact(agent_id, rewards)
            elif action == Actions.DROP:
                self._handle_drop(agent_id, rewards)

        # 3) Cooperative object carry (joint-hold model using engaged_agents)
        self._resolve_cooperative_carry(joint_actions, rewards)

        # 4) Move carried single-agent objects with their carriers
        self._sync_carried_objects()

        # 5) Check automatic delivery for pushed cooperative objects in zone
        self._check_object_delivery_rewards(rewards)

        # 6) Termination / truncation
        if self._all_targets_delivered():
            self.core_env.world.episode.terminated = True
            terminations = {agent_id: True for agent_id in self.agents}
            for agent_id in self.agents:
                rewards[agent_id] += 10.0

        if self.core_env.world.episode.step_count >= self.config.max_steps:
            self.core_env.world.episode.truncated = True
            truncations = {agent_id: True for agent_id in self.agents}

        observations = self._get_all_observations()
        return observations, rewards, terminations, truncations, infos

    def render(self):
        self.core_env.render()
    """def render(self):
        mode = self.config.render_mode

        if mode == "text":
            self._render_text()
            return None

        primary_agent_id = self.agents[0] if self.agents else None
        render_grid = self.core_env.build_render_grid(self.core_env.world, primary_agent_id)

        self.core_env.grid = render_grid

        if primary_agent_id is not None:
            primary = self.core_env.world.agents[primary_agent_id]
            self.core_env.agent_pos = primary.position
            self.core_env.agent_dir = int(primary.direction)

        return self.core_env.render()"""

    def close(self):
        self.core_env.close()

    # ---------- Movement / interaction ----------

    def _turn_left(self, agent: AgentState):
        agent.direction = (int(agent.direction) - 1) % 4
        self.agent_objects[agent.agent_id].dir = agent.direction
        self.agent_dirs[agent.agent_id] = agent.direction

    def _turn_right(self, agent: AgentState):
        agent.direction = (int(agent.direction) + 1) % 4
        self.agent_objects[agent.agent_id].dir = agent.direction
        self.agent_dirs[agent.agent_id] = agent.direction

    def _move_forward(self, agent: AgentState) -> bool:
        dx, dy = DIRECTION_VECTORS[Directions(agent.direction)]
        x, y = agent.position
        next_pos = (x + dx, y + dy)

        if not self._is_free_for_agent(next_pos, moving_agent_id=agent.agent_id):
            return False

        self.core_env.grid.set(*agent.position, None)

        agent.position = next_pos
        self.agent_positions[agent.agent_id] = next_pos
        self.core_env.grid.set(*agent.position, self.agent_objects[agent.agent_id])
        return True

    def _is_free_for_agent(self, pos: Tuple[int, int], moving_agent_id: str) -> bool:
        x, y = pos

        if not (0 <= x < self.config.width and 0 <= y < self.config.height):
            return False

        if pos in self.core_env.world.static.walls:
            return False

        for agent_id, agent in self.core_env.world.agents.items():
            if agent_id != moving_agent_id and agent.position == pos:
                return False

        # do not step onto undelivered, uncarried, unheld objects
        for obj in self.core_env.world.objects.values():
            if obj.delivered or obj.carried_by is not None:
                continue
            if len(obj.engaged_agents) >= obj.required_agents:
                continue  # jointly held and removed from grid
            if obj.position == pos:
                return False

        return True

    def _handle_pick_or_interact(self, agent_id: str, rewards: Dict[str, float]):
        agent = self.core_env.world.agents[agent_id]

        if agent.carrying_object_id is not None:
            return

        front_pos = self._get_front_pos(agent)

        for obj in self.core_env.world.objects.values():
            if obj.delivered or obj.carried_by is not None:
                continue
            if obj.position != front_pos:
                continue

            if obj.required_agents == 1:
                # Single-agent pickup
                obj.carried_by = agent_id
                agent.carrying_object_id = obj.object_id
                rewards[agent_id] += 0.1
                self.core_env.grid.set(*obj.position, None)
            elif obj.required_agents > 1 and agent_id not in obj.engaged_agents:
                # Cooperative engagement: latch on
                obj.engaged_agents.append(agent_id)
                rewards[agent_id] += 0.05
                # Once fully engaged, remove object from grid (it is now "held")
                if len(obj.engaged_agents) >= obj.required_agents:
                    self.core_env.grid.set(*obj.position, None)
            return

    def _handle_drop(self, agent_id: str, rewards: Dict[str, float]):
        agent = self.core_env.world.agents[agent_id]

        # Single-carry drop
        if agent.carrying_object_id is not None:
            obj = self.core_env.world.objects[agent.carrying_object_id]
            obj.position = agent.position
            obj.carried_by = None
            agent.carrying_object_id = None
            if obj.is_target and obj.position in self.core_env.world.static.delivery_zone:
                obj.delivered = True
                self.core_env.world.episode.delivered_target_count += 1
                rewards[agent_id] += 20.0
            return

        # Cooperative disengage: remove agent from any jointly-held object
        for obj in self.core_env.world.objects.values():
            if agent_id not in obj.engaged_agents:
                continue
            was_fully_held = len(obj.engaged_agents) >= obj.required_agents
            obj.engaged_agents.remove(agent_id)
            if was_fully_held:
                # Object is no longer fully held — put it back on the grid
                self._place_object_on_grid(obj)
            break

    def _sync_carried_objects(self):
        for agent in self.core_env.world.agents.values():
            if agent.carrying_object_id is None:
                continue
            obj = self.core_env.world.objects[agent.carrying_object_id]
            obj.position = agent.position

    def _resolve_cooperative_carry(
        self,
        joint_actions: Dict[str, int],
        rewards: Dict[str, float],
    ):
        """
        Joint-carry model using engaged_agents:
        - Agents latch on via PICK_OR_INTERACT (see _handle_pick_or_interact).
        - Once fully engaged (len >= required_agents), the object is held off-grid.
        - Each step: if ALL engaged agents choose MOVE_FORWARD facing the same
          direction, every agent AND the object move one cell together.
        - STAY or COOPERATE keeps the hold without moving.
        - Any other action (TURN is allowed) causes that agent to disengage.
        """
        for obj in self.core_env.world.objects.values():
            if obj.delivered or obj.carried_by is not None:
                continue
            if len(obj.engaged_agents) < obj.required_agents:
                continue

            engaged_ids = list(obj.engaged_agents)

            # Agents that take an incompatible action disengage.
            # PICK_OR_INTERACT is allowed: an agent may use it to latch on
            # in the same step that the hold becomes fully engaged.
            # DROP is handled in phase 2 (_handle_drop) already.
            to_disengage = [
                aid for aid in engaged_ids
                if joint_actions[aid] not in (
                    Actions.MOVE_FORWARD, Actions.STAY, Actions.COOPERATE,
                    Actions.TURN_LEFT, Actions.TURN_RIGHT,
                    Actions.PICK_OR_INTERACT, Actions.DROP,
                )
            ]
            if to_disengage:
                for aid in to_disengage:
                    obj.engaged_agents.remove(aid)
                # No longer fully held — put object back on grid
                self._place_object_on_grid(obj)
                continue

            # Check if all want to move forward
            movers = [
                self.core_env.world.agents[aid]
                for aid in obj.engaged_agents
                if joint_actions[aid] == Actions.MOVE_FORWARD
            ]

            if len(movers) != len(obj.engaged_agents):
                # Some are staying / turning — hold in place this step
                continue

            # All moving: require same facing direction
            directions = {int(a.direction) for a in movers}
            if len(directions) != 1:
                continue  # Disagreement on direction — hold in place

            move_dir = Directions(next(iter(directions)))
            dx, dy = DIRECTION_VECTORS[move_dir]
            new_obj_pos = (obj.position[0] + dx, obj.position[1] + dy)
            new_agent_positions = {
                a.agent_id: (a.position[0] + dx, a.position[1] + dy)
                for a in movers
            }
            current_mover_positions = {a.position for a in movers}

            # Atomic feasibility check for object and all agents
            feasible = True
            for pos in list(new_agent_positions.values()) + [new_obj_pos]:
                x, y = pos
                if not (0 <= x < self.config.width and 0 <= y < self.config.height):
                    feasible = False; break
                if pos in self.core_env.world.static.walls:
                    feasible = False; break
                if pos in current_mover_positions:
                    continue  # Will be vacated this step
                for other_id, other in self.core_env.world.agents.items():
                    if other_id not in new_agent_positions and other.position == pos:
                        feasible = False; break
                if not feasible:
                    break
                for other_obj in self.core_env.world.objects.values():
                    if other_obj.object_id == obj.object_id or other_obj.delivered:
                        continue
                    if other_obj.carried_by is not None:
                        continue
                    if len(other_obj.engaged_agents) >= other_obj.required_agents:
                        continue  # Also off-grid
                    if other_obj.position == pos:
                        feasible = False; break

            if not feasible:
                continue

            # Execute joint move: clear old agent cells, update, set new cells
            for agent in movers:
                self.core_env.grid.set(*agent.position, None)
            for agent in movers:
                new_pos = new_agent_positions[agent.agent_id]
                agent.position = new_pos
                self.agent_positions[agent.agent_id] = new_pos
                self.core_env.grid.set(*new_pos, self.agent_objects[agent.agent_id])
                rewards[agent.agent_id] += 0.2

            obj.position = new_obj_pos
            # Object stays off-grid while held; delivery check uses logical position

    def _is_agent_in_joint_hold(self, agent_id: str) -> bool:
        """Returns True if the agent is part of a fully-engaged cooperative hold."""
        for obj in self.core_env.world.objects.values():
            if agent_id in obj.engaged_agents and len(obj.engaged_agents) >= obj.required_agents:
                return True
        return False

    def _place_object_on_grid(self, obj) -> None:
        """Put a cooperative object back onto the MiniGrid grid at its logical position."""
        from objects import TargetPackage, DecoyPackage
        cell_obj = TargetPackage() if obj.is_target else DecoyPackage()
        self.core_env.grid.set(*obj.position, cell_obj)

    def _is_free_for_object(self, pos: Tuple[int, int], ignore_object_id: int) -> bool:
        x, y = pos
        if not (0 <= x < self.config.width and 0 <= y < self.config.height):
            return False

        if pos in self.core_env.world.static.walls:
            return False

        for agent in self.core_env.world.agents.values():
            if agent.position == pos:
                return False

        for obj in self.core_env.world.objects.values():
            if obj.object_id == ignore_object_id or obj.delivered:
                continue
            if obj.carried_by is not None:
                continue
            if obj.position == pos:
                return False

        return True

    # ---------- Observation ----------

    def _get_all_observations(self) -> Dict[str, Dict[str, Any]]:
        return {
            agent_id: self._get_observation_for_agent(agent_id)
            for agent_id in self.agents
        }

    def _get_observation_for_agent(self, agent_id: str) -> Dict[str, Any]:
        agent = self.core_env.world.agents[agent_id]

        pos = self.agent_positions[agent_id]
        self.core_env.agent_pos = pos
        self.core_env.agent_dir = self.agent_dirs[agent_id]
        self.core_env.grid.set(*pos, None)
        mini_obs  = self.core_env.gen_obs()
        self.core_env.grid.set(*pos, self.agent_objects[agent_id])


        return mini_obs

    def _extract_local_grid(
        self,
        center_pos: Tuple[int, int],
        view_size: int,
    ) -> List[List[int]]:
        half = view_size // 2
        cx, cy = center_pos

        grid = []
        for dy in range(-half, half + 1):
            row = []
            for dx in range(-half, half + 1):
                x, y = cx + dx, cy + dy
                row.append(self._encode_cell((x, y), observer_pos=center_pos))
            grid.append(row)

        return grid

    def _encode_cell(self, pos: Tuple[int, int], observer_pos: Tuple[int, int]) -> int:
        x, y = pos

        if not (0 <= x < self.config.width and 0 <= y < self.config.height):
            return int(CellType.WALL)

        if pos in self.core_env.world.static.walls:
            return int(CellType.WALL)

        # Option 1: self is NOT encoded as AGENT, only underlying world
        if pos in self.core_env.world.static.delivery_zone:
            return int(CellType.DELIVERY)

        for agent in self.core_env.world.agents.values():
            if agent.position == pos and pos != observer_pos:
                return int(CellType.AGENT)

        for obj in self.core_env.world.objects.values():
            if obj.delivered or obj.carried_by is not None:
                continue
            if obj.position == pos:
                return int(CellType.TARGET_OBJECT if obj.is_target else CellType.NON_TARGET_OBJECT)

        return int(CellType.EMPTY)

    # ---------- Helpers ----------

    def _get_front_pos(self, agent: AgentState) -> Tuple[int, int]:
        dx, dy = DIRECTION_VECTORS[Directions(agent.direction)]
        x, y = agent.position
        return (x + dx, y + dy)

    def _manhattan(self, a: Tuple[int, int], b: Tuple[int, int]) -> int:
        return abs(a[0] - b[0]) + abs(a[1] - b[1])

    def _all_targets_delivered(self) -> bool:
        targets = [obj for obj in self.core_env.world.objects.values() if obj.is_target]
        return all(obj.delivered for obj in targets)

    def _check_object_delivery_rewards(self, rewards: Dict[str, float]):
        for obj in self.core_env.world.objects.values():
            if obj.delivered:
                continue
            if obj.is_target and obj.position in self.core_env.world.static.delivery_zone:
                obj.delivered = True
                self.core_env.world.episode.delivered_target_count += 1
                for agent_id in obj.engaged_agents:
                    rewards[agent_id] += 20.0

    # ---------- Text render ----------

    def _render_text(self):
        canvas = [["." for _ in range(self.config.width)] for _ in range(self.config.height)]

        for (x, y) in self.core_env.world.static.walls:
            canvas[y][x] = "#"

        for (x, y) in self.core_env.world.static.delivery_zone:
            canvas[y][x] = "D"

        for obj in self.core_env.world.objects.values():
            if obj.delivered or obj.carried_by is not None:
                continue
            x, y = obj.position
            canvas[y][x] = "T" if obj.is_target else "O"

        agent_symbols = ["A", "B", "C", "E", "F", "G", "H", "I"]
        for idx, agent_id in enumerate(self.agents):
            agent = self.core_env.world.agents[agent_id]
            x, y = agent.position
            canvas[y][x] = agent_symbols[idx % len(agent_symbols)]

        print(f"\nStep: {self.core_env.world.episode.step_count}")
        for row in canvas:
            print("".join(row))