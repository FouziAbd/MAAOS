"""Execution labels, typed outcomes, and step accounting (Decisions 2 and 3).

Includes the P0 requirement to resolve code-vs-doc vocabulary inconsistencies explicitly.
"""
import unittest

from domain.box_push_v1 import (
    DOMAIN_IR,
    PROJECTION,
    P_IN_POSE,
    AGENT_0,
    AGENT_1,
    BOX_HEAVY,
    BOX_LIGHT,
    DELIVERY_ZONE,
    initial_state,
    project,
)
from shared.execution import (
    ADVERTISED_BUT_NOT_PRODUCIBLE,
    NON_TERMINAL_PROGRESS_MARKER,
    NEVER_OBSERVABLE_RAW,
    PRODUCIBLE_RAW_LABELS,
    UNREACHABLE_IN_BOXPUSH,
    ExecutionOutcome,
    ExecutionResult,
    FailureStateClass,
    RawLabel,
    StepAccounting,
)
from shared.skills import GroundedSkillCall, OutsideSymbolicModel, SkillName
from shared.state_snapshot import BoxSnapshot


def _call():
    return GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE)


def _moved_state(x=5):
    """Box pushed part-way: the honest post-state for a partial/timeout outcome."""
    s = initial_state()
    b = s.box(BOX_LIGHT)
    return s.with_box(BoxSnapshot(b.box_id, (x, 4), b.required_agents, b.is_target, False))


def _delivered_state():
    s = initial_state()
    b = s.box(BOX_LIGHT)
    return s.with_box(BoxSnapshot(b.box_id, (1, 4), b.required_agents, b.is_target, True))


class TestVocabularyConsistency(unittest.TestCase):
    """Code is authoritative over docstrings and prompts."""

    def test_moved_is_advertised_but_not_producible(self):
        """`moved` appears in skill_executor_push.py:7 and box_push_centralized.py:53/243/288,
        but CooperativePushSkill has no _finish("moved")."""
        self.assertIn("moved", ADVERTISED_BUT_NOT_PRODUCIBLE)
        producible = {str(l) for labels in PRODUCIBLE_RAW_LABELS.values() for l in labels}
        self.assertNotIn("moved", producible)

    def test_cooperative_push_can_return_none_known(self):
        """Producible (skill_executor_push.py:294) though undocumented in the runner's label set."""
        self.assertIn(RawLabel.NONE_KNOWN, PRODUCIBLE_RAW_LABELS[SkillName.COOPERATIVE_PUSH])

    def test_timeout_is_never_observable_as_a_raw_label(self):
        """BaseSkill._timeout sets "timeout" but every subclass overwrites it, which is precisely
        why Decision 3 requires an explicit typed TIMEOUT outcome."""
        self.assertIn("timeout", NEVER_OBSERVABLE_RAW)
        producible = {str(l) for labels in PRODUCIBLE_RAW_LABELS.values() for l in labels}
        self.assertNotIn("timeout", producible)
        self.assertIn(ExecutionOutcome.TIMEOUT, set(ExecutionOutcome))

    def test_found_decoy_is_producible_but_unreachable_in_boxpush(self):
        self.assertIn(RawLabel.FOUND_DECOY, PRODUCIBLE_RAW_LABELS[SkillName.EXPLORE])
        self.assertIn(RawLabel.FOUND_DECOY, UNREACHABLE_IN_BOXPUSH)

    def test_the_producible_label_sets_are_exactly_these(self):
        """LOCKDOWN, not `assertIn`. Every existing check was additive, so `GotoPushPose` could be
        widened with `delivered` — or narrowed, losing `blocked` — with the suite green. This is
        the table that gates `ExecutionResult.raw_label` validation, and the same additive-check
        weakness `TestPreconditionLockdown` exists to close for preconditions."""
        expected = {
            SkillName.EXPLORE: {"found_target", "found_decoy", "explored"},
            SkillName.GOTO_PUSH_POSE: {"in_position", "none_known", "blocked"},
            SkillName.PUSH: {"delivered", "pushed", "blocked", "too_heavy"},
            SkillName.COOPERATIVE_PUSH: {"none_known", "blocked", "delivered", "waiting_partner"},
            SkillName.WAIT: {"done"},
        }
        self.assertEqual(set(PRODUCIBLE_RAW_LABELS), set(expected))
        for skill, labels in expected.items():
            with self.subTest(skill=skill):
                self.assertEqual({str(l) for l in PRODUCIBLE_RAW_LABELS[skill]}, labels)

    def test_every_registry_skill_has_a_declared_label_set(self):
        """Driven off the registry so a newly added skill without a label set fails here."""
        from shared.skills import REGISTRY
        for sig in REGISTRY:
            with self.subTest(skill=sig.name):
                self.assertIn(sig.name, PRODUCIBLE_RAW_LABELS)
                self.assertTrue(PRODUCIBLE_RAW_LABELS[sig.name])


