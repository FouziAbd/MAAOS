import numpy as np
import gymnasium
from gymnasium import spaces
from pettingzoo import ParallelEnv
import pygame
import random

class ToyRescueEnv(ParallelEnv):
    """
    Toy Rescue Custom Environment
    =============================

    A cooperative multi-agent PettingZoo environment where 3 agents must find, retrieve, 
    and deliver specific toys to a Drop Box in Room 7.

    Environment Details
    -------------------
    - Grid Size: 20x20
    - Rooms: 8 distinct rooms (1-8).
    - Drop Zone: Located in Room 7 (approx coordinates (5, 17)).
    
    Agents
    ------
    - Count: 3 (agent_0, agent_1, agent_2)
    - Capabilities: Move, Scan, Pick, Put.

    Toys & Spawning Logic
    ---------------------
    Only one toy can appear per room.
    1. Red (Round): Reward +10. Requires 1 agent. 
       - 90% Room 8, 10% Room 5.
    2. Pink (Square): Reward +50. Requires 2 agents (simultaneous pick & move).
       - 70% Room 1, 20% Room 2, 10% Room 8.
    3. Green (Rect): Reward +5. Requires 1 agent.
       - 50% Room 5, 50% spread among others.
    4. Blue (Round): Reward +15. Requires 1 agent.
       - 50% Room 4, 50% Room 6.

    Action Space (Discrete)
    -----------------------
    0: Stay (Cost 0)
    1: Move Up (Cost -1, 95% success)
    2: Move Down (Cost -1, 95% success)
    3: Move Left (Cost -1, 95% success)
    4: Move Right (Cost -1, 95% success)
       * Co-op Rule: If carrying Pink toy, both agents must move same direction.
    5: Camera (Cost -5, 80% success)
       * Reveals specific toy ID in observation.
    6: Pick (Cost -1 success / -4 fail, 90% success)
       * Pink toy requires 2 agents picking simultaneously.
    7: Put (Cost -1 success / -3 fail)
       * Delivers toy if in Drop Zone.

    Observation Space
    -----------------
    5x5 local grid centered on agent with 6 channels:
    0: Walls/Obstacles
    1: Other Agents
    2: Generic Toy Presence
    3: Specific Toy ID (visible only after successful Camera)
    4: Holding Status (self)
    5: Drop Zone
    """

    metadata = {
        "render_modes": ["human", "rgb_array"], 
        "name": "toy_rescue_v0",
        "render_fps": 4
    }

    def __init__(self, render_mode=None):
        self.possible_agents = [f"agent_{i}" for i in range(3)]
        self.agents = self.possible_agents[:]
        self.render_mode = render_mode
        
        # --- Configs ---
        self.grid_size = 20
        # Action Space: 
        # 0: Stay, 1: Up, 2: Down, 3: Left, 4: Right, 5: Camera, 6: Pick, 7: Put
        self._action_spaces = {agent: spaces.Discrete(8) for agent in self.possible_agents}
        
        # Observation Space: 5x5 grid with 6 channels
        self._observation_spaces = {
            agent: spaces.Box(low=0, high=5, shape=(5, 5, 6), dtype=np.float32)
            for agent in self.possible_agents
        }
        
        # Toys Configuration
        self.toy_specs = {
            1: {"name": "Red", "color": (255, 0, 0), "shape": "round", "reward": 10, "req_agents": 1},
            2: {"name": "Pink", "color": (255, 105, 180), "shape": "square", "reward": 50, "req_agents": 2},
            3: {"name": "Green", "color": (0, 255, 0), "shape": "rect", "reward": 5, "req_agents": 1},
            4: {"name": "Blue", "color": (0, 0, 255), "shape": "round", "reward": 15, "req_agents": 1},
        }

        self.screen = None
        self.clock = None
        self.cell_size = 30
        
        # Define Rooms (1-8)
        # Grid 20x20. 2 cols (0-9, 10-19), 4 rows (0-4, 5-9, 10-14, 15-19)
        self.rooms = {
            1: {"x": (0, 9),   "y": (0, 4)},
            2: {"x": (10, 19), "y": (0, 4)},
            3: {"x": (0, 9),   "y": (5, 9)},
            4: {"x": (10, 19), "y": (5, 9)},
            5: {"x": (0, 9),   "y": (10, 14)},
            6: {"x": (10, 19), "y": (10, 14)},
            7: {"x": (0, 9),   "y": (15, 19)}, # Bottom Left
            8: {"x": (10, 19), "y": (15, 19)}  # Bottom Right
        }

    def reset(self, seed=None, options=None):
        self.agents = self.possible_agents[:]
        self.num_moves = 0
        
        self.grid = np.zeros((self.grid_size, self.grid_size), dtype=int)
        self._build_walls()
        
        # Place Drop Box in Room 7 (Bottom Left)
        # Center of Room 7 approx (5, 17)
        self.drop_zone_pos = (5, 17)
        self.grid[self.drop_zone_pos[1], self.drop_zone_pos[0]] = 7

        self.toys = []
        self.agent_states = {}

        # 1. Spawn Toys (One per room constraint)
        occupied_rooms = set()
        
        # Toy 1 (Red): 90% Room 8, 10% Room 5
        self._spawn_toy(1, {8: 0.9, 5: 0.1}, occupied_rooms)
        
        # Toy 2 (Pink): 70% Room 1, 20% Room 2, 10% Room 8
        self._spawn_toy(2, {1: 0.7, 2: 0.2, 8: 0.1}, occupied_rooms)
        
        # Toy 3 (Green): 50% Room 5, 50% others
        others = [r for r in range(1, 9) if r != 5]
        probs = {5: 0.5}
        for r in others: probs[r] = 0.5 / len(others)
        self._spawn_toy(3, probs, occupied_rooms)
        
        # Toy 4 (Blue): 50% Room 4, 50% Room 6
        self._spawn_toy(4, {4: 0.5, 6: 0.5}, occupied_rooms)

        # 2. Spawn Agents (Random free spots)
        for agent in self.agents:
            pos = self._find_empty_pos_global()
            self.agent_states[agent] = {"pos": list(pos), "holding": None}

        observations = {agent: self._get_obs(agent, camera_active=False) for agent in self.agents}
        infos = {agent: {} for agent in self.agents}
        
        return observations, infos

    def _spawn_toy(self, toy_id, prob_dist, occupied_rooms):
        # prob_dist: {room_id: probability}
        # Normalize probs if rooms are occupied
        available_rooms = [r for r in prob_dist.keys() if r not in occupied_rooms]
        
        target_room = None
        if not available_rooms:
            # Fallback: Find ANY empty room not in original distro
            all_free = [r for r in range(1, 9) if r not in occupied_rooms]
            if all_free:
                target_room = random.choice(all_free)
            else:
                # No rooms left (shouldn't happen with 4 toys 8 rooms), spawn anywhere globally
                pos = self._find_empty_pos_global()
                self.toys.append({"id": toy_id, "pos": list(pos), "active": True, "carrier": None})
                return
        else:
            # Weighted choice among available preferred rooms
            weights = [prob_dist[r] for r in available_rooms]
            total = sum(weights)
            norm_weights = [w/total for w in weights]
            target_room = random.choices(available_rooms, weights=norm_weights, k=1)[0]
            
        # Spawn in target_room
        pos = self._find_empty_pos_in_room(target_room)
        self.toys.append({"id": toy_id, "pos": list(pos), "active": True, "carrier": None})
        occupied_rooms.add(target_room)

    def step(self, actions):
        rewards = {agent: 0 for agent in self.agents}
        terminations = {agent: False for agent in self.agents}
        truncations = {agent: False for agent in self.agents}
        infos = {agent: {} for agent in self.agents}
        camera_results = {}

        # --- Pre-processing: Coupled Movement for Pink Toy ---
        # Identify agents holding Pink Toy (ID 2)
        pink_carriers = [a for a in self.agents if self.agent_states[a]["holding"] == 2]
        
        if len(pink_carriers) == 2:
            a1, a2 = pink_carriers[0], pink_carriers[1]
            act1, act2 = actions[a1], actions[a2]
            
            # Check if both are moving
            is_move_1 = act1 in [1, 2, 3, 4]
            is_move_2 = act2 in [1, 2, 3, 4]
            
            if is_move_1 or is_move_2:
                # If intended actions are different, they FAIL to move (Stay)
                # They still pay the cost of the attempt in the main loop? 
                # Prompt: "if not they will stay in the same spot".
                if act1 != act2:
                    # Override actions to 0 (Stay) effectively preventing movement
                    # But we might want to preserve cost? 
                    # Simpler to just override action to 0, which has 0 cost usually.
                    # Let's override to 0 so they don't move.
                    actions[a1] = 0
                    actions[a2] = 0
                    # Maybe add a small penalty for uncoordinated tug?
                    # rewards[a1] -= 0.5
                    # rewards[a2] -= 0.5
        
        # --- Main Action Loop ---
        for agent, action in actions.items():
            state = self.agent_states[agent]
            
            if action == 0: # Stay
                rewards[agent] += 0
            
            elif action in [1, 2, 3, 4]: # Move
                rewards[agent] += -1
                if random.random() < 0.95:
                    new_pos = list(state["pos"])
                    if action == 1: new_pos[1] -= 1 # Up
                    elif action == 2: new_pos[1] += 1 # Down
                    elif action == 3: new_pos[0] -= 1 # Left
                    elif action == 4: new_pos[0] += 1 # Right
                    
                    if (0 <= new_pos[0] < self.grid_size and 
                        0 <= new_pos[1] < self.grid_size and 
                        self.grid[new_pos[1], new_pos[0]] != 1):
                        state["pos"] = new_pos
            
            elif action == 5: # Camera
                rewards[agent] += -5
                success = random.random() < 0.80
                camera_results[agent] = success
            
            elif action == 7: # Put
                if state["holding"] is not None:
                    rewards[agent] += -1
                    # Check Room 7 Drop Zone (5, 17)
                    if tuple(state["pos"]) == self.drop_zone_pos:
                        toy_id = state["holding"]
                        toy_reward = self.toy_specs[toy_id]["reward"]
                        rewards[agent] += toy_reward
                        
                        # Logic for multi-agent put? 
                        # If pink toy, do both get reward? 
                        # Currently this loop runs per agent. 
                        # If A puts Pink, A gets 50. B is still holding Pink?
                        # We need to handle Shared Holding clear.
                        
                        state["holding"] = None
                        
                        # Clear for partner if shared
                        if self.toy_specs[toy_id]["req_agents"] > 1:
                            for other in self.agents:
                                if self.agent_states[other]["holding"] == toy_id:
                                    self.agent_states[other]["holding"] = None
                                    rewards[other] += toy_reward # Partner gets reward too

                        for t in self.toys:
                            if t["id"] == toy_id:
                                t["active"] = False
                                t["carrier"] = None
                    else:
                        # Drop on ground
                        toy_id = state["holding"]
                        state["holding"] = None
                        
                        # Handle partner drop
                        if self.toy_specs[toy_id]["req_agents"] > 1:
                            for other in self.agents:
                                if self.agent_states[other]["holding"] == toy_id:
                                    self.agent_states[other]["holding"] = None
                        
                        for t in self.toys:
                            if t["id"] == toy_id:
                                t["carrier"] = None
                                t["pos"] = list(state["pos"])
                else:
                    rewards[agent] += -3

        # --- Pick Logic (Synchronous) ---
        picks_attempted = {agent: None for agent in self.agents}
        for agent, action in actions.items():
            if action == 6:
                my_pos = self.agent_states[agent]["pos"]
                target_toy_idx = -1
                for idx, toy in enumerate(self.toys):
                    if not toy["active"] or toy["carrier"] is not None: continue
                    dist = abs(toy["pos"][0] - my_pos[0]) + abs(toy["pos"][1] - my_pos[1])
                    if dist <= 1:
                        target_toy_idx = idx
                        break
                picks_attempted[agent] = target_toy_idx

        processed_agents = set()
        for agent, action in actions.items():
            if action != 6 or agent in processed_agents: continue
            
            toy_idx = picks_attempted[agent]
            if toy_idx == -1:
                rewards[agent] += -4
                processed_agents.add(agent)
                continue

            toy = self.toys[toy_idx]
            req_agents = self.toy_specs[toy["id"]]["req_agents"]
            
            if req_agents == 1:
                if random.random() < 0.90:
                    rewards[agent] += -1
                    self.agent_states[agent]["holding"] = toy["id"]
                    toy["carrier"] = agent
                    toy["pos"] = [-1, -1]
                else:
                    rewards[agent] += -4
                processed_agents.add(agent)
            
            elif req_agents == 2:
                partner = None
                for other, other_idx in picks_attempted.items():
                    if other != agent and other_idx == toy_idx:
                        partner = other
                        break
                
                if partner:
                    if random.random() < 0.90:
                        rewards[agent] += -1
                        rewards[partner] += -1
                        self.agent_states[agent]["holding"] = toy["id"]
                        self.agent_states[partner]["holding"] = toy["id"] # Both hold it
                        toy["carrier"] = "shared"
                        toy["pos"] = [-1, -1]
                    else:
                        rewards[agent] += -4
                        rewards[partner] += -4
                    processed_agents.add(agent)
                    processed_agents.add(partner)
                else:
                    rewards[agent] += -4
                    processed_agents.add(agent)

        # Observations & Termination
        observations = {}
        for agent in self.agents:
            cam_active = camera_results.get(agent, False)
            observations[agent] = self._get_obs(agent, cam_active)
        
        active_toys = [t for t in self.toys if t["active"]]
        if not active_toys:
            terminations = {a: True for a in self.agents}
        
        self.num_moves += 1
        if self.num_moves > 500:
            truncations = {a: True for a in self.agents}

        if self.render_mode == "human":
            self.render()

        return observations, rewards, terminations, truncations, infos

    def _get_obs(self, agent_id, camera_active):
        obs = np.zeros((5, 5, 6), dtype=np.float32)
        agent_pos = self.agent_states[agent_id]["pos"]
        x_start, y_start = agent_pos[0] - 2, agent_pos[1] - 2
        
        for i in range(5):
            for j in range(5):
                gx, gy = x_start + i, y_start + j
                if not (0 <= gx < self.grid_size and 0 <= gy < self.grid_size):
                    obs[i, j, 0] = 1 
                    continue
                if self.grid[gy, gx] == 1: obs[i, j, 0] = 1
                if self.grid[gy, gx] == 7: obs[i, j, 5] = 1 # Drop zone visible

                for other_id, state in self.agent_states.items():
                    if other_id != agent_id and state["pos"] == [gx, gy]:
                        obs[i, j, 1] = 1
                
                for toy in self.toys:
                    # Show toy if active and not carried (OR carried by self/partner?)
                    # Usually if carried, it's not on grid. 
                    if toy["active"] and toy["carrier"] is None and toy["pos"] == [gx, gy]:
                        obs[i, j, 2] = 1
                        if camera_active:
                            obs[i, j, 3] = toy["id"]
        
        if self.agent_states[agent_id]["holding"]:
             obs[:, :, 4] = 1.0 
        return obs

    def _build_walls(self):
        mid_x = self.grid_size // 2
        self.grid[:, mid_x] = 1
        h_steps = [self.grid_size // 4 * i for i in range(1, 4)]
        for y in h_steps: self.grid[y, :] = 1
        for i in range(4):
            y_door = (self.grid_size // 4) * i + 2
            self.grid[y_door, mid_x] = 0
        for y in h_steps:
            self.grid[y, self.grid_size // 4] = 0
            self.grid[y, self.grid_size // 4 * 3] = 0

    def _find_empty_pos_global(self):
        while True:
            x = random.randint(0, self.grid_size-1)
            y = random.randint(0, self.grid_size-1)
            if self._is_valid_spawn(x, y):
                return (x, y)

    def _find_empty_pos_in_room(self, room_id):
        rx, ry = self.rooms[room_id]["x"], self.rooms[room_id]["y"]
        while True:
            x = random.randint(rx[0], rx[1])
            y = random.randint(ry[0], ry[1])
            if self._is_valid_spawn(x, y):
                return (x, y)

    def _is_valid_spawn(self, x, y):
        if self.grid[y, x] != 0: return False # Wall or Box
        # Check occupancy
        for a in self.agent_states.values():
            if a["pos"] == [x, y]: return False
        for t in self.toys:
            if t["pos"] == [x, y]: return False
        return True

    def observation_space(self, agent):
        return self._observation_spaces[agent]

    def action_space(self, agent):
        return self._action_spaces[agent]

    def render(self):
        if self.render_mode is None: return
        if self.screen is None:
            pygame.init()
            if self.render_mode == "human":
                self.screen = pygame.display.set_mode((self.grid_size * self.cell_size, self.grid_size * self.cell_size))
                pygame.display.set_caption("Toy Rescue Env")
            else:
                self.screen = pygame.Surface((self.grid_size * self.cell_size, self.grid_size * self.cell_size))
        if self.clock is None: self.clock = pygame.time.Clock()

        self.screen.fill((255, 255, 255))
        for y in range(self.grid_size):
            for x in range(self.grid_size):
                rect = pygame.Rect(x*self.cell_size, y*self.cell_size, self.cell_size, self.cell_size)
                if self.grid[y, x] == 1: pygame.draw.rect(self.screen, (0, 0, 0), rect)
                elif self.grid[y, x] == 7:
                    pygame.draw.rect(self.screen, (200, 200, 200), rect) # Drop Zone
                    pygame.draw.rect(self.screen, (0, 0, 0), rect, 2)

        for toy in self.toys:
            if toy["active"] and (toy["carrier"] is None):
                tx, ty = toy["pos"]
                center = (tx*self.cell_size + self.cell_size//2, ty*self.cell_size + self.cell_size//2)
                color = self.toy_specs[toy["id"]]["color"]
                shape = self.toy_specs[toy["id"]]["shape"]
                if shape == "round": pygame.draw.circle(self.screen, color, center, self.cell_size//3)
                elif shape == "square": pygame.draw.rect(self.screen, color, (tx*self.cell_size+5, ty*self.cell_size+5, 20, 20))
                elif shape == "rect": pygame.draw.rect(self.screen, color, (tx*self.cell_size+8, ty*self.cell_size+2, 14, 26))

        for agent_id, state in self.agent_states.items():
            ax, ay = state["pos"]
            pygame.draw.circle(self.screen, (100, 100, 100), (ax*self.cell_size+15, ay*self.cell_size+15), 13)
            if state["holding"]:
                pygame.draw.circle(self.screen, self.toy_specs[state["holding"]]["color"], (ax*self.cell_size+15, ay*self.cell_size+15), 6)

        if self.render_mode == "human":
            pygame.display.flip()
            self.clock.tick(self.metadata["render_fps"])

    def close(self):
        if self.screen is not None:
            pygame.quit()
            self.screen = None