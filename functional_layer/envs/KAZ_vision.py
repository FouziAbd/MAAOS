"""
KAZ environment driven by a vision LLM (image observations, vector_state=False).
Each agent's observation is a 512×512 RGB screenshot of the game.
The Ollama vision API is called directly — no DSPy, no vector parsing.

Belief state tracks: absolute heading (exact from action accumulation),
last known zombie direction, reward history, and kill count.

Run from this directory:
    cd functional_layer/envs
    python KAZ_vision.py
"""

import sys
import os
import re
import math
import base64
import io
import time
import numpy as np
import requests
from dataclasses import dataclass, field
from typing import Optional, List
from PIL import Image
from pettingzoo.butterfly import knights_archers_zombies_v10

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from utils.logging_utils import setup_logging, log_message, close_logging

# ── Config ───────────────────────────────────────────────────────────────────
OLLAMA_URL   = "http://localhost:11434/api/chat"
VISION_MODEL = "gemma4:e4b"
TIMEOUT      = 180

ACTION_MAP = {
    0: "move forward",
    1: "move backward",
    2: "rotate left  (-10°)",
    3: "rotate right (+10°)",
    4: "attack / use weapon",
    5: "no-op (do nothing)",
}

VISUAL_GUIDE = (
    "VISUAL GUIDE — what you see in the screenshot:\n"
    "- This is YOUR LOCAL VIEW only (POMDP) — you see only a small area around yourself\n"
    "- YOU are the figure in the CENTER of the image\n"
    "- Dark/black edges = outside your observation range\n"
    "- Only react to what is actually visible — do not assume threats exist offscreen\n"
    "- ZOMBIES: bright green-tinted undead humanoid sprites — the enemy\n"
    "- ARCHERS: small humanoid figures holding a bow\n"
    "- KNIGHTS: small humanoid figures in armor with a sword\n"
    "- The direction YOUR sprite is facing = the direction you will move/attack\n"
)

ROLE_TACTICS = {
    "archer": (
        "ARCHER — follow this priority order, stop at first match:\n"
        "1. Zombie visible AND in front (even slightly off-center) → ACTION 4 (ATTACK) — do not wait for perfect alignment\n"
        "2. Zombie visible but clearly to the side (left or right) → ACTION 2 or 3 (ROTATE toward it, do not move)\n"
        "3. Zombie visible and dangerously close → ACTION 1 (MOVE BACKWARD)\n"
        "4. No zombie visible, wall/edge visible ahead → ACTION 1 (MOVE BACKWARD)\n"
        "5. No zombie visible, open space → ACTION 0 (MOVE FORWARD)\n"
        "NEVER attack if an ally is between you and the zombie (friendly fire).\n"
        "IMPORTANT: if you have been rotating toward a zombie for 2+ steps, ATTACK now — do not keep rotating.\n"
    ),
    "knight": (
        "KNIGHT — follow this priority order, stop at first match:\n"
        "1. Zombie close AND roughly facing it → ACTION 4 (ATTACK) — do not wait for perfect alignment\n"
        "2. Zombie close but clearly to the side → ACTION 2 or 3 (ROTATE toward it)\n"
        "3. Zombie visible but far → ACTION 0 (MOVE FORWARD toward it)\n"
        "4. No zombie visible, wall/edge visible ahead → ACTION 1 (MOVE BACKWARD)\n"
        "5. No zombie visible, open space → ACTION 0 (MOVE FORWARD to search)\n"
        "IMPORTANT: if you have been rotating toward a zombie for 2+ steps, ATTACK now — do not keep rotating.\n"
    ),
}


# ── Belief state ──────────────────────────────────────────────────────────────

@dataclass
class AgentBelief:
    heading_deg: float = 0.0               # exact, accumulated from rotation actions
    last_zombie_dir: Optional[str] = None  # "LEFT", "RIGHT", "AHEAD", "VISIBLE"
    last_zombie_step: int = -1             # step when zombie was last seen
    reward_history: List[float] = field(default_factory=list)  # last 5 rewards
    total_kills: int = 0


