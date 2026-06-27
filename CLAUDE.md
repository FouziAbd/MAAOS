# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**ma_aos** is a multi-agent LLM-driven system where LLMs drive agent decision-making inside PettingZoo parallel environments. The original working environment is **KAZ** (Knights, Archers, Zombies). Two custom POMDP grid environments are under active development: **CooperativeSearchTransport** (CST — joint *carry*) and **BoxPush** (joint *push*, the newest env).

## Running the Code

All demo/entry-point scripts must be run from their own directory because they use bare `from module import ...` imports (no package structure):

```bash
# KAZ with LLM agents (main experiment — vector_state=True, DSPy+Ollama)
cd functional_layer/envs
python KAZ.py

# KAZ with vision LLM (experimental — vector_state=False, raw Ollama vision API)
cd functional_layer/envs
python KAZ_vision.py

# KAZ with RL reward shaping + LLM agents
cd functional_layer/envs
python KAZ_RL_LLM_Agents.py

# Cooperative transport demos (run from env/ directory)
cd functional_layer/custom_env/cooperative_search_transport/env
python demo_cooperative_solution.py   # hardcoded 2-agent cooperative carry
python demo_hardcoded_solution.py
python demo.py
python cst_centralized.py             # single centralized LLM, granular skills

# Box-Push (run from env/ directory)
cd functional_layer/custom_env/box_push/env
python box_push_centralized.py        # centralized LLM picks skills, skills run to completion
python box_push_per_step.py           # centralized LLM decides every primitive (1 call/step — slow)

# Toy rescue env
cd functional_layer/custom_env/toy_rescuce_env
python toy_rescue_env_v0.py
```

**Prerequisites:**
- `pip install pettingzoo gymnasium pygame numpy dspy-ai minigrid Pillow requests`
- Ollama running locally: `ollama serve` (default port 11434)
- A model loaded: `ollama pull llama3`
- For vision experiments: a multimodal model e.g. `ollama pull gemma4:e4b` or `ollama pull qwen3.6`

## Architecture

Four layers, each independently importable:

```
functional_layer/   ← PettingZoo environments (pure gym, no LLM)
middleware_layer/   ← Observation/scenario simplification + tactical assessment
model_layer/        ← LLM agent (DSPy planner, belief state, history)
utils/              ← Logging (logging_utils.py)
```

### Data flow (KAZ)

```
env.step() → raw obs
    → summarize_kaz_obs()          # computes attack_ok, turn_hint, distances
    → MiddlewareOrchestrator.process_observation()  # returns tactical summary as-is
    → Agent.choose_action_with_tactical_info()
        → DSPyPlanner.selec_action_index()  # LLM ChainOfThought — decides ALL actions
    → env.step(action_idx)
```

**The LLM decides all actions. There is no post-processing override.** Tactical rules are enforced through the scenario description prompt, not in code. If agents are ignoring rules, fix the prompt or the tactical signals — do not add code overrides.

### Middleware layer

`MiddlewareOrchestrator` is the single entry point. It:
- Runs one-time LLM simplification of scenario/goal at agent init (cached)
- If `tactical_summary` is provided to `process_observation()`, it is returned directly (bypasses LLM obs simplification)
- `ActionDescriptor` is **deprecated for KAZ** — plain string action maps are used instead
- Belief system is only wired when `entity_schema=` is passed to the constructor; otherwise `belief_manager` is `None`

### Model layer

`Agent` is the main class. Key method: `choose_action_with_tactical_info(obs, tactical_summary)`.

- `DSPyPlanner` (`model_layer/planner/DsPy_planner.py`) — per-agent, decentralized. DSPy `ChainOfThought`, signature `NextActionSig`. Output field `action` is the integer index. Used by KAZ.
- `CentralizedDSPyPlanner` (`model_layer/planner/centralized_dspy_planner.py`) — one LLM call sees ALL agents and returns one decision per agent. Used by the CST/BoxPush `*_centralized.py` and `*_per_step.py` runners. **The signature `TeamActionSig` is generic and never rewritten per environment** — all task specificity (rules, decision menu, situation, agent ids) is passed as input *values* via `decide(...)`, and a caller-supplied `parser(agent_id, raw)` maps each `'agent_id: DECISION'` line to a typed action/skill. On any LLM/parse error it returns `("[error]…", {})` so callers default every agent safely.
- `RewardManager` is a **stub**. The belief system (`BeliefStateManager` + `middleware_layer/belief_updaters/`) is **active** in CST/BoxPush — only KAZ leaves it unwired.
- `History` logs to SQLite (`agent_history.db`).

### Centralized + skill + belief stack (CST and BoxPush)

The custom grid envs do **not** use the KAZ per-agent flow. Instead:

