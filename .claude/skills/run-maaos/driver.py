#!/usr/bin/env python3
"""
Headless driver for the ma_aos multi-agent LLM system.

Two modes, both run the project's REAL code (no reimplementation):

  cst  (default, NO Ollama) : runs the hardcoded cooperative-carry solution for the
                              CooperativeSearchTransport env, monkeypatched to render
                              headlessly (rgb_array + SDL dummy) and dump PNG frames.
                              Deterministic, ~1s, proves env + multi-agent mechanic + render.

  llm  (needs Ollama)       : configures the CentralizedDSPyPlanner exactly like
                              box_push_centralized.py and makes ONE planner.decide() call
                              against the local Ollama model, proving the DSPy->Ollama->parser
                              path works end-to-end.

Usage:
    python .claude/skills/run-maaos/driver.py            # cst mode
    python .claude/skills/run-maaos/driver.py cst
    python .claude/skills/run-maaos/driver.py llm
    python .claude/skills/run-maaos/driver.py all

Screenshots land in .claude/skills/run-maaos/screenshots/.
Exit code 0 = pass, non-zero = failure (usable as a smoke test).
"""
import os
import sys
import argparse

# Headless SDL BEFORE pygame is imported anywhere.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

_THIS = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_THIS, "../../.."))          # .../MAAOS
_CST_ENV = os.path.join(_REPO, "functional_layer/custom_env/cooperative_search_transport/env")
_BOX_ENV = os.path.join(_REPO, "functional_layer/custom_env/box_push/env")
_CUSTOM  = os.path.join(_REPO, "functional_layer/custom_env")
_SHOTS = os.path.join(_THIS, "screenshots")
os.makedirs(_SHOTS, exist_ok=True)


def _save(frame, name):
    import numpy as np
    from PIL import Image
    path = os.path.join(_SHOTS, name)
    Image.fromarray(np.asarray(frame).astype("uint8")).save(path)
    print(f"  [shot] {path}")
    return path


# ── CST mode: run the real hardcoded demo headlessly ────────────────────────────
def run_cst():
    print("== CST hardcoded cooperative-carry demo (headless, no LLM) ==")
    for p in (_CST_ENV,):
        if p not in sys.path:
            sys.path.insert(0, p)

    import demo_cooperative_solution as demo
    from state import EnvConfig as _RealCfg
    from multi_agent_env import MultiAgentCooperativeSearchTransportEnv as _RealEnv

    frames = []
    state = {"terminated": False}

    class _CapEnv(_RealEnv):
        """Same env, but render() captures an rgb frame instead of opening a window,
        and step() records episode success."""
        def render(self):
            frames.append(self.core_env.get_frame(32))

        def step(self, actions):
            out = super().step(actions)
            _, _, terminations, _, _ = out
            if terminations and all(terminations.values()):
                state["terminated"] = True
            return out

    def _headless_cfg(**kw):
        kw["render_mode"] = "rgb_array"   # force off-screen
        return _RealCfg(**kw)

    # Inject into the demo module's namespace + neuter the sleeps.
    demo.MultiAgentCooperativeSearchTransportEnv = _CapEnv
    demo.EnvConfig = _headless_cfg
    demo.time.sleep = lambda *_a, **_k: None

    demo.main()

    if not frames:
        print("FAIL: demo produced no frames")
        return 1
    _save(frames[0], "cst_start.png")
    _save(frames[len(frames) // 2], "cst_mid.png")
    _save(frames[-1], "cst_final.png")
    print(f"  captured {len(frames)} frames")
    if not state["terminated"]:
        print("FAIL: episode did not terminate with all targets delivered")
        return 1
    print("PASS: cooperative carry completed, all targets delivered")
    return 0


# ── LLM mode: one real planner.decide() against Ollama ──────────────────────────
def run_llm():
    print("== Centralized DSPy planner -> Ollama smoke ==")
    for p in (_REPO, _CUSTOM, _CST_ENV, _BOX_ENV):
        if p not in sys.path:
            sys.path.insert(0, p)

    import dspy
    from box_push_centralized import (
        LLM_MODEL, LLM_BASE, _RULES, _DECISION_SPACE, _OBJECTIVE, _skill_parser,
    )
    from model_layer.planner.centralized_dspy_planner import CentralizedDSPyPlanner

    print(f"  model={LLM_MODEL} base={LLM_BASE}")
    lm = dspy.LM(model=LLM_MODEL, api_base=LLM_BASE, api_key="ollama", cache=False)
    planner = CentralizedDSPyPlanner(name="smoke")
    planner.configure_ollama(lm)

    team_situation = (
        "=== agent_0 ===\nYou are at [10,10] facing LEFT. Belief: two red target boxes "
        "somewhere ahead, unexplored to the west.\n\n"
        "=== agent_1 ===\nYou are at [10,9] facing LEFT. Belief: unexplored to the west."
    )
    reasoning, decided = planner.decide(
        task_instructions=_RULES, decision_space=_DECISION_SPACE,
        team_situation=team_situation, objective=_OBJECTIVE,
        agents=["agent_0", "agent_1"], recent_feedback="none yet", parser=_skill_parser,
    )
    print(f"  reasoning: {str(reasoning)[:200]}")
    print(f"  decided:   {decided}")
    if str(reasoning).startswith("[error]") or not decided:
        print("FAIL: planner returned an error / empty decision (is `ollama serve` up "
              "with gemma4:e4b pulled?)")
        return 1
    if set(decided) != {"agent_0", "agent_1"}:
        print(f"FAIL: expected a decision per agent, got keys {list(decided)}")
        return 1
    print("PASS: LLM produced one parsed skill per agent")
    return 0


def main():
    ap = argparse.ArgumentParser(description="ma_aos headless driver")
    ap.add_argument("mode", nargs="?", default="cst", choices=["cst", "llm", "all"])
    args = ap.parse_args()

    rc = 0
    if args.mode in ("cst", "all"):
        rc |= run_cst()
    if args.mode in ("llm", "all"):
        rc |= run_llm()
    print("\n== RESULT: " + ("ALL PASS ==" if rc == 0 else "FAILURE =="))
    return rc


if __name__ == "__main__":
    sys.exit(main())