_COMPASS = ["EAST", "SOUTH-EAST", "SOUTH", "SOUTH-WEST",
            "WEST", "NORTH-WEST", "NORTH", "NORTH-EAST"]


def _heading_label(deg: float) -> str:
    idx = int((deg % 360 + 22.5) / 45) % 8
    return _COMPASS[idx]


def _heading_from_vector(hx: float, hy: float) -> float:
    """Unit vector → degrees. Image coords: 0°=EAST, 90°=SOUTH."""
    return math.degrees(math.atan2(hy, hx)) % 360


def _get_initial_headings(env_kwargs: dict) -> dict:
    """
    Spin up a temporary vector_state=True env to read exact initial headings,
    then close it. KAZ initial conditions are deterministic so this is reliable.
    """
    import copy
    kwargs = copy.copy(env_kwargs)
    kwargs["vector_state"] = True
    kwargs["render_mode"]  = None
    vec_env = knights_archers_zombies_v10.parallel_env(**kwargs)
    obs, _  = vec_env.reset()
    headings = {
        agent_id: _heading_from_vector(float(o[0, 3]), float(o[0, 4]))
        for agent_id, o in obs.items()
    }
    vec_env.close()
    return headings


def _extract_zombie_dir(scene_text: str) -> Optional[str]:
    """
    Parse the SCENE line from LLM response to detect zombie direction.
    Returns None if no zombie mentioned or negated.
    """
    s = scene_text.lower()
    if "zombie" not in s:
        return None
    # Broad negation: handles "no visible zombies", "zombie not visible", etc.
    if re.search(r"no\s+\w*\s*zombie|zombie\w*\s+not|not.*zombie|no green|none visible|no threat|no enemy", s):
        return None
    if "left"  in s: return "LEFT"
    if "right" in s: return "RIGHT"
    if re.search(r"front|ahead|directly|center", s): return "AHEAD"
    return "VISIBLE"


def _update_belief(belief: AgentBelief, action: int, reward: float,
                   zombie_dir: Optional[str], step: int) -> None:
    """Mutate belief in-place after each step."""
    # Exact heading accumulation
    if action == 2:
        belief.heading_deg = (belief.heading_deg - 10) % 360
    elif action == 3:
        belief.heading_deg = (belief.heading_deg + 10) % 360

    # Zombie memory
    if zombie_dir is not None:
        belief.last_zombie_dir  = zombie_dir
        belief.last_zombie_step = step

    # Reward history (keep last 5)
    belief.reward_history.append(reward)
    if len(belief.reward_history) > 5:
        belief.reward_history.pop(0)

    if reward > 0:
        belief.total_kills += int(reward)


def _belief_to_text(belief: AgentBelief, current_step: int) -> str:
    label   = _heading_label(belief.heading_deg)
    deg     = belief.heading_deg
    history = belief.reward_history if belief.reward_history else []

    lines = [
        "MEMORY (computed from your action history — use this alongside the image):",
        f"- Your facing direction: {label} (~{deg:.0f}°)  "
        f"[EAST=right, SOUTH=down, WEST=left, NORTH=up on map]",
    ]

    if belief.last_zombie_step < 0:
        lines.append("- Zombie memory: none seen yet this episode")
    else:
        steps_ago = current_step - belief.last_zombie_step
        if steps_ago == 0:
            lines.append(f"- Zombie: CURRENTLY VISIBLE, last detected {belief.last_zombie_dir}")
        else:
            lines.append(
                f"- Zombie memory: last seen {steps_ago} step(s) ago, "
                f"was to your {belief.last_zombie_dir}"
            )

    if history:
        kills_in_history = sum(1 for r in history if r > 0)
        lines.append(
            f"- Recent rewards (last {len(history)} steps): {[round(r,2) for r in history]} "
            f"— {kills_in_history} kill(s)"
        )
    lines.append(f"- Total kills this episode: {belief.total_kills}")
    return "\n".join(lines)