class TestTypedOutcomeLayering(unittest.TestCase):
    """Decision 3: the raw label is provenance; the typed outcome is authoritative."""

    def test_timeout_is_explicit_even_when_raw_label_says_pushed(self):
        result = ExecutionResult(
            call=_call(),
            outcome=ExecutionOutcome.TIMEOUT,
            pre_state=initial_state(),
            post_state=_moved_state(),              # the box did move before the budget ran out
            accounting=StepAccounting(executive_steps=1, primitive_steps=30),
            raw_label=RawLabel.PUSHED,              # what the backend actually reports on timeout
            failure_class=FailureStateClass.PARTIAL_EXECUTION,
        )
        self.assertIs(result.outcome, ExecutionOutcome.TIMEOUT)
        self.assertIs(result.raw_label, RawLabel.PUSHED)

    def test_raw_label_may_disagree_with_outcome(self):
        """A light box blocked by the partner is always raw-labelled `too_heavy`
        (section18.md headline 0). The typed outcome comes from world state instead."""
        result = ExecutionResult(
            call=_call(),
            outcome=ExecutionOutcome.FAILURE,
            pre_state=initial_state(),
            post_state=initial_state(),
            accounting=StepAccounting(1, 2),
            raw_label=RawLabel.TOO_HEAVY,
            failure_class=FailureStateClass.UNCHANGED,
            detail="partner occupied the landing cell; raw label is belief-derived",
        )
        self.assertIs(result.outcome, ExecutionOutcome.FAILURE)
        self.assertIs(result.raw_label, RawLabel.TOO_HEAVY)

    def test_raw_label_is_optional(self):
        result = ExecutionResult(
            call=_call(),
            outcome=ExecutionOutcome.SUCCESS,
            pre_state=initial_state(),
            post_state=_delivered_state(),
            accounting=StepAccounting(1, 7),
        )
        self.assertIsNone(result.raw_label)

    def test_success_must_not_carry_a_failure_class(self):
        with self.assertRaises(ValueError):
            ExecutionResult(
                call=_call(),
                outcome=ExecutionOutcome.SUCCESS,
                pre_state=initial_state(),
                post_state=_delivered_state(),
                accounting=StepAccounting(1, 7),
                failure_class=FailureStateClass.UNCHANGED,
            )

    def test_non_success_must_record_a_failure_class(self):
        """Never assume a failed skill is a no-op — the class must be recorded per attempt."""
        with self.assertRaises(ValueError):
            ExecutionResult(
                call=_call(),
                outcome=ExecutionOutcome.FAILURE,
                pre_state=initial_state(),
                post_state=initial_state(),
                accounting=StepAccounting(1, 2),
            )

    def test_all_three_failure_classes_are_representable(self):
        self.assertEqual(
            {c.value for c in FailureStateClass},
            {"unchanged", "partial_execution", "rejected_before_transition"},
        )

    def test_partial_execution_records_a_changed_world(self):
        s = initial_state()
        b = s.box(BOX_LIGHT)
        moved = s.with_box(BoxSnapshot(b.box_id, (5, 4), b.required_agents, b.is_target, False))
        result = ExecutionResult(
            call=_call(),
            outcome=ExecutionOutcome.PARTIAL,
            pre_state=s,
            post_state=moved,
            accounting=StepAccounting(1, 12),
            raw_label=RawLabel.BLOCKED,
            failure_class=FailureStateClass.PARTIAL_EXECUTION,
        )
        self.assertTrue(result.world_changed)


