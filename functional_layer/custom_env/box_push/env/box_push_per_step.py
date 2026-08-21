"""
Box-Push driven by a SINGLE centralized LLM that decides EVERY primitive move.

Unlike box_push_centralized.py (which picks high-level skills and lets them run), here the
LLM is consulted EVERY env step. It sees ONE unified belief of both agents and outputs the
next primitive action (TURN_LEFT / TURN_RIGHT / MOVE_FORWARD / STAY) for BOTH agents. There
is no skill layer and no in-code bail logic — all judgment (explore / push / give-up / avoid
the partner) is the LLM's.

Cost: one LLM call PER step → up to a few hundred calls per episode (slow with a local model).

Run from this directory:
    cd functional_layer/custom_env/box_push/env
    python box_push_per_step.py
"""
import sys
import os
import re
import time
from typing import Dict, List, Optional, Tuple

_THIS_DIR  = os.path.dirname(os.path.abspath(__file__))
_CST_ENV   = os.path.abspath(os.path.join(_THIS_DIR, "../../cooperative_search_transport/env"))
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "../../../.."))
for _p in (_REPO_ROOT, _CST_ENV, _THIS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import dspy
from constants import (Actions, Directions, DIRECTION_VECTORS, DIRECTION_NAMES, ACTION_NAMES)
from state import EnvConfig
from obs_parser import parse_cst_obs
from multi_agent_box_push_env import MultiAgentBoxPushEnv
from box_push_env import GOAL_ZONE
from middleware_layer.belief_updaters.deterministic_grid_updater import DeterministicGridUpdater
from model_layer.planner.centralized_dspy_planner import CentralizedDSPyPlanner

# ── Config ────────────────────────────────────────────────────────────────────
LLM_MODEL = "ollama_chat/gemma4:e4b"
LLM_BASE  = "http://localhost:11434"
MAX_STEPS = 200   # one LLM call per step — keep episodes tractable

AGENTS = ["agent_0", "agent_1"]

# Object metadata only (NO positions — POMDP discovery).
_PRIOR_OBJECTS: Dict[int, dict] = {
    0: dict(is_target=True, required_agents=2),   # heavy
    1: dict(is_target=True, required_agents=1),   # light
}

_AGENT_STARTS: Dict[str, Tuple[List[int], int]] = {
    "agent_0": ([10, 10], int(Directions.LEFT)),
    "agent_1": ([10,  9], int(Directions.LEFT)),
}

_GOAL_SET = {tuple(c) for c in GOAL_ZONE}


# ── Belief bootstrap ─────────────────────────────────────────────────────────────

def _build_initial_entities(agent_id: str) -> dict:
    start_pos, start_dir = _AGENT_STARTS[agent_id]
    grid: List[List[str]] = [["unknown"] * 12 for _ in range(12)]
    for cx, cy in GOAL_ZONE:
        grid[cx][cy] = "delivery_zone"
    entities: dict = {
        "self": {
            "direction":            start_dir,
            "position":             list(start_pos),
            "carrying_object_id":   None,
            "engaged_object_ids":   [],
            "delivered_object_ids": [],
        },
        "grid": {"cells": grid},
    }
    for oid, info in _PRIOR_OBJECTS.items():
        entities[f"object_{oid}"] = {
            "is_target":       info["is_target"],
            "required_agents": info["required_agents"],
            "status":          "available",
        }
    return entities


# ── Combined view helpers ─────────────────────────────────────────────────────────

def _target_cells(grid):
    return [(x, y) for x, col in enumerate(grid) for y, c in enumerate(col)
            if c.startswith("target")]


def _interpret_reward(action, reward) -> str:
    if reward is None:
        return "none yet"
    if action == int(Actions.MOVE_FORWARD):
        if reward > 0.15:  return "JOINT PUSH worked (box + both agents moved)"
        if reward > 0.05:  return "pushed the box one cell"
        if reward > -0.06: return "moved forward one cell"
        return "BLOCKED — did not move (wall / partner / heavy box needs 2)"
    return f"turned/stayed (reward {reward:+.2f})"


def _occ(positions) -> Dict[Tuple[int, int], str]:
    occ = {}
    for i, aid in enumerate(AGENTS):
        p = positions.get(aid)
        if p is not None:
            occ[(int(p[0]), int(p[1]))] = str(i)
    return occ


def _render_combined(grid, positions) -> str:
    W = len(grid)
    H = len(grid[0]) if W > 0 else 0
    occ = _occ(positions)
    header = "    " + "".join(str(x % 10) for x in range(W))
    rows = [header]
    for y in range(H):
        rc = []
        for x in range(W):
            if (x, y) in occ:
                rc.append(occ[(x, y)])              # 0 / 1 = the agents
            else:
                c = grid[x][y]
                rc.append("?" if c == "unknown" else
                          "." if c == "empty" else
                          "#" if c == "wall" else
                          "D" if c == "delivery_zone" else
                          "T" if c.startswith("target") else "?")
        rows.append(f"{y:2d}  " + "".join(rc))
    return "\n".join(rows)


def _cell_for(grid, x, y, occ, me: str) -> str:
    if not (0 <= x < len(grid) and 0 <= y < len(grid[0])):
        return "WALL(edge)"
    if (x, y) in occ and occ[(x, y)] != me:
        return "PARTNER"
    c = grid[x][y]
    if c == "wall":                 return "WALL"
    if c == "delivery_zone":        return "GOAL"
    if c.startswith("target"):      return "BOX"
    if c == "unknown":              return "unexplored"
    return "empty"


def _dir_words(frm, to) -> str:
    dx, dy = to[0] - frm[0], to[1] - frm[1]
    parts = []
    if dx > 0:   parts.append(f"RIGHT {dx}")
    elif dx < 0: parts.append(f"LEFT {-dx}")
    if dy > 0:   parts.append(f"DOWN {dy}")
    elif dy < 0: parts.append(f"UP {-dy}")
    return " + ".join(parts) if parts else "here"


def build_team_view(ent_by_agent: Dict[str, dict], last_feedback: Dict[str, str]) -> str:
    grid      = ent_by_agent[AGENTS[0]]["grid"]["cells"]   # shared map
    positions = {aid: ent_by_agent[aid]["self"]["position"] for aid in AGENTS}
    dirs      = {aid: int(ent_by_agent[aid]["self"]["direction"]) for aid in AGENTS}
    occ       = _occ(positions)

    targets = sorted(_target_cells(grid))
    explored = sum(1 for col in grid for c in col if c != "unknown")

    box_lines = []
    for (x, y) in targets:
        tag = "ON GOAL (delivered)" if (x, y) in _GOAL_SET else "in arena"
        box_lines.append(f"  BOX at [{x},{y}] ({tag})")
    if not box_lines:
        box_lines.append("  none discovered yet — explore (move toward '?' cells) to find boxes")

    lines = [
        f"UNIFIED MAP ({explored}/144 explored)  —  0 = agent_0, 1 = agent_1, "
        f"T = box, D = goal column, # = wall, . = empty, ? = unexplored",
        _render_combined(grid, positions),
        "",
        "BOXES:",
        *box_lines,
        "",
        "AGENTS (what MOVE_FORWARD would hit, and what each turn would face):",
    ]
    for i, aid in enumerate(AGENTS):
        p = positions[aid]; d = dirs[aid]; me = str(i)
        ahead, left, right, behind = d, (d - 1) % 4, (d + 1) % 4, (d + 2) % 4

        def nb(dd):
            dx, dy = DIRECTION_VECTORS[Directions(dd)]
            return _cell_for(grid, p[0] + dx, p[1] + dy, occ, me)

        goal_cell = min(GOAL_ZONE, key=lambda c: abs(c[0]-p[0]) + abs(c[1]-p[1]))
        goal_hint = _dir_words(p, goal_cell)
        nearest = min((t for t in targets if t not in _GOAL_SET),
                      key=lambda c: abs(c[0]-p[0]) + abs(c[1]-p[1]), default=None)
        box_hint = _dir_words(p, nearest) if nearest else "none known"

        lines += [
            f"{aid} (= '{i}' on map): at [{p[0]},{p[1]}] facing {DIRECTION_NAMES[d]}",
            f"    AHEAD ({DIRECTION_NAMES[ahead]}) = {nb(ahead)}    <-- MOVE_FORWARD moves into this cell",
            f"    LEFT-hand  ({DIRECTION_NAMES[left]}) = {nb(left)}   (TURN_LEFT to face it)",
            f"    RIGHT-hand ({DIRECTION_NAMES[right]}) = {nb(right)}  (TURN_RIGHT to face it)",
            f"    BEHIND ({DIRECTION_NAMES[behind]}) = {nb(behind)}",
            f"    goal is: {goal_hint}   |   nearest box is: {box_hint}",
            f"    last move: {last_feedback.get(aid, 'none yet')}",
        ]
    return "\n".join(lines)


# ── Planner configuration (passed as params to the reusable CentralizedDSPyPlanner) ──

_OBJECTIVE = "Push both red boxes onto the GOAL column (x=1)."

_RULES = """\
You drive TWO agents on a 12x12 grid, choosing ONE primitive move for EACH agent THIS step.
x increases RIGHT, y increases DOWN.

GOAL: push both red BOXES onto the GOAL column (x=1, shown as 'D').

HOW PUSHING WORKS:
  - To push a box, an agent must FACE it and MOVE_FORWARD (the box is its AHEAD cell).
  - A LIGHT box slides one cell when ONE agent pushes it (the cell beyond must be free).
  - A HEAVY box does NOT move for one agent. TWO agents must line up in TANDEM directly
    behind it — one agent against the box, the SECOND agent directly behind the first,
    BOTH facing the same way — and BOTH MOVE_FORWARD the same step. (You discover a box is
    heavy when a single push reports BLOCKED.)
  - Push boxes toward the goal column (usually face LEFT and push).

RULES OF THUMB:
  - If AHEAD = WALL or PARTNER, MOVE_FORWARD is wasted — TURN instead.
  - To find boxes, move toward unexplored ('?') cells.
  - Do not send both agents into the same cell.
  - Use each agent's AHEAD/LEFT/RIGHT/BEHIND lines and the goal/box direction hints to decide
    whether to turn or move.
"""

_ACTION_MENU = """\
  MOVE_FORWARD — step one cell in the direction the agent faces (into its AHEAD cell)
  TURN_LEFT    — rotate to face the LEFT-hand direction (does not move)
  TURN_RIGHT   — rotate to face the RIGHT-hand direction (does not move)
  STAY         — do nothing
"""


# ── Action parser ──────────────────────────────────────────────────────────────

_MOVE_NAMES = {
    "MOVE_FORWARD": int(Actions.MOVE_FORWARD), "FORWARD": int(Actions.MOVE_FORWARD),
    "MOVE": int(Actions.MOVE_FORWARD), "F": int(Actions.MOVE_FORWARD),
    "TURN_LEFT": int(Actions.TURN_LEFT), "LEFT": int(Actions.TURN_LEFT),
    "TURN_RIGHT": int(Actions.TURN_RIGHT), "RIGHT": int(Actions.TURN_RIGHT),
    "STAY": int(Actions.STAY), "WAIT": int(Actions.STAY), "NOOP": int(Actions.STAY),
}


def _move_parser(agent_id: str, raw: str) -> int:
    """Map one agent's raw decision string (e.g. 'MOVE_FORWARD') → Actions int.
    Passed to CentralizedDSPyPlanner.decide(); unknown → STAY."""
    m = re.search(r'[A-Za-z_]+', raw or "")
    if m and m.group(0).upper() in _MOVE_NAMES:
        return _MOVE_NAMES[m.group(0).upper()]
    return int(Actions.STAY)


# ── Main loop ──────────────────────────────────────────────────────────────────

def main():
    log_path = os.path.join(_THIS_DIR, "box_push_per_step_log.txt")
    print(f"Logging to {log_path}")

    lm = dspy.LM(model=LLM_MODEL, api_base=LLM_BASE, api_key="ollama", cache=False)
    planner = CentralizedDSPyPlanner(name="box_push_per_step")
    planner.configure_ollama(lm)

    config = EnvConfig(width=12, height=12, num_agents=2, num_objects=2,
                       num_target_objects=2, max_steps=MAX_STEPS, agent_view_size=3,
                       render_mode="human", seed=42)
    env = MultiAgentBoxPushEnv(config=config)
    observations, _ = env.reset(seed=42)

    updaters = {aid: DeterministicGridUpdater(_build_initial_entities(aid), 12, 12)
                for aid in AGENTS}
    shared_grid: List[List[str]] = [["unknown"] * 12 for _ in range(12)]
    for cx, cy in GOAL_ZONE:
        shared_grid[cx][cy] = "delivery_zone"
    for aid in AGENTS:
        updaters[aid]._grid = shared_grid
        updaters[aid]._entities["grid"] = {"cells": [list(c) for c in shared_grid]}

    def entities(aid):
        return updaters[aid].get_all_entities()

    def update(aid, action, reward, obs):
        snap = parse_cst_obs(obs, aid)
        snap["action"] = action
        snap["reward"] = reward
        updaters[aid].update_entity(snap)

    print("\n" + "=" * 70)
    print("BOX PUSH  —  PER-STEP CENTRALIZED LLM (one move per agent each step)")
    print("=" * 70)
    print(f"NOTE: one LLM call per step, up to {MAX_STEPS} steps — this is slow.")

    env.render()
    time.sleep(0.3)

    with open(log_path, "w", buffering=1) as log_f:
        def log(msg):
            print(msg)
            log_f.write(msg + "\n")

        last_feedback = {aid: "none yet" for aid in AGENTS}
        step = 0
        done = False
        while not done and step < MAX_STEPS:
            step += 1
            view = build_team_view({aid: entities(aid) for aid in AGENTS}, last_feedback)
            feedback = "  ".join(f"{a}: {last_feedback[a]}" for a in AGENTS)
            log(f"\n{'='*70}\nSTEP {step}\n{'='*70}\n{view}")

            reasoning, decided = planner.decide(
                task_instructions=_RULES, decision_space=_ACTION_MENU,
                team_situation=view, objective=_OBJECTIVE, agents=AGENTS,
                recent_feedback=feedback, parser=_move_parser)
            acts = {aid: decided.get(aid, int(Actions.STAY)) for aid in AGENTS}
            log(f"\n[NOTE] {reasoning}")
            log("[MOVES] " + "  ".join(f"{a}={ACTION_NAMES.get(acts[a], acts[a])}"
                                       for a in AGENTS))

            observations, rewards, terminations, truncations, _ = env.step(acts)
            env.render()
            for aid in AGENTS:
                update(aid, acts[aid], rewards.get(aid, -0.01), observations.get(aid, {}))
                last_feedback[aid] = (f"{ACTION_NAMES.get(acts[aid], acts[aid])} → "
                                      f"{_interpret_reward(acts[aid], rewards.get(aid))}")
            log("[RESULT] " + "  ".join(f"{a}: {last_feedback[a]}" for a in AGENTS))

            if all(terminations.values()):
                log(f"\n SUCCESS — all boxes delivered in {step} steps!")
                done = True
            elif all(truncations.values()):
                log(f"\n Episode truncated at {MAX_STEPS} steps.")
                done = True
            time.sleep(0.05)

    env.close()
    print("\nEpisode finished.")


if __name__ == "__main__":
    main()