# ── Vision helpers ────────────────────────────────────────────────────────────

def enhance_obs(obs: np.ndarray) -> Image.Image:
    """Gamma correction: brightens dark pixels without colour distortion."""
    arr = np.power(obs.astype(np.float32) / 255.0, 0.4) * 255.0
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def obs_to_base64(obs: np.ndarray) -> str:
    img = enhance_obs(obs)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def ask_vision_llm(
    image_b64: str,
    agent_id: str,
    role: str,
    belief: AgentBelief,
    current_step: int,
    last_action: Optional[int] = None,
    last_reward: Optional[float] = None,
) -> tuple:
    """
    Send enhanced POMDP screenshot + belief state + last-step feedback to vision LLM.
    Returns (action: int, zombie_dir: Optional[str]).
    """
    action_list = "\n".join(f"  {k} -> {v}" for k, v in ACTION_MAP.items())
    belief_text = _belief_to_text(belief, current_step)

    feedback = ""
    if last_action is not None and last_reward is not None:
        outcome = "KILL! great, press the attack" if last_reward > 0 else \
                  "no kill — try a different action if stuck" if last_reward == 0 else "penalty"
        feedback = (
            f"LAST STEP: action={last_action} ({ACTION_MAP[last_action]}), "
            f"reward={last_reward:.2f} → {outcome}\n"
        )

    prompt = (
        f"You are deciding the next action for a {role.upper()} agent "
        f"in a zombie survival game.\n\n"
        f"{VISUAL_GUIDE}\n"
        f"{ROLE_TACTICS[role]}\n"
        f"{belief_text}\n"
        f"{feedback}\n"
        "AVAILABLE ACTIONS:\n"
        f"{action_list}\n\n"
        "Study the screenshot carefully. YOU are in the CENTER.\n"
        "Use the image AND your MEMORY above to decide.\n"
        "Respond in this EXACT format:\n"
        "SCENE: [describe what you see — zombie positions relative to you, "
        "walls, allies, your facing direction from the sprite]\n"
        "DECISION: [apply your role priority rules step by step]\n"
        "ACTION: [single digit 0-5]\n"
    )

    payload = {
        "model": VISION_MODEL,
        "messages": [{"role": "user", "content": prompt, "images": [image_b64]}],
        "stream": False,
        "think":  True,
        "options": {"temperature": 0.1},
    }

    try:
        resp     = requests.post(OLLAMA_URL, json=payload, timeout=TIMEOUT)
        resp.raise_for_status()
        msg      = resp.json().get("message", {})
        thinking = msg.get("thinking", "")
        raw      = msg.get("content", "").strip()

        if thinking:
            log_message(
                f"  [{agent_id}] thinking: "
                f"{thinking[:300].replace(chr(10),' ')}"
                f"{'...' if len(thinking) > 300 else ''}"
            )
        log_message(f"  [{agent_id}] response:\n    {raw.replace(chr(10), chr(10)+'    ')}")

        # Extract zombie direction from SCENE line for belief update
        scene_match = re.search(r'SCENE:\s*(.+?)(?=\nDECISION:|$)', raw, re.IGNORECASE | re.DOTALL)
        zombie_dir  = _extract_zombie_dir(scene_match.group(1)) if scene_match else None

        # Parse action
        match = re.search(r'ACTION:\s*([0-5])', raw, re.IGNORECASE)
        if match:
            return int(match.group(1)), zombie_dir
        for ch in raw:
            if ch.isdigit() and int(ch) in ACTION_MAP:
                return int(ch), zombie_dir

        log_message(f"  [{agent_id}] WARNING: could not parse action, defaulting to 5")
        return 5, zombie_dir

    except requests.exceptions.Timeout:
        log_message(f"  [{agent_id}] WARNING: LLM timeout, defaulting to 5")
        return 5, None
    except Exception as e:
        log_message(f"  [{agent_id}] WARNING: LLM error ({e}), defaulting to 5")
        return 5, None


