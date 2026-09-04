"""R3 comparison-lifecycle tests (report Phase 3).

Phase 3 acceptance, made mechanical:

- the comparator contains no direct backend calls and does not choose an action
  (`TestComparatorScopeDiscipline`: import allowlist + no decision/execution surface);
- the generic runtime holds no agent/box/zone rule — the equivalence rule is domain-owned
  and INJECTED (`TestActionEquivalenceIsDomainOwned`: attribute-access scan of the
  comparator source, plus a substitute equivalence changing the classification);
- the orchestration policy receives the comparison report BEFORE deciding
  (`TestComparisonReachesThePolicyBeforeTheDecision`);
- current V1 divergence classifications remain covered (`TestStructuredReport` maps every
  frozen kind to its aspect/severity, and the byte-identical trace payloads are pinned;
  the pre-R3 unit suite in tests/test_p4_runtime.py::TestComparator still runs against the
  legacy compare_tracks wrapper);
- a policy can REACT to a contradiction while symbolic-primary intentionally ignores it
  (`TestPolicyReactionToContradiction`);
- the confidence threshold is constructor configuration, not a hidden module rule
  (`TestConfigurableThreshold`);
- a malformed proposal no longer erases independent findings (`TestStructuredReport`).

Offline and deterministic: the only environment touched is the local adapter.
"""
import ast
import os
import pathlib
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ENV_DIR = os.path.join(_REPO_ROOT, "functional_layer", "custom_env", "box_push", "env")
for _p in (_REPO_ROOT, _ENV_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from domain.box_push_v1 import (
    AGENT_0,
    AGENT_1,
    BOX_HEAVY,
    BOX_LIGHT,
    DELIVERY_ZONE,
    TASK_DELIVER_BOTH,
    BoxPushActionEquivalence,
)
from nl.track import GroundedProposal, MalformedProposal
from shared.contracts import (
    ComparedAspect,
    ComparisonReport,
    FindingSeverity,
    Halt,
    ProposalComparator,
    TrackRequest,
)
from shared.divergence import DivergenceKind
from shared.orchestration_config import OrchestrationConfig, OrchestrationPolicy
from shared.reports import ConfidenceReport, CoverageReport
from shared.skills import GroundedSkillCall, MalformedCall, SkillName

from app.box_push_v1 import build_loop
from app.comparator import (
    DEFAULT_COMPARATOR,
    LOW_CONFIDENCE,
    BoxPushActionComparator,
    compare_tracks,
)
from runtime.policies import AdvisoryTwoTrackPolicy, SymbolicPrimaryPolicy

GOTO = GroundedSkillCall(SkillName.GOTO_PUSH_POSE, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE)
GOTO_A1 = GroundedSkillCall(SkillName.GOTO_PUSH_POSE, (AGENT_1,), BOX_LIGHT, DELIVERY_ZONE)
PUSH = GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE)
GOTO_HEAVY = GroundedSkillCall(SkillName.GOTO_PUSH_POSE, (AGENT_0,), BOX_HEAVY, DELIVERY_ZONE)
WAIT = GroundedSkillCall(SkillName.WAIT, (AGENT_0,))


def _proposal(call=None, malformed=None, residual=(), confidence=1.0):
    coverage = CoverageReport(covered=("x",), residual=tuple(residual))
    if malformed is not None:                       # R6: the two proposal variants
        return MalformedProposal(malformed=malformed, coverage=coverage)
    return GroundedProposal(
        call=call, coverage=coverage,
        confidence=ConfidenceReport(source="nl", confidence=confidence),
    )


class _StubTrack:
    def __init__(self, proposals):
        self._proposals = list(proposals)
        self.proposed = 0

    def observe(self, snapshot, skill=None, outcome=None):
        pass

    def propose(self, task):
        self.proposed += 1
        return self._proposals.pop(0) if self._proposals else _proposal(WAIT, residual=("w",))