1. **Belief** — each agent has a `DeterministicGridUpdater` (`middleware_layer/belief_updaters/`) maintaining an N×M belief grid (`unknown`/`empty`/`wall`/`delivery_zone`/`target_N`/`decoy_N`/`agent`). Self-position is **dead-reckoned from action + reward** (`reward > -0.06` ⇒ MOVE_FORWARD succeeded). The grid is initialized from prior knowledge and swept from each step's partial local view. Wired through `MiddlewareOrchestrator(entity_schema=..., obs_parser_fn=parse_cst_obs, belief_updater_kwargs=...)`.
2. **Shared map (centralized only)** — the `*_centralized.py` runners point every agent's `updater._grid` at one shared list so both agents read/write a single belief map (true centralized POMDP).
3. **Skills** — `CentralizedDSPyPlanner` picks a *skill* per agent (`explore`, `goto_push_pose`, `push`, `cooperate_push`, `wait`); a `BaseSkill` subclass then runs to completion over many primitive steps, re-checking belief each step and returning a *label* (e.g. `delivered`, `too_heavy`, `blocked`) fed back to the planner next cycle. `box_push_per_step.py` skips the skill layer — the LLM emits a primitive per agent every step.
4. **Shared skill scaffolding** — env-agnostic pieces (`BaseSkill`, `ExploreSkill`, `WaitSkill`, cell decoding `_cell_desc`, and BFS/frontier nav helpers) live in `functional_layer/custom_env/shared_skills.py`. Both CST's `skill_executor.py` and box_push's `skill_executor_push.py` import from there, so **no env depends on another**. Each env keeps its own task-specific skills and `make_skill` factory: CST has `goto_target/goto_delivery/pick/drop/cooperate_move` (carry); box_push has `goto_push_pose/push/cooperate_push` (push). `skill_executor.py` re-exports the shared names, so older `from skill_executor import _cell_desc, …` callers (e.g. the package-level `cst_centralized.py`) still resolve.

### CooperativeSearchTransport environment

Lives in `functional_layer/custom_env/cooperative_search_transport/env/`. All files must be imported from that directory.

Key files:
- `state.py` — `AgentState`, `ObjectState` (has `engaged_agents: List[str]`), `WorldState`
- `constants.py` — `Actions` (0–6), `Directions`, `DIRECTION_VECTORS`
- `cooperative_search_transport_env.py` — MiniGrid single-agent base, defines grid layout and initial object positions
- `multi_agent_env.py` — PettingZoo `ParallelEnv` wrapper; all multi-agent logic lives here
- `objects.py` — `TargetPackage`, `DecoyPackage`, `AgentMarker`, `DeliveryTile`

**Grid layout (12×12):** delivery zone at (1–2, 1–2); wall at x=4 (gaps y=3, y=8); wall at x=8 (gap y=6); Object-0 (target, 2-agent) at (2,9); Object-1 (target, 1-agent) at (6,5). Agents start at (10,10) and (10,9) facing LEFT.

**Cooperative carry mechanic** (implemented on `middleware_layer` branch):
1. Agent calls `PICK_OR_INTERACT` facing a `required_agents > 1` object → added to `obj.engaged_agents`
2. Once `len(engaged_agents) >= required_agents`, object is removed from the grid (jointly held)
3. All engaged agents do `MOVE_FORWARD` facing the same direction → agents + object move together
4. `DROP` by any agent removes them from `engaged_agents`; object is put back on grid if hold breaks
5. Agents in a joint hold are **blocked from individual MOVE_FORWARD** (checked via `_is_agent_in_joint_hold`)

**Direction arithmetic:** `TURN_LEFT = (dir-1) % 4`, `TURN_RIGHT = (dir+1) % 4`. `RIGHT=0 DOWN=1 LEFT=2 UP=3`. MOVE_FORWARD with UP moves to `(x, y-1)`.

### BoxPush environment

Lives in `functional_layer/custom_env/box_push/env/`. **Reuses CST's `objects.py`, `state.py`, `constants.py`, `obs_parser.py` (the shared definitions, kept in the CST `env/` dir) and the env-agnostic skill scaffolding in `shared_skills.py` via `sys.path` insertion** — the run scripts add the CST `env/` dir, `functional_layer/custom_env/` (for `shared_skills`), the box_push `env/` dir, and the repo root to `sys.path` at import time. Box-push does **not** import CST's `skill_executor.py` (only `shared_skills.py`). Do not "fix" these path hacks into package imports; the whole repo relies on bare imports run from each script's directory.

