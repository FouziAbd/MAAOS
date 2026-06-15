# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**ma_aos** is a multi-agent LLM-driven system where LLMs drive agent decision-making inside PettingZoo parallel environments. The current working environment is **KAZ** (Knights, Archers, Zombies). A custom POMDP grid environment (**CooperativeSearchTransport**) is under active development.

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

- `DSPyPlanner` uses DSPy `ChainOfThought` with signature `NextActionSig`. Output field `action` is the integer index.
- `RewardManager` and `BeliefStateManager` are **stubs** — not used in active experiments.
- `History` logs to SQLite (`agent_history.db`).

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

Current branch: `middleware_layer`. The `main` branch is the stable baseline. The cooperative transport env and its joint-carry mechanic exist only on this branch.
