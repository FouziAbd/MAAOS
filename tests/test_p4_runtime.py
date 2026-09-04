"""P4 runtime: comparator units, orchestrator routing, and the executive loop's fault/budget/
rejection paths — everything case 7 of the acceptance suite does not cover (its review W6).

Offline and deterministic. The live backend is used where the path needs real execution; the
fault/planner paths use minimal injection seams (subclassing the loop's _plan, or a wrapper
env) — never monkeypatching product internals from outside.
"""
import os
import pathlib
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ENV_DIR = os.path.join(_REPO_ROOT, "functional_layer", "custom_env", "box_push", "env")
for _p in (_REPO_ROOT, _ENV_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from box_push_v1_adapter import BoxPushV1Adapter

from domain.box_push_v1 import (
    AGENT_0,
    AGENT_1,
    BOX_HEAVY,
    BOX_LIGHT,
    DELIVERY_ZONE,
    TASK_DELIVER_BOTH,
)
from nl.track import NLProposal
from shared.contracts import TrackRequest
from shared.divergence import DivergenceKind
from shared.execution import ExecutionOutcome
from shared.faults import FaultKind, InfrastructureFault, InfrastructureFaultError
from shared.ids import AgentId, BoxId
from shared.orchestration_config import (
    ExecutiveDecision,
    OrchestrationConfig,
    OrchestrationPolicy,
)
from shared.planner_result import NoPlan, PlanFound, PlannerFailure
from shared.reports import ConfidenceReport, CoverageReport
from shared.skills import (
    GroundedSkillCall,
    MalformedCall,
    SkillName,
    SymbolicallyInapplicable,
    ValidatedCall,
)
from runtime.comparator import compare_tracks
from runtime.loop import EpisodeOutcome, ExecutiveLoopManager
from runtime.orchestrator import decide

GOTO = GroundedSkillCall(SkillName.GOTO_PUSH_POSE, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE)
PUSH = GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE)
GOTO_A1 = GroundedSkillCall(SkillName.GOTO_PUSH_POSE, (AGENT_1,), BOX_LIGHT, DELIVERY_ZONE)
WAIT = GroundedSkillCall(SkillName.WAIT, (AGENT_0,))


def _proposal(call=None, malformed=None, residual=(), confidence=1.0):
    return NLProposal(
        call=call, malformed=malformed,
        coverage=CoverageReport(covered=("x",), residual=tuple(residual)),
        confidence=ConfidenceReport(source="nl", confidence=confidence) if call else None,
        repaired=False,
    )


# ── comparator ─────────────────────────────────────────────────────────────────────

class TestComparator(unittest.TestCase):
    def test_no_nl_proposal_means_no_divergence(self):
        self.assertEqual(compare_tracks(GOTO, None), ())

    def test_agreement_produces_no_divergence(self):
        self.assertEqual(compare_tracks(GOTO, _proposal(GOTO)), ())

    def test_malformed_nl_proposal_is_a_coverage_gap(self):
        (d,) = compare_tracks(GOTO, _proposal(malformed=MalformedCall("garbage", raw="x")))
        self.assertIs(d.kind, DivergenceKind.COVERAGE_GAP)
        self.assertIn("MalformedCall", d.nl_view)

    def test_outside_model_proposal_is_a_coverage_gap_with_residual(self):
        (d,) = compare_tracks(
            GOTO, _proposal(WAIT, residual=("Wait is outside the V1 symbolic model",))
        )
        self.assertIs(d.kind, DivergenceKind.COVERAGE_GAP)
        self.assertTrue(d.residual)

    def test_task_text_residual_is_translation_residual(self):
        divergences = compare_tracks(GOTO, _proposal(GOTO, residual=("clause: sing a song",)))
        self.assertEqual([d.kind for d in divergences],
                         [DivergenceKind.TRANSLATION_RESIDUAL])

    def test_different_action_is_a_contradiction(self):
        divergences = compare_tracks(GOTO, _proposal(PUSH))
        self.assertIn(DivergenceKind.CONTRADICTION, [d.kind for d in divergences])

    def test_agent_binding_only_difference_is_benign(self):
        divergences = compare_tracks(GOTO, _proposal(GOTO_A1))
        self.assertEqual([d.kind for d in divergences],
                         [DivergenceKind.BENIGN_ABSTRACTION_MISMATCH])
        self.assertTrue(divergences[0].is_benign)

    def test_low_confidence_against_a_standing_plan_is_a_mismatch(self):
        divergences = compare_tracks(GOTO, _proposal(GOTO, confidence=0.4))
        self.assertEqual([d.kind for d in divergences],
                         [DivergenceKind.CONFIDENCE_MISMATCH])
        # the boundary is exact: 0.75 itself is NOT below the threshold (review X8)
        self.assertEqual(compare_tracks(GOTO, _proposal(GOTO, confidence=0.75)), ())

    def test_comparator_never_emits_discrepancies_or_faults(self):
        """Channel separation: every emission is a TrackDivergence."""
        from shared.divergence import TrackDivergence
        for proposal in (_proposal(PUSH, confidence=0.1),
                         _proposal(malformed=MalformedCall("x", raw="y"))):
            for d in compare_tracks(GOTO, proposal):
                self.assertIsInstance(d, TrackDivergence)


# ── orchestrator routing ───────────────────────────────────────────────────────────

