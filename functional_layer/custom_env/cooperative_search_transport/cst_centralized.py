"""
CST driven by a SINGLE centralized LLM that sees BOTH agents' full states
and selects GRANULAR single-purpose SKILLS for BOTH in one call per skill cycle.

Architecture (true POMDP):
  - Outer loop: LLM assigns ONE specific skill to each agent; reacts to its return label.
  - Inner loop: skill executor runs primitive env steps until each skill completes.
  - Beliefs are updated after EVERY primitive step.
  - Object positions are NOT known in advance — discovered via the 3×3 view.

Skills (single-purpose):
  explore         -> found_target | found_decoy | explored
  goto_target     -> at_target | none_known | blocked
  goto_delivery   -> at_delivery | blocked
  pick            -> picked_solo | latched_coop | failed
  drop            -> delivered | dropped | nothing
  cooperate_move  -> moved | waiting_partner | arrived
  wait            -> done

Run from this directory:
    cd functional_layer/custom_env/cooperative_search_transport/env
    python cst_centralized.py
"""

import sys
import os
import re
import time
from typing import Dict, List, Optional, Tuple

_ENV_DIR   = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_ENV_DIR, "../../../.."))
sys.path.insert(0, _ENV_DIR)
sys.path.insert(0, _REPO_ROOT)

import dspy
from constants import Actions, Directions, DIRECTION_NAMES, ACTION_NAMES
from state import EnvConfig
from multi_agent_env import MultiAgentCooperativeSearchTransportEnv
from entity_schema import CST_ENTITY_SCHEMA
from obs_parser import parse_cst_obs
from skill_executor import (
    _cell_desc, _manhattan, _nearest_target_cell, _target_cells, _decoy_cells,
    _DELIVERY_ZONE,
    CooperativeMoveSkill, make_skill,
)

from middleware_layer.middleware_orchestrator import MiddlewareOrchestrator

# ── Config ────────────────────────────────────────────────────────────────────
LLM_MODEL = "ollama_chat/gemma4:e4b"
LLM_BASE  = "http://localhost:11434"

_SKILL_DESCRIPTIONS = [
    "explore        — step toward unexplored cells until an object enters view   → [found_target, found_decoy, explored]",
    "goto_target    — navigate to the nearest DISCOVERED target box              → [at_target, none_known, blocked]",
    "goto_delivery  — navigate to the delivery zone                              → [at_delivery, blocked]",
    "pick           — PICK_OR_INTERACT the box directly in front                 → [picked_solo, latched_coop, failed]",
    "drop           — DROP the held object (delivers if on the zone)             → [delivered, dropped, nothing]",
    "cooperate_move — jointly carry a latched object one leg toward delivery     → [moved, waiting_partner, arrived]",
    "wait           — stay in place this cycle                                   → [done]",
]

# ── Prior knowledge ────────────────────────────────────────────────────────────

_PRIOR_OBJECTS: Dict[int, dict] = {
    0: dict(is_target=True,  required_agents=2, init_pos=[2, 9]),
    1: dict(is_target=True,  required_agents=1, init_pos=[6, 5]),
    2: dict(is_target=False, required_agents=1, init_pos=[9, 2]),
    3: dict(is_target=False, required_agents=1, init_pos=[10, 4]),
}

_AGENT_STARTS: Dict[str, Tuple[List[int], int]] = {
    "agent_0": ([10, 10], int(Directions.LEFT)),
    "agent_1": ([10,  9], int(Directions.LEFT)),
}

_PRIOR_KNOWLEDGE_TEMPLATE = """\
Grid: 12×12. x increases RIGHT, y increases DOWNWARD (UP = y-1, DOWN = y+1).
Delivery zone (far left): (1,1) (2,1) (1,2) (2,2).
Somewhere on the grid are red TARGET boxes and blue DECOY boxes. Their positions are
UNKNOWN — you must EXPLORE to find them. One target can be carried solo; one target
needs BOTH agents (it will only latch, not lift, when one agent picks it).
Walls divide the grid into rooms; gap positions are unknown — discover by exploring.
Belief grid: @ = you, D = delivery zone, 0/1 = known targets, d = decoy, # = wall,
. = empty, ? = unexplored.
"""

