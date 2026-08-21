"""V1 acceptance suite (`/acceptance-test`): the six supervisor cases, each executed against the
LIVE backend through the P1 adapter and recorded as a frozen `TraceEntry` plus a short
human-readable trace.

The traces are rendered deterministically into `docs/implementation/acceptance_traces.md`
(regenerate with `python -m tests.test_v1_acceptance --write`); a pin test keeps the checked-in
document byte-equal to what these tests actually observed — the document cannot drift from the
behaviour it claims to record.

Case map (skill contract → class):

  1. normal successful plan/execution ................ TestCase1NormalSuccess
  2. applicable but backend-rejected (richer feasibility) TestCase2OptimisticFailure
  3. symbolically inapplicable, rejected pre-executor  TestCase3InapplicableRejected
  4. malformed / ungrounded call handling ............ TestCase4MalformedAndUngrounded
  5. `NoPlan` symbolic case .......................... TestCase5NoPlan
  6. deadlock/unsolvable in the backend .............. TestCase6DeadlockNotDefined (documented N/A)

CRITICAL: case 2 passes with NO reachability/feasibility oracle anywhere in the symbolic track —
the guards proving that structurally are `tests/test_p2_symbolic.py::TestSymbolicSideGuards` and
`tests/test_no_backend_imports.py`; here the same fact shows up behaviourally: the plan is chosen
blind and the failure is OBSERVED as an `ExecutionDiscrepancy`, never prevented.

Offline and deterministic: local backend, no LM, no network, no render.
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
    DOMAIN_IR,
    MODEL_VERSION,
    PROJECTION,
    TASK_DELIVER_BOTH,
    initial_state,
    project,
)
from shared.discrepancy import DiscrepancyKind
from shared.execution import ExecutionOutcome, FailureStateClass, RawLabel
from shared.faults import FaultKind
from shared.ids import AgentId, BoxId, ZoneId
from shared.planner_result import NoPlan, PlanFound, PlannerFailure
from shared.skills import (
    GroundedSkillCall,
    MalformedCall,
    SkillName,
    SymbolicallyInapplicable,
    UngroundedCall,
    ValidatedCall,
)
from shared.symbolic_state import GroundedLiteral
from shared.task import Task
from shared.trace_schema import TraceEntry
from shared.versioning import Provenance
from symbolic import (
    ExactSymbolicBelief,
    Universe,
    evaluate,
    monitor_execution,
    plan,
    predict_symbolic,
    predict_world_candidates,
)
from symbolic.synthetic import noplan_instance

TRACE_DOC = pathlib.Path(_REPO_ROOT) / "docs" / "implementation" / "acceptance_traces.md"
PROVENANCE = Provenance(
    source="domain/box_push_v1.py::DOMAIN_IR", model_version=MODEL_VERSION,
    note="V1 acceptance suite (tests/test_v1_acceptance.py)",
)
GOAL_BOTH = frozenset(
    GroundedLiteral("delivered", (str(b),)) for b in TASK_DELIVER_BOTH.goal_delivered
)
TASK_DELIVER_LIGHT = Task(
    task_id="deliver-light-v1", description="Deliver the light box_1 to the delivery zone",
    goal_delivered=(BOX_LIGHT,), zone=DELIVERY_ZONE,
)
GOAL_LIGHT = frozenset({GroundedLiteral("delivered", (str(BOX_LIGHT),))})

_FAILURE_WORDS = {
    FailureStateClass.UNCHANGED: "unchanged",
    FailureStateClass.PARTIAL_EXECUTION: "partial",
    FailureStateClass.BACKEND_REJECTED_BEFORE_TRANSITION: "rejected-before-transition",
}


class RecordingHarness:
    """The P2 acceptance cycle (plan→validate→execute→sync→record→monitor), recording every
    executive cycle as a frozen `TraceEntry`. Test scaffolding, not the P4 orchestrator —
    gating on the verdict here stands in for P4's loop (decisions §19.1 item 2)."""

    def __init__(self, task: Task):
        self.task = task
        self.adapter = BoxPushV1Adapter()
        snapshot = self.adapter.reset()
        self.belief = ExactSymbolicBelief(DOMAIN_IR, PROJECTION, project)
        self.belief.sync(snapshot)
        self.universe = Universe.from_snapshot(snapshot, DELIVERY_ZONE)
        self.entries = []

    def plan(self, goal):
        return plan(DOMAIN_IR, self.belief.state, goal, self.universe, MODEL_VERSION)

    def _predicted_keys(self, verdict, call, pre_symbolic, pre):
        if not isinstance(verdict, ValidatedCall):
            return None, None, ()
        symbolic = predict_symbolic(DOMAIN_IR, pre_symbolic, call)
        symbolic_key = PROJECTION.monitored_key(symbolic) if symbolic is not None else None
        # predict from the SAME snapshot recorded as pre_state — the datum, not an ordering
        # assumption about when this helper runs relative to execution (review NOTE 5)
        candidates = predict_world_candidates(pre, call, DELIVERY_ZONE)
        world_key = candidates[0].world_key() if candidates else None
        return symbolic_key, world_key, candidates

    def attempt(self, call, planner_result=None):
        """One executive cycle. Executes ONLY on a ValidatedCall (or OutsideSymbolicModel);
        a pre-executor rejection is recorded as a validation-only entry (0 executive steps)."""
        pre = self.adapter.export_full_state()
        pre_symbolic = self.belief.state
        verdict = evaluate(DOMAIN_IR, pre_symbolic, call)
        symbolic_key, world_key, candidates = self._predicted_keys(verdict, call, pre_symbolic, pre)

        if verdict.is_pre_executor_rejection:
            entry = TraceEntry(
                executive_step=len(self.entries), task=self.task, pre_state=pre,
                model_version=MODEL_VERSION, provenance=PROVENANCE,
                symbolic_result=planner_result, selected_call=call, validation=verdict,
            )
            self.entries.append(entry)
            return entry

        result = self.adapter.execute_skill(call)
        if isinstance(result, (MalformedCall, UngroundedCall)):
            # DEFENSIVE, never reached by these cases: the symbolic gate above rejects every
            # ghost identity first (case 4's traced fact). The adapter's own production of these
            # verdicts is covered at P1 level (tests/test_p1_adapter.py); this arm just refuses
            # to mis-record one as an execution if a future case reaches it.
            entry = TraceEntry(
                executive_step=len(self.entries), task=self.task, pre_state=pre,
                model_version=MODEL_VERSION, provenance=PROVENANCE,
                symbolic_result=planner_result, selected_call=call, validation=result,
                faults=(result.to_infrastructure_fault(),),
            )
            self.entries.append(entry)
            return entry

        self.belief.sync(self.adapter.export_full_state())
        self.belief.record_outcome(result)
        discrepancies = monitor_execution(
            DOMAIN_IR, PROJECTION, project, pre_symbolic, result, DELIVERY_ZONE, MODEL_VERSION
        )
        entry = TraceEntry(
            executive_step=len(self.entries), task=self.task, pre_state=pre,
            model_version=MODEL_VERSION, provenance=PROVENANCE,
            symbolic_result=planner_result, selected_call=call, validation=verdict,
            predicted_symbolic_key=symbolic_key, predicted_world_key=world_key,
            execution=result, post_state=result.post_state, discrepancies=discrepancies,
        )
        self.entries.append(entry)
        return entry