class TestOrchestratorRouting(unittest.TestCase):
    CONFIG = OrchestrationConfig()

    def test_noplan_routes_to_halt_never_a_fault(self):
        d = decide(self.CONFIG, NoPlan(reason="unreachable"), None, 0)
        self.assertIs(d.decision, ExecutiveDecision.HALT)
        self.assertIn("semantic result", d.reason)

    def test_planner_failure_never_reaches_a_decision(self):
        with self.assertRaises(TypeError):     # typed raise — holds under -O too
            decide(self.CONFIG, PlannerFailure(error="boom"), None, 0)

    def test_applicable_head_executes(self):
        d = decide(self.CONFIG, PlanFound(plan=(GOTO,)), ValidatedCall(call=GOTO), 0)
        self.assertIs(d.decision, ExecutiveDecision.EXECUTE)
        self.assertEqual(d.call, GOTO)

    def test_inapplicable_head_replans(self):
        d = decide(self.CONFIG, PlanFound(plan=(GOTO,)),
                   SymbolicallyInapplicable(reason="drift"), 0)
        self.assertIs(d.decision, ExecutiveDecision.REPLAN)

    def test_threshold_split_is_the_policy_difference(self):
        primary = decide(self.CONFIG, PlanFound(plan=(PUSH,)), ValidatedCall(call=PUSH), 3)
        self.assertIs(primary.decision, ExecutiveDecision.HALT)
        advisory_config = OrchestrationConfig(policy=OrchestrationPolicy.ADVISORY_TWO_TRACK)
        advisory = decide(advisory_config, PlanFound(plan=(PUSH,)), ValidatedCall(call=PUSH), 3)
        self.assertIs(advisory.decision, ExecutiveDecision.REQUEST_PROPOSAL)

    def test_below_threshold_both_policies_execute(self):
        for policy in OrchestrationPolicy:
            config = OrchestrationConfig(policy=policy)
            d = decide(config, PlanFound(plan=(PUSH,)), ValidatedCall(call=PUSH), 2)
            self.assertIs(d.decision, ExecutiveDecision.EXECUTE)


# ── loop fault/budget/rejection paths ──────────────────────────────────────────────

class _PlannerFailureLoop(ExecutiveLoopManager):
    def _plan(self):
        return PlannerFailure(error="injected: solver crashed", timed_out=False)


class _InapplicableHeadLoop(ExecutiveLoopManager):
    """Planner that always proposes a symbolically inapplicable head (Push without pose)."""
    def _plan(self):
        return PlanFound(plan=(GroundedSkillCall(
            SkillName.PUSH, (AGENT_0,), BOX_HEAVY, DELIVERY_ZONE),))


class _CaseCEnv:
    """Wraps the adapter; the FIRST execute_skill raises a mid-execution (case-c) fault."""
    def __init__(self):
        self._inner = BoxPushV1Adapter()
        self._raised = False

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def execute_skill(self, call):
        if not self._raised:
            self._raised = True
            raise InfrastructureFaultError(InfrastructureFault(
                kind=FaultKind.BACKEND_API_EXCEPTION,
                message="injected mid-execution crash",
                detail="primitive_steps_before_failure=7",
            ))
        return self._inner.execute_skill(call)


class _FailingGotoEnv:
    """Wraps the adapter; every GotoPushPose returns a genuine FAILURE result (world untouched).
    Drives the public no-recovery-advice path: GotoPushPose is not a consuming skill, so the
    RecoveryProposer returns () for it."""
    def __init__(self):
        self._inner = BoxPushV1Adapter()

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def execute_skill(self, call):
        if call.skill is not SkillName.GOTO_PUSH_POSE:
            return self._inner.execute_skill(call)
        from shared.execution import (
            ExecutionResult, FailureStateClass, RawLabel, StepAccounting,
        )
        snapshot = self._inner.export_full_state()
        return ExecutionResult(
            call=call, outcome=ExecutionOutcome.FAILURE,
            pre_state=snapshot, post_state=snapshot,
            accounting=StepAccounting(executive_steps=1, primitive_steps=1),
            raw_label=RawLabel.BLOCKED, failure_class=FailureStateClass.UNCHANGED,
            detail="injected: goto always blocked",
        )


class _CaseAEnv:
    """The FIRST execute_skill completes and THEN faults — case (a): result attached."""
    def __init__(self):
        self._inner = BoxPushV1Adapter()
        self._raised = False

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def execute_skill(self, call):
        result = self._inner.execute_skill(call)
        if not self._raised:
            self._raised = True
            raise InfrastructureFaultError(InfrastructureFault(
                kind=FaultKind.EXECUTOR_MONITOR_PROTOCOL_FAILURE,
                message="injected post-flight violation after a completed attempt",
            ), result=result)
        return result


