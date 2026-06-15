"""
KAZ environment driven by a SINGLE centralized LLM that sees ALL agents' situations
and returns ALL agents' actions in one call per step.

Unlike KAZ.py (one LLM call per agent), this lets the LLM coordinate:
  - "archer_0 attack_ok → attack; archer_1 rotate to flank"
  - "knight_0 closing in → knight_1 no-op to avoid blocking"

Run from this directory:
    cd functional_layer/envs
    python KAZ_centralized.py
"""

import sys
import os
import re
import math
import numpy as np
import dspy
from pettingzoo.butterfly import knights_archers_zombies_v10

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from utils.logging_utils import setup_logging, log_message, close_logging

# ── Config ────────────────────────────────────────────────────────────────────
LLM_MODEL = "ollama_chat/gemma4:e4b"
LLM_BASE  = "http://localhost:11434"

ENV_KWARGS = dict(
    spawn_rate=20, num_archers=2, num_knights=2,
    max_zombies=10, max_arrows=10,
    killable_knights=True, killable_archers=True,
    pad_observation=True, line_death=False,
    max_cycles=900, vector_state=True,
    use_typemasks=False, sequence_space=False,
)

ACTIONS = {
    0: "move forward",
    1: "move backward",
    2: "rotate left",
    3: "rotate right",
    4: "attack / use weapon",
    5: "no-op",
}

# ── Observation helpers (copied from KAZ.py) ──────────────────────────────────

_prev_positions: dict = {}


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
    cross = h[0] * r[1] - h[1] * r[0]
    return "RIGHT" if cross > 0 else "LEFT"