# ── Observation helpers ────────────────────────────────────────────────────────

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
                if cell == "unknown":              row_chars.append("?")
                elif cell == "empty":              row_chars.append(".")
                elif cell == "wall":               row_chars.append("#")
                elif cell == "delivery_zone":      row_chars.append("D")
                elif cell.startswith("target_"):   row_chars.append(cell.split("_")[1])
                elif cell.startswith("decoy_"):    row_chars.append("d")
                elif cell == "agent":              row_chars.append("A")
                else:                              row_chars.append("?")
        rows.append(f"{y:2d} " + "".join(row_chars))
    return "\n".join(rows)


def _interpret_reward(action, reward) -> str:
    if reward is None:
        return "unknown"
    if action == Actions.MOVE_FORWARD:
        return "moved OK" if reward > -0.06 else "BLOCKED — did not move"
    if action == Actions.PICK_OR_INTERACT:
        return "pickup/latch succeeded" if reward > 0 else "pickup failed"
    if action == Actions.DROP:
        return "delivered!" if reward > 0.5 else "dropped/disengaged"
    return f"reward={reward:+.2f}"


def summarize_cst_obs(obs: dict, entities: dict, cycle: int = 0,
                      recent_history=None) -> str:
    self_e     = entities.get("self", {})
    direction  = self_e.get("direction", 2)
    carrying   = self_e.get("carrying_object_id")
    engaged    = self_e.get("engaged_object_ids", [])
    delivered  = self_e.get("delivered_object_ids", [])
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
                side   = r - mid
                label  = _cell_desc(image[r][c])
                side_s = ("L" if side < 0 else "R" if side > 0 else "C")
                cells[f"{ahead}_{side_s}"] = label

    front = cells.get("1_C", "unknown")
    view_parts = []
    for ahead in range(VIEW_SIZE - 1, -1, -1):
        row = []
        for side_s in (["L", "C", "R"] if VIEW_SIZE >= 3 else ["C"]):
            k = f"{ahead}_{side_s}"
            v = cells.get(k, "?")
            tag = "[YOU]" if ahead == 0 and side_s == "C" else v
            row.append(tag)
        prefix = f"  {ahead} step{'s' if ahead != 1 else ''} ahead:" if ahead > 0 else "  Your cell:"
        view_parts.append(f"{prefix} {' | '.join(row)}")

    last_outcome = "none yet"
    if recent_history:
        last = recent_history[-1]
        a, r = last.get("action"), last.get("reward")
        name = ACTION_NAMES.get(a, str(a))
        last_outcome = f"{name} → {_interpret_reward(a, r)}"

    if carrying is not None:
        inv = f"carrying a TARGET (solo) — go to delivery zone and drop"
    elif engaged:
        inv = "LATCHED onto a cooperative target — needs partner to latch too, then cooperate_move"
    else:
        inv = "empty hands"

    # Discovered objects only (POMDP): scan the belief grid for seen boxes.
    targets = sorted(_target_cells(grid_cells), key=lambda c: _manhattan(pos, list(c)))
    decoys  = sorted(_decoy_cells(grid_cells),  key=lambda c: _manhattan(pos, list(c)))
    obj_lines = []
    if delivered:
        obj_lines.append(f"  DELIVERED targets: {len(delivered)}")
    if carrying is not None:
        obj_lines.append("  You are CARRYING a target (solo).")
    if engaged:
        obj_lines.append("  You are LATCHED on a cooperative target.")
    for (x, y) in targets:
        obj_lines.append(f"  TARGET seen at [{x}, {y}] (~{_manhattan(pos, [x, y])} steps)")
    for (x, y) in decoys:
        obj_lines.append(f"  decoy seen at [{x}, {y}] (ignore)")
    if not obj_lines:
        obj_lines.append("  none discovered yet — EXPLORE to find targets")

    on_delivery_zone = list(pos) in [list(c) for c in _DELIVERY_ZONE]
    front_blocked    = (front == "WALL" or front.startswith("AGENT"))
    target_in_front  = (front == "TARGET_OBJECT")

    explored   = _grid_explored(grid_cells) if grid_cells else 0
    grid_ascii = _render_grid_ascii(grid_cells, pos) if grid_cells else "(no grid)"

    room = "LEFT" if pos[0] < 4 else "MIDDLE" if pos[0] < 8 else "RIGHT"
    lines = [
        f"CYCLE {cycle} | pos={pos} | facing={dir_name} | room={room}",
        f"IN FRONT: {front}",
        f"front_blocked={front_blocked}",
        f"target_in_front={target_in_front}",
        f"on_delivery_zone={on_delivery_zone}",
        f"INVENTORY: {inv}",
        f"LAST PRIMITIVE: {last_outcome}",
        "",
        "OBJECT STATUS:",
        *obj_lines,
        "",
        f"BELIEF GRID ({explored}/144 cells explored):",
        grid_ascii,
        "",
        "LOCAL VIEW (rows = steps ahead, cols = left|center|right):",
        *view_parts,
    ]
    return "\n".join(lines)


