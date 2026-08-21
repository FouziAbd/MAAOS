"""Trace schema, budgets, and repeated-failure bookkeeping (supervisor :70, :118, :163)."""
import unittest

from domain.box_push_v1 import (
    AGENT_0,
    BOX_LIGHT,
    DELIVERY_ZONE,
    MODEL_VERSION,
    TASK_DELIVER_LIGHT,
    initial_state,
)
from shared.execution import (
    ExecutionOutcome,
    ExecutionResult,
    FailureStateClass,
    RawLabel,
    StepAccounting,
)
from shared.faults import PRE_EXECUTION_FAULT_KINDS, FaultKind, InfrastructureFault
from shared.orchestration_config import (
    ExecutiveDecision,
    OrchestrationConfig,
    OrchestrationPolicy,
)
from shared.skills import GroundedSkillCall, MalformedCall, SkillName
from shared.state_snapshot import BoxSnapshot
from runtime.executive_history import ExecutiveHistory
from shared.trace_schema import TraceEntry
from shared.versioning import ModelPatch, ModelVersion, Provenance

_PROV = Provenance(source="tests", model_version=MODEL_VERSION)


def _call(box=BOX_LIGHT):
    return GroundedSkillCall(SkillName.PUSH, (AGENT_0,), box, DELIVERY_ZONE)


def _failed_execution(pre, call=None, primitive_steps=2, raw_label=RawLabel.TOO_HEAVY):
    return ExecutionResult(
        call=call or _call(),
        outcome=ExecutionOutcome.FAILURE,
        pre_state=pre,
        post_state=pre,
        raw_label=raw_label,
        accounting=StepAccounting(1, primitive_steps),
        failure_class=FailureStateClass.UNCHANGED,
    )


def _entry(step, pre, execution=None, faults=(), validation=None):
    return TraceEntry(
        executive_step=step,
        task=TASK_DELIVER_LIGHT,
        pre_state=pre,
        model_version=MODEL_VERSION,
        provenance=_PROV,
        decision=ExecutiveDecision.EXECUTE,
        execution=execution,
        post_state=execution.post_state if execution else None,
        faults=faults,
        validation=validation,
    )


class TestTraceEntry(unittest.TestCase):
    def test_entry_records_the_full_cycle(self):
        pre = initial_state()
        entry = _entry(0, pre, execution=_failed_execution(pre))
        blob = entry.canonical()
        for key in (
            "executive_step", "task", "pre_state", "post_state", "model_version",
            "provenance", "decision", "execution", "discrepancies", "divergences", "faults",
        ):
            with self.subTest(field=key):
                self.assertIn(key, blob)
        # Values, not just keys: a field that still appears but carries the wrong thing is the
        # likelier regression, and the post-state plus step accounting are the two records the
        # testing rule names explicitly for a failed skill.
        # LITERALS, not `entry.<field>`: comparing the blob against the same object it was built
        # from is a mirror, and `_entry(0, ...)` makes a hardcoded `"executive_step": 0` pass.
        self.assertEqual(blob["executive_step"], 0)
        self.assertEqual(blob["execution"]["accounting"], {"executive_steps": 1, "primitive_steps": 2})
        # `_failed_execution` is UNCHANGED, so pre_state == post_state here BY CONSTRUCTION and
        # these two cannot detect a post-state/pre-state swap. The discriminative version lives in
        # `test_contract_invariants.py::test_populated_fields_carry_the_RIGHT_VALUES...`, whose
        # fixture is PARTIAL_EXECUTION with a moved box.
        self.assertEqual(blob["pre_state"], entry.pre_state.world_key())
        self.assertEqual(blob["post_state"], blob["pre_state"])

    def test_executed_entry_consumes_one_executive_step(self):
        pre = initial_state()
        entry = _entry(0, pre, execution=_failed_execution(pre, primitive_steps=9))
        self.assertEqual(entry.executive_steps_consumed, 1)
        self.assertEqual(entry.primitive_steps_consumed, 9)

    def test_rejected_entry_consumes_zero_executive_steps(self):
        """Decision 2: pre-executor rejections are free."""
        entry = _entry(0, initial_state(), validation=MalformedCall("unparseable"))
        self.assertEqual(entry.executive_steps_consumed, 0)
        self.assertEqual(entry.primitive_steps_consumed, 0)

    def test_fault_short_circuits_the_entry(self):
        fault = InfrastructureFault(kind=FaultKind.BACKEND_API_EXCEPTION, message="LM down")
        entry = _entry(0, initial_state(), faults=(fault,))
        self.assertTrue(entry.short_circuited)

    def test_entry_without_fault_does_not_short_circuit(self):
        pre = initial_state()
        self.assertFalse(_entry(0, pre, execution=_failed_execution(pre)).short_circuited)

    def test_negative_step_rejected(self):
        with self.assertRaises(ValueError):
            _entry(-1, initial_state())


