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

    def test_goal_reached_under_both_policies(self):
        for policy in OrchestrationPolicy:
            with self.subTest(policy=policy.value):
                loop = assemble_loop(DOMAIN, config=OrchestrationConfig(policy=policy))
                episode = loop.run()
                self.assertIs(episode.outcome, EpisodeOutcome.GOAL_REACHED, episode.reason)

    # TODO(author): add your designed physical failure — an applicable call that fails in
    # the environment — and assert the ExecutionDiscrepancy the runtime reports for it, the
    # halt under symbolic_primary, and the recovery under advisory_two_track.


if __name__ == "__main__":
    unittest.main()