def _build_initial_entities(agent_id: str) -> dict:
    start_pos, start_dir = _AGENT_STARTS[agent_id]
    # True POMDP: only the delivery zone is known. Object positions stay "unknown"
    # until discovered through the agent's 3×3 view.
    grid: List[List[str]] = [["unknown"] * 12 for _ in range(12)]
    for cx, cy in _DELIVERY_ZONE:
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
You are part of a 2-agent team in a Cooperative Search and Transport task on a 12×12 grid.
Your decisions are made by a centralized commander who sees both agents' states.
The delivery zone is at the far left: (1,1)-(2,2).
Two TARGET boxes are hidden on the grid: one is carry-solo, one needs BOTH agents.
You do NOT know where they are — explore to find them, then deliver both.
"""


def get_goal_description(agent_id: str) -> str:
    return "Deliver both TARGET objects to the delivery zone. Cooperate."


# ── DSPy centralized signature ────────────────────────────────────────────────

class CentralizedCSTPlan(dspy.Signature):
    """
    You are the TEAM PLANNER for a 2-agent Cooperative Search and Transport task.
    You see BOTH agents' full states and assign ONE specific SKILL to EACH agent per cycle.
    React to each skill's return label (shown as 'LAST SKILL: name → label').

    TEAM TASK: find and deliver TWO hidden TARGET boxes to the delivery zone.
    Positions are UNKNOWN — agents must explore. One target is carry-solo; the other
    needs BOTH agents (a single pick only LATCHES it; it cannot be lifted alone).

    AVAILABLE SKILLS (assign by name, no arguments):
      explore        — search for objects                → [found_target, found_decoy, explored]
      goto_target    — walk to nearest seen target       → [at_target, none_known, blocked]
      goto_delivery  — walk to the delivery zone         → [at_delivery, blocked]
      pick           — interact with the box in front    → [picked_solo, latched_coop, failed]
      drop           — drop / deliver the held object    → [delivered, dropped, nothing]
      cooperate_move — joint-carry a latched target      → [moved, waiting_partner, arrived]
      wait           — do nothing this cycle             → [done]

    OUTPUT FORMAT — exactly two lines:
      agent_0: skill_name
      agent_1: skill_name

    PLANNING LOGIC — pick each agent's next skill from its LAST SKILL label:
      - No target known yet           → explore
      - explore → found_target        → goto_target
      - goto_target → at_target       → pick
      - pick → picked_solo (it was the SOLO target) → goto_delivery
      - goto_delivery → at_delivery   → drop
      - pick → latched_coop (it was the COOP target) → that agent should wait;
        send the OTHER agent to explore/goto_target/pick the SAME box to latch it too.
      - When BOTH agents show latched_coop → assign cooperate_move to BOTH, repeat
        cooperate_move each cycle until 'arrived' (the coop target auto-delivers).
      - explore → explored (nothing found) → explore again (keep searching).
    PARALLELISM — keep BOTH agents busy until BOTH targets are delivered:
      - NEVER assign 'wait' to an agent just because it finished a task. An idle agent
        wastes the episode. If the coop target is not found yet, an empty-handed agent
        must 'explore' (two searchers find it faster).
      - Only use 'wait' for an agent that has ALREADY latched the coop target and is
        holding it while the partner travels to latch too.
      - You share ONE map: once either agent discovers the coop target, BOTH can
        'goto_target' to it.
    """
    team_situation: str = dspy.InputField(
        desc="Both agents' observation summaries including position, inventory, belief grid, last skill result"
    )
    coordination_plan: str = dspy.OutputField(
        desc="1-2 sentences: what each agent should do this skill cycle and why"
    )
    skills: str = dspy.OutputField(
        desc="Exactly two lines: 'agent_0: skill_name' and 'agent_1: skill_name'"
    )


# ── Skill parser ───────────────────────────────────────────────────────────────

_VALID_SKILLS = {
    "explore", "goto_target", "goto_delivery", "pick", "drop", "cooperate_move", "wait",
}


def parse_team_skills(
    response: str, active_agents: list
) -> Dict[str, Tuple[str, Optional[str]]]:
    """Return {agent_id: (skill_name, arg_or_None)}. Falls back to ("wait", None)."""
    result = {}
    for agent_id in active_agents:
        m = re.search(
            rf'{re.escape(agent_id)}\s*[=:]\s*(\w+)(?:\((\d+)\))?',
            response,
        )
        if m:
            skill_name = m.group(1)
            arg        = m.group(2)
            if skill_name not in _VALID_SKILLS:
                print(f"  [WARN] unknown skill '{skill_name}' for {agent_id}, defaulting to wait")
                skill_name, arg = "wait", None
            result[agent_id] = (skill_name, arg)
        else:
            result[agent_id] = ("wait", None)
            print(f"  [WARN] could not parse skill for {agent_id}, defaulting to wait")
    return result


# ── Main loop ──────────────────────────────────────────────────────────────────

def main():
    log_path = os.path.join(_ENV_DIR, "cst_centralized_log.txt")
    print(f"Logging to {log_path}")

    lm = dspy.LM(model=LLM_MODEL, api_base=LLM_BASE, api_key="ollama", cache=False)
    dspy.configure(lm=lm)

    planner = dspy.ChainOfThought(CentralizedCSTPlan)

    config = EnvConfig(
        width=12, height=12,
        num_agents=2, num_objects=4, num_target_objects=2,
        max_steps=500, agent_view_size=3,
        render_mode="human", seed=42,
    )

    env = MultiAgentCooperativeSearchTransportEnv(config=config)
    observations, _ = env.reset(seed=42)

    print("\n" + "=" * 70)
    print("COOPERATIVE SEARCH & TRANSPORT  —  CENTRALIZED LLM (skill-based)")
    print("=" * 70)

    middlewares: Dict[str, MiddlewareOrchestrator] = {}

    for agent_id in env.agents:
        initial_ents = _build_initial_entities(agent_id)
        mw = MiddlewareOrchestrator(
            env=env,
            agent_id=agent_id,
            LLM_model=lm,
            scenario_description=get_scenario_description(agent_id),
            goal_description=get_goal_description(agent_id),
            action_space=_SKILL_DESCRIPTIONS,
            environment_name="CooperativeSearchTransport",
            observation_spec="Partial 3×3 local view + belief state",
            entity_schema=CST_ENTITY_SCHEMA,
            initial_entities=initial_ents,
            obs_parser_fn=parse_cst_obs,
            prior_knowledge=_PRIOR_KNOWLEDGE_TEMPLATE,
            history_window=6,
            belief_updater_kwargs={"grid_width": 12, "grid_height": 12},
        )
        middlewares[agent_id] = mw
        print(f"[init] middleware ready for {agent_id}")

    # ── Shared world map ──────────────────────────────────────────────────────
    # This is a CENTRALIZED controller: the commander legitimately sees BOTH agents'
    # observations, so they share ONE belief map (walls / discovered objects / explored
    # cells). Whatever one agent observes, the other immediately knows. Only self-state
    # (position, direction, inventory) stays per-agent. The map still obeys POMDP: it
    # contains only what SOME agent has actually seen — nothing is pre-seeded.
    shared_grid: List[List[str]] = [["unknown"] * 12 for _ in range(12)]
    for cx, cy in _DELIVERY_ZONE:
        shared_grid[cx][cy] = "delivery_zone"
    for agent_id in env.agents:
        updater = middlewares[agent_id].belief_manager.updater
        updater._grid = shared_grid  # same object reference → writes are shared
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

        # ── Outer loop (one LLM call per skill cycle) ─────────────────────────
        while env.agents and not episode_done:
            skill_cycle += 1
            log(f"\n{'='*70}")
            log(f"SKILL CYCLE {skill_cycle}  |  agents: {list(env.agents)}")
            log(f"{'='*70}")

            # Build combined team situation
            sections = []
            entities_cache: Dict[str, dict] = {}
            for agent_id in env.agents:
                mw       = middlewares[agent_id]
                entities = mw.belief_manager.updater.get_all_entities()
                entities_cache[agent_id] = entities
                summary  = summarize_cst_obs(
                    observations[agent_id], entities, skill_cycle,
                    recent_history=mw.belief_manager.history_as_json,
                )
                last_skill_str = ""
                if agent_id in last_skill_info:
                    sname, slabel = last_skill_info[agent_id]
                    last_skill_str = f"LAST SKILL: {sname} → {slabel}\n"
                sections.append(f"=== {agent_id} ===\n{last_skill_str}{summary}")

            team_situation = "\n\n".join(sections)
            log(f"\n[TEAM SITUATION]\n{team_situation}")

            # Single LLM call
            result = planner(team_situation=team_situation)
            log(f"\n[COORDINATION PLAN] {result.coordination_plan}")
            log(f"[SKILLS RAW]\n{result.skills}")

            skill_calls_map = parse_team_skills(result.skills, list(env.agents))
            skill_str = "  ".join(
                f"{aid}={sname}({arg})" if arg else f"{aid}={sname}"
                for aid, (sname, arg) in sorted(skill_calls_map.items())
            )
            log(f"[SKILLS] {skill_str}")

            # Create skill instances
            agent_list   = list(env.agents)
            active_skills = {}
            for agent_id in agent_list:
                sname, arg = skill_calls_map[agent_id]
                partner_id = next((a for a in agent_list if a != agent_id), None)
                active_skills[agent_id] = make_skill(agent_id, sname, arg,
                                                     partner_id=partner_id)

            # Log immediately-done skills (WaitSkill)
            logged_done: set = set()
            for agent_id in agent_list:
                skill = active_skills[agent_id]
                if skill.is_done:
                    logged_done.add(agent_id)
                    log(f"[SKILL DONE] {agent_id}: {skill_calls_map[agent_id][0]} → {skill.label}")

            # ── Inner loop (primitive env steps) ──────────────────────────────
            while True:
                if all(active_skills[aid].is_done for aid in env.agents):
                    break

                primitive_actions: Dict[str, int] = {}
                for agent_id in env.agents:
                    skill = active_skills[agent_id]
                    if skill.is_done:
                        primitive_actions[agent_id] = int(Actions.STAY)
                    elif isinstance(skill, CooperativeMoveSkill):
                        p_id   = skill.partner_id
                        p_ents = entities_cache.get(p_id, {})
                        primitive_actions[agent_id] = skill.step(
                            observations[agent_id], entities_cache[agent_id], p_ents
                        )
                    else:
                        primitive_actions[agent_id] = skill.step(
                            observations[agent_id], entities_cache[agent_id]
                        )

                    if skill.is_done and agent_id not in logged_done:
                        logged_done.add(agent_id)
                        log(f"[SKILL DONE] {agent_id}: {skill_calls_map[agent_id][0]} → {skill.label}")

                observations, rewards, terminations, truncations, _ = env.step(primitive_actions)
                env.render()

                rew_str = "  ".join(f"{aid}={rewards[aid]:+.2f}" for aid in sorted(rewards))
                log(f"[REWARDS] {rew_str}")

                # Update beliefs and entities cache after every primitive step
                for agent_id in sorted(primitive_actions):
                    if agent_id in middlewares:
                        middlewares[agent_id].update_belief(
                            primitive_actions[agent_id],
                            rewards.get(agent_id, -0.01),
                            observations.get(agent_id, {}),
                        )

                entities_cache = {
                    aid: middlewares[aid].belief_manager.updater.get_all_entities()
                    for aid in env.agents
                    if aid in middlewares
                }

                if all(terminations.values()):
                    log("\n SUCCESS — all targets delivered!")
                    episode_done = True
                    break
                if all(truncations.values()):
                    log("\n Episode truncated (max steps reached)")
                    episode_done = True
                    break

                time.sleep(0.05)

            # Record last skill result for next cycle's team situation
            for agent_id in list(env.agents):
                skill = active_skills.get(agent_id)
                if skill:
                    last_skill_info[agent_id] = (
                        skill_calls_map[agent_id][0],
                        skill.label or "in_progress",
                    )

    env.close()
    print("\nEpisode finished.")


if __name__ == "__main__":
    main()