def summarize_kaz_obs(obs, role: str, num_archers: int, num_knights: int,
                      max_arrows: int, max_zombies: int, agent_id: str = "") -> str:
    obs = np.asarray(obs, dtype=float)
    sx, sy, hx, hy = obs[0, 1], obs[0, 2], obs[0, 3], obs[0, 4]
    heading = np.array([hx, hy], dtype=float)

    zombie_start = 1 + num_archers + num_knights + num_knights + max_arrows
    zombie_end   = zombie_start + max_zombies

    nearest_z = None
    for r in range(zombie_start, zombie_end):
        dist = float(obs[r, 0])
        if dist <= 0:
            continue
        relx, rely = float(obs[r, 1]), float(obs[r, 2])
        if nearest_z is None or dist < nearest_z[0]:
            nearest_z = (dist, relx, rely)

    nearest_a = None
    for r in range(1, 1 + num_archers + num_knights):
        dist = float(obs[r, 0])
        if dist <= 0:
            continue
        relx, rely = float(obs[r, 1]), float(obs[r, 2])
        if nearest_a is None or dist < nearest_a[0]:
            nearest_a = (dist, relx, rely)

    if role.lower() == "archer":
        max_dist, max_angle = 0.85, 20.0
        ally_block_dist, ally_block_angle = 0.20, 15.0
    else:
        max_dist, max_angle = 0.25, 70.0
        ally_block_dist, ally_block_angle = 0.15, 25.0

    ally_block_attack = False
    if nearest_a is not None:
        ad, ax, ay = nearest_a
        ally_angle, ally_dot = _angle_deg_and_dot(heading, [ax, ay])
        ally_block_attack = (ad <= ally_block_dist) and (ally_dot > 0) and (ally_angle <= ally_block_angle)

    if nearest_z is None:
        z_txt, attack_ok, turn, z_angle = "none", False, "NONE", None
    else:
        zd, zx, zy = nearest_z
        z_angle, z_dot = _angle_deg_and_dot(heading, [zx, zy])
        in_front  = (z_dot > 0) and (z_angle <= max_angle)
        attack_ok = bool(in_front and (zd <= max_dist) and (not ally_block_attack))
        turn      = _turn_hint(heading, [zx, zy])
        z_txt     = f"dist={zd:.2f} rel=({zx:.2f},{zy:.2f}) angle_deg={z_angle:.1f} in_front={in_front}"

    a_txt = "none" if nearest_a is None else f"dist={nearest_a[0]:.2f} rel=({nearest_a[1]:.2f},{nearest_a[2]:.2f})"

    movement_blocked = False
    if agent_id:
        prev = _prev_positions.get(agent_id)
        if prev is not None:
            movement_blocked = (abs(sx - prev[0]) < 0.005 and abs(sy - prev[1]) < 0.005)
        _prev_positions[agent_id] = (sx, sy)

    distance_status = ""
    rotations_needed = 0
    if nearest_z is not None:
        if role.lower() == "knight":
            distance_status = "IN_RANGE" if nearest_z[0] <= 0.25 else "TOO_FAR"
        if z_angle is not None and not attack_ok:
            rotations_needed = max(0, math.ceil((z_angle - max_angle) / 10.0))

    summary = (
        f"pos=({sx:.2f},{sy:.2f}) heading=({hx:.2f},{hy:.2f})\n"
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


# ── DSPy centralized signature ────────────────────────────────────────────────

class CentralizedKAZSig(dspy.Signature):
    """
    You are the TEAM COMMANDER for a zombie survival game.
    You see ALL agents' tactical situations and choose actions for ALL of them in one decision.
    This lets you coordinate: e.g. two archers cover different sides, a knight flanks while
    an archer suppresses, or two agents avoid shooting through each other.

    AGENTS:
      archer_0, archer_1 — ranged. attack_ok=True means fire now. Range up to 0.85.
      knight_0, knight_1 — melee. Must be within 0.25 distance. Wider angle (70°).

    ACTIONS (same set for every agent):
      0=move_forward  1=move_backward  2=rotate_left  3=rotate_right  4=attack  5=no-op

    COORDINATION RULES:
      - If two agents have attack_ok=True for likely the same zombie, one attacks, one advances.
      - Never attack if ally_block_attack=True.
      - Knights: if TOO_FAR, move toward zombie (0). If IN_RANGE and roughly facing, attack (4).
      - Archers: attack_ok=True → 4. Zombie visible but off-angle → rotate (2 or 3). No zombie → 0.
      - If movement_blocked, rotate or go backward instead of repeating forward.
    """
    team_situation: str = dspy.InputField(desc="All active agents' tactical summaries")
    reasoning: str      = dspy.OutputField(desc="One sentence team coordination plan")
    actions: str        = dspy.OutputField(
        desc="One line per agent: 'agent_id: N' where N is 0-5. "
             "Include ONLY the active agents listed in team_situation."
    )


# ── Action parser ─────────────────────────────────────────────────────────────

def parse_team_actions(response: str, active_agents: list) -> dict:
    result = {}
    for agent_id in active_agents:
        m = re.search(rf'{re.escape(agent_id)}\s*[=:]\s*([0-5])', response)
        if m:
            result[agent_id] = int(m.group(1))
        else:
            result[agent_id] = 5  # no-op fallback
            log_message(f"  [WARN] could not parse action for {agent_id}, defaulting to 5")
    return result


# ── Main loop ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    setup_logging(filename="logs_centralized_run.txt", episode_type="EPISODE")

    lm = dspy.LM(model=LLM_MODEL, api_base=LLM_BASE, api_key="ollama", cache=False)
    dspy.configure(lm=lm)

    planner = dspy.ChainOfThought(CentralizedKAZSig)

    try:
        env = knights_archers_zombies_v10.parallel_env(render_mode=None, **ENV_KWARGS)
        observations, _ = env.reset()
        log_message(f"Agents: {env.agents}")
        log_message(f"LLM model: {LLM_MODEL}")

        kills      = {a: 0 for a in env.agents}
        step_count = 0

        while env.agents:
            step_count += 1
            log_message(f"\n{'='*70}")
            log_message(f"STEP {step_count}  |  active: {list(env.agents)}")
            log_message(f"{'='*70}")

            # Build combined situation string for all active agents
            sections = []
            for agent_id in env.agents:
                role = "archer" if "archer" in agent_id else "knight"
                summary = summarize_kaz_obs(
                    observations[agent_id], role,
                    num_archers=2, num_knights=2,
                    max_arrows=10, max_zombies=10,
                    agent_id=agent_id,
                )
                sections.append(f"=== {agent_id} ({role.upper()}) ===\n{summary}")

            team_situation = "\n\n".join(sections)
            log_message(f"\n[TEAM SITUATION]\n{team_situation}")

            # Single LLM call for all agents
            result = planner(team_situation=team_situation)
            log_message(f"\n[REASONING] {result.reasoning}")
            log_message(f"[ACTIONS RAW]\n{result.actions}")

            actions = parse_team_actions(result.actions, list(env.agents))

            for agent_id, action in actions.items():
                log_message(f"  {agent_id}: {action} ({ACTIONS[action]})")

            observations, rewards, terminations, truncations, _ = env.step(actions)

            for agent_id, reward in rewards.items():
                if reward > 0:
                    kills[agent_id] += reward
                    log_message(f"  [KILL] {agent_id} +{reward:.1f}  total={kills[agent_id]:.0f}")

            terminated = [a for a in terminations if terminations[a]]
            truncated  = [a for a in truncations  if truncations[a]]
            if terminated: log_message(f"[TERMINATED] {terminated}")
            if truncated:  log_message(f"[TRUNCATED]  {truncated}")
            log_message(f"[KILLS] {kills}")

        log_message(f"\n{'='*70}")
        log_message("EPISODE FINISHED")
        log_message(f"{'='*70}")
        total = 0
        for a in sorted(kills):
            log_message(f"  {a:15s}: {kills[a]:.0f} kills")
            total += kills[a]
        log_message(f"  {'TOTAL':15s}: {total:.0f} kills")
        env.close()

    except KeyboardInterrupt:
        log_message("\n[INTERRUPTED]")
        log_message(f"Kills so far: {kills}")
        env.close()
    finally:
        close_logging()
