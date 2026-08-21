"""LIVE LM integration for the P3 NL track — separately marked, NEVER run by default.

Requires a local Ollama serving the pinned model and the explicit opt-in MAAOS_LIVE_LM=1.
Everything here may be slow and model-dependent; nothing here is part of the offline battery.
"""
import os
import unittest


@unittest.skipUnless(
    os.environ.get("MAAOS_LIVE_LM") == "1",
    "live LM integration: set MAAOS_LIVE_LM=1 with a local Ollama serving the pinned model",
)
class TestLiveNLTrack(unittest.TestCase):
    def test_one_live_proposal_cycle_is_typed(self):
        from domain.box_push_v1 import TASK_DELIVER_BOTH, initial_state
        from model_layer.planner.v1_nl_live import build_live_seam
        from nl import NLTrack, PINNED_V1_NL_RUNTIME
        from shared.skills import GroundedSkillCall, MalformedCall

        track = NLTrack(build_live_seam(PINNED_V1_NL_RUNTIME))
        track.observe(initial_state())
        proposal = track.propose(TASK_DELIVER_BOTH)
        # a LIVE model may answer well or badly; the contract is that the result is TYPED
        self.assertTrue(
            isinstance(proposal.call, GroundedSkillCall)
            or isinstance(proposal.malformed, MalformedCall)
        )


if __name__ == "__main__":
    unittest.main()
