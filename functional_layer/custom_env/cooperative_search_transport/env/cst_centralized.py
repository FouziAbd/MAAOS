"""
CST driven by a SINGLE centralized LLM that sees BOTH agents' full states
and returns BOTH agents' actions in one call per step.

Unlike cst_llm_demo.py (one LLM call per agent), the centralized controller can:
  - Assign: "agent_0 picks up obj_1 solo; agent_1 head to obj_0 and wait"
  - Coordinate cooperative carry: "both face obj_0 and PICK_OR_INTERACT together"
  - Synchronize delivery: "both MOVE_FORWARD toward delivery zone in sync"

Each agent still has its own belief system (grid tracking, position dead-reckoning).
Only the action decision step is centralized.

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
from constants import Actions, Directions, DIRECTION_VECTORS, ACTION_NAMES, DIRECTION_NAMES
from state import EnvConfig
from multi_agent_env import MultiAgentCooperativeSearchTransportEnv
from entity_schema import CST_ENTITY_SCHEMA
from obs_parser import parse_cst_obs

from middleware_layer.middleware_orchestrator import MiddlewareOrchestrator

# ── Config ────────────────────────────────────────────────────────────────────
LLM_MODEL = "ollama_chat/gemma4:e4b"
LLM_BASE  = "http://localhost:11434"

ACTIONS_DETAILS = [
    "0 (TURN_LEFT): Rotate 90° to the left in place",
    "1 (TURN_RIGHT): Rotate 90° to the right in place",
    "2 (MOVE_FORWARD): Move one step forward in the direction you are currently facing",
    "3 (STAY): Stay in place, do nothing",
    "4 (PICK_OR_INTERACT): Use ONLY when a TARGET object is DIRECTLY IN FRONT of you",
    "5 (DROP): Drop carried object; if on delivery zone, delivers it",
    "6 (COOPERATE): Hold cooperative grip while waiting for partner to reposition",
]

_ACTION_SHORT = {
    0: "TURN_LEFT", 1: "TURN_RIGHT", 2: "MOVE_FORWARD",
    3: "STAY", 4: "PICK_OR_INTERACT", 5: "DROP", 6: "COOPERATE",
}

# ── Prior knowledge (shared with cst_llm_demo.py) ─────────────────────────────

_PRIOR_OBJECTS: Dict[int, dict] = {
    0: dict(is_target=True,  required_agents=2, init_pos=[2, 9]),
    1: dict(is_target=True,  required_agents=1, init_pos=[6, 5]),
    2: dict(is_target=False, required_agents=1, init_pos=[9, 2]),
    3: dict(is_target=False, required_agents=1, init_pos=[10, 4]),
}

_DELIVERY_ZONE: List[List[int]] = [[1, 1], [2, 1], [1, 2], [2, 2]]

_AGENT_STARTS: Dict[str, Tuple[List[int], int]] = {
    "agent_0": ([10, 10], int(Directions.LEFT)),
    "agent_1": ([10,  9], int(Directions.LEFT)),
}

_PRIOR_KNOWLEDGE_TEMPLATE = """\
Grid: 12×12. x increases RIGHT, y increases DOWNWARD (UP = y-1, DOWN = y+1).
Delivery zone (far left): (1,1) (2,1) (1,2) (2,2).
Object locations at episode start:
  obj_0: TARGET at [2, 9] — requires 2 agents (cooperative carry)
  obj_1: TARGET at [6, 5] — requires 1 agent (solo carry)
  obj_2: DECOY  at [9, 2] — ignore
  obj_3: DECOY  at [10, 4] — ignore