# ── Main loop ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    setup_logging(filename="logs_vision_run.txt", episode_type="EPISODE")

    ENV_KWARGS = dict(
        spawn_rate=20, num_archers=2, num_knights=2,
        max_zombies=10, max_arrows=10,
        killable_knights=True, killable_archers=True,
        pad_observation=True, line_death=False,
        max_cycles=900, use_typemasks=False, sequence_space=False,
    )

    try:
        # Get exact initial headings from a vector env (deterministic in KAZ)
        log_message("Reading initial headings from vector env...")
        initial_headings = _get_initial_headings(ENV_KWARGS)
        log_message(f"Initial headings: { {a: f'{d:.1f}°' for a,d in initial_headings.items()} }")

        env = knights_archers_zombies_v10.parallel_env(
            render_mode=None,
            vector_state=False,
            **ENV_KWARGS,
        )
        observations, infos = env.reset()
        log_message(f"Obs shape: {next(iter(observations.values())).shape}")
        log_message(f"Vision model: {VISION_MODEL}")

        # Init belief state per agent with exact heading
        beliefs     = {
            a: AgentBelief(heading_deg=initial_headings.get(a, 0.0))
            for a in env.agents
        }
        kills       = {a: 0 for a in env.agents}
        last_action = {}
        last_reward = {}
        step_count  = 0

        while env.agents:
            step_count += 1
            log_message(f"\n{'='*60}")
            log_message(f"STEP {step_count}  |  agents: {list(env.agents)}")
            log_message(f"{'='*60}")

            actions     = {}
            zombie_dirs = {}

            for agent_id in env.agents:
                role      = "archer" if "archer" in agent_id else "knight"
                image_b64 = obs_to_base64(observations[agent_id])

                t0 = time.time()
                action, zombie_dir = ask_vision_llm(
                    image_b64, agent_id, role,
                    belief=beliefs[agent_id],
                    current_step=step_count,
                    last_action=last_action.get(agent_id),
                    last_reward=last_reward.get(agent_id),
                )
                elapsed = time.time() - t0

                actions[agent_id]     = action
                zombie_dirs[agent_id] = zombie_dir
                log_message(
                    f"  [{agent_id}] action={action} ({ACTION_MAP[action]})  "
                    f"heading={_heading_label(beliefs[agent_id].heading_deg)}  "
                    f"zombie_dir={zombie_dir}  llm_time={elapsed:.1f}s"
                )

            observations, rewards, terminations, truncations, infos = env.step(actions)

            # Update beliefs and last-step feedback
            for agent_id, action in actions.items():
                reward = rewards.get(agent_id, 0.0)
                last_action[agent_id] = action
                last_reward[agent_id] = reward
                _update_belief(
                    beliefs[agent_id], action, reward,
                    zombie_dirs.get(agent_id), step_count,
                )
                if reward > 0:
                    kills[agent_id] += reward
                    log_message(
                        f"  [REWARD] {agent_id} +{reward}  "
                        f"total={kills[agent_id]}"
                    )

            terminated = [a for a in terminations if terminations[a]]
            truncated  = [a for a in truncations  if truncations[a]]
            if terminated: log_message(f"[TERMINATED] {terminated}")
            if truncated:  log_message(f"[TRUNCATED]  {truncated}")
            log_message(f"[KILLS] {kills}")

        log_message(f"\n{'='*60}")
        log_message("EPISODE FINISHED")
        log_message(f"{'='*60}")
        total = 0
        for a in sorted(kills):
            log_message(f"  {a:15s}: {kills[a]} kills")
            total += kills[a]
        log_message(f"  {'TOTAL':15s}: {total} kills")
        env.close()

    except KeyboardInterrupt:
        log_message("\n[INTERRUPTED] Ctrl+C")
        log_message(f"Kills so far: {kills}")
        env.close()
    finally:
        close_logging()