class TestStructuredReport(unittest.TestCase):
    """Every frozen V1 classification, now with aspect + severity + evidence structure,
    and byte-identical TrackDivergence payloads underneath."""

    def _one(self, report):
        self.assertEqual(len(report.findings), 1)
        return report.findings[0]

    def test_agreement_is_an_empty_report_not_an_absent_one(self):
        report = DEFAULT_COMPARATOR.compare(GOTO, _proposal(GOTO))
        self.assertIsInstance(report, ComparisonReport)
        self.assertEqual(report.findings, ())
        self.assertFalse(report.contradicted)
        self.assertTrue(report.all_benign)          # vacuously: nothing diverged

    def test_no_proposal_compares_to_an_empty_report(self):
        self.assertEqual(DEFAULT_COMPARATOR.compare(GOTO, None).findings, ())

    def test_contradiction_finding_structure(self):
        finding = self._one(DEFAULT_COMPARATOR.compare(GOTO, _proposal(PUSH)))
        self.assertIs(finding.aspect, ComparedAspect.ACTION_CHOICE)
        self.assertIs(finding.severity, FindingSeverity.ATTENTION)
        self.assertIs(finding.classification, DivergenceKind.CONTRADICTION)
        self.assertEqual(finding.summary, "tracks propose different actions")
        self.assertEqual(finding.divergence.symbolic_view, str(GOTO))
        self.assertEqual(finding.divergence.nl_view, str(PUSH))

    def test_benign_agent_binding_finding_structure(self):
        finding = self._one(DEFAULT_COMPARATOR.compare(GOTO, _proposal(GOTO_A1)))
        self.assertIs(finding.aspect, ComparedAspect.ACTION_CHOICE)
        self.assertIs(finding.severity, FindingSeverity.BENIGN)
        self.assertIs(finding.classification, DivergenceKind.BENIGN_ABSTRACTION_MISMATCH)
        self.assertTrue(finding.divergence.is_benign)

    def test_outside_model_and_confidence_and_residual_aspects(self):
        outside = self._one(DEFAULT_COMPARATOR.compare(GOTO, _proposal(WAIT, residual=("r",))))
        self.assertIs(outside.aspect, ComparedAspect.MODEL_COVERAGE)
        self.assertIs(outside.classification, DivergenceKind.COVERAGE_GAP)
        self.assertEqual(outside.divergence.residual, ("r",))
        residual = self._one(DEFAULT_COMPARATOR.compare(GOTO, _proposal(GOTO, residual=("r",))))
        self.assertIs(residual.aspect, ComparedAspect.TASK_TRANSLATION)
        self.assertIs(residual.classification, DivergenceKind.TRANSLATION_RESIDUAL)
        confidence = self._one(DEFAULT_COMPARATOR.compare(GOTO, _proposal(GOTO, confidence=0.4)))
        self.assertIs(confidence.aspect, ComparedAspect.CONFIDENCE)
        self.assertIs(confidence.classification, DivergenceKind.CONFIDENCE_MISMATCH)

    def test_malformed_no_longer_erases_the_independent_residual_finding(self):
        """Phase 3 item 6: pre-R3 the malformed branch returned early and the
        task-translation residual vanished. Both findings must now stand."""
        report = DEFAULT_COMPARATOR.compare(
            GOTO,
            _proposal(malformed=MalformedCall("garbage", raw="x"),
                      residual=("clause: sing a song",)),
        )
        self.assertEqual(
            [(f.aspect, f.classification) for f in report.findings],
            [(ComparedAspect.PROPOSAL_FORM, DivergenceKind.COVERAGE_GAP),
             (ComparedAspect.TASK_TRANSLATION, DivergenceKind.TRANSLATION_RESIDUAL)],
        )
        self.assertEqual(report.findings[1].divergence.residual, ("clause: sing a song",))

    def test_malformed_without_residual_is_still_exactly_one_finding(self):
        report = DEFAULT_COMPARATOR.compare(
            GOTO, _proposal(malformed=MalformedCall("garbage", raw="x")))
        (finding,) = report.findings
        self.assertIs(finding.aspect, ComparedAspect.PROPOSAL_FORM)
        self.assertIn("MalformedCall", finding.divergence.nl_view)

    def test_legacy_wrapper_equals_the_report_divergences(self):
        for proposal in (_proposal(PUSH, confidence=0.4), _proposal(GOTO_A1), None,
                         _proposal(malformed=MalformedCall("g", raw="x"), residual=("r",))):
            self.assertEqual(
                compare_tracks(GOTO, proposal),
                DEFAULT_COMPARATOR.compare(GOTO, proposal).divergences,
            )

    def test_trace_payloads_are_byte_identical_to_the_pre_r3_comparator(self):
        """The serialized trace channel must not move: pin the canonical() dict of a
        representative divergence of every kind."""
        (contradiction,) = compare_tracks(GOTO, _proposal(PUSH))
        self.assertEqual(contradiction.canonical(), {
            "channel": "TrackDivergence", "kind": "contradiction",
            "message": "tracks propose different actions",
            "nl_view": str(PUSH), "symbolic_view": str(GOTO), "residual": [],
        })
        (benign,) = compare_tracks(GOTO, _proposal(GOTO_A1))
        self.assertEqual(
            benign.message,
            "same skill/box/zone, different agent binding — symbolically "
            "equivalent under non-exclusive optimism (Decision 6)",
        )
        (confidence,) = compare_tracks(GOTO, _proposal(GOTO, confidence=0.4))
        self.assertIn("NL confidence 0.4 below 0.75", confidence.message)