class TestLoopFaultAndBudgetPaths(unittest.TestCase):
    def test_planner_failure_becomes_a_typed_fault_and_short_circuits(self):
        loop = _PlannerFailureLoop(BoxPushV1Adapter(), TASK_DELIVER_BOTH)
        episode = loop.run()
        self.assertIs(episode.outcome, EpisodeOutcome.FAULTED)
        (fault,) = episode.history.entries[-1].faults
        self.assertIs(fault.kind, FaultKind.PLANNER_COMPUTATION_FAILURE)
        self.assertEqual(loop.executive_steps_charged, 0)      # nothing executed

    def test_noplan_through_the_loop_halts_semantically(self):
        """Case 5, loop-driven: a task naming an undeliverable goal in a universe where the
        planner cannot reach it — via the synthetic single-agent universe injection."""
        from shared.task import Task
        from symbolic import Universe
        task = Task(task_id="heavy-solo", description="Deliver the heavy box",
                    goal_delivered=(BOX_HEAVY,), zone=DELIVERY_ZONE)
        loop = ExecutiveLoopManager(BoxPushV1Adapter(), task)
        loop._universe = Universe(agents=(AGENT_0,), boxes=(BOX_HEAVY,), zone=DELIVERY_ZONE)
        episode = loop.run()
        self.assertIs(episode.outcome, EpisodeOutcome.HALTED_NO_PLAN)
        self.assertIn("semantic result", episode.reason)
        final = episode.history.entries[-1]
        self.assertIsInstance(final.symbolic_result, NoPlan)
        self.assertIs(final.decision, ExecutiveDecision.HALT)
        self.assertEqual(loop.executive_steps_charged, 0)

    def test_rejection_guard_bounds_free_replans(self):
        """Decision 2: pre-executor rejections are free, so the loop must bound them."""
        loop = _InapplicableHeadLoop(
            BoxPushV1Adapter(), TASK_DELIVER_BOTH,
            OrchestrationConfig(max_rejections_per_cycle=2),
        )
        episode = loop.run()
        self.assertIs(episode.outcome, EpisodeOutcome.FAULTED)
        (fault,) = episode.history.entries[-1].faults
        self.assertIs(fault.kind, FaultKind.EXECUTOR_MONITOR_PROTOCOL_FAILURE)
        self.assertIn("rejections", fault.message)
        self.assertEqual(loop.executive_steps_charged, 0)

    def test_case_c_fault_charges_one_executive_and_the_detail_primitives(self):
        loop = ExecutiveLoopManager(_CaseCEnv(), TASK_DELIVER_BOTH)
        episode = loop.run()
        self.assertIs(episode.outcome, EpisodeOutcome.FAULTED)
        self.assertEqual(loop.executive_steps_charged, 1)      # charged from fault provenance
        self.assertEqual(loop.primitive_steps_charged, 7)
        self.assertEqual(episode.history.executive_steps_used, 0)  # NOT in recorded accounting
        # DECIDED: case-(c) does not feed repeated-failure counts
        entry = episode.history.entries[-1]
        self.assertEqual(
            loop.history.failure_count(entry.pre_state, entry.selected_call), 0
        )

    def test_case_c_charges_count_against_the_budget_not_just_recorded_sums(self):
        """Kills L13: a budget checked against RECORDED accounting alone under-charges exactly
        the case-(c) attempts a budget exists for (runtime/executive_history.py's own warning).
        Here the ONLY charge is the case-(c) fault — recorded sums stay 0."""
        loop = ExecutiveLoopManager(
            _CaseCEnv(), TASK_DELIVER_BOTH,
            OrchestrationConfig(executive_step_budget=1,
                                halt_on_infrastructure_fault=False),
        )
        episode = loop.run()
        self.assertIs(episode.outcome, EpisodeOutcome.BUDGET_EXHAUSTED)
        self.assertEqual(loop.executive_steps_charged, 1)
        self.assertEqual(episode.history.executive_steps_used, 0)

    def test_liveness_guard_terminates_a_zero_charge_fault_cycle(self):
        """Kills L14: in continue mode a permanently failing planner charges nothing, so no
        budget can end the episode — only the cross-cycle liveness guard can. (With the guard
        disabled this test HANGS, which the mutation harness counts as a kill via timeout.)"""
        loop = _PlannerFailureLoop(
            BoxPushV1Adapter(), TASK_DELIVER_BOTH,
            OrchestrationConfig(halt_on_infrastructure_fault=False,
                                max_rejections_per_cycle=3),
        )
        episode = loop.run()
        self.assertIs(episode.outcome, EpisodeOutcome.FAULTED)
        self.assertIn("liveness guard", episode.reason)
        self.assertEqual(loop.executive_steps_charged, 0)
        # guard bound (3) + 1 detection cycle + the guard's OWN typed fault entry: a FAULTED
        # episode must carry its fault in the record (architecture review W3)
        self.assertEqual(len(episode.history), 5)
        (guard_fault,) = episode.history.entries[-1].faults
        self.assertIs(guard_fault.kind, FaultKind.EXECUTOR_MONITOR_PROTOCOL_FAILURE)
        self.assertIn("liveness guard", guard_fault.message)
        self.assertTrue(episode.history.all_faults())          # never FAULTED with empty faults

    def test_monitor_is_wired_on_the_belief_not_a_reprojection(self):
        """Decisions §19.1 item 3: on this domain the belief and a fresh projection are
        EXTENSIONALLY EQUIVALENT for the monitored view, so no behavioural test can separate
        them (mutant L9 is equivalent) — the decision itself says the belief is the
        contractually correct argument, so the wiring is pinned at the identifier level,
        the same technique as the P0/P2 static guards."""
        import re as _re
        source = (pathlib.Path(_REPO_ROOT) / "runtime" / "loop.py").read_text(encoding="utf-8")
        self.assertRegex(source, _re.compile(r"pre_symbolic = self\.belief\.state"))
        self.assertNotIn("pre_symbolic = project(", source)

    def test_fault_continue_mode_survives_the_fault_and_completes(self):
        loop = ExecutiveLoopManager(
            _CaseCEnv(), TASK_DELIVER_BOTH,
            OrchestrationConfig(policy=OrchestrationPolicy.ADVISORY_TWO_TRACK,
                                halt_on_infrastructure_fault=False),
        )
        episode = loop.run()
        self.assertIs(episode.outcome, EpisodeOutcome.GOAL_REACHED)
        self.assertTrue(episode.history.all_faults())          # the fault IS in the record

    def test_case_a_fault_records_the_attached_result_and_charges_recorded_accounting(self):
        """Architecture review F1: a case-(a) fault's attached ExecutionResult IS the record —
        one executive step via RECORDED accounting (never _charge_case_c), post-state kept."""
        loop = ExecutiveLoopManager(_CaseAEnv(), TASK_DELIVER_BOTH)
        episode = loop.run()
        self.assertIs(episode.outcome, EpisodeOutcome.FAULTED)
        entry = episode.history.entries[-1]
        self.assertIsNotNone(entry.execution)                  # the result survived
        self.assertIsNotNone(entry.post_state)
        self.assertTrue(entry.faults)
        self.assertEqual(episode.history.executive_steps_used, 1)   # recorded, not extra
        self.assertEqual(loop.executive_steps_charged, 1)
        self.assertEqual(loop._extra_executive, 0)             # case-(c) charging NOT applied
        # FIRST-CLASS record (consistency round W3): decision + both prediction bases
        self.assertIs(entry.decision, ExecutiveDecision.EXECUTE)
        self.assertIsNotNone(entry.predicted_symbolic_key)
        self.assertIsNotNone(entry.predicted_world_key)
        # Decision-13.8 maintenance ran (W4): the completed goto established its in_pose
        self.assertTrue(loop.belief.tracked.literals)

    def test_case_a_in_continue_mode_needs_no_redundant_reestablishment(self):
        """W4 follow-through: with record_outcome applied on the case-(a) path, the episode
        completes in the normal 9 steps — before the fix the lost in_pose cost a 10th."""
        loop = ExecutiveLoopManager(
            _CaseAEnv(), TASK_DELIVER_BOTH,
            OrchestrationConfig(policy=OrchestrationPolicy.ADVISORY_TWO_TRACK,
                                halt_on_infrastructure_fault=False),
        )
        episode = loop.run()
        self.assertIs(episode.outcome, EpisodeOutcome.GOAL_REACHED)
        self.assertEqual(loop.executive_steps_charged, 9)
        self.assertEqual(len(episode.history.all_faults()), 1)

    def test_fault_carrying_failure_escalates_through_one_channel_only(self):
        """W2 reconciled: a case-(a) entry with a NON-SUCCESS attached result feeds the fault
        channel and must NOT also accrue repeated-failure counts."""
        class _CaseAFailEnv(_FailingGotoEnv):
            def execute_skill(self, call):
                result = super().execute_skill(call)
                if call.skill is SkillName.GOTO_PUSH_POSE:
                    raise InfrastructureFaultError(InfrastructureFault(
                        kind=FaultKind.EXECUTOR_MONITOR_PROTOCOL_FAILURE,
                        message="injected post-flight violation on a failed attempt",
                    ), result=result)
                return result

        loop = ExecutiveLoopManager(
            _CaseAFailEnv(), TASK_DELIVER_BOTH,
            OrchestrationConfig(halt_on_infrastructure_fault=False),
        )
        loop.env.reset()
        snapshot = loop._sync()
        loop._run_cycle(0, snapshot)
        entry = loop.history.entries[-1]
        self.assertTrue(entry.faults)
        self.assertIsNotNone(entry.execution)
        self.assertIsNot(entry.execution.outcome, ExecutionOutcome.SUCCESS)
        self.assertEqual(
            loop.history.failure_count(entry.pre_state, entry.execution.call), 0
        )

    def test_no_recovery_advice_halts_instead_of_spinning(self):
        """Test review F2 (public path): repeated failure of a NON-consuming skill under
        advisory yields no recovery advice; the loop must HALT, not spin REQUEST_PROPOSAL."""
        loop = ExecutiveLoopManager(
            _FailingGotoEnv(), TASK_DELIVER_BOTH,
            OrchestrationConfig(policy=OrchestrationPolicy.ADVISORY_TWO_TRACK),
        )
        episode = loop.run()
        self.assertIs(episode.outcome, EpisodeOutcome.HALTED_REPEATED_FAILURE)
        self.assertIn("no recovery advice available", episode.reason)
        final = episode.history.entries[-1]
        self.assertIs(final.decision, ExecutiveDecision.HALT)
        request = [e for e in episode.history.entries
                   if e.decision is ExecutiveDecision.REQUEST_PROPOSAL]
        self.assertEqual(len(request), 1)                      # asked once, then halted

    def test_primitive_budget_exhausts(self):
        """Test review F1: the primitive branch was shipped dead — a wait/wait-style episode
        is bounded by the EXECUTIVE budget, but primitive-heavy skills need this one."""
        loop = ExecutiveLoopManager(
            BoxPushV1Adapter(), TASK_DELIVER_BOTH,
            OrchestrationConfig(primitive_step_budget=5),
        )
        episode = loop.run()
        self.assertIs(episode.outcome, EpisodeOutcome.BUDGET_EXHAUSTED)
        self.assertIn("primitive budget", episode.reason)
        self.assertGreaterEqual(loop.primitive_steps_charged, 5)

    def test_goal_wins_the_budget_tie(self):
        """DECIDED (review X10): the goal test is free, so a completed task reports
        GOAL_REACHED even when the budget is simultaneously exhausted."""
        loop = ExecutiveLoopManager(
            BoxPushV1Adapter(), TASK_DELIVER_BOTH,
            OrchestrationConfig(policy=OrchestrationPolicy.ADVISORY_TWO_TRACK,
                                executive_step_budget=9),   # exactly the episode's step count
        )
        episode = loop.run()
        self.assertIs(episode.outcome, EpisodeOutcome.GOAL_REACHED)
        self.assertEqual(loop.executive_steps_charged, 9)

    def test_liveness_guard_reset_tolerates_interleaved_zero_charge_cycles(self):
        """Test review W3: NON-consecutive zero-charge cycles must never trip the guard —
        pins the reset branch. Zero-charge CYCLES are manufactured for real: a stale
        (inapplicable) recovery call planted before every other cycle produces a typed
        REPLAN entry that charges nothing; the following cycle executes normally. With more
        stale cycles in total than the bound, only the RESET keeps the episode alive."""
        stale = GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BOX_HEAVY, DELIVERY_ZONE)

        class _StaleAdviceLoop(ExecutiveLoopManager):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                self._cycle_no = 0

            def _run_cycle(self, step, snapshot):
                self._cycle_no += 1
                if self._cycle_no % 2 and self._cycle_no <= 12:
                    self._pending_recovery = (stale,)
                return super()._run_cycle(step, snapshot)

        loop = _StaleAdviceLoop(
            BoxPushV1Adapter(), TASK_DELIVER_BOTH,
            OrchestrationConfig(policy=OrchestrationPolicy.ADVISORY_TWO_TRACK,
                                max_rejections_per_cycle=3),
        )
        episode = loop.run()
        self.assertIs(episode.outcome, EpisodeOutcome.GOAL_REACHED)
        zero_charge = [e for e in episode.history.entries
                       if e.execution is None and e.decision is ExecutiveDecision.REPLAN]
        self.assertGreater(len(zero_charge), loop.config.max_rejections_per_cycle)

    def test_ungrounded_fault_drops_pending_recovery_in_continue_mode(self):
        """Test review X5: ghost advice must not stand after its fault, or continue mode
        loops on it until the liveness guard fires with a misleading reason."""
        loop = ExecutiveLoopManager(
            BoxPushV1Adapter(), TASK_DELIVER_BOTH,
            OrchestrationConfig(halt_on_infrastructure_fault=False),
        )
        loop.env.reset()
        snapshot = loop._sync()
        ghost = GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BoxId.parse("box_9"), DELIVERY_ZONE)
        loop._pending_recovery = (ghost,)
        outcome = loop._run_cycle(0, snapshot)
        self.assertIsNone(outcome)                             # continue mode: episode goes on
        self.assertEqual(loop._pending_recovery, ())

    def test_monitor_value_error_is_wrapped_into_a_typed_fault(self):
        """§19.1 item 4, directly exercised (test review W7): the escape is unreachable in the
        single-zone V1 domain, so the wrap is pinned at the unit seam."""
        from shared.ids import ZoneId
        loop = ExecutiveLoopManager(BoxPushV1Adapter(), TASK_DELIVER_BOTH)
        loop.env.reset()
        loop._sync()
        alien = GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BOX_LIGHT, ZoneId("mars"))
        from shared.execution import ExecutionResult, StepAccounting
        snapshot = loop.env.export_full_state()
        doctored = ExecutionResult(
            call=alien, outcome=ExecutionOutcome.SUCCESS,
            pre_state=snapshot, post_state=snapshot,
            accounting=StepAccounting(executive_steps=1, primitive_steps=1),
        )
        discrepancies, fault = loop._monitor(loop.belief.state, doctored)
        self.assertEqual(discrepancies, ())
        self.assertIsNotNone(fault)
        self.assertIs(fault.kind, FaultKind.EXECUTOR_MONITOR_PROTOCOL_FAILURE)
        self.assertIn("ValueError", fault.message)

    def test_executor_signature_is_the_policy_independence_guarantee(self):
        """Test review W5/E2: the prose claim, pinned structurally — env + call, nothing else,
        and no policy/history/config machinery in the import surface."""
        import ast as _ast
        import inspect
        from runtime.executor import execute
        self.assertEqual(list(inspect.signature(execute).parameters), ["env", "call"])
        source = (pathlib.Path(_REPO_ROOT) / "runtime" / "executor.py").read_text("utf-8")
        tree = _ast.parse(source)
        imported = {a.name for n in _ast.walk(tree) if isinstance(n, _ast.ImportFrom)
                    for a in n.names} | {n.module for n in _ast.walk(tree)
                                         if isinstance(n, _ast.ImportFrom) and n.module}
        for forbidden in ("orchestrator", "comparator", "executive_history",
                          "orchestration_config"):
            for name in imported:
                self.assertNotIn(forbidden, name)

    def test_standing_recovery_is_routed_through_the_orchestrator(self):
        """Architecture review W5, pinned at the identifier level: the bypass mutant returns
        an IDENTICAL decision (behaviorally equivalent), so — like the L9 wiring pin — the
        contractually correct routing is asserted structurally: the loop's selection hands
        standing advice to decide(), the orchestrator issues the EXECUTE."""
        source = (pathlib.Path(_REPO_ROOT) / "runtime" / "loop.py").read_text("utf-8")
        self.assertIn("standing_recovery=self._pending_recovery[0]", source)

    def test_executive_budget_exhausts(self):
        loop = ExecutiveLoopManager(
            BoxPushV1Adapter(), TASK_DELIVER_BOTH,
            OrchestrationConfig(executive_step_budget=2),
        )
        episode = loop.run()
        self.assertIs(episode.outcome, EpisodeOutcome.BUDGET_EXHAUSTED)
        self.assertEqual(loop.executive_steps_charged, 2)

    def test_ghost_identity_routes_as_missing_grounding_before_applicability(self):
        """§19.1 item 5, loop-driven case 4: grounding gate FIRST, typed fault, cycle
        short-circuited, backend untouched."""
        loop = ExecutiveLoopManager(BoxPushV1Adapter(), TASK_DELIVER_BOTH)
        loop.env.reset()
        snapshot = loop._sync()
        ghost = GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BoxId.parse("box_9"), DELIVERY_ZONE)
        loop._pending_recovery = (ghost,)
        before = loop.env.export_full_state().episode.step_count
        outcome = loop._run_cycle(0, snapshot)
        self.assertIsNotNone(outcome)                          # halted on the fault (default)
        self.assertIs(outcome.outcome, EpisodeOutcome.FAULTED)
        (fault,) = loop.history.entries[-1].faults
        self.assertIs(fault.kind, FaultKind.MISSING_GROUNDING)
        self.assertEqual(loop.env.export_full_state().episode.step_count, before)
        self.assertEqual(loop.executive_steps_charged, 0)

    def test_stale_recovery_advice_is_dropped_on_inapplicability(self):
        """Case 3, loop-driven: an inapplicable standing call is a typed REPLAN entry with
        zero steps; the loop recovers by replanning, not by faulting."""
        loop = ExecutiveLoopManager(BoxPushV1Adapter(), TASK_DELIVER_BOTH)
        loop.env.reset()
        snapshot = loop._sync()
        stale = GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BOX_HEAVY, DELIVERY_ZONE)
        loop._pending_recovery = (stale,)
        outcome = loop._run_cycle(0, snapshot)
        self.assertIsNone(outcome)                             # episode continues
        entry = loop.history.entries[-1]
        self.assertIsInstance(entry.validation, SymbolicallyInapplicable)
        self.assertIs(entry.decision, ExecutiveDecision.REPLAN)
        self.assertIsNone(entry.execution)
        self.assertEqual(loop._pending_recovery, ())           # stale advice dropped


