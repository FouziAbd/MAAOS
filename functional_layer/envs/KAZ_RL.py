"""
KAZ_RL.py - Simple Reinforcement Learning Wrapper for Knights, Archers, Zombies

This module wraps the Pettingzoo KAZ environment with standard RL rewards:
  - Action penalty: -0.01 per step (all actions penalized for efficiency)
  - Kill reward: +1.0 for each zombie killed (good outcome)
  - Death penalty: -1.0 when agent dies (failure)
  - Escape penalty: -1.0 when zombie reaches bottom border (failure)
"""

import numpy as np
from pettingzoo.butterfly import knights_archers_zombies_v10
from typing import Dict, Tuple, Any


class KAZRLWrapper:
    """
    Simple RL reward wrapper for the KAZ environment.
    Standard RL approach: all actions penalized, only good outcomes rewarded.
    """

    def __init__(
        self,
        render_mode=None,
        spawn_rate=20,
        num_archers=2,
        num_knights=2,
        max_zombies=10,
        max_arrows=10,
        killable_knights=True,
        killable_archers=True,
        pad_observation=True,
        line_death=False,
        max_cycles=900,
        vector_state=True,
        use_typemasks=False,
        sequence_space=False,
        # Standard RL reward parameters
        reward_kill=1.0,
        penalty_action=-0.01,  # All actions penalized for efficiency
        penalty_death=-1.0,
        penalty_zombie_escape=-1.0,
    ):
        """
        Initialize KAZ_RL wrapper with standard RL rewards.
        
        Args:
            Standard PettingZoo KAZ parameters...
            reward_kill : Reward for killing a zombie
            penalty_action : Penalty for taking any action (-0.01 encourages efficiency)
            penalty_death : Penalty when agent dies
            penalty_zombie_escape : Penalty when zombie escapes to bottom
        """
        self.base_env = knights_archers_zombies_v10.parallel_env(
            render_mode=render_mode,
            spawn_rate=spawn_rate,
            num_archers=num_archers,
            num_knights=num_knights,
            max_zombies=max_zombies,
            max_arrows=max_arrows,
            killable_knights=killable_knights,
            killable_archers=killable_archers,
            pad_observation=pad_observation,
            line_death=line_death,
            max_cycles=max_cycles,
            vector_state=vector_state,
            use_typemasks=use_typemasks,
            sequence_space=sequence_space,
        )

        # Store environment config
        self.num_archers = num_archers
        self.num_knights = num_knights
        self.max_zombies = max_zombies
        self.max_arrows = max_arrows

        # Standard RL rewards
        self.reward_kill = reward_kill
        self.penalty_action = penalty_action  # Applied to all actions
        self.penalty_death = penalty_death
        self.penalty_zombie_escape = penalty_zombie_escape

    def reset(self, seed=None, options=None):
        """Reset environment and auxiliary tracking."""
        observations, infos = self.base_env.reset(seed=seed, options=options)
        self.prev_zombie_y = {}
        return observations, infos

    def step(self, actions: Dict[str, int]) -> Tuple[Dict, Dict, Dict, Dict, Dict]:
        """
        Execute step with standard RL rewards.
        
        Args:
            actions: Dict mapping agent_id -> action (0-5)
            
        Returns:
            observations, rl_rewards, terminations, truncations, infos
        """
        # Get base environment step
        observations, base_rewards, terminations, truncations, infos = self.base_env.step(actions)

        # Compute RL rewards (standard approach: all actions penalized)
        rl_rewards = {}
        for agent_id in self.base_env.agents:
            reward = 0.0
            
            # 1. ACTION PENALTY - all actions cost -0.01 (encourages efficiency)
            reward += self.penalty_action
            
            # 2. KILL REWARD - good outcome
            if base_rewards[agent_id] > 0:
                reward += base_rewards[agent_id] * self.reward_kill
            
            # 3. DEATH PENALTY - major failure
            if terminations.get(agent_id, False):
                reward += self.penalty_death
            
            # 4. ZOMBIE ESCAPE PENALTY - major failure
            if agent_id in observations:
                obs = np.asarray(observations[agent_id], dtype=float)
                escape_penalty = self._check_zombie_escape(obs)
                reward += escape_penalty
            
            rl_rewards[agent_id] = float(reward)

        return observations, rl_rewards, terminations, truncations, infos

    def _check_zombie_escape(self, obs: np.ndarray) -> float:
        """
        Check if any zombie reached the bottom border (y ≈ 1.0).
        
        Args:
            obs: Observation array (N+1, 5)
            
        Returns:
            Penalty if zombie escaped, 0.0 otherwise
        """
        # Zombie rows: start after agents and weapons
        zombie_start = 1 + self.num_archers + self.num_knights + self.num_knights + self.max_arrows
        zombie_end = zombie_start + self.max_zombies

        for r in range(zombie_start, zombie_end):
            dist = float(obs[r, 0])
            if dist > 0:  # Zombie is active
                # Row 2: pos_y (normalized, 1.0 = bottom border)
                y_pos = float(obs[r, 2])
                if y_pos >= 0.95:  # Very close to or at bottom border
                    return self.penalty_zombie_escape

        return 0.0

    # Delegate standard environment methods
    def render(self):
        """Render the environment."""
        return self.base_env.render()

    def close(self):
        """Close the environment."""
        return self.base_env.close()

    def seed(self, seed=None):
        """Set random seed."""
        return self.base_env.seed(seed)

    @property
    def agents(self):
        """Get active agents."""
        return self.base_env.agents

    @property
    def render_mode(self):
        """Get render mode."""
        return self.base_env.render_mode

    @property
    def observation_space(self):
        """Get observation space."""
        return self.base_env.observation_space

    @property
    def action_space(self):
        """Get action space."""
        return self.base_env.action_space


def create_kaz_rl_env(**kwargs):
    """
    Convenience function to create a KAZ_RL wrapped environment.
    
    Args:
        **kwargs: Arguments passed to KAZRLWrapper
        
    Returns:
        KAZRLWrapper instance
    """
    return KAZRLWrapper(**kwargs)


if __name__ == "__main__":
    # Example usage with standard RL rewards
    env = create_kaz_rl_env(
        num_archers=2,
        num_knights=2,
        max_zombies=10,
        max_arrows=10,
        max_cycles=900,
        reward_kill=1.0,
        penalty_action=-0.01,  # All actions cost -0.01
        penalty_death=-1.0,
        penalty_zombie_escape=-1.0,
    )

    observations, infos = env.reset()

    for step in range(100):
        # Random actions for testing
        actions = {agent_id: env.action_space(agent_id).sample() for agent_id in env.agents}
        
        observations, rewards, terminations, truncations, infos = env.step(actions)
        
        print(f"Step {step}")
        for agent_id, reward in rewards.items():
            print(f"  {agent_id}: reward={reward:.4f}")

        if not env.agents:
            break

    env.close()
    print("Test completed!")