class TestConfigurableThreshold(unittest.TestCase):
    def test_threshold_is_constructor_configuration(self):
        strict = BoxPushActionComparator(
            BoxPushActionEquivalence(), low_confidence_threshold=0.95)
        lax = BoxPushActionComparator(
            BoxPushActionEquivalence(), low_confidence_threshold=0.2)
        proposal = _proposal(GOTO, confidence=0.6)
        self.assertEqual(
            [f.classification for f in strict.compare(GOTO, proposal).findings],
            [DivergenceKind.CONFIDENCE_MISMATCH],
        )
        self.assertEqual(lax.compare(GOTO, proposal).findings, ())

    def test_default_keeps_the_accepted_exact_boundary(self):
        # review X8: the boundary is exact — 0.75 itself is NOT below the threshold
        self.assertEqual(DEFAULT_COMPARATOR.low_confidence_threshold, LOW_CONFIDENCE)
        self.assertEqual(DEFAULT_COMPARATOR.compare(GOTO, _proposal(GOTO, confidence=0.75)).findings, ())
        self.assertTrue(DEFAULT_COMPARATOR.compare(GOTO, _proposal(GOTO, confidence=0.7499)).findings)

    def test_threshold_is_validated(self):
        with self.assertRaises(ValueError):
            BoxPushActionComparator(BoxPushActionEquivalence(), low_confidence_threshold=1.5)

    def test_raw_confidence_and_source_survive_unclaimed(self):
        """Item 4's second half: the comparator uses the confidence only descriptively —
        the raw value appears verbatim in the evidence, the proposal's ConfidenceReport is
        not replaced or rescaled by comparison, and no comparator output claims a
        calibrated measure."""
        proposal = _proposal(GOTO, confidence=0.4)
        report = DEFAULT_COMPARATOR.compare(GOTO, proposal)
        (finding,) = report.findings
        self.assertIn("NL confidence 0.4", finding.summary)     # raw value, verbatim
        self.assertEqual((proposal.confidence.source, proposal.confidence.confidence),
                         ("nl", 0.4))                            # untouched by comparison
        for attr in ("probability", "calibrated", "calibration"):
            self.assertFalse(hasattr(report, attr))
            self.assertFalse(hasattr(finding, attr))


