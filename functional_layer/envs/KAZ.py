import time

import dspy
import pygame
from pettingzoo.butterfly import knights_archers_zombies_v10

from model_layer.agent import Agent


# https://pettingzoo.farama.org/environments/butterfly/knights_archers_zombies/


def get_scenario_description(agent_id):
    # Determine the role based on the ID string (e.g., 'archer_0' -> 'Archer')
    role = "Archer" if "archer" in agent_id else "Knight"

    # --- 1. Dynamic Scenario Description ---
    # Includes details on Physics, Vision, and Map layout
    base_scenario = (
        "CONTEXT: You are an agent in a 2D top-down survival simulation called 'Knights Archers Zombies'. "
        "The environment uses a physics engine with momentum and collision mechanics. "
        "Zombies spawn continuously at the top of the screen and move downwards toward the bottom. "
        "Your vision is NOT a camera image; it is a set of 'lidar' ray-casts that detect the distance "
        "and type of objects (walls, zombies, allies) around you in a 360-degree radius. "
    )

    if role == "Archer":
        scenario_description = base_scenario + (
            "ROLE DETAILS: You are an Archer (Ranged Unit). You are equipped with a bow and arrows. "
            "You move faster than Knights but have lower defense. "
            "Your arrows travel in a straight line and can bounce off walls or kill friendly units if you miss."
        )
    else:  # Knight
        scenario_description = base_scenario + (
            "ROLE DETAILS: You are a Knight (Melee Unit). You are equipped with a sword. "
            "You move slower than Archers but are more robust. "
            "Your sword has a short swing radius. You act as the first line of defense against the zombie horde."
        )
    return scenario_description


def get_goal_description(agent_id):
    role = "Archer" if "archer" in agent_id else "Knight"
    if role == "Archer":
        goal_description = (
            "OBJECTIVE: Eliminate zombies before they reach the bottom of the screen or kill your team. "
            "TACTICS: 1) Maintain distance; do not let zombies touch you. "
            "2) Aim carefully to avoid shooting your fellow Knights who are fighting in the front lines (Friendly Fire is ON). "
            "3) Prioritize zombies that are closest to breaching the defense."
        )
    else:  # Knight
        goal_description = (
            "OBJECTIVE: Intercept and destroy zombies to protect the Archers behind you. "
            "TACTICS: 1) Close the gap immediately; you must be near a zombie to hit it. "
            "2) Body-block zombies to prevent them from reaching the Archers. "
            "3) Swing your sword constantly when in range. "
            "4) Avoid getting surrounded by multiple zombies at once."
        )

    return goal_description


if __name__ == "__main__":
    env = knights_archers_zombies_v10.parallel_env(
        render_mode="human",
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

    )
    observations, infos = env.reset()

    my_controllers = {}
    lm = dspy.LM(
        model='ollama_chat/qwen2.5-coder:1.5b',  # The model name matches your Ollama tag
        api_base='http://localhost:11434',  # Standard local Ollama port
        api_key=''  # No API key needed for local Ollama
    )

    while env.agents:
        # Force the window to process clicks/movements so it doesn't freeze
        if env.render_mode == "human":
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    env.close()
                    exit()

        # --- 3. Dynamic Controller Management ---
        # If an agent is in the game but we don't have a controller for it, create one
        for agent_id in env.agents:
            if agent_id not in my_controllers:
                my_controllers[agent_id] = Agent(agent_id=agent_id,
                                                 scenario_description=get_scenario_description(agent_id),
                                                 goal_description=get_goal_description(agent_id),
                                                 action_space=env.action_space(agent_id),
                                                 LLM_model=lm)

        # Optional: Clean up controllers for dead agents to save memory
        # (Compare keys in my_controllers vs env.agents)
        active_ids = set(env.agents)
        my_controllers = {k: v for k, v in my_controllers.items() if k in active_ids}

        actions = {}
        for agent_id in env.agents:
            # Get the specific observation for this agent
            agent_obs = observations[agent_id]

            # Ask your custom class for the move
            actions[agent_id] = my_controllers[agent_id].choose_action(agent_obs)

        observations, rewards, terminations, truncations, infos = env.step(actions)

    env.close()
