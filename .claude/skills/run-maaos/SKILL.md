---
name: run-maaos
description: Build, launch, drive, and screenshot the ma_aos multi-agent LLM system (KAZ, CooperativeSearchTransport, BoxPush PettingZoo envs). Use when asked to run maaos, run the environments, take a screenshot of an env, smoke-test the DSPy/Ollama planner, or verify the multi-agent envs still work headlessly.
---

# Run ma_aos

`ma_aos` is a set of PettingZoo multi-agent environments (KAZ, CooperativeSearchTransport,
BoxPush) where an LLM (DSPy + local Ollama) drives agent decisions. The entry-point scripts
(`KAZ.py`, `box_push_centralized.py`, `demo_cooperative_solution.py`, …) open a **pygame
window** and `time.sleep` between steps — useless headless. This skill's driver runs the
**same code** off-screen (`SDL_VIDEODRIVER=dummy`, MiniGrid `rgb_array`) and dumps PNG frames.

All paths below are relative to the repo root (the dir containing `requirements.txt`).
The driver lives at `.claude/skills/run-maaos/driver.py`.

## Prerequisites

Python 3.12. Install the deps (already present in the `PettingZooEnv` venv on this machine):

```bash
pip install -r requirements.txt
```

For the LLM path only: Ollama running with the model the runners use.

```bash
ollama serve                 # if not already up (default :11434)
ollama pull gemma4:e4b       # model used by box_push_centralized.py
```

No display / Xvfb needed — the driver forces `SDL_VIDEODRIVER=dummy` itself.

## Run (agent path) — the driver

```bash
# Deterministic, NO Ollama: runs the hardcoded cooperative-carry solve for
# CooperativeSearchTransport headless, ~1s, and writes 3 PNGs. Best "does it render?" check.
python3 .claude/skills/run-maaos/driver.py cst

# Ollama smoke: one real CentralizedDSPyPlanner.decide() call (gemma4:e4b) → one skill/agent.
python3 .claude/skills/run-maaos/driver.py llm

# Both:
python3 .claude/skills/run-maaos/driver.py all
```

Exit code is `0` on pass, non-zero on failure — usable as a smoke test.
Screenshots land in `.claude/skills/run-maaos/screenshots/` (`cst_start.png`,
`cst_mid.png`, `cst_final.png`). In `cst_final.png` both agent triangles sit in the
green delivery zone = the 2-agent box was jointly carried and delivered.

Verified output tail:

```
Step 45 | carry ×7 : Object →(2,2) DELIVERED! | a0=FWD R=+30.19 | a1=FWD R=+30.19
✓  SUCCESS — all targets delivered!
PASS: cooperative carry completed, all targets delivered
== RESULT: ALL PASS ==
```

```
== Centralized DSPy planner -> Ollama smoke ==
  model=ollama_chat/gemma4:e4b base=http://localhost:11434
  decided:   {'agent_0': ('explore', None), 'agent_1': ('explore', None)}
PASS: LLM produced one parsed skill per agent
```

## Run (human path) — the real runners with a window

Each runner uses bare imports, so it **must** be run from its own directory. On a machine
with a real display these open a live pygame window (headless: prefix with
`SDL_VIDEODRIVER=dummy` or they will fail to open a display).

```bash
cd functional_layer/custom_env/cooperative_search_transport/env
python demo_cooperative_solution.py     # hardcoded 2-agent carry (no LLM)
python cst_centralized.py               # centralized LLM + skills (needs Ollama)

cd ../../box_push/env
python box_push_centralized.py          # centralized LLM picks skills, runs to completion
python box_push_per_step.py             # LLM emits a primitive per agent every step (slow)

cd ../../../envs
python KAZ.py                           # Knights-Archers-Zombies, per-agent DSPy planners
```

LLM runners write a `*_log.txt` next to the script (e.g. `box_push_centralized_log.txt`).

## Gotchas

- **`env.render()` returns `None` in `rgb_array` mode.** The multi-agent wrapper's
  `render()` just calls `core_env.render()` (which returns nothing here). To capture a
  frame you must call `env.core_env.get_frame(32)` directly — that returns the 384×384×3
  uint8 array. The driver's `cst` mode does exactly this via a `render()` override.
- **The runners hardcode `render_mode="human"` and `time.sleep(...)`** inside `main()`.
  The driver monkeypatches the demo module's `EnvConfig` (→ `rgb_array`), its env class
  (→ frame-capturing subclass), and `time.sleep` (→ no-op) so the *actual* demo code runs
  headless and fast. It does **not** reimplement the action sequence — no drift.
- **Every entry-point script uses bare `from module import ...`** (no package). You must
  `cd` into the script's own directory first, or imports fail. BoxPush additionally reaches
  into the CST `env/` dir and the repo root via `sys.path` insertion — expected, do not
  "fix" into package imports.
- **Ollama model must actually be pulled.** If `gemma4:e4b` is missing the planner returns
  a string starting `[error]` and defaults every agent to `explore`; the driver's `llm`
  mode treats that as FAIL. Check with `curl -s localhost:11434/api/tags`.
- **No automated test suite exists** (no pytest). This driver is the closest thing to a
  smoke test — validate env/render/planner changes by running it.

## Troubleshooting

- `pygame ... No available video device` → you invoked a raw runner without a display.
  Prefix with `SDL_VIDEODRIVER=dummy` (the driver sets this automatically).
- `ModuleNotFoundError: constants` / `multi_agent_env` → you ran a raw runner from the
  wrong directory. `cd` into that script's own `env/` dir first.
- LLM mode hangs or fails → confirm `ollama serve` is up and `ollama pull gemma4:e4b` has
  completed; first call can be slow while the model loads into memory.