class TestExecutiveHistory(unittest.TestCase):
    def test_budgets_accumulate_only_from_executed_attempts(self):
        pre = initial_state()
        h = ExecutiveHistory()
        h.append(_entry(0, pre, execution=_failed_execution(pre, primitive_steps=4)))
        h.append(_entry(1, pre, validation=MalformedCall("bad")))
        h.append(_entry(2, pre, execution=_failed_execution(pre, primitive_steps=6)))
        self.assertEqual(len(h), 3)
        self.assertEqual(h.executive_steps_used, 2)
        self.assertEqual(h.primitive_steps_used, 10)

    def test_repeated_failure_keyed_on_pre_state_and_grounded_call(self):
        """:118 — the key is (pre-attempt StateSnapshot, grounded skill)."""
        pre = initial_state()
        h = ExecutiveHistory()
        call = _call()
        for step in range(3):
            h.append(_entry(step, pre, execution=_failed_execution(pre, call=call)))
        self.assertEqual(h.failure_count(pre, call), 3)

    def test_a_different_call_has_an_independent_count(self):
        from domain.box_push_v1 import BOX_HEAVY
        pre = initial_state()
        h = ExecutiveHistory()
        h.append(_entry(0, pre, execution=_failed_execution(pre, call=_call(BOX_LIGHT))))
        self.assertEqual(h.failure_count(pre, _call(BOX_LIGHT)), 1)
        self.assertEqual(h.failure_count(pre, _call(BOX_HEAVY)), 0)

    def test_a_different_pre_state_has_an_independent_count(self):
        pre = initial_state()
        b = pre.box(BOX_LIGHT)
        other = pre.with_box(BoxSnapshot(b.box_id, (5, 4), b.required_agents, b.is_target, False))
        h = ExecutiveHistory()
        h.append(_entry(0, pre, execution=_failed_execution(pre)))
        self.assertEqual(h.failure_count(pre, _call()), 1)
        self.assertEqual(h.failure_count(other, _call()), 0)

    def test_successful_attempts_are_not_counted_as_failures(self):
        pre = initial_state()
        b = pre.box(BOX_LIGHT)
        post = pre.with_box(BoxSnapshot(b.box_id, (1, 4), b.required_agents, b.is_target, True))
        success = ExecutionResult(
            call=_call(),
            outcome=ExecutionOutcome.SUCCESS,
            pre_state=pre,
            post_state=post,
            accounting=StepAccounting(1, 7),
        )
        h = ExecutiveHistory()
        h.append(_entry(0, pre, execution=success))
        self.assertEqual(h.failure_count(pre, _call()), 0)

    def test_failure_key_ignores_episode_bookkeeping(self):
        """The key uses world_key(), so an unrelated step_count must not split the bucket."""
        from shared.state_snapshot import EpisodeSnapshot
        pre = initial_state()
        later = pre.replace_episode(EpisodeSnapshot(step_count=42))
        h = ExecutiveHistory()
        h.append(_entry(0, pre, execution=_failed_execution(pre)))
        self.assertEqual(h.failure_count(later, _call()), 1)

    def test_faults_since_a_cycle_boundary(self):
        """:163 exposes *recent* fault history to the FOLLOWING cycle, not every fault ever."""
        old = InfrastructureFault(kind=FaultKind.SERIALIZATION_FAILURE, message="old")
        new = InfrastructureFault(kind=FaultKind.BACKEND_API_EXCEPTION, message="new")
        h = ExecutiveHistory()
        h.append(_entry(0, initial_state(), faults=(old,)))
        h.append(_entry(1, initial_state(), faults=(new,)))
        self.assertEqual(h.faults_since(1), (new,))
        self.assertEqual(h.all_faults(), (old, new))


class TestOrchestrationConfig(unittest.TestCase):
    def test_defaults_are_symbolic_primary(self):
        self.assertIs(OrchestrationConfig().policy, OrchestrationPolicy.SYMBOLIC_PRIMARY)

    def test_both_policies_are_representable(self):
        self.assertEqual(
            {p.value for p in OrchestrationPolicy},
            {"symbolic_primary", "advisory_two_track"},
        )

    def test_executive_and_primitive_budgets_are_independent_knobs(self):
        """A wait/wait cycle performs zero env.step() calls, so a primitive budget alone can never
        bound the loop. The two budgets must therefore be separately configurable, and an entry
        that consumed zero primitive steps must still consume an executive step."""
        cfg = OrchestrationConfig(executive_step_budget=7, primitive_step_budget=999)
        self.assertNotEqual(cfg.executive_step_budget, cfg.primitive_step_budget)

        pre = initial_state()
        free_entry = _entry(
            0, pre,
            execution=ExecutionResult(
                call=_call(), outcome=ExecutionOutcome.SUCCESS, pre_state=pre, post_state=pre,
                accounting=StepAccounting(executive_steps=1, primitive_steps=0),
            ),
        )
        h = ExecutiveHistory()
        h.append(free_entry)
        self.assertEqual(h.primitive_steps_used, 0)
        self.assertEqual(h.executive_steps_used, 1)

    def test_invalid_budgets_rejected(self):
        for kwargs in (
            {"executive_step_budget": 0},
            {"primitive_step_budget": 0},
            {"max_rejections_per_cycle": 0},
            {"repeated_failure_threshold": 0},
        ):
            with self.subTest(**kwargs):
                with self.assertRaises(ValueError):
                    OrchestrationConfig(**kwargs)

    def test_executive_decisions_cover_the_contract_consequences(self):
        for expected in ("execute", "continue", "interrupt", "replan", "ask_user", "halt"):
            with self.subTest(decision=expected):
                self.assertIn(expected, {d.value for d in ExecutiveDecision})