# ── advisory with a live NL proposal: the comparator through the loop ──────────────

class _StubNLTrack:
    """Duck-typed NL track: fixed proposals per cycle, no LM. Proves the comparator path."""
    def __init__(self, proposals):
        self._proposals = list(proposals)
        self.observed = 0

    def observe(self, snapshot, skill=None, outcome=None):
        self.observed += 1

    def propose(self, task):
        self.proposed = getattr(self, "proposed", 0) + 1
        return self._proposals.pop(0) if self._proposals else _proposal(WAIT, residual=("w",))


class _ExplodingNLTrack:
    """Duck-typed NL track whose propose() RAISES — the H8 infrastructure case."""
    def __init__(self, error=None):
        self.error = error if error is not None else RuntimeError("LM seam exploded")
        self.observed = 0

    def observe(self, snapshot, skill=None, outcome=None):
        self.observed += 1

    def propose(self, task):
        raise self.error


class _ObserveExplodingTrack(_StubNLTrack):
    """Duck-typed NL track whose observe() RAISES from the `fail_from`-th call on — the H8
    WARN-1 case. fail_from=1 hits the first-cycle (pre-execution) site; fail_from=2 lets the
    first observe succeed and hits the post-execution site."""
    def __init__(self, proposals, fail_from=1, error=None):
        super().__init__(proposals)
        self.fail_from = fail_from
        self.error = error if error is not None else RuntimeError("observer exploded")

    def observe(self, snapshot, skill=None, outcome=None):
        self.observed += 1
        if self.observed >= self.fail_from:
            raise self.error