# ── human-readable rendering ──────────────────────────────────────────────────────

def _snap_line(snapshot):
    agents = " ".join(
        f"{a.agent_id.value}@{a.position}d{a.direction}" for a in snapshot.agents
    )
    boxes = " ".join(
        f"{b.box_id}@{b.position}{'[DELIVERED]' if b.delivered else ''}" for b in snapshot.boxes
    )
    return f"{agents} | {boxes} | world_key={snapshot.world_key()[:16]}"


def render_entry(entry: TraceEntry) -> str:
    lines = [f"#### executive cycle {entry.executive_step} — `{entry.selected_call}`", ""]
    lines.append(f"- task: `{entry.task.task_id}` — {entry.task.description}")
    lines.append(f"- pre-attempt state: `{_snap_line(entry.pre_state)}`")
    lines.append(f"- grounded executive skill: `{entry.selected_call.key()}`")
    v = entry.validation
    lines.append(f"- symbolic applicability: `{type(v).__name__}`"
                 + (f" — {v.reason}; unsatisfied: {list(v.unsatisfied)}"
                    if isinstance(v, SymbolicallyInapplicable) else ""))
    if entry.predicted_symbolic_key or entry.predicted_world_key:
        lines.append(f"- symbolic prediction (monitored key): `{entry.predicted_symbolic_key}`")
        lines.append(f"- world prediction (first admissible candidate key): "
                     f"`{str(entry.predicted_world_key)[:16]}`")
    if entry.execution is not None:
        r = entry.execution
        lines.append(f"- backend terminal label (provenance): `{r.raw_label}` → authoritative "
                     f"typed outcome: `{r.outcome}`")
        lines.append(f"- post-attempt state: `{_snap_line(r.post_state)}`")
        lines.append("- failure classification: "
                     + (f"`{_FAILURE_WORDS[r.failure_class]}`" if r.failure_class else "n/a (success)")
                     + (f" — {r.detail}" if r.detail else ""))
        lines.append(f"- primitive steps: {r.accounting.primitive_steps}; "
                     f"executive step consumed: {r.accounting.executive_steps == 1}")
    else:
        lines.append("- backend: NOT consulted — pre-executor rejection, 0 primitive steps, "
                     "0 executive steps")
    if entry.discrepancies:
        for d in entry.discrepancies:
            lines.append(f"- ExecutionDiscrepancy: `{d.kind}` — {d.message}")
    elif entry.faults:
        for f in entry.faults:
            lines.append(f"- InfrastructureFault: `{f.kind}` — {f.message} (short-circuits "
                         f"the cycle: {entry.short_circuited})")
    else:
        lines.append("- report channels: none (no discrepancy, no divergence, no fault)")
    lines.append("")
    return "\n".join(lines)