class TestStepAccounting(unittest.TestCase):
    """Decision 2."""

    def test_executed_attempt_consumes_exactly_one_executive_step(self):
        for outcome, fc in (
            (ExecutionOutcome.SUCCESS, None),
            (ExecutionOutcome.FAILURE, FailureStateClass.UNCHANGED),
            (ExecutionOutcome.PARTIAL, FailureStateClass.PARTIAL_EXECUTION),
            (ExecutionOutcome.TIMEOUT, FailureStateClass.PARTIAL_EXECUTION),
        ):
            with self.subTest(outcome=outcome):
                changed = fc is FailureStateClass.PARTIAL_EXECUTION
                r = ExecutionResult(
                    call=_call(),
                    outcome=outcome,
                    pre_state=initial_state(),
                    post_state=_moved_state() if changed else initial_state(),
                    accounting=StepAccounting(1, 3),
                    failure_class=fc,
                )
                self.assertEqual(r.accounting.executive_steps, 1)

    def test_execution_result_cannot_represent_a_rejected_call(self):
        """Pre-executor rejections consume zero executive steps and are CallValidation values,
        never ExecutionResult."""
        with self.assertRaises(ValueError):
            ExecutionResult(
                call=_call(),
                outcome=ExecutionOutcome.FAILURE,
                pre_state=initial_state(),
                post_state=initial_state(),
                accounting=StepAccounting(0, 0),
                failure_class=FailureStateClass.BACKEND_REJECTED_BEFORE_TRANSITION,
            )

    def test_executive_steps_beyond_one_rejected(self):
        with self.assertRaises(ValueError):
            StepAccounting(executive_steps=2, primitive_steps=1)

    def test_primitive_steps_tracked_independently_of_executive_steps(self):
        a = StepAccounting(1, 0)     # e.g. Wait: completes without any env.step()
        b = StepAccounting(1, 150)   # e.g. CooperativePush burning its whole budget
        self.assertEqual(a.executive_steps, b.executive_steps)
        self.assertNotEqual(a.primitive_steps, b.primitive_steps)

    def test_negative_primitive_steps_rejected(self):
        with self.assertRaises(ValueError):
            StepAccounting(1, -1)


class TestRawLabelMembershipIsEnforced(unittest.TestCase):
    """`PRODUCIBLE_RAW_LABELS` was a well-evidenced table that constrained nothing: an
    `ExecutionResult` accepted any label from any skill, so a mis-wired adapter reporting
    `Push -> waiting_partner` looked exactly like a backend surprise."""

    def _result(self, skill_call, label):
        s = initial_state()
        return ExecutionResult(
            call=skill_call, outcome=ExecutionOutcome.SUCCESS, pre_state=s, post_state=s,
            accounting=StepAccounting(1, 2), raw_label=label,
        )

    def test_a_label_from_another_skill_is_refused(self):
        push = GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE)
        with self.assertRaises(ValueError):
            self._result(push, RawLabel.WAITING_PARTNER)      # CooperativePush-only

    def test_every_producible_label_is_accepted_for_its_own_skill(self):
        cases = {
            SkillName.PUSH: GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE),
            SkillName.GOTO_PUSH_POSE: GroundedSkillCall(
                SkillName.GOTO_PUSH_POSE, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE),
            SkillName.EXPLORE: GroundedSkillCall(SkillName.EXPLORE, (AGENT_0,)),
            SkillName.WAIT: GroundedSkillCall(SkillName.WAIT, (AGENT_0,)),
        }
        for skill, call in cases.items():
            for label in PRODUCIBLE_RAW_LABELS[skill]:
                with self.subTest(skill=skill, label=label):
                    self.assertEqual(self._result(call, label).raw_label, label)

    def test_no_label_at_all_is_still_allowed(self):
        """`raw_label` is provenance and stays optional — absence must not become an error."""
        push = GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE)
        self.assertIsNone(self._result(push, None).raw_label)

    def test_the_enforcement_covers_cooperative_push_too(self):
        coop = GroundedSkillCall(
            SkillName.COOPERATIVE_PUSH, (AGENT_0, AGENT_1), BOX_HEAVY, DELIVERY_ZONE)
        self.assertEqual(self._result(coop, RawLabel.WAITING_PARTNER).raw_label,
                         RawLabel.WAITING_PARTNER)
        with self.assertRaises(ValueError):
            self._result(coop, RawLabel.TOO_HEAVY)           # Push-only