class TestAdvisoryComparatorThroughTheLoop(unittest.TestCase):
    def test_divergences_are_recorded_on_executed_entries(self):
        proposals = [_proposal(PUSH, confidence=0.4)] * 40     # contradiction + low confidence
        loop = ExecutiveLoopManager(
            BoxPushV1Adapter(), TASK_DELIVER_BOTH,
            OrchestrationConfig(policy=OrchestrationPolicy.ADVISORY_TWO_TRACK),
            nl_track=_StubNLTrack(proposals),
        )
        episode = loop.run()
        self.assertIs(episode.outcome, EpisodeOutcome.GOAL_REACHED)
        executed = [e for e in episode.history.entries if e.execution is not None]
        with_divergence = [e for e in executed if e.divergences]
        self.assertTrue(with_divergence)
        kinds = {d.kind for e in with_divergence for d in e.divergences}
        self.assertIn(DivergenceKind.CONFIDENCE_MISMATCH, kinds)
        # each divergence is computed against THAT cycle's selected call (review X3) — in a
        # recovery cycle the plan head differs from the selected call
        for entry in with_divergence:
            for d in entry.divergences:
                if d.symbolic_view:
                    self.assertEqual(d.symbolic_view, str(entry.selected_call))
        # divergences never blocked execution and never leaked into other channels
        for entry in with_divergence:
            self.assertEqual(entry.faults, ())
        # the track observed every executed outcome
        self.assertGreaterEqual(loop.nl_track.observed, len(executed))

    def test_real_nl_track_missing_fixture_is_an_nl_track_failure_fault(self):
        """H8 closed: with a REAL NLTrack and no recorded fixtures, propose() raises the
        typed UnrecordedRequestError — infrastructure, not reasoning content. The loop must
        record NL_TRACK_FAILURE and short-circuit, never launder the raise into a
        COVERAGE_GAP divergence. The observe-first fix is proven en passant: without it the
        error would be the RuntimeError precondition, not the typed fixture miss."""
        from nl import NLTrack, RecordedLM
        loop = ExecutiveLoopManager(
            BoxPushV1Adapter(), TASK_DELIVER_BOTH,
            OrchestrationConfig(policy=OrchestrationPolicy.ADVISORY_TWO_TRACK),
            nl_track=NLTrack(RecordedLM()),
        )
        episode = loop.run()
        self.assertIs(episode.outcome, EpisodeOutcome.FAULTED)
        (fault,) = episode.history.entries[-1].faults
        self.assertIs(fault.kind, FaultKind.NL_TRACK_FAILURE)
        self.assertIn("UnrecordedRequestError", fault.message)
        # the raise never becomes divergence evidence anywhere in the history
        for entry in episode.history.entries:
            self.assertEqual(entry.divergences, ())

    def test_an_agreeing_advisory_proposal_cannot_disappear_from_the_trace(self):
        """Consistency-all W1: agreement means the comparator has nothing to raise — but the
        frozen schema's proposal columns must still carry the NL evidence. The stub proposes
        the plan's own first head, so cycle 0 AGREES (no divergence) and must still record
        nl_proposal + coverage + confidence."""
        first_head = GroundedSkillCall(
            SkillName.GOTO_PUSH_POSE, (AGENT_0,), BOX_HEAVY, DELIVERY_ZONE
        )
        agreeing = _proposal(first_head)
        loop = ExecutiveLoopManager(
            BoxPushV1Adapter(), TASK_DELIVER_BOTH,
            OrchestrationConfig(policy=OrchestrationPolicy.ADVISORY_TWO_TRACK),
            nl_track=_StubNLTrack([agreeing] * 40),
        )
        episode = loop.run()
        self.assertIs(episode.outcome, EpisodeOutcome.GOAL_REACHED)
        entry = episode.history.entries[0]
        self.assertEqual(entry.divergences, ())                # genuine agreement
        self.assertEqual(entry.nl_proposal, first_head)        # ...yet the evidence survives
        self.assertIsNotNone(entry.coverage)
        self.assertEqual(len(entry.confidence), 1)
        self.assertEqual(entry.confidence[0].source, "nl")
        # and every executed advisory entry carries the proposal column
        for executed in (e for e in episode.history.entries if e.execution is not None):
            self.assertIsNotNone(executed.nl_proposal)

    def test_normal_cycles_export_exactly_once(self):
        """Consistency-all W4: post-execution belief/NL updates reuse the result's
        authoritative post_state, so a cycle exports exactly once (in _sync). Pinned by
        count so redundant re-exports cannot creep back."""
        class _CountingEnv:
            def __init__(self):
                self._inner = BoxPushV1Adapter()
                self.exports = 0

            def __getattr__(self, name):
                return getattr(self._inner, name)

            def export_full_state(self):
                self.exports += 1
                return self._inner.export_full_state()

        env = _CountingEnv()
        loop = ExecutiveLoopManager(
            env, TASK_DELIVER_BOTH,
            OrchestrationConfig(policy=OrchestrationPolicy.ADVISORY_TWO_TRACK),
        )
        episode = loop.run()
        self.assertIs(episode.outcome, EpisodeOutcome.GOAL_REACHED)
        iterations = 9 + 1                                     # 9 executing cycles + goal check
        self.assertEqual(env.exports, iterations)

    def test_nl_track_exception_short_circuits_before_the_backend(self):
        """H8 closed, the loop-driven pin: an exception ESCAPING nl_track.propose() is a
        pre-executor NL_TRACK_FAILURE fault — the backend is never invoked, zero
        executive/primitive steps are charged, the world is untouched, and no
        TrackDivergence is manufactured for it.

        R3 moved acquisition BEFORE the decision (report Phase 3 item 7), so the fault now
        arrives pre-decision: the entry carries the cycle's planning record and the fault,
        and — unlike the pre-R3 lifecycle — no decision, selection, validation, or
        prediction had happened yet to record."""
        class _ExecCountingEnv:
            def __init__(self):
                self._inner = BoxPushV1Adapter()
                self.executions = 0

            def __getattr__(self, name):
                return getattr(self._inner, name)

            def execute_skill(self, call):
                self.executions += 1
                return self._inner.execute_skill(call)

        env = _ExecCountingEnv()
        loop = ExecutiveLoopManager(
            env, TASK_DELIVER_BOTH,
            OrchestrationConfig(policy=OrchestrationPolicy.ADVISORY_TWO_TRACK),
            nl_track=_ExplodingNLTrack(),
        )
        episode = loop.run()
        self.assertIs(episode.outcome, EpisodeOutcome.FAULTED)
        entry = episode.history.entries[-1]
        (fault,) = entry.faults
        self.assertIs(fault.kind, FaultKind.NL_TRACK_FAILURE)
        # classified PRE-EXECUTOR: detection precedes execute(), so no attempt occurred
        self.assertTrue(fault.arises_before_execution)
        # the cycle's already-established record survives on the fault entry: planning had
        # happened (R3: acquisition follows required_inputs, before decide/gates/predict)
        self.assertIsNotNone(entry.symbolic_result)
        # ...and nothing later in the cycle is fabricated: no decision was made, nothing
        # was selected/validated/predicted, no proposal, no divergence, no execution
        self.assertIsNone(entry.decision)
        self.assertIsNone(entry.selected_call)
        self.assertIsNone(entry.validation)
        self.assertIsNone(entry.predicted_symbolic_key)
        self.assertIsNone(entry.predicted_world_key)
        self.assertIsNone(entry.nl_proposal)
        self.assertEqual(entry.divergences, ())
        self.assertIsNone(entry.execution)
        # the backend was never reached and nothing was charged
        self.assertEqual(env.executions, 0)
        self.assertEqual(env.export_full_state().episode.step_count, 0)
        self.assertEqual(loop.executive_steps_charged, 0)
        self.assertEqual(loop.primitive_steps_charged, 0)

    def test_malformed_lm_output_is_still_coverage_gap_evidence_not_a_fault(self):
        """The channel boundary, both directions: the LM RETURNING content the parser/repair
        rejected is a typed NLProposal.malformed → COVERAGE_GAP through the comparator —
        never an infrastructure fault, and execution proceeds normally."""
        malformed = _proposal(malformed=MalformedCall("garbage from the LM", raw="x"))
        loop = ExecutiveLoopManager(
            BoxPushV1Adapter(), TASK_DELIVER_BOTH,
            OrchestrationConfig(policy=OrchestrationPolicy.ADVISORY_TWO_TRACK),
            nl_track=_StubNLTrack([malformed] * 40),
        )
        episode = loop.run()
        self.assertIs(episode.outcome, EpisodeOutcome.GOAL_REACHED)
        executed = [e for e in episode.history.entries if e.execution is not None]
        self.assertTrue(executed)
        for entry in executed:
            self.assertIn(DivergenceKind.COVERAGE_GAP,
                          [d.kind for d in entry.divergences])
        for entry in episode.history.entries:
            self.assertNotIn(FaultKind.NL_TRACK_FAILURE,
                             [f.kind for f in entry.faults])

    def test_nl_fault_preserves_the_original_exception_as_cause(self):
        """`raise ... from error`: the typed wrap must not orphan the real traceback."""
        original = ValueError("seam blew up mid-request")
        loop = ExecutiveLoopManager(
            BoxPushV1Adapter(), TASK_DELIVER_BOTH,
            OrchestrationConfig(policy=OrchestrationPolicy.ADVISORY_TWO_TRACK),
            nl_track=_ExplodingNLTrack(original),
        )
        with self.assertRaises(InfrastructureFaultError) as ctx:
            loop._advisory_proposal(TrackRequest(nl_proposal=True))
        self.assertIs(ctx.exception.__cause__, original)
        self.assertIsNone(ctx.exception.result)                # no attempt ever occurred
        self.assertIs(ctx.exception.fault.kind, FaultKind.NL_TRACK_FAILURE)
        self.assertIn("ValueError", ctx.exception.fault.message)

    def test_symbolic_primary_never_consults_the_nl_track(self):
        track = _StubNLTrack([])
        loop = ExecutiveLoopManager(
            BoxPushV1Adapter(), TASK_DELIVER_BOTH,
            OrchestrationConfig(policy=OrchestrationPolicy.SYMBOLIC_PRIMARY),
            nl_track=track,
        )
        episode = loop.run()
        for entry in episode.history.entries:
            self.assertEqual(entry.divergences, ())
        # observe() feeding is legitimate (data flows loop->NL only); propose() must be 0
        self.assertEqual(getattr(track, "proposed", 0), 0)