def build_traces() -> str:
    """Run every executed acceptance case and render the full deterministic trace document."""
    out = [
        "# V1 acceptance traces",
        "",
        "GENERATED by `python -m tests.test_v1_acceptance --write` — do not hand-edit;",
        "`tests/test_v1_acceptance.py::TestTraceDocumentPinned` keeps this byte-equal to the",
        "live behaviour it records. Since P4 landed, cases 1-6 keep their scripted-harness form",
        "(component-level acceptance) and case 7 adds the EXECUTIVE LOOP form: the same story",
        "driven by the P4 orchestrator under both policies, with the decision/recovery column.",
        "",
        "## Case 1 — normal successful plan/execution",
        "",
    ]
    h = RecordingHarness(TASK_DELIVER_LIGHT)
    result = h.plan(GOAL_LIGHT)
    out.append(f"planner: `PlanFound`, {len(result.plan)} steps: "
               + ", ".join(f"`{c}`" for c in result.plan))
    out.append("")
    for call in result.plan:
        out.append(render_entry(h.attempt(call, planner_result=result)))

    out += ["## Case 2 — symbolically applicable, rejected by the richer backend", ""]
    h2 = RecordingHarness(TASK_DELIVER_BOTH)
    result2 = h2.plan(GOAL_BOTH)
    out.append(f"planner: `PlanFound`, {len(result2.plan)} steps (chosen blind to geometry — "
               "the optimism is the design): " + ", ".join(f"`{c}`" for c in result2.plan))
    out.append("")
    for call in result2.plan:
        out.append(render_entry(h2.attempt(call, planner_result=result2)))
    out.append("recovery (scripted stand-in for P4): replan from the unchanged belief returns the "
               "bare failed step again (the recorded consuming-skill livelock, decisions §19.1); "
               "re-establishing the formation with `GotoPushPose` and retrying completes the task:")
    out.append("")
    replan = h2.plan(GOAL_BOTH)
    out.append(f"- replan: `PlanFound`, steps: " + ", ".join(f"`{c}`" for c in replan.plan))
    out.append("")
    failed_call = result2.plan[-1]
    recovery = GroundedSkillCall(
        SkillName.GOTO_PUSH_POSE, failed_call.agents, failed_call.box, failed_call.zone
    )
    for call in (recovery, failed_call):
        out.append(render_entry(h2.attempt(call)))

    out += ["## Case 3 — symbolically inapplicable, rejected before the executor", ""]
    h3 = RecordingHarness(TASK_DELIVER_BOTH)
    bad = GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BOX_HEAVY, DELIVERY_ZONE)
    out.append(render_entry(h3.attempt(bad)))

    out += ["## Case 4 — malformed / ungrounded grounded calls", "",
            "Constructor-level malformedness (wrong types, wrong arity) is rejected before a call",
            "object can even exist — exercised in `TestCase4MalformedAndUngrounded`, nothing to",
            "trace. A ghost identity (`box_9`) is rejected by the SYMBOLIC gate first (it appears",
            "in no projected literal); probing the adapter directly, its identity-only pre-flight",
            "independently returns a typed `UngroundedCall` (`MISSING_GROUNDING`) before any",
            "transition. Both layers, traced:", ""]
    h4 = RecordingHarness(TASK_DELIVER_BOTH)
    ghost = GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BoxId.parse("box_9"), DELIVERY_ZONE)
    out.append(render_entry(h4.attempt(ghost)))
    steps_before = h4.adapter.export_full_state().episode.step_count
    direct = h4.adapter.execute_skill(ghost)
    steps_after = h4.adapter.export_full_state().episode.step_count
    out.append(f"direct adapter probe (bypassing the symbolic gate): `{type(direct).__name__}` — "
               f"{direct.reason}; fault kind `{direct.to_infrastructure_fault().kind}`; "
               f"step_count {steps_before} → {steps_after} (measured: no transition)")
    out.append("")

    out += ["## Case 5 — `NoPlan` (synthetic instance, Decision 12)", ""]
    state, goal, universe = noplan_instance()
    r5 = plan(DOMAIN_IR, state, goal, universe, MODEL_VERSION)
    out.append(f"- instance: single-agent universe, heavy `box_0` pending "
               f"(`symbolic/synthetic.py` — never the frozen instance)")
    out.append(f"- planner result: `NoPlan` — {r5.reason}")
    out.append("- no call selected, no execution, no fault: `NoPlan` is a SEMANTIC result routed "
               "to the orchestrator (:128), never conflated with `PlannerFailure`")
    out.append("")

    out += ["## Case 7 — the P4 executive loop drives the same story (both policies)", ""]
    from shared.orchestration_config import OrchestrationConfig, OrchestrationPolicy
    from runtime.loop import ExecutiveLoopManager
    for policy in (OrchestrationPolicy.SYMBOLIC_PRIMARY, OrchestrationPolicy.ADVISORY_TWO_TRACK):
        loop = ExecutiveLoopManager(
            BoxPushV1Adapter(), TASK_DELIVER_BOTH, OrchestrationConfig(policy=policy)
        )
        episode = loop.run()
        out.append(f"### policy `{policy.value}`")
        out.append("")
        out.append(f"- episode outcome: `{episode.outcome.value}` — {episode.reason}")
        out.append(f"- executive steps charged: {loop.executive_steps_charged}; "
                   f"primitive steps charged: {loop.primitive_steps_charged}; "
                   f"trace entries: {len(episode.history)}; "
                   f"discrepancies: {len(episode.discrepancies)}")
        previous = None
        for entry in episode.history.entries:
            decision = entry.decision.value if entry.decision else (
                "faulted" if entry.faults else "halt-recorded")
            if entry.nl_proposal is not None:
                # the column carries EITHER enacted recovery advice OR the cycle's advisory
                # proposal (W1); recovery is identified by adjacency to its REQUEST_PROPOSAL
                from shared.orchestration_config import ExecutiveDecision as _ED
                is_recovery = (previous is not None
                               and previous.decision is _ED.REQUEST_PROPOSAL
                               and previous.executive_step == entry.executive_step)
                decision += " (nl-recovery)" if is_recovery else " (nl-advisory)"
            previous = entry
            call = str(entry.selected_call) if entry.selected_call else "(no call)"
            outcome = (entry.execution.outcome.value if entry.execution else "-")
            predictions = (
                f"; predicted sym={str(entry.predicted_symbolic_key)[:12]} "
                f"world={str(entry.predicted_world_key)[:12]}"
                if entry.execution is not None else ""
            )
            out.append(f"- cycle {entry.executive_step}: decision `{decision}` — `{call}` "
                       f"-> {outcome}{predictions}"
                       + (f"; discrepancy: {entry.discrepancies[0].kind}"
                          if entry.discrepancies else ""))
        out.append("")
    out.append("The two policies share one executor and diverge ONLY in decisions: "
               "SYMBOLIC_PRIMARY halts at the repeated-failure threshold with the discrepancy "
               "history (never strengthening the model); ADVISORY_TWO_TRACK escapes the "
               "recorded livelock via the NL RecoveryProposer's re-establishment advice and "
               "completes the task.")
    out.append("")

    out += ["## Case 6 — deadlock/unsolvable in the backend: not defined (documented N/A)", "",
            "- the frozen V1 instance is always solvable (case 2's plan exists) and Decision 12",
            "  records that the backend defines NO deadlock/unsolvable detection (section18 §D:",
            "  'Deadlock semantics: MISSING from the backend').",
            "- the unsolvable-case obligation is therefore met by case 5's synthetic instance;",
            "  nothing here is skipped silently.", ""]
    return "\n".join(out) + "\n"


