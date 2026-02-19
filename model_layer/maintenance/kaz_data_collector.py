import torch
import numpy as np
from pettingzoo.butterfly import knights_archers_zombies_v10


def collect_kaz_transitions(num_episodes=5, max_steps_per_episode=100):
    print(f"--- Starting KAZ Data Collection ({num_episodes} Episodes) ---")

    # Initialize the parallel environment with vector states for easy matrix math
    env = knights_archers_zombies_v10.parallel_env(
        max_cycles=max_steps_per_episode,
        vector_state=True
    )

    # Lists to hold our transition tuples
    states_list = []
    actions_list = []
    rewards_list = []
    next_states_list = []

    for episode in range(num_episodes):
        obs, infos = env.reset()

        # We will track the transitions of a single agent (e.g., 'knight_0')
        # to keep our first multi-dimensional Pyro model manageable.
        target_agent = 'knight_0'

        while env.agents:
            # 1. Store the current state (s_t)
            # If the target agent died, it won't be in the observation dict
            if target_agent not in obs:
                break

            current_state = obs[target_agent]

            # 2. Sample random actions for all living agents
            actions = {agent: env.action_space(agent).sample() for agent in env.agents}
            target_action = actions[target_agent]

            # 3. Step the environment forward
            next_obs, rewards, terminations, truncations, infos = env.step(actions)

            # 4. Extract reward (r_t) and next state (s_{t+1})
            if target_agent in next_obs:
                reward = rewards[target_agent]
                next_state = next_obs[target_agent]

                # Append to our dataset
                states_list.append(current_state)
                actions_list.append(target_action)
                rewards_list.append(reward)
                next_states_list.append(next_state)

            # Update obs for the next loop iteration
            obs = next_obs

    env.close()

    # Convert lists to PyTorch Tensors
    states_tensor = torch.tensor(np.array(states_list), dtype=torch.float32)
    actions_tensor = torch.tensor(np.array(actions_list), dtype=torch.float32).unsqueeze(-1)
    rewards_tensor = torch.tensor(np.array(rewards_list), dtype=torch.float32)
    next_states_tensor = torch.tensor(np.array(next_states_list), dtype=torch.float32)

    print("\n--- Data Collection Complete ---")
    print(f"Total Transitions Collected: {len(states_tensor)}")
    print(f"State Tensor Shape:      {states_tensor.shape}")
    print(f"Action Tensor Shape:     {actions_tensor.shape}")
    print(f"Reward Tensor Shape:     {rewards_tensor.shape}")
    print(f"Next State Tensor Shape: {next_states_tensor.shape}")

    # Save the dataset so our Pyro pipeline can load it later
    dataset = {
        'states': states_tensor,
        'actions': actions_tensor,
        'rewards': rewards_tensor,
        'next_states': next_states_tensor
    }
    torch.save(dataset, 'kaz_transitions.pt')
    print("\nSaved dataset to 'kaz_transitions.pt'")

    return dataset


if __name__ == "__main__":
    dataset = collect_kaz_transitions(num_episodes=10)