class TestActionEquivalenceIsDomainOwned(unittest.TestCase):
    def test_the_domain_rule_answers_decision_6(self):
        equivalence = BoxPushActionEquivalence()
        reason = equivalence.benign_equivalence(GOTO_A1, GOTO)
        self.assertIsNotNone(reason)
        self.assertIn("Decision 6", reason)
        self.assertIsNone(equivalence.benign_equivalence(GOTO_HEAVY, GOTO))
        self.assertIsNone(equivalence.benign_equivalence(PUSH, GOTO))

    def test_the_rule_is_injected_not_baked_in(self):
        """Substituting the equivalence changes the classification: the comparator holds
        no agent-binding rule of its own."""
        class _NothingIsEquivalent:
            def benign_equivalence(self, proposed, selected, /):
                return None

        comparator = BoxPushActionComparator(_NothingIsEquivalent())
        (finding,) = comparator.compare(GOTO, _proposal(GOTO_A1)).findings
        self.assertIs(finding.classification, DivergenceKind.CONTRADICTION)

        class _EverythingIsEquivalent:
            def benign_equivalence(self, proposed, selected, /):
                return "test equivalence: everything matches"

        comparator = BoxPushActionComparator(_EverythingIsEquivalent())
        (finding,) = comparator.compare(GOTO, _proposal(PUSH)).findings
        self.assertIs(finding.classification, DivergenceKind.BENIGN_ABSTRACTION_MISMATCH)
        self.assertEqual(finding.summary, "test equivalence: everything matches")

    def test_comparator_source_holds_no_agent_box_zone_rule(self):
        """Acceptance: the generic side's comparison rules mention no agents/boxes/zones.
        Mechanical form: the comparator source never reads a .box/.zone/.agents attribute
        (the extracted equivalence rule was exactly such a read)."""
        source = pathlib.Path(_REPO_ROOT, "app", "comparator.py").read_text("utf-8")
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Attribute):
                self.assertNotIn(
                    node.attr, {"box", "zone", "agents"},
                    f"app/comparator.py reads .{node.attr} — the domain equivalence "
                    f"rule must own that vocabulary",
                )


class TestComparatorScopeDiscipline(unittest.TestCase):
    """Acceptance: no direct backend calls; the comparator does not choose an action."""

    def test_comparator_imports_no_backend_executor_or_environment(self):
        tree = ast.parse(pathlib.Path(_REPO_ROOT, "app", "comparator.py").read_text("utf-8"))
        allowed = {"__future__", "typing", "shared", "domain", "nl"}
        for node in ast.walk(tree):
            roots = []
            if isinstance(node, ast.Import):
                roots = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots = [node.module.split(".")[0]]
            for root in roots:
                self.assertIn(
                    root, allowed,
                    f"app/comparator.py imports {root!r} — a comparator may see typed "
                    f"channels only, never the backend/executor/loop",
                )

    def test_comparator_output_is_evidence_only(self):
        """A report carries findings — no call to enact, no decision member. The protocol
        conformance is witnessed statically in tests/contract_conformance.py."""
        self.assertIsInstance(DEFAULT_COMPARATOR, ProposalComparator)
        report = DEFAULT_COMPARATOR.compare(GOTO, _proposal(PUSH))
        self.assertFalse(hasattr(report, "call"))
        self.assertFalse(hasattr(report, "decision"))


class TestComparisonReachesThePolicyBeforeTheDecision(unittest.TestCase):
    """Acceptance: the orchestration policy receives the comparison report (Phase 3
    item 7) — pinned at the decide() seam, through the real loop."""

    def test_advisory_decides_with_the_report_of_the_call_it_enacts(self):
        from box_push_v1_adapter import BoxPushV1Adapter
        from runtime.loop import EpisodeOutcome, ExecutiveLoopManager

        class _RecordingAdvisory(AdvisoryTwoTrackPolicy):
            def __init__(self, **kw):
                super().__init__(**kw)
                self.decide_contexts = []

            def decide(self, context, /):
                self.decide_contexts.append(context)
                return super().decide(context)

        policy = _RecordingAdvisory(repeated_failure_threshold=3)
        contradicting = [_proposal(PUSH, confidence=0.4)] * 40
        loop = build_loop(
            BoxPushV1Adapter(), TASK_DELIVER_BOTH,
            OrchestrationConfig(policy=OrchestrationPolicy.ADVISORY_TWO_TRACK),
            nl_track=_StubTrack(contradicting), policy=policy,
        )
        episode = loop.run()
        # frozen V1: the advisory policy SEES the evidence and still decides identically
        self.assertIs(episode.outcome, EpisodeOutcome.GOAL_REACHED)
        enacting = [c for c in policy.decide_contexts if c.nl_proposal is not None]
        self.assertTrue(enacting)
        for context in enacting:
            self.assertIsNotNone(context.comparison)       # report exists AT decide time
        # and the executed trace rows carry exactly the pre-decision report's payloads
        executed = [e for e in episode.history.entries if e.execution is not None]
        with_report = [c for c in policy.decide_contexts if c.comparison is not None]
        self.assertEqual(len(executed), len(with_report))
        for entry, context in zip(executed, with_report):
            self.assertEqual(entry.divergences, context.comparison.divergences)
            for d in entry.divergences:
                if d.symbolic_view:
                    self.assertEqual(d.symbolic_view, str(entry.selected_call))

    def test_symbolic_primary_never_has_a_report_to_ignore(self):
        from box_push_v1_adapter import BoxPushV1Adapter
        from runtime.loop import EpisodeOutcome, ExecutiveLoopManager

        class _RecordingPrimary(SymbolicPrimaryPolicy):
            def __init__(self, **kw):
                super().__init__(**kw)
                self.comparisons = []

            def decide(self, context, /):
                self.comparisons.append(context.comparison)
                return super().decide(context)

        policy = _RecordingPrimary(repeated_failure_threshold=3)
        track = _StubTrack([_proposal(PUSH)] * 40)
        loop = build_loop(
            BoxPushV1Adapter(), TASK_DELIVER_BOTH,
            OrchestrationConfig(policy=OrchestrationPolicy.SYMBOLIC_PRIMARY),
            nl_track=track, policy=policy,
        )
        episode = loop.run()
        self.assertIs(episode.outcome, EpisodeOutcome.HALTED_REPEATED_FAILURE)
        self.assertEqual(track.proposed, 0)                # declared no inputs, none acquired
        self.assertEqual(policy.comparisons, [None] * len(policy.comparisons))
        self.assertTrue(policy.comparisons)