# ── the six cases as assertions ───────────────────────────────────────────────────

def _assert_success_matches_predictions(test, entry):
    """A successful entry's post-state must MATCH its recorded predictions on both bases —
    asserted directly (review WARN 3): `discrepancies == ()` alone is also satisfied by a
    success-blind monitor, so the match itself is proven here, not inferred from silence."""
    post = entry.execution.post_state
    test.assertEqual(
        PROJECTION.monitored_key(project(post)), entry.predicted_symbolic_key
    )
    candidates = predict_world_candidates(entry.pre_state, entry.selected_call, DELIVERY_ZONE)
    test.assertTrue(candidates)
    test.assertIn(post.world_key(), [c.world_key() for c in candidates])


class TestCase1NormalSuccess(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.h = RecordingHarness(TASK_DELIVER_LIGHT)
        cls.result = cls.h.plan(GOAL_LIGHT)

    def test_plan_found_and_executes_to_the_goal_with_clean_channels(self):
        self.assertIsInstance(self.result, PlanFound)
        # the plan IDENTITY is the acceptance record (review WARN 2), not just its length —
        # a different-but-valid plan is a planner regression this test must surface itself,
        # without leaning on the regenerable golden file
        self.assertEqual(
            [str(c) for c in self.result.plan],
            ["GotoPushPose(agent_0; box_1; delivery_zone)",
             "Push(agent_0; box_1; delivery_zone)"],
        )
        for call in self.result.plan:
            entry = self.h.attempt(call, planner_result=self.result)
            self.assertIsInstance(entry.validation, ValidatedCall)
            self.assertIs(entry.execution.outcome, ExecutionOutcome.SUCCESS)
            self.assertEqual(entry.executive_steps_consumed, 1)
            self.assertGreater(entry.primitive_steps_consumed, 0)
            self.assertEqual(entry.discrepancies, ())
            self.assertEqual(entry.faults, ())
            _assert_success_matches_predictions(self, entry)
        self.assertTrue(self.h.adapter.export_full_state().box(BOX_LIGHT).delivered)


class TestCase2OptimisticFailure(unittest.TestCase):
    """The critical case: NO oracle is added to make it pass — the failure IS the pass."""

    @classmethod
    def setUpClass(cls):
        cls.h = RecordingHarness(TASK_DELIVER_BOTH)
        cls.result = cls.h.plan(GOAL_BOTH)
        expected_plan = [
            "GotoPushPose(agent_0; box_0; delivery_zone)",
            "GotoPushPose(agent_0; box_1; delivery_zone)",
            "GotoPushPose(agent_1; box_0; delivery_zone)",
            "CooperativePush(agent_0,agent_1; box_0; delivery_zone)",
            "Push(agent_0; box_1; delivery_zone)",
        ]
        if [str(c) for c in cls.result.plan] != expected_plan:
            raise RuntimeError("the frozen 5-step optimistic plan changed identity")
        cls.entries = [cls.h.attempt(c, planner_result=cls.result) for c in cls.result.plan]

    def test_the_final_applicable_step_fails_and_is_reported_not_prevented(self):
        last = self.entries[-1]
        self.assertIsInstance(last.validation, ValidatedCall)   # symbolically applicable...
        self.assertIsNot(last.execution.outcome, ExecutionOutcome.SUCCESS)  # ...backend says no
        self.assertEqual(last.executive_steps_consumed, 1)      # a failed attempt still costs 1
        # the failure RECORD is first-class here (review WARN 1), not delegated to the golden
        # file a --write would re-baseline: this exact failure is a pre-transition rejection
        # that left the world untouched, and its raw provenance is the backend's own label
        self.assertIs(
            last.execution.failure_class, FailureStateClass.BACKEND_REJECTED_BEFORE_TRANSITION
        )
        self.assertIs(last.execution.raw_label, RawLabel.BLOCKED)
        self.assertTrue(last.execution.pre_state.same_world(last.execution.post_state))
        kinds = [d.kind for d in last.discrepancies]
        self.assertIn(DiscrepancyKind.EXECUTION_FAILURE_OF_APPLICABLE_SKILL, kinds)

    def test_the_four_prior_steps_succeed_with_no_discrepancy(self):
        self.assertEqual(len(self.entries), 5)                  # review NOTE 9
        for entry in self.entries[:-1]:
            self.assertIs(entry.execution.outcome, ExecutionOutcome.SUCCESS)
            self.assertEqual(entry.discrepancies, ())
            _assert_success_matches_predictions(self, entry)


class TestCase3InapplicableRejected(unittest.TestCase):
    def test_rejected_pre_executor_zero_steps_backend_untouched(self):
        h = RecordingHarness(TASK_DELIVER_BOTH)
        before = h.adapter.export_full_state().episode.step_count
        entry = h.attempt(GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BOX_HEAVY, DELIVERY_ZONE))
        self.assertIsInstance(entry.validation, SymbolicallyInapplicable)
        self.assertGreaterEqual(len(entry.validation.unsatisfied), 2)
        self.assertIsNone(entry.execution)
        self.assertEqual(entry.executive_steps_consumed, 0)
        self.assertEqual(entry.primitive_steps_consumed, 0)
        self.assertEqual(h.adapter.export_full_state().episode.step_count, before)
        # a symbolic-track verdict, never a fault and never a discrepancy
        self.assertEqual(entry.faults, ())
        self.assertEqual(entry.discrepancies, ())


