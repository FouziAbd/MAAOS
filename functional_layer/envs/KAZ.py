import time
import numpy as np
import math
import dspy
import pygame
from pettingzoo.butterfly import knights_archers_zombies_v10

from model_layer.agent import Agent


# https://pettingzoo.farama.org/environments/butterfly/knights_archers_zombies/


def get_scenario_description(agent_id):
    role = "Archer" if "archer" in agent_id else "Knight"
    base = (
        "You control ONE agent in a cooperative zombie survival game.\n"
        "Choose exactly ONE action index from ACTION_MAP.\n"
        "Hard rules:\n"
        "- Output action must be an integer in [0, n_actions-1].\n"
        "- If unsure, prioritize survival and preventing immediate loss.\n"
        "- Do NOT invent actions outside ACTION_MAP.\n"
    )

    base = base + (
        "observation description:\n"
        "ach agent’s observation is a (N+1) × 5 array, where\n"
        "   - N = num_archers + num_knights + num_swords + max_arrows + max_zombies\n"
        "   - num_swords = num_knights\n"
        "Row ordering\n"
        "Rows appear in a fixed order:\n"
        "   1. Current agent\n"
        "   2. Archers (up to num_archers)\n"
        "   3. Knights (up to num_knights)\n"
        "   4. Swords (up to num_swords = num_knights)\n"
        "   5. Arrows (up to max_arrows)\n"
        "   6. Zombies (up to max_zombies)\n"
        "So the observation looks like:\n"
        "[\n"
        "[current agent],\n"
        "[archer 1], ... , [archer num_archers],\n"
        "[knight 1], ... , [knight num_knights],\n"
        "[sword 1],  ... , [sword num_swords],\n"
        "[arrow 1],  ... , [arrow max_arrows],\n"
        "[zombie 1], ... , [zombie max_zombies]\n"
        "]\n"
        "There are always N+1 rows. If an entity doesn’t exist in a slot (e.g., fewer zombies than max_zombies), that row is all zeros, but the slot order never changes.\n"
        "Coordinate system and normalization\n"
        "   - All distance/position values are normalized to [0, 1].\n"
        "   - Image coordinates: (0, 0) is the top-left.\n"
        "   - Down is positive y.\n"
        "   - Left is positive x.\n"
        "What the 5 values in each row mean\n"
        "Row 0: current agent (5 values)\n"
        "   [0, pos_x, pos_y, heading_x, heading_y]\n"
        "   - Value 1: always 0 (unused)\n"
        "   - Values 2–3: absolute position of the agent, normalized by image width/height\n"
        "   - Values 4–5: agent heading as a unit vector (heading_x, heading_y)\n"
        "All other rows: entities (5 values)\n"
        "   [dist, rel_x, rel_y, dir_x, dir_y]\n"
        "   - Value 1: absolute distance from the entity to the current agent\n"
        "   - Values 2–3: entity position relative to the current agent (rel_x, rel_y)\n"
        "   - Values 4–5: entity orientation/heading as a unit vector in world coordinates (dir_x, dir_y)\n"
        )

    if role == "Archer":
        return base + (
            "Role tactics (ARCHER):\n"
            "- Stay away from zombies; avoid close contact.\n"
            "- Avoid friendly fire: if an ally is in front, don’t attack.\n"
            "- Attack only when a zombie is aligned in front and reasonably close.\n"
            "- Otherwise rotate/reposition to line up a safe shot.\n"
            "Hard rules:\n"
            "- If ally_block_attack=true, do NOT choose ATTACK.\n"
            "Policy:\n"
            "- If attack_ok=true, choose ATTACK.\n"
            "- Else, choose ROTATE in direction of turn_hint.\n"
            "- If no zombie exists, move forward or no-op.\n"
        )
    else:
        return base + (
            "Role tactics (KNIGHT):\n"
            "- You are frontline: close distance to nearest threatening zombie.\n"
            "- Attack when a zombie is in front and close.\n"
            "- Otherwise rotate toward the nearest zombie and move forward.\n"
            "Hard rules:\n"
            "- If ally_block_attack=true, do NOT choose ATTACK.\n"
            "Policy:\n"
            "- If attack_ok=true, choose ATTACK.\n"
            "- Else, choose ROTATE in direction of turn_hint.\n"
            "- If no zombie exists, move forward or no-op.\n"
        )


def get_goal_description(agent_id):
    role = "Archer" if "archer" in agent_id else "Knight"
    if role == "Archer":
        goal_description = (
            "killing zombies "
            #"TEAM OBJECTIVE: Prevent any zombie from reaching the bottom border and keep at least one teammate alive. Score increases by killing zombies (+1 per kill)."
            #"ARCHER ROLE:"
            #"- If attack_ok=true, choose ATTACK.\n"
            #"- Else, choose ROTATE in direction of turn_hint.\n"
            #"- If no zombie exists, move forward or no-op.\n"
            #"PRIORITIES: (1) stop bottom-threatening zombies, (2) survive, (3) attack if likely to hit, (4) reposition/rotate for a better shot."
            #"SAFETY RULE: Avoid shooting/attacking blindly; if no clear target ahead, rotate/reposition instead."
        )
    else:  # Knight
        goal_description = (
            "killing zombies "
            #"TEAM OBJECTIVE: Prevent any zombie from reaching the bottom border and keep at least one teammate alive. Score increases by killing zombies (+1 per kill)."
            #"KNIGHT ROLE:"
            #"- If attack_ok=true, choose ATTACK.\n"
            #"- Else, choose ROTATE in direction of turn_hint.\n"
            #"- If no zombie exists, move forward or no-op.\n"
            #"PRIORITIES: (1) stop bottom-threatening zombies, (2) survive (don’t get trapped/surrounded), (3) attack if likely to connect, (4) reposition/rotate toward nearest zombie."
        )

    return goal_description

