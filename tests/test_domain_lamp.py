"""Domain `lamp` — generated test: the domain validates and reaches its goal under both
policies. Extend it with your domain's designed physical failure (an applicable call that
fails in the environment) and what the runtime reports for it.

Offline and deterministic.
"""
from __future__ import annotations

import pathlib
import sys
import unittest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.assembly import assemble_loop                          # noqa: E402
from app.validation import Status, validate_domain               # noqa: E402
from runtime.loop import EpisodeOutcome                          # noqa: E402
from shared.discrepancy import DiscrepancyKind                   # noqa: E402
from shared.orchestration_config import (                        # noqa: E402
    OrchestrationConfig,
    OrchestrationPolicy,
)
from tests.fixture_lamp import DOMAIN                            # noqa: E402


class TestDomain(unittest.TestCase):
    def test_validate_domain_passes(self):
        report = validate_domain(DOMAIN)
        self.assertTrue(report.ok, report.render())
        self.assertEqual([f.code for f in report.findings if f.status is Status.FAIL], [])

    def test_goal_reached_under_the_advisory_policy(self):
        # with the stuck switch, symbolic_primary halts by design (asserted below); the
        # advisory policy recovers and reaches the goal
        loop = assemble_loop(DOMAIN, config=OrchestrationConfig(policy=OrchestrationPolicy.ADVISORY_TWO_TRACK))
        episode = loop.run()
        self.assertIs(episode.outcome, EpisodeOutcome.GOAL_REACHED, episode.reason)

    # TODO(author): add your designed physical failure — an applicable call that fails in
    # the environment — and assert the ExecutionDiscrepancy the runtime reports for it, the
    # halt under symbolic_primary, and the recovery under advisory_two_track.
    def test_the_stuck_switch_is_reported_halted_on_and_recovered_from(self):
        """Lamp l2's switch is physically stuck. The symbolic model does not know this
        (optimism by design): `TurnOn(l2)` is applicable and fails in the environment."""
        primary = assemble_loop(DOMAIN, config=OrchestrationConfig(policy=OrchestrationPolicy.SYMBOLIC_PRIMARY))
        halted = primary.run()
        self.assertIs(halted.outcome, EpisodeOutcome.HALTED_REPEATED_FAILURE, halted.reason)
        self.assertEqual([str(d.call) for d in halted.discrepancies], ["TurnOn(l2)"] * 3)
        self.assertTrue(all(d.kind is DiscrepancyKind.EXECUTION_FAILURE_OF_APPLICABLE_SKILL
                            for d in halted.discrepancies))

        advisory = assemble_loop(DOMAIN, config=OrchestrationConfig(policy=OrchestrationPolicy.ADVISORY_TWO_TRACK))
        recovered = advisory.run()
        self.assertIs(recovered.outcome, EpisodeOutcome.GOAL_REACHED, recovered.reason)
        executed = [str(e.selected_call) for e in recovered.history.entries if e.execution is not None]
        self.assertEqual(executed, ["TurnOn(l1)", "TurnOn(l2)", "TurnOn(l2)", "TurnOn(l2)", "Nudge(l2)", "TurnOn(l2)"])
        self.assertEqual(len(recovered.discrepancies), 3)     # the failures stay on record


if __name__ == "__main__":
    unittest.main()