class TestCase4MalformedAndUngrounded(unittest.TestCase):
    def test_wrong_types_and_arity_cannot_construct_a_call(self):
        with self.assertRaises(TypeError):
            GroundedSkillCall(SkillName.PUSH, ("agent_0",), BOX_LIGHT, DELIVERY_ZONE)
        with self.assertRaises(ValueError):
            GroundedSkillCall(SkillName.PUSH, (AGENT_0, AGENT_1), BOX_LIGHT, DELIVERY_ZONE)

    def test_malformed_call_converts_to_the_typed_fault_never_a_substitute_skill(self):
        """The P3 parser (`nl/parser.py`) produces MalformedCall from raw text and has its
        own suite; THIS case constructs one by hand because what the acceptance layer pins is
        the frozen HANDLING contract, independent of any producer. Review WARN 4: asserting
        `short_circuited` on an entry the test itself built was self-fulfilling — the load-
        bearing fact is that the trace REFUSES to record a faulted-and-executed cycle, asserted
        below against a genuine ExecutionResult (invariant also P0-pinned in
        tests/test_trace_and_history.py)."""
        verdict = MalformedCall(reason="unparseable planner output", raw="push(the nearest box)")
        self.assertTrue(verdict.is_pre_executor_rejection)
        fault = verdict.to_infrastructure_fault()
        self.assertIs(fault.kind, FaultKind.MALFORMED_SKILL_CALL)

        entry = TraceEntry(
            executive_step=0, task=TASK_DELIVER_BOTH, pre_state=initial_state(),
            model_version=MODEL_VERSION, provenance=PROVENANCE, validation=verdict,
            faults=(fault,),
        )
        self.assertTrue(entry.short_circuited)
        self.assertEqual(entry.executive_steps_consumed, 0)

        # the enforcement: a real execution result cannot coexist with either the rejection
        # verdict or its pre-execution fault in the same cycle
        h = RecordingHarness(TASK_DELIVER_BOTH)
        goto = GroundedSkillCall(SkillName.GOTO_PUSH_POSE, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE)
        real = h.adapter.execute_skill(goto)
        base = dict(
            executive_step=0, task=TASK_DELIVER_BOTH, pre_state=initial_state(),
            model_version=MODEL_VERSION, provenance=PROVENANCE,
        )
        with self.assertRaises(ValueError):
            TraceEntry(**base, validation=verdict, execution=real)
        with self.assertRaises(ValueError):
            TraceEntry(**base, faults=(fault,), execution=real)

    def test_ungrounded_box_is_rejected_symbolically_first_then_typed_by_the_adapter(self):
        """Layering, recorded: a ghost identity never appears in the projected state, so the
        SYMBOLIC gate rejects it first (`SymbolicallyInapplicable`, backend untouched). The
        adapter's own identity pre-flight — probed directly, bypassing the gate the way a buggy
        P4 wiring might — still returns a typed `UngroundedCall` before any transition; the two
        layers agree that no substitution and no state change ever happens."""
        h = RecordingHarness(TASK_DELIVER_BOTH)
        before = h.adapter.export_full_state().episode.step_count
        ghost = GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BoxId.parse("box_9"), DELIVERY_ZONE)
        entry = h.attempt(ghost)
        self.assertIsInstance(entry.validation, SymbolicallyInapplicable)
        self.assertIsNone(entry.execution)
        # direct adapter probe: the identity pre-flight is its own typed defense
        direct = h.adapter.execute_skill(ghost)
        self.assertIsInstance(direct, UngroundedCall)
        self.assertIs(direct.to_infrastructure_fault().kind, FaultKind.MISSING_GROUNDING)
        self.assertEqual(h.adapter.export_full_state().episode.step_count, before)