Agent starting positions: agent_0 at [10,10] facing LEFT, agent_1 at [10,9] facing LEFT.
Walls divide the grid into rooms. Wall gap positions are unknown — discover by exploring.
Belief grid: @ = you, D = delivery zone, 0/1 = targets, d = decoy, # = wall, . = empty, ? = unexplored.
"""

# ── Observation helpers (copied from cst_llm_demo.py) ─────────────────────────

_OBJ_TYPE_IDX = {
    0: "unseen", 1: "empty",  2: "wall", 3: "floor", 4: "door",
    5: "key",    6: "ball",   7: "box",  8: "goal",  9: "lava",  10: "agent",
}
_COLOR_IDX = {0: "red", 1: "green", 2: "blue", 3: "purple", 4: "yellow", 5: "grey"}
_DIR_NAMES  = {0: "RIGHT", 1: "DOWN", 2: "LEFT", 3: "UP"}


def _cell_desc(cell) -> str:
    t, c = int(cell[0]), int(cell[1])
    if t == 0: return "unseen"
    if t == 1: return "empty"
    if t == 2: return "WALL"
    if t == 3 and c == 1: return "DELIVERY_ZONE"
    if t == 3: return "floor"
    if t == 7 and c == 0: return "TARGET_OBJECT"
    if t == 7 and c == 2: return "DECOY_OBJECT"
    if t == 10: return f"AGENT({_COLOR_IDX.get(c, '?')})"
    return f"{_OBJ_TYPE_IDX.get(t,'?')}({_COLOR_IDX.get(c,'?')})"


def _manhattan(a, b) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _smart_nav_hint(pos, direction: int, goal_pos, grid_cells) -> Tuple[int, str]:
    dx, dy = goal_pos[0] - pos[0], goal_pos[1] - pos[1]
    if dx == 0 and dy == 0:
        return 3, "already at goal"
    if abs(dx) >= abs(dy) and dx != 0:
        primary   = 0 if dx > 0 else 2
        secondary = 1 if dy >= 0 else 3
    else:
        primary   = 1 if dy > 0 else 3
        secondary = 0 if dx >= 0 else 2

    def next_cell_is_wall(d):
        dvec = DIRECTION_VECTORS[d]
        nx, ny = pos[0] + dvec[0], pos[1] + dvec[1]
        if grid_cells and 0 <= nx < len(grid_cells) and 0 <= ny < len(grid_cells[0]):
            return grid_cells[nx][ny] == "wall"
        return False

    primary_wall   = next_cell_is_wall(primary)
    secondary_wall = next_cell_is_wall(secondary)

    if primary_wall and not secondary_wall:
        wanted = secondary
        note   = f"wall blocks {_DIR_NAMES[primary]} — go {_DIR_NAMES[secondary]} to find gap"
    elif primary_wall and secondary_wall:
        wanted = (primary + 2) % 4
        note   = "both forward blocked — turning back"
    else:
        wanted = primary
        note   = f"clear {_DIR_NAMES[primary]}"

    if direction == wanted:
        action = 2
    elif (direction + 1) % 4 == wanted:
        action = 1
    elif (direction - 1) % 4 == wanted:
        action = 0
    else:
        action = 1
    return action, note


def _obj_grid_pos(grid_cells, oid: int, is_target: bool) -> Optional[List[int]]:
    kind = "target" if is_target else "decoy"
    lbl  = f"{kind}_{oid}"
    for x, col in enumerate(grid_cells):
        for y, cell in enumerate(col):
            if cell == lbl:
                return [x, y]
    return None


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
                if cell == "unknown":         row_chars.append("?")
                elif cell == "empty":         row_chars.append(".")
                elif cell == "wall":          row_chars.append("#")
                elif cell == "delivery_zone": row_chars.append("D")
                elif cell.startswith("target_"): row_chars.append(cell.split("_")[1])
                elif cell.startswith("decoy_"):  row_chars.append("d")
                elif cell == "agent":             row_chars.append("A")
                else:                             row_chars.append("?")
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


def summarize_cst_obs(obs: dict, entities: dict, step: int = 0,
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
        name = _ACTION_SHORT.get(a, str(a))
        last_outcome = f"{name} → {_interpret_reward(a, r)}"

    if carrying is not None:
        obj_e = entities.get(f"object_{carrying}", {})
        inv = f"carrying obj_{carrying} ({'TARGET' if obj_e.get('is_target') else 'DECOY'})"
    elif engaged:
        obj_e_eng = entities.get(f"object_{engaged[0]}", {})
        req_eng   = obj_e_eng.get("required_agents", 1)
        gpos_eng  = _obj_grid_pos(grid_cells, engaged[0], obj_e_eng.get("is_target", True))
        if req_eng > 1 and gpos_eng is not None:
            inv = (f"PARTIAL LATCH on obj_{engaged[0]} at {gpos_eng} "
                   f"(needs {req_eng} agents — partner has NOT yet latched)")
        else:
            inv = f"FULL cooperative hold on obj_{engaged[0]}"
    else:
        inv = "empty hands"

    obj_lines = []
    for oid in range(len(_PRIOR_OBJECTS)):
        obj_e  = entities.get(f"object_{oid}", {})
        kind   = "TARGET" if obj_e.get("is_target") else "DECOY"
        req    = obj_e.get("required_agents", 1)
        status = obj_e.get("status", "available")
        gpos   = _obj_grid_pos(grid_cells, oid, obj_e.get("is_target", False))
        dist   = _manhattan(pos, gpos) if gpos else "?"
        if status == "delivered" or oid in delivered:
            obj_lines.append(f"  obj_{oid} [{kind}]: DELIVERED")
        elif oid == carrying:
            obj_lines.append(f"  obj_{oid} [{kind}]: YOU ARE CARRYING IT")
        elif oid in engaged:
            gpos_e = _obj_grid_pos(grid_cells, oid, obj_e.get("is_target", True))
            if req > 1 and gpos_e is not None:
                obj_lines.append(
                    f"  obj_{oid} [{kind}]: PARTIAL LATCH — you latched (1 of {req}), "
                    f"at {gpos_e}. Partner must also PICK_OR_INTERACT!"
                )
            else:
                obj_lines.append(f"  obj_{oid} [{kind}]: FULL cooperative hold — jointly carried")
        elif gpos:
            obj_lines.append(f"  obj_{oid} [{kind}, needs {req} agent(s)]: at {gpos}, ~{dist} steps")
        else:
            obj_lines.append(f"  obj_{oid} [{kind}, needs {req} agent(s)]: not on grid")

    on_delivery_zone = list(pos) in [list(c) for c in _DELIVERY_ZONE]
    front_blocked    = (front == "WALL" or front.startswith("AGENT"))

    nav_hint_str = "none"
    if carrying is not None:
        goal      = min(_DELIVERY_ZONE, key=lambda c: _manhattan(pos, c))
        act, note = _smart_nav_hint(pos, direction, goal, grid_cells)
        nav_hint_str = f"{_ACTION_SHORT.get(act, str(act))} [{note}] → delivery zone {goal}"
    elif engaged:
        obj_e_eng = entities.get(f"object_{engaged[0]}", {})
        req_eng   = obj_e_eng.get("required_agents", 1)
        gpos_eng  = _obj_grid_pos(grid_cells, engaged[0], obj_e_eng.get("is_target", True))
        if req_eng > 1 and gpos_eng is not None:
            nav_hint_str = (
                f"COOPERATE [PARTIAL LATCH on obj_{engaged[0]} at {gpos_eng}. "
                f"Needs {req_eng} agents — partner must PICK_OR_INTERACT to complete hold.]"
            )
        else:
            goal      = min(_DELIVERY_ZONE, key=lambda c: _manhattan(pos, c))
            act, note = _smart_nav_hint(pos, direction, goal, grid_cells)
            if on_delivery_zone:
                nav_hint_str = (
                    f"WAIT — FULL hold, YOU are on delivery zone {goal}. "
                    f"Partner must also reach delivery zone before either agent DROPs. "
                    f"Use COOPERATE (6) or STAY (3) until partner arrives."
                )
            else:
                nav_hint_str = (
                    f"{_ACTION_SHORT.get(act, str(act))} [FULL hold — navigate to delivery {goal}. {note}]"
                )
    else:
        best_goal, best_dist_val = None, float("inf")
        for oid in range(len(_PRIOR_OBJECTS)):
            obj_e = entities.get(f"object_{oid}", {})
            if not obj_e.get("is_target", False):
                continue
            if obj_e.get("status") in ("delivered", "carried_by_self"):
                continue
            gpos_t = _obj_grid_pos(grid_cells, oid, True)
            if gpos_t:
                d = _manhattan(pos, gpos_t)
                if d < best_dist_val:
                    best_dist_val, best_goal = d, gpos_t
        if best_goal:
            act, note    = _smart_nav_hint(pos, direction, best_goal, grid_cells)
            nav_hint_str = f"{_ACTION_SHORT.get(act, str(act))} [{note}] → target at {best_goal} (~{best_dist_val} steps)"
        else:
            nav_hint_str = "explore — no undelivered target on grid"

    explored   = _grid_explored(grid_cells) if grid_cells else 0
    grid_ascii = _render_grid_ascii(grid_cells, pos) if grid_cells else "(no grid)"

    room = "LEFT" if pos[0] < 4 else "MIDDLE" if pos[0] < 8 else "RIGHT"
    lines = [
        f"STEP {step} | pos={pos} | facing={dir_name} | room={room}",
        f"IN FRONT: {front}",
        f"front_blocked={front_blocked}",
        f"on_delivery_zone={on_delivery_zone}",
        f"INVENTORY: {inv}",
        f"LAST ACTION: {last_outcome}",
        f"NAV_HINT: {nav_hint_str}",
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
    grid: List[List[str]] = [["unknown"] * 12 for _ in range(12)]
    for cx, cy in _DELIVERY_ZONE:
        grid[cx][cy] = "delivery_zone"
    for oid, info in _PRIOR_OBJECTS.items():
        x, y = info["init_pos"]
        kind = "target" if info["is_target"] else "decoy"
        grid[x][y] = f"{kind}_{oid}"
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
    return f"""\