class TestVersioning(unittest.TestCase):
    def test_version_increments(self):
        v = ModelVersion(revision=0, label="boxpush-v1")
        self.assertEqual(v.next().revision, 1)
        self.assertLess(v, v.next())

    def test_patch_requires_a_forward_version(self):
        v0 = ModelVersion(0)
        with self.assertRaises(ValueError):
            ModelPatch(target="skill:Push", rationale="x", from_version=v0, to_version=v0)

    def test_patch_defaults_to_unapplied(self):
        """V1 records patches; it never applies them silently (Decision 6)."""
        p = ModelPatch(
            target="predicate:in_pose",
            rationale="considered adding exclusivity",
            from_version=ModelVersion(0),
            to_version=ModelVersion(1),
        )
        self.assertFalse(p.applied)


class TestTraceLifecycleLegality(unittest.TestCase):
    """A cycle either reaches the executor or it does not. Both used to be representable at once —
    the suite's own "complete trace" fixture did exactly that."""

    def _entry_kwargs(self, pre):
        return dict(
            executive_step=0, task=TASK_DELIVER_LIGHT, pre_state=pre,
            model_version=MODEL_VERSION, provenance=_PROV,
        )

    def test_a_pre_executor_rejection_cannot_coexist_with_an_execution(self):
        from shared.skills import MalformedCall, SymbolicallyInapplicable, UngroundedCall
        pre = initial_state()
        for rejection in (MalformedCall("r"), UngroundedCall("r"), SymbolicallyInapplicable("r")):
            with self.subTest(kind=type(rejection).__name__), self.assertRaises(ValueError):
                TraceEntry(
                    **self._entry_kwargs(pre),
                    validation=rejection,
                    execution=_failed_execution(pre),
                )

    def test_an_acceptance_may_coexist_with_an_execution(self):
        from shared.skills import ValidatedCall
        pre = initial_state()
        execution = _failed_execution(pre)
        entry = TraceEntry(
            **self._entry_kwargs(pre),
            validation=ValidatedCall(call=execution.call),
            execution=execution,
        )
        self.assertEqual(entry.executive_steps_consumed, 1)

    def test_a_pre_execution_fault_cannot_coexist_with_an_execution(self):
        """:163 — such a fault aborts the cycle at the point of detection, which is upstream of
        the executor, so no attempt can also have happened."""
        pre = initial_state()
        for kind in PRE_EXECUTION_FAULT_KINDS:
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                TraceEntry(
                    **self._entry_kwargs(pre),
                    execution=_failed_execution(pre),
                    faults=(InfrastructureFault(kind=kind, message="x"),),
                )

    def test_a_fault_detected_during_or_after_execution_may_coexist(self):
        """A backend exception or a malformed backend RESULT can only be seen by attempting."""
        pre = initial_state()
        for kind in set(FaultKind) - set(PRE_EXECUTION_FAULT_KINDS):
            with self.subTest(kind=kind):
                entry = TraceEntry(
                    **self._entry_kwargs(pre),
                    execution=_failed_execution(pre),
                    faults=(InfrastructureFault(kind=kind, message="x"),),
                )
                self.assertTrue(entry.short_circuited)

    def test_pre_execution_faults_are_exactly_the_upstream_kinds(self):
        self.assertEqual(
            {str(k) for k in PRE_EXECUTION_FAULT_KINDS},
            {"malformed_skill_call", "missing_grounding", "planner_computation_failure"},
        )
        for kind in PRE_EXECUTION_FAULT_KINDS:
            with self.subTest(kind=kind):
                self.assertTrue(InfrastructureFault(kind=kind, message="x").arises_before_execution)
        for kind in set(FaultKind) - set(PRE_EXECUTION_FAULT_KINDS):
            with self.subTest(kind=kind):
                self.assertFalse(
                    InfrastructureFault(kind=kind, message="x").arises_before_execution
                )

    def test_a_rejected_cycle_with_no_execution_is_legal(self):
        from shared.skills import MalformedCall
        pre = initial_state()
        entry = TraceEntry(**self._entry_kwargs(pre), validation=MalformedCall("r"))
        self.assertEqual(entry.executive_steps_consumed, 0)
        self.assertEqual(entry.primitive_steps_consumed, 0)

    def test_the_validation_field_is_not_called_rejection(self):
        """It legitimately holds a `ValidatedCall` on the execution path; a field named
        `rejection` holding an acceptance is the ambiguity Decision 7 exists to remove."""
        self.assertIn("validation", TraceEntry.__slots__)
        self.assertNotIn("rejection", TraceEntry.__slots__)
        pre = initial_state()
        self.assertIn("validation", TraceEntry(**self._entry_kwargs(pre)).canonical())


if __name__ == "__main__":
    unittest.main()
