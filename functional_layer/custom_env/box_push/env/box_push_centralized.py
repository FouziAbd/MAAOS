"""
Box-Push driven by a SINGLE centralized LLM that sees BOTH agents' states and
assigns ONE granular skill to each per cycle (true POMDP, shared belief map).

Skills (single-purpose):
  explore         -> found_target | explored
  goto_push_pose  -> in_position | none_known | blocked
  push            -> pushed | delivered | too_heavy | blocked
  cooperate_push  -> moved | delivered | waiting_partner | blocked
  wait            -> done

Run from this directory:
    cd functional_layer/custom_env/box_push/env
    python box_push_centralized.py
"""
import sys
import os
import re
import time
from typing import Dict, List, Optional, Tuple

_THIS_DIR    = os.path.dirname(os.path.abspath(__file__))
_CUSTOM_ENV  = os.path.abspath(os.path.join(_THIS_DIR, "../.."))  # functional_layer/custom_env
_CST_ENV     = os.path.join(_CUSTOM_ENV, "cooperative_search_transport", "env")
_REPO_ROOT   = os.path.abspath(os.path.join(_THIS_DIR, "../../../.."))
for _p in (_REPO_ROOT, _CUSTOM_ENV, _CST_ENV, _THIS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import dspy
from constants import Actions, Directions, DIRECTION_NAMES, ACTION_NAMES
from state import EnvConfig
from obs_parser import parse_cst_obs
from shared_skills import _cell_desc  # reused view formatter (env-agnostic)
from multi_agent_box_push_env import MultiAgentBoxPushEnv
from box_push_env import GOAL_ZONE
from box_push_schema import BOX_PUSH_ENTITY_SCHEMA
from skill_executor_push import (
    make_skill, CooperativePushSkill, _nearest_undelivered_target,
)

from middleware_layer.middleware_orchestrator import MiddlewareOrchestrator
from model_layer.planner.centralized_dspy_planner import CentralizedDSPyPlanner

# ── Config ────────────────────────────────────────────────────────────────────
LLM_MODEL = "ollama_chat/gemma4:e4b"
LLM_BASE  = "http://localhost:11434"

_SKILL_DESCRIPTIONS = [
    "explore                — step toward unexplored cells until a box enters view        → [found_target, explored]",
    "goto_push_pose [bx,by] — move behind the target box at [bx,by] (side away from goal)  → [in_position, none_known, blocked]",
    "push [tx,ty]           — push the box in front cell-by-cell to [tx,ty] (goal cell)    → [pushed, delivered, too_heavy, blocked]",
    "cooperate_push [bx,by] — with the partner, jointly push the HEAVY box at [bx,by]       → [moved, delivered, waiting_partner, blocked]",
    "wait                   — stay in place this cycle                                     → [done]",
]

# Object metadata only (NO positions — POMDP discovery).
_PRIOR_OBJECTS: Dict[int, dict] = {
    0: dict(is_target=True, required_agents=2),   # heavy
    1: dict(is_target=True, required_agents=1),   # light
}

_AGENT_STARTS: Dict[str, Tuple[List[int], int]] = {
    "agent_0": ([10, 10], int(Directions.LEFT)),
    "agent_1": ([10,  9], int(Directions.LEFT)),
}

_PRIOR_KNOWLEDGE_TEMPLATE = """\
Grid: 12×12, open arena. x increases RIGHT, y increases DOWNWARD.
GOAL zone = the far-left column x=1 (green). Push the TARGET boxes onto it.
Two red TARGET boxes are somewhere on the grid; positions are UNKNOWN — EXPLORE to find
them. One target is LIGHT (one agent can push it); one is HEAVY (a lone push won't move
it — two agents must line up behind it and push together).
Belief grid: @ = you, D = goal, 0/1 = known targets, # = wall, . = empty, ? = unexplored.
"""

# ── View / grid helpers ─────────────────────────────────────────────────────────

_GOAL_SET = {tuple(c) for c in GOAL_ZONE}


def _grid_explored(grid_cells) -> int:
    return sum(1 for col in grid_cells for cell in col if cell != "unknown")


def _render_grid_ascii(grid_cells, self_pos) -> str:
    W = len(grid_cells)
    H = len(grid_cells[0]) if W > 0 else 0
    header = "   " + "".join(str(x % 10) for x in range(W))
    rows = [header]
    for y in range(H):
        row_chars = []
        for x in range(W):
            if [x, y] == list(self_pos):
                row_chars.append("@")
            else:
                cell = grid_cells[x][y]
                if cell == "unknown":            row_chars.append("?")
                elif cell == "empty":            row_chars.append(".")
                elif cell == "wall":             row_chars.append("#")
                elif cell == "delivery_zone":    row_chars.append("D")
                elif cell.startswith("target_"): row_chars.append(cell.split("_")[1] if cell.split("_")[1].isdigit() else "T")
                elif cell == "agent":            row_chars.append("A")
                else:                            row_chars.append("?")
        rows.append(f"{y:2d} " + "".join(row_chars))
    return "\n".join(rows)


def _interpret_reward(action, reward) -> str:
    if reward is None:
        return "unknown"
    if action == Actions.MOVE_FORWARD:
        if reward > 0.15:  return "JOINT PUSH ok"
        if reward > 0.05:  return "pushed/moved ok"
        if reward > -0.06: return "moved ok"
        return "BLOCKED / too heavy"
    return f"reward={reward:+.2f}"


def _target_cells(grid):
    return [(x, y) for x, col in enumerate(grid) for y, c in enumerate(col)
            if c.startswith("target")]


def summarize_box_obs(obs: dict, entities: dict, cycle: int = 0, recent_history=None) -> str:
    self_e     = entities.get("self", {})
    direction  = self_e.get("direction", 2)
    pos        = self_e.get("position", [0, 0])
    dir_name   = DIRECTION_NAMES.get(direction, str(direction))
    grid_cells = entities.get("grid", {}).get("cells", [])

    image     = obs.get("image")
    VIEW_SIZE = len(image) if image is not None else 3
    cells: dict = {}
    if image is not None:
        mid = VIEW_SIZE // 2
        for r in range(VIEW_SIZE):
            for c in range(VIEW_SIZE):
                ahead  = (VIEW_SIZE - 1) - c
                side_s = ("L" if (r - mid) < 0 else "R" if (r - mid) > 0 else "C")
                cells[f"{ahead}_{side_s}"] = _cell_desc(image[r][c])
    front = cells.get("1_C", "unknown")
    view_parts = []
    for ahead in range(VIEW_SIZE - 1, -1, -1):
        row = []
        for side_s in (["L", "C", "R"] if VIEW_SIZE >= 3 else ["C"]):
            v = cells.get(f"{ahead}_{side_s}", "?")
            row.append("[YOU]" if ahead == 0 and side_s == "C" else v)
        prefix = f"  {ahead} ahead:" if ahead > 0 else "  Your cell:"
        view_parts.append(f"{prefix} {' | '.join(row)}")

    last_outcome = "none yet"
    if recent_history:
        last = recent_history[-1]
        a, r = last.get("action"), last.get("reward")
        last_outcome = f"{ACTION_NAMES.get(a, str(a))} → {_interpret_reward(a, r)}"

    # Discovered boxes (POMDP); a target on the goal is delivered.
    targets = sorted(_target_cells(grid_cells), key=lambda c: abs(c[0]-pos[0])+abs(c[1]-pos[1]))
    obj_lines = []
    for (x, y) in targets:
        tag = "ON GOAL (delivered)" if (x, y) in _GOAL_SET else f"~{abs(x-pos[0])+abs(y-pos[1])} steps"
        obj_lines.append(f"  TARGET box at [{x}, {y}] ({tag})")
    if not obj_lines:
        obj_lines.append("  none discovered yet — EXPLORE to find boxes")

    near_goal = any(abs(pos[0]-gx)+abs(pos[1]-gy) <= 1 for gx, gy in _GOAL_SET)
    box_in_front = (front == "TARGET_OBJECT")
    front_blocked = (front == "WALL" or front.startswith("AGENT"))
    explored = _grid_explored(grid_cells) if grid_cells else 0
    grid_ascii = _render_grid_ascii(grid_cells, pos) if grid_cells else "(no grid)"

    lines = [
        f"CYCLE {cycle} | pos={pos} | facing={dir_name}",
        f"IN FRONT: {front}",
        f"box_in_front={box_in_front}",
        f"front_blocked={front_blocked}",
        f"near_goal={near_goal}",
        f"LAST PRIMITIVE: {last_outcome}",
        "",
        "BOX STATUS (discovered only):",
        *obj_lines,
        "",
        f"BELIEF GRID ({explored}/144 explored):",
        grid_ascii,
        "",
        "LOCAL VIEW (rows = steps ahead, cols = L|C|R):",
        *view_parts,
    ]
    return "\n".join(lines)


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


def get_scenario_description(agent_id: str) -> str:
    return """\
You are part of a 2-agent team in a Box-Push task on an open 12×12 grid.
A centralized commander sees both agents' states and assigns each a skill.
The GOAL is the far-left column (x=1). Push both red TARGET boxes onto it.
One target is light (one pusher); one is heavy (needs both agents pushing together).
Positions are unknown — explore to find the boxes.
"""


def get_goal_description(agent_id: str) -> str:
    return "Push both TARGET boxes onto the goal column. Cooperate on the heavy one."


# ── Planner configuration (passed as params to the reusable CentralizedDSPyPlanner) ──

_OBJECTIVE = "Find and push both red TARGET boxes onto the goal column (x=1)."

_DECISION_SPACE = """\
  explore                 — search for boxes (no arg)        → [found_target, explored]
  goto_push_pose [bx,by]  — get behind the TARGET box at [bx,by], on the side away from the
                            goal, facing it                    → [in_position, none_known, blocked]
  push [tx,ty]            — push the box in front cell-by-cell ALL THE WAY to [tx,ty]
                            (use the goal cell [1, by])         → [pushed, delivered, too_heavy, blocked]
  cooperate_push [bx,by]  — the two agents line up in TANDEM behind the HEAVY box at [bx,by]
                            and push it ALL THE WAY to the goal in one call (arranges both
                            agents)                            → [delivered, moved, waiting_partner, blocked]
  wait                    — do nothing                        → [done]
"""

_RULES = """\
You are the TEAM PLANNER for a 2-agent Box-Push task. Assign ONE skill to EACH agent per
cycle and react to each skill's return label ('LAST SKILL: name → label').

TASK: find and push TWO red TARGET boxes onto the goal column (x=1). Positions are UNKNOWN.
One target is LIGHT (one pusher moves it); one is HEAVY — a lone push won't move it; TWO
agents must line up directly behind it (one in front of the other) and push the same
direction together.

OUTPUT: each line is 'agent_id: skill_name [x,y]'. Include the [x,y] for
goto_push_pose / push / cooperate_push (choose it from the BOX STATUS list); omit it for
explore / wait. Example: 'agent_0: goto_push_pose [8,4]'.

DIVISION OF LABOR (critical — do NOT pile both agents on one box):
  - A LIGHT box needs only ONE agent. Assign goto_push_pose/push for it to ONE agent;
    send the OTHER agent to explore for the second box, or to handle a different known box.
  - Assign the SAME box to BOTH agents ONLY for the HEAVY box (cooperate_push).
  - Give each agent a DISTINCT [x,y] when they work separate boxes.
  - UNKNOWN-WEIGHT box (newly found, never pushed): send exactly ONE agent to
    goto_push_pose+push to TEST its weight; send the OTHER to explore or another box.
    Two agents CANNOT share one push pose — sending both to goto_push_pose just makes the
    second one block. Only bring both together (cooperate_push) AFTER push returns too_heavy.
    Do NOT pre-position both "just in case it is heavy".

COOPERATION RULES (heavy box — read carefully):
  - JOINT PUSH IS ALL-OR-NOTHING: to cooperate, assign cooperate_push [box] to BOTH agents
    in the SAME cycle. cooperate_push positions BOTH agents itself, so NEVER pair it with
    goto_push_pose / push / wait on the other agent — that strands a partner.
  - HEAVY IS STICKY: once a push of a box returns too_heavy, that box is HEAVY. From then on
    ONLY ever cooperate_push it — never push or goto_push_pose it again.
  - One cooperate_push call delivers the heavy box outright, so expect
    'cooperate_push → delivered' (not many 'moved' cycles).

PLANNING LOGIC (per agent, from its LAST SKILL label):
  - No target discovered            → explore
  - explore → found_target          → ONE agent goto_push_pose [box] (test its weight);
                                       the OTHER agent explores / handles a different box
  - goto_push_pose → in_position     → push [goal cell, e.g. [1, by]]
  - push → pushed                    → push [goal cell] again (continue toward the goal)
  - push → delivered                 → explore (find the other box) or handle another known box
  - push → too_heavy (it is HEAVY)   → BOTH agents cooperate_push [that box] (delivers in one cycle)
  - cooperate_push → moved           → BOTH agents cooperate_push [same box] again (only if interrupted)
  - cooperate_push → waiting_partner → BOTH agents cooperate_push [same box] (the partner was not also cooperating)
  - goto_push_pose → blocked         → another agent likely occupies the pose; send THIS agent
                                       to explore or to a different box instead of retrying
  - explore → explored (nothing)     → explore again
NEVER assign 'wait' while a target box is undelivered. You share ONE map: once either agent
sees a box, both know it — use the [x,y] from BOX STATUS to direct each agent.
"""


# ── Parser ────────────────────────────────────────────────────────────────────

_VALID_SKILLS = {"explore", "goto_push_pose", "push", "cooperate_push", "wait"}


def _skill_parser(agent_id: str, raw: str) -> Tuple[str, Optional[Tuple[int, int]]]:
    """One agent's decision text (e.g. 'goto_push_pose [8,4]') → (skill_name, (x,y)|None).
    Passed to CentralizedDSPyPlanner.decide(); unknown/garbage → ('explore', None)."""
    m = re.match(r'\s*([a-zA-Z_]+)(.*)', raw or "")
    if m and m.group(1) in _VALID_SKILLS:
        arg = None
        c = re.search(r'\[?\(?\s*(\d+)\s*,\s*(\d+)\s*\)?\]?', m.group(2))
        if c:
            arg = (int(c.group(1)), int(c.group(2)))
        return (m.group(1), arg)
    print(f"  [WARN] unparseable skill '{raw}' for {agent_id}, defaulting to explore")
    return ("explore", None)


# ── Main loop ──────────────────────────────────────────────────────────────────

def main():
    log_path = os.path.join(_THIS_DIR, "box_push_centralized_log.txt")
    print(f"Logging to {log_path}")

    lm = dspy.LM(model=LLM_MODEL, api_base=LLM_BASE, api_key="ollama", cache=False)
    planner = CentralizedDSPyPlanner(name="box_push_centralized")
    planner.configure_ollama(lm)

    config = EnvConfig(width=12, height=12, num_agents=2, num_objects=2,
                       num_target_objects=2, max_steps=600, agent_view_size=3,
                       render_mode="human", seed=42)
    env = MultiAgentBoxPushEnv(config=config)
    observations, _ = env.reset(seed=42)

    print("\n" + "=" * 70)
    print("BOX PUSH  —  CENTRALIZED LLM (granular skills, shared map)")
    print("=" * 70)

    middlewares: Dict[str, MiddlewareOrchestrator] = {}
    for agent_id in env.agents:
        mw = MiddlewareOrchestrator(
            env=env, agent_id=agent_id, LLM_model=lm,
            scenario_description=get_scenario_description(agent_id),
            goal_description=get_goal_description(agent_id),
            action_space=_SKILL_DESCRIPTIONS,
            environment_name="BoxPush",
            observation_spec="Partial 3×3 local view + belief state",
            entity_schema=BOX_PUSH_ENTITY_SCHEMA,
            initial_entities=_build_initial_entities(agent_id),
            obs_parser_fn=parse_cst_obs,
            prior_knowledge=_PRIOR_KNOWLEDGE_TEMPLATE,
            history_window=6,
            belief_updater_kwargs={"grid_width": 12, "grid_height": 12},
        )
        middlewares[agent_id] = mw
        print(f"[init] middleware ready for {agent_id}")

    # Shared world map (centralized — both agents read/write one belief grid).
    shared_grid: List[List[str]] = [["unknown"] * 12 for _ in range(12)]
    for cx, cy in GOAL_ZONE:
        shared_grid[cx][cy] = "delivery_zone"
    for agent_id in env.agents:
        updater = middlewares[agent_id].belief_manager.updater
        updater._grid = shared_grid
        updater._entities["grid"] = {"cells": [list(c) for c in shared_grid]}
    print("[init] shared belief map wired across agents")

    env.render()
    time.sleep(0.5)

    with open(log_path, "w", buffering=1) as log_f:
        def log(msg):
            print(msg)
            log_f.write(msg + "\n")

        last_skill_info: Dict[str, Tuple[str, str]] = {}
        skill_cycle = 0
        episode_done = False

        while env.agents and not episode_done:
            skill_cycle += 1
            log(f"\n{'='*70}\nSKILL CYCLE {skill_cycle}  |  agents: {list(env.agents)}\n{'='*70}")

            sections = []
            entities_cache: Dict[str, dict] = {}
            for agent_id in env.agents:
                entities = middlewares[agent_id].belief_manager.updater.get_all_entities()
                entities_cache[agent_id] = entities
                summary = summarize_box_obs(observations[agent_id], entities, skill_cycle,
                                            recent_history=middlewares[agent_id].belief_manager.history_as_json)
                last_str = ""
                if agent_id in last_skill_info:
                    n, l = last_skill_info[agent_id]
                    last_str = f"LAST SKILL: {n} → {l}\n"
                sections.append(f"=== {agent_id} ===\n{last_str}{summary}")
            team_situation = "\n\n".join(sections)
            log(f"\n[TEAM SITUATION]\n{team_situation}")

            feedback = "  ".join(
                f"{aid}: {last_skill_info[aid][0]} → {last_skill_info[aid][1]}"
                for aid in env.agents if aid in last_skill_info) or "none yet"
            reasoning, decided = planner.decide(
                task_instructions=_RULES, decision_space=_DECISION_SPACE,
                team_situation=team_situation, objective=_OBJECTIVE,
                agents=list(env.agents), recent_feedback=feedback, parser=_skill_parser)
            skill_calls = {aid: decided.get(aid, ("explore", None)) for aid in env.agents}
            log(f"\n[COORDINATION PLAN] {reasoning}")
            log("[SKILLS] " + "  ".join(
                f"{a}={s}" + (f"{list(arg)}" if arg else "")
                for a, (s, arg) in sorted(skill_calls.items())))

            agent_list = list(env.agents)
            active_skills = {}
            for agent_id in agent_list:
                sname, arg = skill_calls[agent_id]
                partner_id = next((a for a in agent_list if a != agent_id), None)
                active_skills[agent_id] = make_skill(agent_id, sname, arg, partner_id=partner_id)

            logged_done: set = set()
            for agent_id in agent_list:
                if active_skills[agent_id].is_done:
                    logged_done.add(agent_id)
                    log(f"[SKILL DONE] {agent_id}: {skill_calls[agent_id][0]} → {active_skills[agent_id].label}")

            while True:
                if all(active_skills[aid].is_done for aid in env.agents):
                    break
                primitive_actions: Dict[str, int] = {}
                for agent_id in env.agents:
                    skill = active_skills[agent_id]
                    if skill.is_done:
                        primitive_actions[agent_id] = int(Actions.STAY)
                    elif isinstance(skill, CooperativePushSkill):
                        p_id = skill.partner_id
                        primitive_actions[agent_id] = skill.step(
                            observations[agent_id], entities_cache[agent_id],
                            entities_cache.get(p_id, {}))
                    else:
                        primitive_actions[agent_id] = skill.step(
                            observations[agent_id], entities_cache[agent_id])
                    if skill.is_done and agent_id not in logged_done:
                        logged_done.add(agent_id)
                        log(f"[SKILL DONE] {agent_id}: {skill_calls[agent_id][0]} → {skill.label}")

                observations, rewards, terminations, truncations, _ = env.step(primitive_actions)
                env.render()
                log("[REWARDS] " + "  ".join(f"{a}={rewards[a]:+.2f}" for a in sorted(rewards)))

                for agent_id in sorted(primitive_actions):
                    if agent_id in middlewares:
                        middlewares[agent_id].update_belief(
                            primitive_actions[agent_id], rewards.get(agent_id, -0.01),
                            observations.get(agent_id, {}))
                entities_cache = {aid: middlewares[aid].belief_manager.updater.get_all_entities()
                                  for aid in env.agents if aid in middlewares}

                if all(terminations.values()):
                    log("\n SUCCESS — all target boxes delivered!")
                    episode_done = True
                    break
                if all(truncations.values()):
                    log("\n Episode truncated (max steps reached)")
                    episode_done = True
                    break
                time.sleep(0.05)

            for agent_id in list(env.agents):
                sk = active_skills.get(agent_id)
                if sk:
                    last_skill_info[agent_id] = (skill_calls[agent_id][0], sk.label or "in_progress")

    env.close()
    print("\nEpisode finished.")


if __name__ == "__main__":
    main()