class TestPolicyReactionToContradiction(unittest.TestCase):
    """Acceptance: a policy CAN react to a contradiction — impossible pre-R3, when the
    comparison was computed only after the decision — while symbolic-primary intentionally
    ignores the whole channel (previous test) and the shipped advisory policy sees it yet
    decides identically (frozen V1)."""

    def test_a_reactive_policy_halts_on_contradicted_evidence(self):
        from box_push_v1_adapter import BoxPushV1Adapter
        from runtime.loop import EpisodeOutcome, ExecutiveLoopManager

        class _ContradictionHaltPolicy(AdvisoryTwoTrackPolicy):
            def required_inputs(self, context, /):
                return TrackRequest(nl_proposal=True)

            def decide(self, context, /):
                if context.comparison is not None and context.comparison.contradicted:
                    return Halt(reason="tracks contradict — reactive test policy stops")
                return super().decide(context)

        loop = build_loop(
            BoxPushV1Adapter(), TASK_DELIVER_BOTH,
            OrchestrationConfig(policy=OrchestrationPolicy.ADVISORY_TWO_TRACK),
            nl_track=_StubTrack([_proposal(PUSH)] * 4),    # contradicts the first head
            policy=_ContradictionHaltPolicy(repeated_failure_threshold=3),
        )
        episode = loop.run()
        self.assertIs(episode.outcome, EpisodeOutcome.HALTED_NO_PLAN)
        self.assertEqual(episode.reason, "tracks contradict — reactive test policy stops")
        # nothing was executed: the reaction happened BEFORE any enactment
        self.assertEqual(loop.executive_steps_charged, 0)
        self.assertEqual([e for e in episode.history.entries if e.execution is not None], [])

    def test_the_shipped_advisory_policy_still_treats_contradiction_as_evidence_only(self):
        from box_push_v1_adapter import BoxPushV1Adapter
        from runtime.loop import EpisodeOutcome, ExecutiveLoopManager
        loop = build_loop(
            BoxPushV1Adapter(), TASK_DELIVER_BOTH,
            OrchestrationConfig(policy=OrchestrationPolicy.ADVISORY_TWO_TRACK),
            nl_track=_StubTrack([_proposal(PUSH, confidence=0.4)] * 40),
        )
        episode = loop.run()
        self.assertIs(episode.outcome, EpisodeOutcome.GOAL_REACHED)