def _angle_deg_and_dot(u, v):
    u = np.asarray(u, float)
    v = np.asarray(v, float)
    u = u / (np.linalg.norm(u) + 1e-9)
    v = v / (np.linalg.norm(v) + 1e-9)
    dot = float(np.clip(np.dot(u, v), -1.0, 1.0))
    ang = math.degrees(math.acos(dot))
    return ang, dot

def _turn_hint(heading_xy, rel_xy):
    h = np.asarray(heading_xy, float)
    r = np.asarray(rel_xy, float)
    cross = h[0] * r[1] - h[1] * r[0]  # z component of 2D cross
    return "LEFT" if cross > 0 else "RIGHT"

def summarize_kaz_obs(
    obs, role: str,
    num_archers: int, num_knights: int,
    max_arrows: int, max_zombies: int,
):
    """
    obs: (N+1,5) numpy array for vector_state=True
    Produces an LLM-friendly summary + precomputed booleans.
    """
    obs = np.asarray(obs, dtype=float)
    # row 0: [0, posx, posy, headingx, headingy]
    sx, sy, hx, hy = obs[0, 1], obs[0, 2], obs[0, 3], obs[0, 4]
    heading = np.array([hx, hy], dtype=float)

    # KAZ row layout: [current], archers, knights, swords(num_knights), arrows(max_arrows), zombies(max_zombies)
    zombie_start = 1 + num_archers + num_knights + num_knights + max_arrows
    zombie_end = zombie_start + max_zombies

    # --- nearest zombie ---
    nearest_z = None  # (dist, relx, rely)
    for r in range(zombie_start, zombie_end):
        dist = float(obs[r, 0])
        if dist <= 0:
            continue
        relx, rely = float(obs[r, 1]), float(obs[r, 2])
        if nearest_z is None or dist < nearest_z[0]:
            nearest_z = (dist, relx, rely)

    # --- nearest ally (among agent rows only: archers+knights) ---
    ally_start = 1
    ally_end = 1 + num_archers + num_knights
    nearest_a = None  # (dist, relx, rely)
    for r in range(ally_start, ally_end):
        dist = float(obs[r, 0])
        if dist <= 0:
            continue
        relx, rely = float(obs[r, 1]), float(obs[r, 2])
        if nearest_a is None or dist < nearest_a[0]:
            nearest_a = (dist, relx, rely)

    # thresholds (start values; tune later)
    if role.lower() == "archer":
        max_dist = 0.70
        max_angle = 15.0
        ally_block_dist = 0.20
        ally_block_angle = 15.0
    else:  # knight
        max_dist = 0.25
        max_angle = 60.0
        ally_block_dist = 0.15
        ally_block_angle = 25.0

    # friendly-fire / “don’t attack if ally is in front and close”
    ally_block_attack = False
    ally_angle = None
    if nearest_a is not None:
        ad, ax, ay = nearest_a
        ally_angle, ally_dot = _angle_deg_and_dot(heading, [ax, ay])
        ally_block_attack = (ad <= ally_block_dist) and (ally_dot > 0) and (ally_angle <= ally_block_angle)

    # compute attack_ok + turn hint
    if nearest_z is None:
        z_txt = "none"
        attack_ok = False
        turn = "NONE"
        z_angle = None
    else:
        zd, zx, zy = nearest_z
        z_angle, z_dot = _angle_deg_and_dot(heading, [zx, zy])
        in_front = (z_dot > 0) and (z_angle <= max_angle)
        close_enough = (zd <= max_dist)
        attack_ok = bool(in_front and close_enough and (not ally_block_attack))
        turn = _turn_hint(heading, [zx, zy])
        z_txt = f"dist={zd:.2f} rel=({zx:.2f},{zy:.2f}) angle_deg={z_angle:.1f} in_front={in_front}"

    a_txt = "none" if nearest_a is None else f"dist={nearest_a[0]:.2f} rel=({nearest_a[1]:.2f},{nearest_a[2]:.2f})"

    # LLM-friendly summary
    summary = (
        f"self: pos=({sx:.2f},{sy:.2f}) heading=({hx:.2f},{hy:.2f})\n"
        f"nearest_ally: {a_txt}\n"
        f"nearest_zombie: {z_txt}\n"
        f"ally_block_attack={ally_block_attack}\n"
        f"attack_ok={attack_ok}\n"
        f"turn_hint={turn}"
    )
    return summary

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

    actions_details = [
        "0 -> move forward",
        "1 -> move backward",
        "2 -> rotate left",
        "3 -> rotate right",
        "4 -> attack / use weapon",
        "5 -> no-op",
    ]
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
            role = "Archer" if "archer" in agent_id else "Knight"
            if agent_id == "archer_0":
                print(f"obs =\n {agent_obs} \n")
            obs_summary = summarize_kaz_obs(
                obs=agent_obs,
                role=role,
                num_archers=2,
                num_knights=2,
                max_arrows=10,
                max_zombies=10,
            )
 

            # Ask your custom class for the move
            #actions[agent_id] = my_controllers[agent_id].choose_action(obs_summary)
            actions[agent_id] = my_controllers[agent_id].choose_random_action()

        observations, rewards, terminations, truncations, infos = env.step(actions)

    env.close()
