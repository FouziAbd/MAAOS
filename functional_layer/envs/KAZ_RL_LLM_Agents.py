"""
KAZ_RL_LLM_Agents.py - LLM Agents Solving the KAZ_RL Environment

This script uses the LLM-based agents from the middleware layer to solve
the Knights, Archers, Zombies environment with dense RL rewards.

The agents use LLMs (via DSPy and ollama) to make tactical decisions based on
observations and tactical summaries, now with proper RL reward signals.
"""

import sys
import os
import time
import numpy as np
import math
import dspy
import pygame
from KAZ_RL import create_kaz_rl_env

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from model_layer.agent import Agent
from middleware_layer.middleware_orchestrator import MiddlewareOrchestrator
from utils.logging_utils import setup_logging, log_message, close_logging


def get_observation_description():
    """
    Returns detailed observation structure description for KAZ environment.
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
        "\n"
        "Each row has 5 values:\n"
        "Row 0 (current agent): [0, pos_x, pos_y, heading_x, heading_y]\n"
        "Other rows (entities): [dist, rel_x, rel_y, dir_x, dir_y]\n"
        "   - dist: absolute distance from entity to current agent\n"
        "   - rel_x, rel_y: entity position relative to current agent\n"
        "   - dir_x, dir_y: entity orientation as a unit vector\n"
        "\n"
        "All values are normalized to [0, 1], with (0,0) at top-left.\n"
    )


def get_scenario_description(agent_id):
    """Get scenario description for a specific agent."""
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
        return base + (
            "Role tactics (ARCHER):\n"
            "- Stay away from zombies; avoid close contact distance > 0.70.\n"
            "- Avoid friendly fire: if an ally is in front, don't attack.\n"
            "- Attack only when perfectly aimed at zombie within range.\n"
            "- Otherwise rotate/reposition to line up a safe shot.\n"
            "\n### CRITICAL RULES ###\n"
            "If 'attack_ok=true' in the observation → CHOOSE ACTION 4 (ATTACK) immediately. No rotation.\n"
            "If 'attack_ok=false' in the observation → DO NOT ATTACK. Instead:\n"
            "  - If turn_hint=LEFT → Choose action 2 (rotate left)\n"
            "  - If turn_hint=RIGHT → Choose action 3 (rotate right)\n"
            "  - If no zombie → Choose action 0 (move forward) or action 5 (no-op)\n"
            "If ally_block_attack=true → Do NOT choose action 4.\n"
        )
    else:
        return base + (
            "Role tactics (KNIGHT):\n"
            "- You are frontline: close distance to nearest threatening zombie distance < 0.25.\n"
            "- Attack when zombie is in front and close, angle < 60 degrees.\n"
            "- Otherwise rotate toward nearest zombie and move forward.\n"
            "\n### CRITICAL RULES ###\n"
            "If 'attack_ok=true' in the observation → CHOOSE ACTION 4 (ATTACK) immediately. No rotation.\n"
            "If 'attack_ok=false' in the observation → DO NOT ATTACK. Instead:\n"
            "  - If turn_hint=LEFT → Choose action 2 (rotate left)\n"
            "  - If turn_hint=RIGHT → Choose action 3 (rotate right)\n"
            "  - If no zombie → Choose action 0 (move forward) or action 5 (no-op)\n"
            "If ally_block_attack=true → Do NOT choose action 4.\n"
        )


def get_goal_description(agent_id):
    """Get goal description for a specific agent."""
    return "killing zombies"


def _angle_deg_and_dot(u, v):
    """Compute angle in degrees and dot product between two vectors."""
    u = np.asarray(u, float)
    v = np.asarray(v, float)
    u = u / (np.linalg.norm(u) + 1e-9)
    v = v / (np.linalg.norm(v) + 1e-9)
    dot = float(np.clip(np.dot(u, v), -1.0, 1.0))
    ang = math.degrees(math.acos(dot))
    return ang, dot


def _turn_hint(heading_xy, rel_xy):
    """Determine turn direction based on heading and relative position."""
    h = np.asarray(heading_xy, float)
    r = np.asarray(rel_xy, float)
    cross = h[0] * r[1] - h[1] * r[0]
    return "LEFT" if cross > 0 else "RIGHT"


def summarize_kaz_obs(obs, role: str, num_archers: int, num_knights: int,
                      max_arrows: int, max_zombies: int):
    """
    Produces an LLM-friendly summary from raw observation.
    """
    obs = np.asarray(obs, dtype=float)
    sx, sy, hx, hy = obs[0, 1], obs[0, 2], obs[0, 3], obs[0, 4]
    heading = np.array([hx, hy], dtype=float)

    zombie_start = 1 + num_archers + num_knights + num_knights + max_arrows
    zombie_end = zombie_start + max_zombies

    nearest_z = None
    for r in range(zombie_start, zombie_end):
        dist = float(obs[r, 0])
        if dist <= 0:
            continue
        relx, rely = float(obs[r, 1]), float(obs[r, 2])
        if nearest_z is None or dist < nearest_z[0]:
            nearest_z = (dist, relx, rely)

    ally_start = 1
    ally_end = 1 + num_archers + num_knights
    nearest_a = None
    for r in range(ally_start, ally_end):
        dist = float(obs[r, 0])
        if dist <= 0:
            continue
        relx, rely = float(obs[r, 1]), float(obs[r, 2])
        if nearest_a is None or dist < nearest_a[0]:
            nearest_a = (dist, relx, rely)

    # Role-specific thresholds
    if role.lower() == "archer":
        max_dist = 0.85
        max_angle = 20.0
        ally_block_dist = 0.20
        ally_block_angle = 15.0
    else:
        max_dist = 0.60
        max_angle = 100.0
        ally_block_dist = 0.15
        ally_block_angle = 25.0

    ally_block_attack = False
    if nearest_a is not None:
        ad, ax, ay = nearest_a
        ally_angle, ally_dot = _angle_deg_and_dot(heading, [ax, ay])
        ally_block_attack = (ad <= ally_block_dist) and (ally_dot > 0) and (ally_angle <= ally_block_angle)

    if nearest_z is None:
        z_txt = "none"
        attack_ok = False
        turn = "NONE"
    else:
        zd, zx, zy = nearest_z
        z_angle, z_dot = _angle_deg_and_dot(heading, [zx, zy])
        in_front = (z_dot > 0) and (z_angle <= max_angle)
        close_enough = (zd <= max_dist)
        attack_ok = bool(in_front and close_enough and (not ally_block_attack))
        turn = _turn_hint(heading, [zx, zy])
        z_txt = f"dist={zd:.2f} rel=({zx:.2f},{zy:.2f}) angle_deg={z_angle:.1f} in_front={in_front}"

    a_txt = "none" if nearest_a is None else f"dist={nearest_a[0]:.2f} rel=({nearest_a[1]:.2f},{nearest_a[2]:.2f})"

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
    setup_logging(filename='logs_rl_run.txt', episode_type='KAZ_RL EPISODE')
    
    try:
        # Create KAZ_RL environment with dense rewards
        env = create_kaz_rl_env(
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
            # RL reward configuration
            reward_kill=1.0,
            penalty_action=-0.01,
            penalty_death=-1.0,
            penalty_zombie_escape=-1.0,
        )

        observations, infos = env.reset()

        # Initialize LLM
        my_controllers = {}
        lm = dspy.LM(
            model='ollama_chat/llama3:latest',
            api_base='http://localhost:11434',
            api_key=''
        )

        actions_details = [
            "0 -> move forward",
            "1 -> move backward",
            "2 -> rotate left",
            "3 -> rotate right",
            "4 -> attack / use weapon",
            "5 -> no-op",
        ]

        # Track statistics
        kills = {agent_id: 0 for agent_id in env.agents}
        cumulative_rewards = {agent_id: 0.0 for agent_id in env.agents}
        step_count = 0

        while env.agents:
            step_count += 1
            log_message(f"\n{'='*80}")
            log_message(f"STEP {step_count}")
            log_message(f"{'='*80}")

            # Dynamic Controller Management
            for agent_id in env.agents:
                if agent_id not in my_controllers:
                    middleware = MiddlewareOrchestrator(
                        env=env.base_env,  # Pass base_env for middleware
                        agent_id=agent_id,
                        LLM_model=lm,
                        scenario_description=get_scenario_description(agent_id),
                        goal_description=get_goal_description(agent_id),
                        action_space=actions_details,
                        environment_name="KAZ_RL Zombie Survival (Dense Rewards)",
                        observation_spec=get_observation_description()
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
            
            # Get actions from agents
            for agent_id in env.agents:
                agent_obs = observations[agent_id]
                
                role = "Archer" if "archer" in agent_id else "Knight"
                tactical_summary = summarize_kaz_obs(
                    obs=agent_obs,
                    role=role,
                    num_archers=2,
                    num_knights=2,
                    max_arrows=10,
                    max_zombies=10
                )
                
                log_message(f"\n[Agent: {agent_id}]")
                log_message(f"  Tactical Summary:\n    {tactical_summary.replace(chr(10), chr(10) + '    ')}")
                
                actions[agent_id] = my_controllers[agent_id].choose_action_with_tactical_info(
                    agent_obs, tactical_summary
                )
                
                log_message(f"  Action Chosen: {actions[agent_id]} ({actions_details[actions[agent_id]]})")

            # Step environment - NOW WITH DENSE RL REWARDS
            observations, rl_rewards, terminations, truncations, infos = env.step(actions)
            
            # Track rewards and kills
            terminated_agents = [a for a in terminations if terminations[a]]
            truncated_agents = [a for a in truncations if truncations[a]]
            
            if terminated_agents:
                log_message(f"\n[TERMINATED] Agents reached terminal state: {terminated_agents}")
            if truncated_agents:
                log_message(f"[TRUNCATED] Agents reached time limit: {truncated_agents}")
            
            # Remove controllers for ended agents
            active_ids = set(env.agents)
            removed_agents = set(my_controllers.keys()) - active_ids
            for agent_id in removed_agents:
                reason = "TERMINATED" if agent_id in terminated_agents else "TRUNCATED" if agent_id in truncated_agents else "UNKNOWN"
                log_message(f"[REMOVED] {agent_id} ({reason}) - Final kills: {kills[agent_id]}, Cumulative reward: {cumulative_rewards[agent_id]:.2f}")
            
            my_controllers = {k: v for k, v in my_controllers.items() if k in active_ids}

            # Track RL rewards and kills
            for agent_id, reward in rl_rewards.items():
                cumulative_rewards[agent_id] += reward
                
                if reward > 0:
                    if reward >= 0.99:  # Kill reward (1.0 - 0.01 action penalty)
                        kills[agent_id] += 1
                
                log_message(f"[REWARD] {agent_id}: step_reward={reward:.4f}, cumulative={cumulative_rewards[agent_id]:.2f}")
            
            log_message(f"\n[CUMULATIVE STATS] Kills: {kills} | Rewards: {cumulative_rewards}")

            # Count active zombies
            if env.agents:
                first_agent = list(env.agents)[0]
                obs = observations[first_agent]
                num_archers = 2
                num_knights = 2
                max_arrows = 10
                zombie_start = 1 + num_archers + num_knights + num_knights + max_arrows
                zombie_end = zombie_start + 10
                
                zombie_count = 0
                for r in range(zombie_start, zombie_end):
                    if obs[r, 0] > 0:
                        zombie_count += 1
                
                log_message(f"[ENVIRONMENT] Zombies alive: {zombie_count}")

        # Print final statistics
        log_message(f"\n{'='*80}")
        log_message("EPISODE FINISHED - FINAL STATISTICS")
        log_message(f"{'='*80}")
        total_kills = 0
        total_reward = 0.0
        for agent_id in sorted(kills.keys()):
            agent_kills = kills[agent_id]
            agent_reward = cumulative_rewards[agent_id]
            total_kills += agent_kills
            total_reward += agent_reward
            log_message(f"{agent_id:15s}: {agent_kills:3d} kills, reward={agent_reward:10.2f}")
        log_message(f"{'TOTAL':15s}: {total_kills:3d} kills, reward={total_reward:10.2f}")
        log_message(f"{'='*80}\n")

        env.close()
        
    except KeyboardInterrupt:
        log_message("\n[INTERRUPTED] Episode interrupted by user (Ctrl+C)")
        log_message(f"Final kills so far: {kills}\n")
        env.close()
    finally:
        close_logging()