You are part of a 2-agent team in a Cooperative Search and Transport task on a 12×12 grid.
Your decisions are made by a centralized commander who sees both agents' states.
The delivery zone is at the far left: (1,1)-(2,2).
obj_1 at [6,5] can be carried solo. obj_0 at [2,9] needs BOTH agents to cooperate.
"""


def get_goal_description(agent_id: str) -> str:
    return "Deliver both TARGET objects to the delivery zone. Cooperate."


# ── DSPy centralized signature ────────────────────────────────────────────────

class CentralizedCSTPlan(dspy.Signature):
    """
    You are the TEAM PLANNER for a 2-agent Cooperative Search and Transport task.
    You see BOTH agents' full states and choose actions for BOTH simultaneously.

    TEAM TASK:
      obj_1 at [6,5]: 1 agent can carry it alone → send one agent
      obj_0 at [2,9]: needs BOTH agents → coordinate approach, both PICK_OR_INTERACT, then move in sync

    ACTIONS (0-6 for each agent):
      0=TURN_LEFT  1=TURN_RIGHT  2=MOVE_FORWARD  3=STAY
      4=PICK_OR_INTERACT  5=DROP  6=COOPERATE

    COORDINATION RULES:
      - Assign one agent to obj_1 (solo) and one to head toward obj_0 early.
      - For cooperative carry: both agents must face obj_0 and PICK_OR_INTERACT.
        Then both MOVE_FORWARD together to carry it to delivery zone.
      - If one agent has PARTIAL LATCH: that agent should COOPERATE (6), the other goes to latch.
      - If one agent has FULL cooperative hold: both move in sync toward delivery zone.
      - Don't MOVE_FORWARD if front_blocked=True — rotate or change direction.
      - Trust NAV_HINT for wall navigation.

    DROP RULES — read carefully:
      - Solo carry (carrying_object_id set): if on_delivery_zone=True → DROP (5) immediately.
      - Cooperative carry (FULL hold): BOTH agents must be on delivery zone simultaneously
        before EITHER drops. If only one is on delivery zone, that agent uses COOPERATE (6)
        or STAY (3) and the other navigates to the delivery zone. Drop together only when
        BOTH are on delivery zone.
      - NEVER drop a target object outside the delivery zone — it will be lost.
    """
    team_situation: str = dspy.InputField(
        desc="Both agents' observation summaries including position, inventory, belief grid, nav hints"
    )
    coordination_plan: str = dspy.OutputField(
        desc="1-2 sentences: what each agent should do this step and why"
    )
    actions: str = dspy.OutputField(
        desc="Exactly two lines: 'agent_0: N' and 'agent_1: N' where N is 0-6"
    )


# ── Action parser ─────────────────────────────────────────────────────────────

def parse_team_actions(response: str, active_agents: list) -> dict:
    result = {}
    for agent_id in active_agents:
        m = re.search(rf'{re.escape(agent_id)}\s*[=:]\s*([0-6])', response)
        if m:
            result[agent_id] = int(m.group(1))
        else:
            result[agent_id] = 3  # STAY fallback
            print(f"  [WARN] could not parse action for {agent_id}, defaulting to STAY")
    return result


# ── Main loop ─────────────────────────────────────────────────────────────────

def main():
    log_path = os.path.join(_ENV_DIR, "cst_centralized_log.txt")
    print(f"Logging to {log_path}")

    lm = dspy.LM(model=LLM_MODEL, api_base=LLM_BASE, api_key="ollama", cache=False)
    dspy.configure(lm=lm)

    planner = dspy.ChainOfThought(CentralizedCSTPlan)

    config = EnvConfig(
        width=12, height=12,
        num_agents=2, num_objects=4, num_target_objects=2,
        max_steps=250, agent_view_size=3,
        render_mode="human", seed=42,
    )

    env = MultiAgentCooperativeSearchTransportEnv(config=config)
    observations, _ = env.reset(seed=42)

    print("\n" + "=" * 70)
    print("COOPERATIVE SEARCH & TRANSPORT  —  CENTRALIZED LLM")
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
            action_space=ACTIONS_DETAILS,
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

    env.render()
    time.sleep(0.5)

    with open(log_path, "w", buffering=1) as log_f:
        def log(msg):
            print(msg)
            log_f.write(msg + "\n")

        step = 0
        while env.agents:
            step += 1
            log(f"\n{'='*70}")
            log(f"STEP {step}  |  agents: {list(env.agents)}")
            log(f"{'='*70}")

            # Build combined situation for all active agents
            sections = []
            for agent_id in env.agents:
                mw       = middlewares[agent_id]
                entities = mw.belief_manager.updater.get_all_entities()
                summary  = summarize_cst_obs(
                    observations[agent_id], entities, step,
                    recent_history=mw.belief_manager.history_as_json,
                )
                sections.append(f"=== {agent_id} ===\n{summary}")

            team_situation = "\n\n".join(sections)
            log(f"\n[TEAM SITUATION]\n{team_situation}")

            # Single LLM call for all agents
            result  = planner(team_situation=team_situation)
            log(f"\n[COORDINATION PLAN] {result.coordination_plan}")
            log(f"[ACTIONS RAW]\n{result.actions}")

            actions = parse_team_actions(result.actions, list(env.agents))

            act_str = "  ".join(
                f"{aid}={_ACTION_SHORT.get(actions[aid], str(actions[aid]))}"
                for aid in sorted(actions)
            )
            log(f"[ACTIONS] {act_str}")

            observations, rewards, terminations, truncations, _ = env.step(actions)
            env.render()

            rew_str = "  ".join(f"{aid}={rewards[aid]:+.2f}" for aid in sorted(rewards))
            log(f"[REWARDS] {rew_str}")

            # Update each agent's belief
            for agent_id in sorted(actions):
                if agent_id in middlewares:
                    middlewares[agent_id].update_belief(
                        actions[agent_id],
                        rewards.get(agent_id, -0.01),
                        observations.get(agent_id, {}),
                    )

            if all(terminations.values()):
                log("\n SUCCESS — all targets delivered!")
                break
            if all(truncations.values()):
                log("\n Episode truncated (max steps reached)")
                break

            time.sleep(0.1)

    env.close()
    print("\nEpisode finished.")


if __name__ == "__main__":
    main()