Key contrast with CST — the interaction model is **PUSH, not carry**:
- **Open 12×12 arena**, outer wall only (a walled maze makes box-pushing Sokoban-hard). Goal zone = left column `x=1, y=1..10`. Box-0 = HEAVY (`required_agents=2`) at (6,6); Box-1 = LIGHT (`required_agents=1`) at (8,4). Agents start on the right facing LEFT.
- **Action space is `Discrete(4)`**: `TURN_LEFT=0, TURN_RIGHT=1, MOVE_FORWARD=2, STAY=3`. **There is no PICK/DROP/COOPERATE action** — cooperation is *emergent* from MOVE_FORWARD.
- **Light push:** one agent MOVE_FORWARD into the box slides it one cell if the cell beyond is free; the pusher follows.
- **Heavy push = TANDEM:** the box moves only when two agents line up *in-line* behind it (A1 at B−D, A2 at B−2D, both facing D) and **both** MOVE_FORWARD the same step. A lone push of a heavy box is blocked — this is the "discover it's heavy" signal (`too_heavy`).
- **Delivery is by position:** a target box whose cell lands in the goal zone is delivered. Resolution order each step (`MultiAgentBoxPushEnv.step`): turns → `_resolve_pushes` (Phase A heavy tandems, Phase B individual moves/light pushes) → `_check_delivery` → termination.
- **Skill-layer caveats** (`skill_executor_push.py`): navigation treats boxes as obstacles (`_bfs_avoid_boxes`) so repositioning agents don't bulldoze boxes; the shared map records agents as `empty`, so skills add no-progress/stuck backstops to avoid silently freezing against a stationary partner. Heavy is "sticky" — once `push` returns `too_heavy`, only ever `cooperate_push` that box.

## KAZ-Specific Implementation Details

### Thresholds in `summarize_kaz_obs()`

| Role | max_dist | max_angle | ally_block_dist | ally_block_angle |
|------|----------|-----------|-----------------|------------------|
| Archer | 0.85 | 20° | 0.20 | 15° |
| Knight | 0.25 | 70° | 0.15 | 25° |

`attack_ok=True` requires: zombie in front (`z_dot > 0`), within `max_angle`, within `max_dist`, and `ally_block_attack=False`.

### `_turn_hint` — coordinate system gotcha

KAZ uses **image coordinates** (y increases downward). This flips cross-product handedness vs standard math:

```python
cross = h[0] * r[1] - h[1] * r[0]
return "RIGHT" if cross > 0 else "LEFT"   # opposite of standard math — do not change
```

Swapping this back to standard math breaks all rotation guidance.

### `_prev_positions` global state

`summarize_kaz_obs()` uses a module-level `_prev_positions: dict` to detect `movement_blocked`. This dict persists across calls and must be agent-keyed. Pass `agent_id=` on every call.

### `rotations_needed` is informational

`rotations_needed` is included in the tactical summary only when > 0. It is an estimate, not a condition. The LLM should attack when `attack_ok=True`, not wait for `rotations_needed == 0`.

### Archer patrol zones

`archer_0` patrols `x=0.15–0.50`, `archer_1` patrols `x=0.50–0.85` — split to prevent clustering. The split is implemented in `get_scenario_description()` via `"0" in agent_id`.

## KAZ Vision Experiment (`KAZ_vision.py`)

An alternative KAZ runner using `vector_state=False` (512×512 RGB image per agent) with a vision-capable Ollama model instead of DSPy. Bypasses the entire middleware/model layer — calls Ollama `/api/chat` directly.

**Key design decisions:**
- Each agent gets its own **POMDP local obs** (centered on itself) — not the global render frame. `env.render()` gives a god-view that breaks self-identification.
- Raw obs is too dark (max pixel ~198 on dark maroon background). **Gamma correction** (`gamma=0.4`) brightens dark pixels without color distortion — do not use `autocontrast` or linear brightness (both over-expose).
- `"think": True` enables Qwen3/Gemma4 reasoning mode. For Qwen3 specifically, use `/api/chat` not `/api/generate` — the latter returns empty `response` because thinking tokens consume the token budget.
- Structured output format `SCENE / DECISION / ACTION:` forces per-step visual reasoning before action selection.
- Logs to `logs_vision_run.txt` (separate from `logs_run.txt`).

**Tuning levers** (top of file): `VISION_MODEL`, `TIMEOUT`, `gamma` inside `enhance_obs()`.

## KAZ RL Files

- `KAZ_RL.py` — `KAZRLWrapper` class adding shaped rewards: `-0.01` per step, `+1.0` kill, `-1.0` death or zombie escape. Import via `from KAZ_RL import create_kaz_rl_env`.
- `KAZ_RL_LLM_Agents.py` — Same LLM agent setup as `KAZ.py` but running on top of `KAZRLWrapper` for denser reward signals.

## Branch Notes

Current branch: `middleware_layer`. The `main` branch is the stable baseline. The CST joint-carry env, the BoxPush joint-push env, the centralized/skill/belief stack, and the centralized planner all exist only on this branch.

Run artifacts (e.g. `box_push_centralized_log.txt`, `box_push_per_step_log.txt`, `logs_run.txt`, `logs_vision_run.txt`, `agent_history.db`) are written next to the scripts and should not be committed — consider adding them to `.gitignore`.