class TestProgressIsNotATerminalLabel(unittest.TestCase):
    """`in_progress` is the runner's substitute for a skill that is STILL RUNNING at episode end
    (`box_push_centralized.py::main`). It denotes the ABSENCE of a terminal label, and it used to sit
    inside `RawLabel` belonging to none of the declared buckets."""

    def test_in_progress_is_not_a_raw_label(self):
        self.assertNotIn("in_progress", {str(l) for l in RawLabel})
        self.assertEqual(NON_TERMINAL_PROGRESS_MARKER, "in_progress")

    def test_every_raw_label_belongs_to_a_declared_bucket(self):
        """The partition must be total — that is what would have caught `in_progress`."""
        producible = {str(l) for labels in PRODUCIBLE_RAW_LABELS.values() for l in labels}
        unclassified = (
            {str(l) for l in RawLabel}
            - producible
            - set(ADVERTISED_BUT_NOT_PRODUCIBLE)
            - set(NEVER_OBSERVABLE_RAW)
        )
        self.assertEqual(unclassified, set())

    def test_the_progress_marker_cannot_be_used_as_an_execution_label(self):
        """`TypeError` (it is a bare `str`, not a `RawLabel`) rather than `ValueError` — either
        way it cannot enter an execution record."""
        s = initial_state()
        with self.assertRaises(TypeError):
            ExecutionResult(
                call=GroundedSkillCall(SkillName.WAIT, (AGENT_0,)),
                outcome=ExecutionOutcome.SUCCESS, pre_state=s, post_state=s,
                accounting=StepAccounting(1, 0), raw_label=NON_TERMINAL_PROGRESS_MARKER,
            )

    def test_a_bare_string_that_matches_a_producible_label_is_still_refused(self):
        """`RawLabel` is a StrEnum, so `"done"` would pass the membership test by value alone —
        the check would have been satisfied by a completely untyped field."""
        s = initial_state()
        with self.assertRaises(TypeError):
            ExecutionResult(
                call=GroundedSkillCall(SkillName.WAIT, (AGENT_0,)),
                outcome=ExecutionOutcome.SUCCESS, pre_state=s, post_state=s,
                accounting=StepAccounting(1, 0), raw_label="done",
            )
        self.assertEqual(str(RawLabel.DONE), "done")     # the value really does match


class TestTheTwoSensesOfRejected(unittest.TestCase):
    """Both used to be called "rejected" in the same module."""

    def test_pre_executor_rejections_are_identifiable_as_such(self):
        from shared.skills import (
            MalformedCall, SymbolicallyInapplicable, UngroundedCall, ValidatedCall,
        )
        for rejection in (MalformedCall("r"), UngroundedCall("r"), SymbolicallyInapplicable("r")):
            with self.subTest(kind=type(rejection).__name__):
                self.assertTrue(rejection.is_pre_executor_rejection)
        for accepted in (
            ValidatedCall(GroundedSkillCall(SkillName.WAIT, (AGENT_0,))),
            OutsideSymbolicModel(reason="r", skill=SkillName.EXPLORE),
        ):
            with self.subTest(kind=type(accepted).__name__):
                self.assertFalse(accepted.is_pre_executor_rejection)

    def test_the_backend_class_is_named_so_it_cannot_be_mistaken(self):
        self.assertTrue(
            hasattr(FailureStateClass, "BACKEND_REJECTED_BEFORE_TRANSITION"),
            "the backend-side class must carry the BACKEND_ prefix",
        )
        self.assertFalse(hasattr(FailureStateClass, "REJECTED_BEFORE_TRANSITION"))

    def test_the_backend_class_still_carries_the_supervisor_wording(self):
        """The Python name disambiguates; the wire value keeps traceability to :110-114."""
        self.assertEqual(
            str(FailureStateClass.BACKEND_REJECTED_BEFORE_TRANSITION),
            "rejected_before_transition",
        )

    def test_a_pre_executor_rejection_produces_no_execution_result(self):
        """The two senses differ in executive-step cost, which is the reason they must not merge."""
        s = initial_state()
        with self.assertRaises(ValueError):
            ExecutionResult(
                call=GroundedSkillCall(SkillName.WAIT, (AGENT_0,)),
                outcome=ExecutionOutcome.SUCCESS, pre_state=s, post_state=s,
                accounting=StepAccounting(0, 0),      # zero executive steps
            )