# ── H8 WARN-1/WARN-2: the typed nl_track.observe() boundary ───────────────────────

class TestObserveFaultBoundary(unittest.TestCase):
    def _advisory(self, env, track, **cfg):
        return ExecutiveLoopManager(
            env, TASK_DELIVER_BOTH,
            OrchestrationConfig(policy=OrchestrationPolicy.ADVISORY_TWO_TRACK, **cfg),
            nl_track=track,
        )

    def test_first_cycle_observe_fault_is_pre_execution_at_that_site(self):
        """WARN-1 site 1: observe() fails before ANY planning or execution — classified by
        POSITION: zero steps, world untouched, backend never invoked, cycle replaced."""
        class _ExecCountingEnv:
            def __init__(self):
                self._inner = BoxPushV1Adapter()
                self.executions = 0

            def __getattr__(self, name):
                return getattr(self._inner, name)

            def execute_skill(self, call):
                self.executions += 1
                return self._inner.execute_skill(call)

        env = _ExecCountingEnv()
        loop = self._advisory(env, _ObserveExplodingTrack([], fail_from=1))
        episode = loop.run()
        self.assertIs(episode.outcome, EpisodeOutcome.FAULTED)
        entry = episode.history.entries[-1]
        (fault,) = entry.faults
        self.assertIs(fault.kind, FaultKind.NL_TRACK_FAILURE)
        self.assertEqual(fault.stage, "observe")
        self.assertIn("observe()", fault.message)
        # the fault REPLACED the cycle: nothing downstream was established or touched
        self.assertIsNone(entry.symbolic_result)
        self.assertIsNone(entry.execution)
        self.assertEqual(entry.divergences, ())
        self.assertEqual(env.executions, 0)
        self.assertEqual(env.export_full_state().episode.step_count, 0)
        self.assertEqual(loop.executive_steps_charged, 0)
        self.assertEqual(loop.primitive_steps_charged, 0)

    def test_post_execution_observe_fault_preserves_the_execution_evidence(self):
        """WARN-1 site 3: the attempt COMPLETED before observe() failed — the result,
        post_state, recorded accounting, and the cycle's divergence evidence all stay
        first-class on the fault-carrying entry; only the monitor comparison is skipped."""
        loop = self._advisory(BoxPushV1Adapter(), _ObserveExplodingTrack([], fail_from=2))
        episode = loop.run()
        self.assertIs(episode.outcome, EpisodeOutcome.FAULTED)
        entry = episode.history.entries[-1]
        (fault,) = entry.faults
        self.assertIs(fault.kind, FaultKind.NL_TRACK_FAILURE)
        self.assertEqual(fault.stage, "observe")
        # NOT reinterpreted as a pre-executor refusal: the kind-based guarantee is withheld
        self.assertFalse(fault.arises_before_execution)
        self.assertIsNotNone(entry.execution)
        self.assertIsNotNone(entry.post_state)
        self.assertIs(entry.decision, ExecutiveDecision.EXECUTE)
        self.assertIsNotNone(entry.coverage)                   # NL evidence columns survive
        # the WAIT stub proposal's COVERAGE_GAP was computed pre-execution and survives too
        self.assertIn(DivergenceKind.COVERAGE_GAP, [d.kind for d in entry.divergences])
        # the completed attempt's accounting is charged, not discarded
        self.assertEqual(loop.executive_steps_charged, 1)
        self.assertEqual(
            loop.primitive_steps_charged, entry.execution.accounting.primitive_steps
        )

    def test_observer_fault_never_accrues_a_symbolic_execution_failure(self):
        """Item: a FAILED execution whose observer also failed escalates through the fault
        channel only — the repeated-failure count stays untouched (single-channel rule)."""
        loop = self._advisory(_FailingGotoEnv(), _ObserveExplodingTrack([], fail_from=2))
        episode = loop.run()
        self.assertIs(episode.outcome, EpisodeOutcome.FAULTED)
        entry = episode.history.entries[-1]
        self.assertIsNotNone(entry.execution)
        self.assertIsNot(entry.execution.outcome, ExecutionOutcome.SUCCESS)
        self.assertTrue(entry.faults)
        self.assertEqual(
            episode.history.failure_count(entry.pre_state, entry.selected_call), 0
        )

    def test_case_a_records_both_the_primary_and_the_observer_fault(self):
        """WARN-1 site 2: an observer fault during case-(a) handling is RECORDED alongside
        the primary executor-boundary fault; the primary stays the cycle's verdict."""
        loop = self._advisory(_CaseAEnv(), _ObserveExplodingTrack([], fail_from=2))
        episode = loop.run()
        self.assertIs(episode.outcome, EpisodeOutcome.FAULTED)
        entry = episode.history.entries[-1]
        self.assertIsNotNone(entry.execution)                  # case (a): result attached
        kinds = [f.kind for f in entry.faults]
        self.assertEqual(kinds, [FaultKind.EXECUTOR_MONITOR_PROTOCOL_FAILURE,
                                 FaultKind.NL_TRACK_FAILURE])
        self.assertIn(str(FaultKind.EXECUTOR_MONITOR_PROTOCOL_FAILURE), episode.reason)

    def test_repeated_observe_faults_in_continue_mode_are_bounded(self):
        """Continue mode: every observe-fault cycle is zero-charge, so the cross-cycle
        liveness guard — not an infinite loop — terminates the episode."""
        loop = self._advisory(
            BoxPushV1Adapter(), _ObserveExplodingTrack([], fail_from=1),
            halt_on_infrastructure_fault=False,
        )
        episode = loop.run()
        self.assertIs(episode.outcome, EpisodeOutcome.FAULTED)
        self.assertIn("liveness", episode.reason)
        self.assertEqual(loop.executive_steps_charged, 0)

    def test_typed_faults_pass_through_both_boundaries_unwrapped(self):
        """WARN-2: an already-typed InfrastructureFaultError raised by the NL track is
        re-raised IDENTICALLY — never re-wrapped, never coarsened to NL_TRACK_FAILURE."""
        typed = InfrastructureFaultError(InfrastructureFault(
            kind=FaultKind.BACKEND_API_EXCEPTION, message="already typed",
        ))
        loop = self._advisory(BoxPushV1Adapter(), _ExplodingNLTrack(typed))
        with self.assertRaises(InfrastructureFaultError) as ctx:
            loop._advisory_proposal(TrackRequest(nl_proposal=True))
        self.assertIs(ctx.exception, typed)
        loop = self._advisory(
            BoxPushV1Adapter(), _ObserveExplodingTrack([], fail_from=1, error=typed)
        )
        with self.assertRaises(InfrastructureFaultError) as ctx:
            loop._observe(None)
        self.assertIs(ctx.exception, typed)

    def test_observe_fault_cause_chaining_is_preserved(self):
        original = ValueError("belief update blew up")
        loop = self._advisory(
            BoxPushV1Adapter(), _ObserveExplodingTrack([], fail_from=1, error=original)
        )
        with self.assertRaises(InfrastructureFaultError) as ctx:
            loop._observe(None)
        self.assertIs(ctx.exception.__cause__, original)
        self.assertIsNone(ctx.exception.result)                # no attempt attached
        self.assertIs(ctx.exception.fault.kind, FaultKind.NL_TRACK_FAILURE)
        self.assertEqual(ctx.exception.fault.stage, "observe")


if __name__ == "__main__":
    unittest.main()
