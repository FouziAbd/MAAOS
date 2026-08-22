"""Human-watchable V1 executive run — the V1 counterpart of the legacy runner's demo.

Runs the P4 `ExecutiveLoopManager` over the real backend with pygame rendering, printing each
executive cycle as it happens. Unlike the legacy runner this needs NO LLM: the symbolic track
plans, and under the advisory policy the deterministic NL RecoveryProposer supplies the
livelock escape.

    cd functional_layer/custom_env/box_push/env
    python box_push_v1_run.py                     # advisory policy, rendered, completes
    python box_push_v1_run.py --policy symbolic_primary   # halts at the designed livelock
    python box_push_v1_run.py --headless          # no window (CI/smoke)
    python box_push_v1_run.py --delay 0.05        # slow the primitive steps down
    python box_push_v1_run.py --nl live           # live DSPy proposals each cycle (Ollama)

With --nl live the pinned gemma model PROPOSES a skill every cycle through the P3 NL track;
the V1 architecture records it as typed evidence (agreement/contradiction/confidence
divergences) beside the symbolic decision — the LLM advises, the symbolic plan drives, and
only the RecoveryProposer's advice is ever executed (through the same gates as any call).

Lives on the legacy side of the import guards BY DESIGN: guarded packages may not import the
backend, so a demo that owns both the env config and the loop belongs here, like the adapter.
"""
import argparse
import os
import sys
import time

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_THIS, "..", "..", "..", ".."))
for _p in (_ROOT, _THIS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from box_push_env import EnvConfig                                   # noqa: E402
from box_push_v1_adapter import BoxPushV1Adapter, _default_config    # noqa: E402

from domain.box_push_v1 import TASK_DELIVER_BOTH                     # noqa: E402
from runtime.loop import ExecutiveLoopManager                        # noqa: E402
from shared.orchestration_config import (                            # noqa: E402
    OrchestrationConfig,
    OrchestrationPolicy,
)


class _WatchableAdapter(BoxPushV1Adapter):
    """Renders (and optionally sleeps) after every primitive env.step — the V1 loop itself
    stays untouched; watching is an adapter-side concern, like all rendering."""

    def __init__(self, config: EnvConfig, delay: float) -> None:
        super().__init__(config)
        self._delay = delay
        self._rendering = config.render_mode == "human"

    def execute_skill(self, call):
        # render between primitive steps by wrapping env.step
        original_step = self._env.step

        def stepped(actions):
            result = original_step(actions)
            if self._rendering:
                self._env.render()
                if self._delay:
                    time.sleep(self._delay)
            return result

        self._env.step = stepped
        try:
            return super().execute_skill(call)
        finally:
            self._env.step = original_step


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--policy", choices=[p.value for p in OrchestrationPolicy],
                        default=OrchestrationPolicy.ADVISORY_TWO_TRACK.value)
    parser.add_argument("--headless", action="store_true", help="no pygame window")
    parser.add_argument("--delay", type=float, default=0.03,
                        help="seconds to sleep per primitive step when rendering")
    parser.add_argument("--nl", choices=["off", "live"], default="off",
                        help="'live': attach the P3 NL track over the pinned local Ollama "
                             "model so DSPy proposes a skill every cycle (advisory evidence)")
    args = parser.parse_args()

    nl_track = None
    if args.nl == "live":
        from model_layer.planner.v1_nl_live import build_live_seam
        from nl import NLTrack, PINNED_V1_NL_RUNTIME
        nl_track = NLTrack(build_live_seam(PINNED_V1_NL_RUNTIME))
        print(f"live NL track: {PINNED_V1_NL_RUNTIME.model} @ {PINNED_V1_NL_RUNTIME.api_base}")

    base = _default_config()
    config = EnvConfig(
        width=base.width, height=base.height, num_agents=base.num_agents,
        num_objects=base.num_objects, num_target_objects=base.num_target_objects,
        max_steps=base.max_steps, agent_view_size=base.agent_view_size,
        render_mode=None if args.headless else "human", seed=base.seed,
    )
    loop = ExecutiveLoopManager(
        _WatchableAdapter(config, args.delay), TASK_DELIVER_BOTH,
        OrchestrationConfig(policy=OrchestrationPolicy(args.policy)),
        nl_track=nl_track,
    )
    print(f"policy={args.policy}  task={TASK_DELIVER_BOTH.task_id}  "
          f"({'headless' if args.headless else 'rendered'})")
    episode = loop.run()

    previous = None
    for entry in episode.history.entries:
        decision = entry.decision.value if entry.decision else (
            "faulted" if entry.faults else "recorded")
        call = str(entry.selected_call) if entry.selected_call else "-"
        outcome = entry.execution.outcome.value if entry.execution else "-"
        extra = ""
        if entry.discrepancies:
            extra = f"  !! {entry.discrepancies[0].kind}"
        # enacted NL RECOVERY is identified by adjacency to its REQUEST_PROPOSAL entry
        # (the nl_proposal column also carries ordinary advisory proposals — W1)
        from shared.orchestration_config import ExecutiveDecision as _ED
        if (entry.nl_proposal is not None and entry.execution is not None
                and previous is not None
                and previous.decision is _ED.REQUEST_PROPOSAL
                and previous.executive_step == entry.executive_step):
            extra += "  [nl recovery]"
        previous = entry
        print(f"  cycle {entry.executive_step:2}  {decision:17} {call:45} -> {outcome}{extra}")
        if entry.execution is not None and (entry.divergences or entry.coverage is not None):
            nl_view = next((d.nl_view for d in entry.divergences if d.nl_view), None)
            agreement = ("agrees" if not entry.divergences else
                         ", ".join(d.kind.value for d in entry.divergences))
            conf = (f"  conf={entry.confidence[0].confidence}" if entry.confidence else "")
            print(f"       nl proposed: {nl_view or call}  [{agreement}]{conf}")

    print(f"\n{episode.outcome.value.upper()}: {episode.reason}")
    print(f"executive steps: {loop.executive_steps_charged}  "
          f"primitive steps: {loop.primitive_steps_charged}  "
          f"discrepancies: {len(episode.discrepancies)}")
    loop.env.close()


if __name__ == "__main__":
    main()
