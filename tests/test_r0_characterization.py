"""R0 characterization: pin BOTH current policies' exact executive decision sequences.

Supervisor report Phase 0 requires "characterization tests for both current policies,
including the exact number and order of executive decisions in the accepted scenario"
(docs/supervisor/MAAOS_code_review_and_refactoring_report.md, Phase 0). The existing
acceptance suite (tests/test_v1_acceptance.py::TestCase7ExecutiveLoop) pins outcomes,
thresholds, and the shared prefix; THIS module pins the full cycle-by-cycle story so a
later R-phase cannot reorder, drop, or add an executive decision unnoticed.

Two layers of pinning, deliberately redundant:

  1. The decision-kind order is hard-coded here (execute x7 + halt / execute x7 +
     request_proposal + execute x2) — meaningful even if the baseline artifacts are
     regenerated wrongly.
  2. Every cycle line (decision, grounded call, outcome, discrepancy kind, recovery
     marker) and the step-accounting footer must equal the pristine pre-refactor
     transcripts frozen at docs/refactor/baseline/demo_*.txt, rendered with the same
     mapping box_push_v1_run.py uses.

Offline and deterministic: local backend, no LM, no network, no render.
"""
import os
import pathlib
import re
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ENV_DIR = os.path.join(_REPO_ROOT, "functional_layer", "custom_env", "box_push", "env")
for _p in (_REPO_ROOT, _ENV_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from box_push_v1_adapter import BoxPushV1Adapter

from domain.box_push_v1 import TASK_DELIVER_BOTH
from runtime.loop import EpisodeOutcome, ExecutiveLoopManager
from shared.discrepancy import DiscrepancyKind
from shared.execution import ExecutionOutcome
from shared.orchestration_config import (
    ExecutiveDecision,
    OrchestrationConfig,
    OrchestrationPolicy,
)

_BASELINE_DIR = os.path.join(_REPO_ROOT, "docs", "refactor", "baseline")
_TRANSCRIPTS = {
    OrchestrationPolicy.ADVISORY_TWO_TRACK: "demo_advisory_two_track.txt",
    OrchestrationPolicy.SYMBOLIC_PRIMARY: "demo_symbolic_primary.txt",
}

# One episode per policy for the whole module; the run itself is the object under test.
_CACHE: dict[OrchestrationPolicy, tuple[ExecutiveLoopManager, object]] = {}


def _episode(policy):
    if policy not in _CACHE:
        loop = ExecutiveLoopManager(
            BoxPushV1Adapter(), TASK_DELIVER_BOTH, OrchestrationConfig(policy=policy)
        )
        _CACHE[policy] = (loop, loop.run())
    return _CACHE[policy]


# A parsed/rendered cycle row: every field of a demo transcript cycle line.
# (step, decision, call, outcome, discrepancy_kind_or_None, is_nl_recovery)
_CYCLE_LINE = re.compile(
    r"^  cycle\s+(?P<step>\d+)\s+(?P<decision>\S+)\s+(?P<call>.*?)\s+->\s+(?P<outcome>\S+)"
    r"(?:\s+!!\s+(?P<discrepancy>\S+))?(?P<recovery>\s+\[nl recovery\])?\s*$"
)
_FOOTER = re.compile(
    r"^executive steps:\s+(?P<executive>\d+)\s+primitive steps:\s+(?P<primitive>\d+)"
    r"\s+discrepancies:\s+(?P<discrepancies>\d+)\s*$"
)
_OUTCOME_LINE = re.compile(r"^(?P<outcome>[A-Z_]+): (?P<reason>.+)$")


def _parse_transcript(policy):
    text = pathlib.Path(_BASELINE_DIR, _TRANSCRIPTS[policy]).read_text(encoding="utf-8")
    rows, footer, outcome = [], None, None
    for line in text.splitlines():
        m = _CYCLE_LINE.match(line)
        if m:
            rows.append((
                int(m.group("step")),
                m.group("decision"),
                m.group("call"),
                m.group("outcome"),
                m.group("discrepancy"),
                m.group("recovery") is not None,
            ))
            continue
        f = _FOOTER.match(line)
        if f:
            footer = (int(f.group("executive")), int(f.group("primitive")),
                      int(f.group("discrepancies")))
            continue
        o = _OUTCOME_LINE.match(line)
        if o:
            outcome = (o.group("outcome"), o.group("reason"))
    return rows, footer, outcome


def _render_episode(episode):
    """The same entry->row mapping box_push_v1_run.py prints, minus column padding."""
    rows, previous = [], None
    for entry in episode.history.entries:
        decision = entry.decision.value if entry.decision else (
            "faulted" if entry.faults else "recorded")
        call = str(entry.selected_call) if entry.selected_call else "-"
        outcome = entry.execution.outcome.value if entry.execution else "-"
        discrepancy = f"{entry.discrepancies[0].kind}" if entry.discrepancies else None
        recovery = (entry.nl_proposal is not None and entry.execution is not None
                    and previous is not None
                    and previous.decision is ExecutiveDecision.REQUEST_PROPOSAL
                    and previous.executive_step == entry.executive_step)
        rows.append((entry.executive_step, decision, call, outcome, discrepancy, recovery))
        previous = entry
    return rows


class TestDecisionOrderIsPinnedInCode(unittest.TestCase):
    """Layer 1: the exact number and order of executive decisions, hard-coded."""

    def test_symbolic_primary_decision_sequence(self):
        _, episode = _episode(OrchestrationPolicy.SYMBOLIC_PRIMARY)
        self.assertEqual(
            [e.decision for e in episode.history.entries],
            [ExecutiveDecision.EXECUTE] * 7 + [ExecutiveDecision.HALT],
        )

    def test_advisory_two_track_decision_sequence(self):
        _, episode = _episode(OrchestrationPolicy.ADVISORY_TWO_TRACK)
        self.assertEqual(
            [e.decision for e in episode.history.entries],
            [ExecutiveDecision.EXECUTE] * 7
            + [ExecutiveDecision.REQUEST_PROPOSAL]
            + [ExecutiveDecision.EXECUTE] * 2,
        )

    def test_outcomes_are_the_accepted_ones(self):
        _, primary = _episode(OrchestrationPolicy.SYMBOLIC_PRIMARY)
        _, advisory = _episode(OrchestrationPolicy.ADVISORY_TWO_TRACK)
        self.assertIs(primary.outcome, EpisodeOutcome.HALTED_REPEATED_FAILURE)
        self.assertIs(advisory.outcome, EpisodeOutcome.GOAL_REACHED)


class TestEpisodesEqualTheFrozenBaselineTranscripts(unittest.TestCase):
    """Layer 2: cycle-by-cycle equality with the pristine pre-refactor transcripts."""

    def _assert_matches(self, policy):
        loop, episode = _episode(policy)
        expected_rows, expected_footer, expected_outcome = _parse_transcript(policy)
        self.assertGreater(len(expected_rows), 0,
                           "baseline transcript parsed to zero cycle lines — "
                           "the pin would be vacuous")
        self.assertIsNotNone(expected_footer, "baseline transcript footer missing")
        self.assertIsNotNone(expected_outcome, "baseline transcript outcome line missing")
        self.assertEqual(_render_episode(episode), expected_rows)
        self.assertEqual(
            (loop.executive_steps_charged, loop.primitive_steps_charged,
             len(episode.discrepancies)),
            expected_footer,
        )
        # the human-facing outcome/reason line is part of the accepted story too
        self.assertEqual((episode.outcome.value.upper(), episode.reason), expected_outcome)

    def test_symbolic_primary_matches_its_baseline_transcript(self):
        self._assert_matches(OrchestrationPolicy.SYMBOLIC_PRIMARY)

    def test_advisory_two_track_matches_its_baseline_transcript(self):
        self._assert_matches(OrchestrationPolicy.ADVISORY_TWO_TRACK)


class TestDesignedDiscrepanciesStayVisible(unittest.TestCase):
    """Phase 0 acceptance: the same three designed physical discrepancies remain visible
    under each policy; none is silently patched. All three are the optimistic-symbolic
    story: the SAME applicable Push call fails in the backend three times."""

    def _designed(self, episode):
        return [d for d in episode.discrepancies
                if d.kind is DiscrepancyKind.EXECUTION_FAILURE_OF_APPLICABLE_SKILL]

    def test_each_policy_shows_exactly_three_on_one_repeated_call(self):
        for policy in _TRANSCRIPTS:
            with self.subTest(policy=policy.value):
                _, episode = _episode(policy)
                designed = self._designed(episode)
                self.assertEqual(len(designed), 3)
                self.assertEqual(len(episode.discrepancies), 3,
                                 "no additional discrepancy kinds in the accepted run")
                self.assertEqual({str(d.call) for d in designed},
                                 {"Push(agent_0; box_1; delivery_zone)"})

    def test_failures_really_executed_and_charged(self):
        """The failures are realized backend executions, not pre-filtered: each failing
        cycle carries an execution result and its own attached discrepancy."""
        for policy in _TRANSCRIPTS:
            with self.subTest(policy=policy.value):
                _, episode = _episode(policy)
                failing = [e for e in episode.history.entries
                           if e.execution is not None
                           and e.execution.outcome is not ExecutionOutcome.SUCCESS]
                self.assertEqual(len(failing), 3)
                for entry in failing:
                    self.assertIn(
                        DiscrepancyKind.EXECUTION_FAILURE_OF_APPLICABLE_SKILL,
                        [d.kind for d in entry.discrepancies],
                    )


if __name__ == "__main__":
    unittest.main()