class TestOptimisticButInfeasibleAcceptanceRecord(unittest.TestCase):
    """The acceptance case `.claude/rules/testing.md` requires, bound into ONE record — at the
    SCHEMA level. Read the scope limit before relying on this.

    **This proves the record SHAPE, not the backend BEHAVIOUR.** There is no executor and no
    wrapper in the tree at P0, so `test_3` hand-builds the `ExecutionResult` it then inspects:
    "the backend can still fail it" is asserted about a literal this test wrote. The behavioural
    version — drive the real backend, observe the real label, derive the authoritative outcome —
    lands with the P1 wrapper and must not be considered covered until then.

    What IS real here: `test_1` evaluates applicability against the projected symbolic state and
    dies if `project()` drops a literal, if `PROJECTION` reclassifies one, or if `SkillIR.bind`
    mis-binds. Note that the `in_pose` conjunct is injected by `setUp` (it is executive-tracked, so
    the world cannot supply it) and is therefore a fixture, not a derivation.

    Every piece existed separately; nothing tied them together, and nothing asserted the
    APPLICABILITY half — that the symbolic preconditions of the attempted skill really do all hold.
    A reusable applicability evaluator is P2, but literal membership is checkable now.

    Scenario: `Push(agent_0, box_1, delivery_zone)` — symbolically applicable (in_pose, light,
    pending all hold) and yet the backend can fail it, because the symbolic model carries no path,
    distance or occupancy model. That failure is the designed V1 signal, not a modelling bug.
    """

    def setUp(self):
        from shared.symbolic_state import GroundedLiteral
        self.pre = initial_state()
        self.call = GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE)
        self.ir = DOMAIN_IR.skill(SkillName.PUSH)
        self.binding = self.ir.bind(self.call)
        # The one fluent the world cannot supply: GotoPushPose established it (Decision 13.8).
        self.symbolic = PROJECTION.establish(
            project(self.pre),
            GroundedLiteral(P_IN_POSE, (AGENT_0.value, str(BOX_LIGHT))),
        )

    def test_1_the_skill_is_symbolically_applicable(self):
        from shared.symbolic_state import GroundedLiteral
        for predicate in self.ir.preconditions:
            literal = GroundedLiteral(
                str(predicate.name), tuple(self.binding[a] for a in predicate.args)
            )
            with self.subTest(precondition=literal.canonical()):
                self.assertTrue(self.symbolic.holds(literal))

    def test_2_no_precondition_consults_a_feasibility_oracle(self):
        """Applicability holds on literals alone — no path, distance or occupancy model."""
        names = {str(p.name) for p in self.ir.preconditions}
        self.assertEqual(names, {"in_pose", "light", "pending"})

    def test_3_the_backend_can_still_fail_it_and_the_record_is_complete(self):
        result = ExecutionResult(
            call=self.call,
            outcome=ExecutionOutcome.PARTIAL,
            pre_state=self.pre,
            post_state=_moved_box(self.pre),          # box travelled, then the push failed
            accounting=StepAccounting(executive_steps=1, primitive_steps=7),
            raw_label=RawLabel.TOO_HEAVY,
            failure_class=FailureStateClass.PARTIAL_EXECUTION,
        )
        # pre-attempt state, grounded skill, backend label, post-attempt state
        self.assertEqual(result.pre_state, self.pre)
        self.assertEqual(result.call, self.call)
        self.assertEqual(result.raw_label, RawLabel.TOO_HEAVY)
        self.assertNotEqual(result.post_state.world_key(), result.pre_state.world_key())
        # classification + step accounting
        self.assertEqual(result.failure_class, FailureStateClass.PARTIAL_EXECUTION)
        self.assertTrue(result.world_changed)
        self.assertEqual(result.accounting.executive_steps, 1)
        self.assertEqual(result.accounting.primitive_steps, 7)
        # the raw label is provenance only; the typed outcome is authoritative and they differ
        self.assertNotEqual(str(result.raw_label), str(result.outcome))

    def test_4_it_is_reported_as_an_execution_discrepancy_not_a_fault(self):
        from shared.discrepancy import DiscrepancyKind, ExecutionDiscrepancy
        from shared.skills import MalformedCall, SymbolicallyInapplicable, UngroundedCall
        discrepancy = ExecutionDiscrepancy(
            kind=DiscrepancyKind.EXECUTION_FAILURE_OF_APPLICABLE_SKILL,
            call=self.call,
            message="too_heavy",
        )
        self.assertEqual(discrepancy.comparison_bases, ())      # outcome alone suffices (13.7)
        # The meaningful claim is about ROUTING, not class hierarchy: this is a discrepancy, so it
        # must not be convertible to a fault and must not short-circuit the cycle. (An
        # `assertNotIsInstance` against three unrelated classes cannot fail.)
        self.assertFalse(hasattr(discrepancy, "to_infrastructure_fault"))
        self.assertFalse(hasattr(discrepancy, "short_circuits_cycle"))
        self.assertEqual(discrepancy.canonical()["channel"], "ExecutionDiscrepancy")
        self.assertIs(discrepancy.kind, DiscrepancyKind.EXECUTION_FAILURE_OF_APPLICABLE_SKILL)

    def test_5_the_symbolic_model_was_not_strengthened_to_hide_it(self):
        """The whole point: a failure here must never be repaired by adding a precondition."""
        self.assertEqual(len(self.ir.preconditions), 3)
        self.assertNotIn("reachable", {str(p.name) for p in DOMAIN_IR.predicates})


def _moved_box(state):
    b = state.box(BOX_LIGHT)
    return state.with_box(
        BoxSnapshot(b.box_id, (5, 4), b.required_agents, b.is_target, b.delivered)
    )


if __name__ == "__main__":
    unittest.main()
