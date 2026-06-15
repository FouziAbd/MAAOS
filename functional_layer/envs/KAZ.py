import sys
import os
import time
import numpy as np
import math
import dspy
import pygame
from pettingzoo.butterfly import knights_archers_zombies_v10

# Add project root to path to support direct execution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from model_layer.agent import Agent
from middleware_layer.middleware_orchestrator import MiddlewareOrchestrator
from utils.logging_utils import setup_logging, log_message, close_logging
from functional_layer.envs.entity_schema import KAZ_ENTITY_SCHEMA
from functional_layer.envs.obs_parser import parse_kaz_obs


# https://pettingzoo.farama.org/environments/butterfly/knights_archers_zombies/


def get_observation_description():
    """
    Returns detailed observation structure description for KAZ environment.
    This is used by the middleware to help the LLM understand raw observations.
    """
    return (
        "observation description:\n"
        "Each agent's observation is a (N+1) × 5 array, where\n"
        "   - N = num_archers + num_knights + num_swords + max_arrows + max_zombies\n"
        "   - num_swords = num_knights\n"
        "Row ordering:\n"
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
        "There are always N+1 rows. If an entity doesn't exist in a slot (e.g., fewer zombies than max_zombies), that row is all zeros, but the slot order never changes.\n"
        "\n"
        "Coordinate system and normalization:\n"
        "   - All distance/position values are normalized to [0, 1].\n"
        "   - Image coordinates: (0, 0) is the top-left.\n"
        "   - Down is positive y.\n"
        "   - Right is positive x.\n"
        "\n"
        "What the 5 values in each row mean:\n"
        "Row 0: current agent (5 values)\n"
        "   [0, pos_x, pos_y, heading_x, heading_y]\n"
        "   - Value 1: always 0 (unused)\n"
        "   - Values 2 and 3: absolute position of the agent, normalized by image width/height\n"
        "   - Values 4 and 5: agent heading as a unit vector (heading_x, heading_y)\n"
        "\n"
        "All other rows: entities (5 values)\n"
        "   [dist, rel_x, rel_y, dir_x, dir_y]\n"
        "   - Value 1: absolute distance from the entity to the current agent\n"
        "   - Values 2 and 3: entity position relative to the current agent (rel_x, rel_y)\n"
        "   - Values 4 and 5: entity orientation/heading as a unit vector in world coordinates (dir_x, dir_y)\n"
    )


def get_scenario_description(agent_id):
    role = "Archer" if "archer" in agent_id else "Knight"
    base = (
        "You control ONE agent in a cooperative zombie survival game.\n"
        "Choose exactly ONE action index from ACTION_MAP.\n"
        "Hard rules:\n"
        "- Output action must be an integer in [0, n_actions-1].\n"
        "- If unsure, prioritize survival and preventing immediate loss.\n"
        "- Do NOT invent actions outside ACTION_MAP.\n"
        "- Rotation only turns 10 degrees per step. Multiple rotations may be needed to face a target.\n"
    )

    base = base + "\n" + get_observation_description() + "\n"

    if role == "Archer":
        patrol = "x=0.15–0.50, y=0.20–0.80" if "0" in agent_id else "x=0.50–0.85, y=0.20–0.80"
        return base + (
            "Role tactics (ARCHER):\n"
            "- Stay away from zombies; keep distance > 0.70.\n"
            "- Avoid friendly fire: if an ally is in front, don't attack.\n"
            f"- Patrol zone (when no zombie visible): {patrol}. Move toward your zone if outside it.\n"
            "- If movement_blocked=True, you hit a wall. Rotate (action 2 or 3) to turn away.\n"
            "- Each rotation changes your heading by exactly 10 degrees.\n"
            "- rotations_needed is informational only: approximate rotations left before you can fire.\n"
            "\n### CRITICAL RULES ###\n"
            "If 'attack_ok=True' → CHOOSE ACTION 4 (ATTACK) immediately.\n"
            "If 'attack_ok=False' AND zombie is visible:\n"
            "  - DO NOT move forward. You must align first.\n"
            "  - If turn_hint=LEFT → Choose action 2 (rotate left)\n"
            "  - If turn_hint=RIGHT → Choose action 3 (rotate right)\n"
            "  - Keep rotating the same direction until attack_ok=True.\n"
            "If 'attack_ok=False' AND no zombie:\n"
            "  - If movement_blocked=True → Choose action 2 or 3 to turn away from wall.\n"
            "  - Otherwise → Choose action 0 (move forward) toward your patrol zone.\n"
            "If ally_block_attack=True → Do NOT choose action 4.\n"
        )
    else:
        return base + (
            "Role tactics (KNIGHT):\n"
            "- You are melee: close distance to zombie below 0.25 AND roughly face it to hit.\n"
            "- Each rotation changes your heading by exactly 10 degrees.\n"
            "- rotations_needed is informational only: approximate rotations left before you can fire.\n"
            "- If movement_blocked=True, you hit a wall. Rotate to find a clear path to zombie.\n"
            "- Advance toward zombies — do not patrol, close the gap.\n"
            "\n### CRITICAL RULES ###\n"
            "If 'attack_ok=True' → CHOOSE ACTION 4 (ATTACK) immediately.\n"
            "If 'attack_ok=False' AND zombie is visible:\n"
            "  - If distance_status=TOO_FAR → rotate per turn_hint to face zombie, then move forward.\n"
            "  - If distance_status=IN_RANGE → rotate per turn_hint until attack_ok=True.\n"
            "  - If turn_hint=LEFT → Choose action 2 (rotate left)\n"
            "  - If turn_hint=RIGHT → Choose action 3 (rotate right)\n"
            "If 'attack_ok=False' AND no zombie:\n"
            "  - If movement_blocked=True → Choose action 2 or 3 to change direction.\n"
            "  - Otherwise → Choose action 0 (move forward) to find zombies.\n"
            "If ally_block_attack=True → Do NOT choose action 4.\n"
        )