class TestCase5NoPlan(unittest.TestCase):
    def test_noplan_is_semantic_and_distinct_from_plannerfailure(self):
        """The trio distinction itself (PlannerFailure on budget/exception, its fault bridge)
        is behaviourally covered in tests/test_p2_symbolic.py::TestPlanner and
        tests/test_result_and_report_channels.py; this case records the NoPlan half live."""
        state, goal, universe = noplan_instance()
        result = plan(DOMAIN_IR, state, goal, universe, MODEL_VERSION)
        self.assertIsInstance(result, NoPlan)
        self.assertTrue(result.reason)


class TestCase6DeadlockNotDefined(unittest.TestCase):
    def test_the_frozen_instance_is_solvable_and_the_gap_is_documented(self):
        """Decision 12: the backend defines no deadlock; case 5's synthetic instance meets the
        unsolvable obligation. This test pins that the frozen instance really is solvable."""
        snapshot = initial_state()
        result = plan(
            DOMAIN_IR,
            project(snapshot),
            GOAL_BOTH,
            Universe.from_snapshot(snapshot, DELIVERY_ZONE),
            MODEL_VERSION,
        )
        self.assertIsInstance(result, PlanFound)
        self.assertIn("documented N/A", TRACE_DOC.read_text(encoding="utf-8"))


