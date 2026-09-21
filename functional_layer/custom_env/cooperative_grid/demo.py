"""The human-visible CooperativeGrid demo: watch MAAOS drive the two agents live.

    python -m functional_layer.custom_env.cooperative_grid.demo --policy symbolic_primary
    python -m functional_layer.custom_env.cooperative_grid.demo --policy advisory_two_track

Run from the repository root. Options: `--fps N` paces the primitive steps (default 2 per
second, slow enough to follow), `--headless` runs the same episode without a window (used by
the automated tests), `--hold S` keeps the window open S seconds after the episode ends.

The window is MiniGrid-style: grey walls, the yellow door (a red wedge under it marks the
jam — visible to you, invisible to the symbolic planner), the two blue-outlined handle
cells, the green goal cells, and the agents as red (A) and blue (B) triangles. The banner
shows the high-level MAAOS call under way and the last physical event.

This module lives on the backend side: the generic runtime knows nothing about rendering.
"""
from __future__ import annotations

import argparse
import sys
import time

from app.assembly import assemble_loop
from domains.cooperative_grid import DOMAIN
from domains.cooperative_grid.environment import make_environment
from shared.orchestration_config import OrchestrationConfig, OrchestrationPolicy


def run(policy: OrchestrationPolicy, *, headless: bool, fps: int, hold: float) -> int:
    env = make_environment(render_mode=None if headless else "human", render_fps=fps)
    loop = assemble_loop(DOMAIN, config=OrchestrationConfig(policy=policy), environment=env)
    print(f"cooperative_grid under {policy.value} ({'headless' if headless else 'live'})")
    started = time.monotonic()
    episode = loop.run()
    print(f"outcome: {episode.outcome.value} — {episode.reason}")
    print("decisions:")
    for entry in episode.history.entries:
        execution = entry.execution
        result = "-"
        if execution is not None:
            result = execution.outcome.value
            if execution.detail:
                result += f" ({execution.detail})"
            result += f", {execution.accounting.primitive_steps} primitive steps"
        decision = entry.decision.value if entry.decision is not None else "fault"
        evidence = "".join(f" [{d.kind.value}]" for d in entry.discrepancies)
        print(f"  {entry.executive_step:>2} {decision:<17} {str(entry.selected_call):<28} "
              f"{result}{evidence}")
    print(f"discrepancies recorded: {len(episode.discrepancies)}")
    final = env.export_full_state()
    for agent in final.agents:
        print(f"  {agent.name} at {agent.cell} ({final.place_of(agent.name)})")
    print(f"  door open={final.door.is_open} jammed={final.door.jammed}")
    print(f"elapsed: {time.monotonic() - started:.1f}s")
    if not headless and hold > 0:
        time.sleep(hold)
    env.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--policy", choices=[p.value for p in OrchestrationPolicy],
                        default=OrchestrationPolicy.ADVISORY_TWO_TRACK.value)
    parser.add_argument("--fps", type=int, default=2, help="primitive steps per second")
    parser.add_argument("--headless", action="store_true", help="no window (tests)")
    parser.add_argument("--hold", type=float, default=3.0,
                        help="seconds to keep the window open at the end")
    args = parser.parse_args(argv)
    return run(OrchestrationPolicy(args.policy), headless=args.headless, fps=args.fps,
               hold=args.hold)


if __name__ == "__main__":
    sys.exit(main())