def get_goal_description(agent_id):
    role = "Archer" if "archer" in agent_id else "Knight"
    if role == "Archer":
        goal_description = (
            "killing zombies "
        )
    else:  # Knight
        goal_description = (
            "killing zombies "
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
    # KAZ uses image coords (y increases downward) — handedness is flipped vs standard math
    return "RIGHT" if cross > 0 else "LEFT"


_prev_positions: dict = {}  # agent_id -> (sx, sy) from last step


def summarize_kaz_obs(
    obs, role: str,
    num_archers: int, num_knights: int,
    max_arrows: int, max_zombies: int,
    agent_id: str = "",
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

    # thresholds
    if role.lower() == "archer":
        max_dist = 0.85
        max_angle = 20.0
        ally_block_dist = 0.20
        ally_block_angle = 15.0
    else:  # knight — melee: must be close, angle is wider than archer
        max_dist = 0.25
        max_angle = 70.0
        ally_block_dist = 0.15
        ally_block_angle = 25.0

    # friendly-fire / "don't attack if ally is in front and close"
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

    # Fix 1: movement_blocked — compare to previous position
    movement_blocked = False
    if agent_id:
        prev = _prev_positions.get(agent_id)
        if prev is not None:
            movement_blocked = (abs(sx - prev[0]) < 0.005 and abs(sy - prev[1]) < 0.005)
        _prev_positions[agent_id] = (sx, sy)

    # Fix 3: distance_status + rotations_needed
    distance_status = ""
    rotations_needed = 0
    if nearest_z is not None:
        if role.lower() == "knight":
            distance_status = "IN_RANGE" if nearest_z[0] <= 0.25 else "TOO_FAR"
        if z_angle is not None and not attack_ok:
            import math as _math
            rotations_needed = max(0, _math.ceil((z_angle - max_angle) / 10.0))

    # LLM-friendly summary
    summary = (
        f"self: pos=({sx:.2f},{sy:.2f}) heading=({hx:.2f},{hy:.2f})\n"
        f"nearest_ally: {a_txt}\n"
        f"nearest_zombie: {z_txt}\n"
        f"ally_block_attack={ally_block_attack}\n"
        f"attack_ok={attack_ok}\n"
        f"turn_hint={turn}\n"
        f"movement_blocked={movement_blocked}"
    )
    if distance_status:
        summary += f"\ndistance_status={distance_status}"
    if rotations_needed > 0:
        summary += f"\nrotations_needed={rotations_needed}"
    return summary


if __name__ == "__main__":
    setup_logging(filename='logs_run.txt', episode_type='EPISODE')
    
    try:
        env = knights_archers_zombies_v10.parallel_env(
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
        )
        observations, infos = env.reset()

        my_controllers = {}
        lm = dspy.LM(
            model='ollama_chat/gemma4:e4b',
            api_base='http://localhost:11434',
            api_key='',
            cache=False,
        )

        actions_details = [
            "0 -> move forward",
            "1 -> move backward",
            "2 -> rotate left",
            "3 -> rotate right",
            "4 -> attack / use weapon",
            "5 -> no-op",
        ]

        # Track kills per agent
        kills = {agent_id: 0 for agent_id in env.agents}
        step_count = 0

        while env.agents:
            step_count += 1
            log_message(f"\n{'='*80}")
            log_message(f"STEP {step_count}")
            log_message(f"{'='*80}")
            
            if env.render_mode == "human":
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        env.close()
                        close_logging()
                        exit()

            # Dynamic Controller Management
            for agent_id in env.agents:
                if agent_id not in my_controllers:
                    from functools import partial
                    kaz_parser = partial(
                        parse_kaz_obs,
                        num_archers=2, num_knights=2,
                        max_arrows=10, max_zombies=10,
                    )
                    agent_role = "archer" if "archer" in agent_id else "knight"
                    middleware = MiddlewareOrchestrator(
                        env=env,
                        agent_id=agent_id,
                        LLM_model=lm,
                        scenario_description=get_scenario_description(agent_id),
                        goal_description=get_goal_description(agent_id),
                        action_space=actions_details,
                        environment_name="KAZ Zombie Survival",
                        observation_spec=get_observation_description(),
                        # ── belief system ──────────────────────────────────
                        entity_schema=KAZ_ENTITY_SCHEMA,
                        initial_entities={"self": {}},
                        obs_parser_fn=kaz_parser,
                        history_window=6,
                        belief_updater_kwargs={"agent_role": agent_role},
                    )

                    my_controllers[agent_id] = Agent(
                        agent_id=agent_id,
                        scenario_description=get_scenario_description(agent_id),
                        goal_description=get_goal_description(agent_id),
                        action_space=actions_details,
                        LLM_model=lm,
                        middleware=middleware
                    )

            actions = {}
            
            # Process only agents that are still active (not terminated/truncated)
            for agent_id in env.agents:
                agent_obs = observations[agent_id]
                
                # Compute tactical summary using the built-in function
                role = "Archer" if "archer" in agent_id else "Knight"
                tactical_summary = summarize_kaz_obs(
                    obs=agent_obs,
                    role=role,
                    num_archers=2,
                    num_knights=2,
                    max_arrows=10,
                    max_zombies=10,
                    agent_id=agent_id,
                )
                
                log_message(f"\n[Agent: {agent_id}]")
                log_message(f"  Tactical Summary:\n    {tactical_summary.replace(chr(10), chr(10) + '    ')}")
                
                actions[agent_id] = my_controllers[agent_id].choose_action_with_tactical_info(agent_obs, tactical_summary)

                log_message(f"  Action Chosen: {actions[agent_id]} ({actions_details[actions[agent_id]]})")

            observations, rewards, terminations, truncations, infos = env.step(actions)

            # Update belief state from step outcomes
            for agent_id, action in actions.items():
                if agent_id in my_controllers:
                    my_controllers[agent_id].middleware.update_belief(
                        action,
                        rewards.get(agent_id, 0.0),
                        observations.get(agent_id),
                    )

            # Clean up controllers and log terminations/truncations
            terminated_agents = [a for a in terminations if terminations[a]]
            truncated_agents = [a for a in truncations if truncations[a]]
            
            if terminated_agents:
                log_message(f"\n[TERMINATED] Agents reached terminal state: {terminated_agents}")
            if truncated_agents:
                log_message(f"[TRUNCATED] Agents reached time limit: {truncated_agents}")
            
            # Remove controllers for agents that ended
            active_ids = set(env.agents)
            removed_agents = set(my_controllers.keys()) - active_ids
            for agent_id in removed_agents:
                reason = "TERMINATED" if agent_id in terminated_agents else "TRUNCATED" if agent_id in truncated_agents else "UNKNOWN"
                log_message(f"[REMOVED] {agent_id} ({reason}) - Final kills: {kills[agent_id]}")
            
            my_controllers = {k: v for k, v in my_controllers.items() if k in active_ids}

            # Track kills and print current kill count
            for agent_id, reward in rewards.items():
                if reward > 0:
                    kills[agent_id] += reward
                    log_message(f"[REWARD] {agent_id} received {reward} reward(s) - Total kills: {kills[agent_id]}")
            
            log_message(f"\n[CUMULATIVE KILLS] {kills}")

            # Count and print number of zombies from first agent's observation
            if env.agents:
                first_agent = list(env.agents)[0]
                obs = observations[first_agent]
                # Get environment parameters for zombie row indexing
                num_archers = 2
                num_knights = 2
                max_arrows = 10
                zombie_start = 1 + num_archers + num_knights + num_knights + max_arrows
                zombie_end = zombie_start + 10
                
                # Count active zombies (non-zero distance)
                zombie_count = 0
                for r in range(zombie_start, zombie_end):
                    if obs[r, 0] > 0:  # distance > 0 means zombie is active
                        zombie_count += 1
                
                log_message(f"[ENVIRONMENT] Zombies alive: {zombie_count}")

        # Print final kill count statistics
        log_message(f"\n{'='*80}")
        log_message("EPISODE FINISHED - FINAL STATISTICS")
        log_message(f"{'='*80}")
        total_kills = 0
        for agent_id in sorted(kills.keys()):
            agent_kills = kills[agent_id]
            total_kills += agent_kills
            log_message(f"{agent_id:15s}: {agent_kills:3d} zombies killed")
        log_message(f"{'TOTAL':15s}: {total_kills:3d} zombies killed")
        log_message(f"{'='*80}\n")

        env.close()
        
    except KeyboardInterrupt:
        log_message("\n[INTERRUPTED] Episode interrupted by user (Ctrl+C)")
        log_message(f"Final kills so far: {kills}\n")
        env.close()
    finally:
        close_logging()