class TestCase7ExecutiveLoop(unittest.TestCase):
    """The P4 column of the acceptance record: the SAME optimistic story driven by the real
    orchestrator/loop, with decisions and recovery recorded per cycle. The policy split IS the
    architecture's thesis: identical executor, different decisions."""

    @classmethod
    def setUpClass(cls):
        from shared.orchestration_config import OrchestrationConfig, OrchestrationPolicy
        from runtime.loop import EpisodeOutcome, ExecutiveLoopManager
        cls.EpisodeOutcome = EpisodeOutcome
        cls.episodes = {}
        cls.loops = {}
        for policy in (OrchestrationPolicy.SYMBOLIC_PRIMARY,
                       OrchestrationPolicy.ADVISORY_TWO_TRACK):
            loop = ExecutiveLoopManager(
                BoxPushV1Adapter(), TASK_DELIVER_BOTH, OrchestrationConfig(policy=policy)
            )
            cls.loops[policy] = loop
            cls.episodes[policy] = loop.run()

    def _by_policy(self):
        from shared.orchestration_config import OrchestrationPolicy
        return (self.episodes[OrchestrationPolicy.SYMBOLIC_PRIMARY],
                self.episodes[OrchestrationPolicy.ADVISORY_TWO_TRACK])

    def test_symbolic_primary_halts_at_the_livelock_with_the_discrepancy_history(self):
        primary, _ = self._by_policy()
        self.assertIs(primary.outcome, self.EpisodeOutcome.HALTED_REPEATED_FAILURE)
        self.assertIn("SYMBOLIC_PRIMARY", primary.reason)
        from shared.orchestration_config import OrchestrationPolicy
        loop = self.loops[OrchestrationPolicy.SYMBOLIC_PRIMARY]
        failures = [d for d in primary.discrepancies
                    if d.kind is DiscrepancyKind.EXECUTION_FAILURE_OF_APPLICABLE_SKILL]
        self.assertEqual(len(failures), loop.config.repeated_failure_threshold)
        self.assertEqual(len({d.call.key() for d in failures}), 1)   # SAME call...
        failure_entries = [e for e in primary.history.entries
                          if e.execution is not None
                          and e.execution.outcome is not ExecutionOutcome.SUCCESS]
        self.assertEqual(len({e.pre_state.world_key() for e in failure_entries}), 1)
        # ...and the discrepancy is ATTACHED to each failing entry, not just aggregated
        for entry in failure_entries:
            kinds = [d.kind for d in entry.discrepancies]
            self.assertIn(DiscrepancyKind.EXECUTION_FAILURE_OF_APPLICABLE_SKILL, kinds)
        final = primary.history.entries[-1]
        from shared.orchestration_config import ExecutiveDecision
        self.assertIs(final.decision, ExecutiveDecision.HALT)
        self.assertIsNone(final.execution)                     # halting executed nothing

    def test_advisory_two_track_escapes_via_recovery_and_reaches_the_goal(self):
        _, advisory = self._by_policy()
        self.assertIs(advisory.outcome, self.EpisodeOutcome.GOAL_REACHED)
        entries = advisory.history.entries
        from shared.orchestration_config import ExecutiveDecision, OrchestrationPolicy
        loop = self.loops[OrchestrationPolicy.ADVISORY_TWO_TRACK]
        # the failures REALLY happened, exactly to the threshold — a hidden oracle removing
        # them would fail here, not silently degrade the recovery filter
        failure_steps = [e.executive_step for e in entries
                         if e.execution is not None
                         and e.execution.outcome is not ExecutionOutcome.SUCCESS]
        self.assertEqual(len(failure_steps), loop.config.repeated_failure_threshold)
        # the DECISION is materialized in the record: REQUEST_PROPOSAL entry, then a recovery
        # execution carrying typed NL provenance (nl_proposal == selected_call)
        request = [e for e in entries
                   if e.decision is ExecutiveDecision.REQUEST_PROPOSAL]
        self.assertEqual(len(request), 1)
        self.assertGreaterEqual(request[0].executive_step, max(failure_steps))
        recovery = [e for prev, e in zip(entries, entries[1:])
                    if prev.decision is ExecutiveDecision.REQUEST_PROPOSAL
                    and prev.executive_step == e.executive_step
                    and e.nl_proposal is not None
                    and e.selected_call.skill is SkillName.GOTO_PUSH_POSE
                    and e.execution is not None
                    and e.execution.outcome is ExecutionOutcome.SUCCESS]
        self.assertEqual(len(recovery), 1, "exactly one NL-recovery execution expected")
        self.assertGreater(recovery[0].executive_step, max(failure_steps))
        # post-divergence executions are CONSTRAINED, not just outcome-checked (review W7):
        # each success after the split must land exactly on its recorded world prediction
        for entry in entries:
            if (entry.executive_step > max(failure_steps)
                    and entry.execution is not None
                    and entry.execution.outcome is ExecutionOutcome.SUCCESS):
                self.assertEqual(
                    entry.execution.post_state.world_key(), entry.predicted_world_key
                )
        self.assertTrue(all(b.delivered for b in entries[-1].post_state.boxes))

    def test_policies_share_one_executor_semantics_on_the_common_prefix(self):
        """Policy changes DECISIONS, not executor semantics: until the decisions diverge (the
        repeated-failure threshold), both episodes execute the identical call sequence with
        byte-identical world outcomes."""
        primary, advisory = self._by_policy()
        prim_exec = [e for e in primary.history.entries if e.execution is not None]
        adv_exec = [e for e in advisory.history.entries if e.execution is not None]
        prefix = min(len(prim_exec), len(adv_exec))
        self.assertGreaterEqual(prefix, 5)
        for a, b in zip(prim_exec[:prefix], adv_exec[:prefix]):
            self.assertEqual(a.execution.call, b.execution.call)
            self.assertEqual(a.execution.outcome, b.execution.outcome)
            self.assertEqual(a.execution.post_state.world_key(),
                             b.execution.post_state.world_key())

    def test_every_loop_cycle_is_a_complete_trace_entry(self):
        """Executed cycles carry decision, validation, post-state, and BOTH prediction bases;
        the accounting accessors agree with the loop's charges (no case-(c) fault here)."""
        from shared.orchestration_config import OrchestrationPolicy
        for policy, episode in self.episodes.items():
            loop = self.loops[policy]
            with self.subTest(policy=policy.value):
                self.assertEqual(
                    loop.executive_steps_charged,
                    episode.history.executive_steps_used,   # no case-(c) fault occurred
                )
                for entry in episode.history.entries:
                    self.assertIsNotNone(entry.symbolic_result)
                    self.assertIs(entry.task, TASK_DELIVER_BOTH)
                    if entry.execution is not None:
                        self.assertIsInstance(entry.validation, ValidatedCall)
                        self.assertIsNotNone(entry.post_state)
                        # the decision column survives without the doc pin (review M3)
                        from shared.orchestration_config import ExecutiveDecision
                        self.assertIs(entry.decision, ExecutiveDecision.EXECUTE)
                        # both prediction bases recorded (Decision 13.6; review W5)
                        self.assertIsNotNone(entry.predicted_symbolic_key)
                        self.assertIsNotNone(entry.predicted_world_key)


class TestTraceDocumentPinned(unittest.TestCase):
    def test_checked_in_traces_equal_live_behaviour_byte_for_byte(self):
        self.assertEqual(TRACE_DOC.read_text(encoding="utf-8"), build_traces())


if __name__ == "__main__":
    if "--write" in sys.argv:
        TRACE_DOC.write_text(build_traces(), encoding="utf-8")
        print(f"wrote {TRACE_DOC}")
    else:
        unittest.main()
