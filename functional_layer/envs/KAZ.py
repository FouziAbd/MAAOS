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
    base_scenario = """# Knights Archers Zombies ('KAZ')

```{figure} butterfly_knights_archers_zombies.gif
:width: 200px
:name: knights_archers_zombies
```

This environment is part of the <a href='..'>butterfly environments</a>. Please read that page first for general information.

| Import               | `from pettingzoo.butterfly import knights_archers_zombies_v10` |
|----------------------|----------------------------------------------------------------|
| Actions              | Discrete                                                       |
| Parallel API         | Yes                                                            |
| Manual Control       | Yes                                                            |
| Agents               | `agents= ['archer_0', 'archer_1', 'knight_0', 'knight_1']`     |
| Agents               | 4                                                              |
| Action Shape         | (1,)                                                           |
| Action Values        | [0, 5]                                                         |
| Observation Shape    | (512, 512, 3)                                                  |
| Observation Values   | (0, 255)                                                       |
| State Shape          | (720, 1280, 3)                                                 |
| State Values         | (0, 255)                                                       |


Zombies walk from the top border of the screen down to the bottom border in unpredictable paths. The agents you control are knights and archers (default 2 knights and 2 archers) that are initially positioned at the bottom border of the screen. Each agent can rotate clockwise or counter-clockwise
and move forward or backward. Each agent can also attack to kill zombies. When a knight attacks, it swings a mace in an arc in front of its current heading direction. When an archer attacks, it fires an arrow in a straight line in the direction of the archer's heading. The game ends when all
agents die (collide with a zombie) or a zombie reaches the bottom screen border. A knight is rewarded 1 point when its mace hits and kills a zombie. An archer is rewarded 1 point when one of their arrows hits and kills a zombie.
There are two possible observation types for this environment, vectorized and image-based.

#### Vectorized (Default)
Pass the argument `vector_state=True` to the environment.

The observation is an (N+1)x5 array for each agent, where `N = num_archers + num_knights + num_swords + max_arrows + max_zombies`.
> Note that `num_swords = num_knights`

The ordering of the rows of the observation look something like this:
```
[
[current agent],
[archer 1],
...,
[archer N],
[knight 1],
...
[knight M],
[sword 1],
...
[sword M],
[arrow 1],
...
[arrow max_arrows],
[zombie 1],
...
[zombie max_zombies]
]
```

In total, there will be N+1 rows. Rows with no entities will be all 0, but the ordering of the entities will not change.

**Vector Breakdown**

This breaks down what a row in the observation means. All distances are normalized to [0, 1].
Note that for positions, [0, 0] is the top left corner of the image. Down is positive y, Left is positive x.

For the vector for `current agent`:
- The first value means nothing and will always be 0.
- The next four values are the position and angle of the current agent.
  - The first two values are position values, normalized to the width and height of the image respectively.
  - The final two values are heading of the agent represented as a unit vector.

For everything else:
- Each row of the matrix (this is an 5 wide vector) has a breakdown that looks something like this:
  - The first value is the absolute distance between an entity and the current agent.
  - The next four values are relative position and absolute angles of each entity relative to the current agent.
    - The first two values are position values relative to the current agent.
    - The final two values are the angle of the entity represented as a directional unit vector relative to the world.

**Typemasks**

There is an option to prepend a typemask to each row vector. This can be enabled by passing `use_typemasks=True` as a kwarg.

The typemask is a 6 wide vector, that looks something like this:
```
[0., 0., 0., 1., 0., 0.]
```

Each value corresponds to either
```
[zombie, archer, knight, sword, arrow, current agent]
```

If there is no entity there, the whole typemask (as well as the whole state vector) will be 0.

As a result, setting `use_typemask=True` results in the observation being a (N+1)x11 vector.

**Sequence Space** (Experimental)

There is an option to also pass `sequence_space=True` as a kwarg to the environment. This just removes all non-existent entities from the observation and state vectors. Note that this is **still experimental** as the state and observation size are no longer constant. In particular, `N` is now a
variable number."""

    if role == "Archer":
        scenario_description = base_scenario + (
            f"your are {role} ROLE DETAILS: You are an Archer (Ranged Unit). You are equipped with a bow and arrows. "
            "You move faster than Knights but have lower defense. "
            "Your arrows travel in a straight line and can bounce off walls or kill friendly units if you miss."
        )
    else:  # Knight
        scenario_description = base_scenario + (
            f"your are {role} and your ROLE DETAILS: You are a Knight (Melee Unit). You are equipped with a sword. "
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
        model='ollama_chat/gemma:2b',  # The model name matches your Ollama tag
        api_base='http://localhost:11434',  # Standard local Ollama port
        api_key=''  # No API key needed for local Ollama
    )

    actions_details = [ "0 -> move forward", "1 - > move brackward", "2 -> rotate left", "3 -> rotate right", "4 -> use weapon"]
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
                                                 action_space=actions_details,
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