class TestAcquisitionAccounting(unittest.TestCase):
    """Pin the R3 consultation counts (test-reviewer WARN): exactly one acquisition per
    cycle that requests, exactly one consultation per enacting decision in the accepted
    scenario, and the deliberate non-recording of gated-cycle evidence."""

    def test_accepted_advisory_episode_consults_once_per_enacting_decision(self):
        from box_push_v1_adapter import BoxPushV1Adapter
        from runtime.loop import EpisodeOutcome, ExecutiveLoopManager
        track = _StubTrack([])                  # falls back to a canned proposal each call
        loop = build_loop(
            BoxPushV1Adapter(), TASK_DELIVER_BOTH,
            OrchestrationConfig(policy=OrchestrationPolicy.ADVISORY_TWO_TRACK),
            nl_track=track,
        )
        episode = loop.run()
        self.assertIs(episode.outcome, EpisodeOutcome.GOAL_REACHED)
        executed = [e for e in episode.history.entries if e.execution is not None]
        # the accepted per-enactment consultation frequency, preserved across the reorder:
        # one propose() per enacting decision — none for REQUEST_PROPOSAL/goal cycles
        self.assertEqual(track.proposed, len(executed))
        for entry in executed:
            self.assertIsNotNone(entry.nl_proposal)

    def test_gated_out_enactment_consumes_one_proposal_and_records_none(self):
        """R3 lifecycle consequence, pinned: acquisition precedes the post-decision gates,
        so a stale standing recovery costs exactly ONE consultation — and the REPLAN entry
        keeps the pre-R3 trace shape (no proposal columns, no divergences): computed
        evidence for a gated-out call is deliberately not recorded."""
        from box_push_v1_adapter import BoxPushV1Adapter
        from runtime.loop import ExecutiveLoopManager
        from shared.orchestration_config import ExecutiveDecision
        track = _StubTrack([_proposal(GOTO)] * 4)
        loop = build_loop(
            BoxPushV1Adapter(), TASK_DELIVER_BOTH,
            OrchestrationConfig(policy=OrchestrationPolicy.ADVISORY_TWO_TRACK),
            nl_track=track,
        )
        loop.env.reset()
        snapshot = loop._sync()
        stale = GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BOX_HEAVY, DELIVERY_ZONE)
        loop._pending_recovery = (stale,)
        outcome = loop._run_cycle(0, snapshot)
        self.assertIsNone(outcome)                             # dropped, episode continues
        self.assertEqual(track.proposed, 1)
        entry = loop.history.entries[-1]
        self.assertIs(entry.decision, ExecutiveDecision.REPLAN)
        self.assertIsNone(entry.nl_proposal)
        self.assertEqual(entry.divergences, ())

    def test_acquisition_is_cached_across_iterations_within_one_cycle(self):
        """Kills the cache-removal mutant the reviewer found surviving: a cycle that
        re-selects repeatedly (inapplicable head -> replan, up to the rejection bound)
        under an always-requesting policy must still consult propose() exactly once."""
        from box_push_v1_adapter import BoxPushV1Adapter
        from runtime.loop import EpisodeOutcome, ExecutiveLoopManager
        from shared.ids import AgentId, BoxId, ZoneId
        from shared.planner_result import PlanFound

        class _AlwaysRequesting(AdvisoryTwoTrackPolicy):
            def required_inputs(self, context, /):
                return TrackRequest(nl_proposal=True)

        inapplicable = GroundedSkillCall(
            SkillName.PUSH, (AGENT_0,), BOX_HEAVY, DELIVERY_ZONE)  # no pose -> inapplicable

        class _InapplicableHeadLoop(ExecutiveLoopManager):
            def _plan(self, snapshot):
                return PlanFound(plan=(inapplicable,))

        track = _StubTrack([_proposal(GOTO)] * 40)
        loop = build_loop(
            BoxPushV1Adapter(), TASK_DELIVER_BOTH,
            OrchestrationConfig(policy=OrchestrationPolicy.ADVISORY_TWO_TRACK),
            nl_track=track,
            policy=_AlwaysRequesting(repeated_failure_threshold=3),
            loop_class=_InapplicableHeadLoop,
        )
        loop.env.reset()
        snapshot = loop._sync()
        outcome = loop._run_cycle(0, snapshot)
        self.assertIsNotNone(outcome)          # rejection bound faulted the cycle (default)
        self.assertIs(outcome.outcome, EpisodeOutcome.FAULTED)
        self.assertEqual(track.proposed, 1)    # many re-selections, ONE acquisition


if __name__ == "__main__":
    unittest.main()
