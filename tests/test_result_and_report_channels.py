"""Planner result trio and the three typed report channels.

Supervisor :120-129 (PlanFound / NoPlan / PlannerFailure) and :131-163 (ExecutionDiscrepancy /
TrackDivergence / InfrastructureFault). The project rule forbids conflating either trio.
"""
import unittest

from domain.box_push_v1 import AGENT_0, BOX_LIGHT, DELIVERY_ZONE, MODEL_VERSION
from shared.comparison_keys import WorldKey
from shared.discrepancy import DiscrepancyKind, ExecutionDiscrepancy
from shared.divergence import DivergenceKind, TrackDivergence
from shared.faults import FaultKind, InfrastructureFault
from shared.planner_result import NoPlan, PlanFound, PlannerFailure, PlannerResult
from shared.reports import ConfidenceReport, CoverageReport
from shared.skills import GroundedSkillCall, SkillName


def _call():
    return GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE)


class TestPlannerResultTrio(unittest.TestCase):
    def test_three_results_are_distinct_types(self):
        found = PlanFound(plan=(_call(),))
        none = NoPlan(reason="goal unreachable in the abstraction")
        fail = PlannerFailure(error="search timed out", timed_out=True)
        for r in (found, none, fail):
            self.assertIsInstance(r, PlannerResult)
        self.assertNotIsInstance(none, PlannerFailure)
        self.assertNotIsInstance(fail, NoPlan)

    def test_exactly_one_predicate_is_true_per_result(self):
        for r, flags in (
            (PlanFound(plan=()), (True, False, False)),
            (NoPlan(reason="x"), (False, True, False)),
            (PlannerFailure(error="x"), (False, False, True)),
        ):
            with self.subTest(result=type(r).__name__):
                self.assertEqual((r.is_plan, r.is_no_plan, r.is_failure), flags)

    def test_no_plan_is_not_an_infrastructure_fault(self):
        """:128 — NoPlan is a legitimate symbolic result routed to the orchestrator."""
        self.assertFalse(hasattr(NoPlan(reason="x"), "to_infrastructure_fault"))

    def test_planner_failure_becomes_an_infrastructure_fault(self):
        """:129 — PlannerFailure becomes an InfrastructureFault and must never be read as
        evidence the task is symbolically unsolvable."""
        fault = PlannerFailure(error="solver crashed").to_infrastructure_fault()
        self.assertIsInstance(fault, InfrastructureFault)
        self.assertIs(fault.kind, FaultKind.PLANNER_COMPUTATION_FAILURE)
        self.assertTrue(fault.short_circuits_cycle)

    def test_no_plan_requires_a_reason(self):
        with self.assertRaises(ValueError):
            NoPlan(reason="")

    def test_planner_failure_requires_an_error(self):
        with self.assertRaises(ValueError):
            PlannerFailure(error="")

    def test_planner_failure_carries_its_error_into_the_fault(self):
        """`to_infrastructure_fault()` is the only bridge from a planner result to the fault
        channel; dropping the error text there loses the only diagnosis the orchestrator gets."""
        fault = PlannerFailure(error="solver segfaulted", timed_out=True).to_infrastructure_fault()
        self.assertIn("solver segfaulted", fault.message)

    def test_plan_cost_sums_skill_costs(self):
        plan = PlanFound(plan=(_call(), _call()), model_version=MODEL_VERSION)
        self.assertEqual(plan.length, 2)
        self.assertEqual(plan.cost, sum(c.cost for c in plan.plan))

    def test_plan_cost_is_not_plan_length_in_disguise(self):
        """Every V1 skill costs 1, so `cost == length` on any real plan and `sum(c.cost ...)` ->
        `len(self.plan)` survives untouched. `SkillSignature.cost` is an explicit declared knob
        (:104), so temporarily price one skill above 1 and require the two to diverge.

        A locally-built registry is not enough: `GroundedSkillCall.cost` resolves through the
        module-level `REGISTRY`, so the substitution has to happen there.
        """
        from unittest import mock

        from shared.skills import REGISTRY, SkillSignature
        base = REGISTRY.get(SkillName.PUSH)
        pricey = SkillSignature(
            name=base.name, parameters=base.parameters, cost=3,
            in_symbolic_action_set=base.in_symbolic_action_set,
            backend_mapping=base.backend_mapping,
            backend_dispatch_key=base.backend_dispatch_key,
        )
        with mock.patch.dict(REGISTRY._by_name, {SkillName.PUSH: pricey}):
            plan = PlanFound(plan=(_call(), _call()), model_version=MODEL_VERSION)
            self.assertEqual(plan.length, 2)
            self.assertEqual(plan.cost, 6)
            self.assertNotEqual(plan.cost, plan.length)
        # and the substitution is undone
        self.assertEqual(REGISTRY.get(SkillName.PUSH).cost, 1)


class TestThreeReportChannels(unittest.TestCase):
    def test_channels_are_distinct_types(self):
        d = ExecutionDiscrepancy(
            kind=DiscrepancyKind.EXECUTION_FAILURE_OF_APPLICABLE_SKILL, call=_call()
        )
        t = TrackDivergence(kind=DivergenceKind.COVERAGE_GAP)
        f = InfrastructureFault(kind=FaultKind.MISSING_GROUNDING, message="unknown box")
        self.assertNotIsInstance(d, type(t))
        self.assertNotIsInstance(t, type(f))
        self.assertNotIsInstance(f, type(d))

    def test_channel_tags_are_distinct(self):
        tags = {
            ExecutionDiscrepancy(
                kind=DiscrepancyKind.UNEXPECTED_OUTCOME, call=_call()
            ).canonical()["channel"],
            TrackDivergence(kind=DivergenceKind.CONTRADICTION).canonical()["channel"],
            InfrastructureFault(
                kind=FaultKind.BACKEND_API_EXCEPTION, message="boom"
            ).canonical()["channel"],
        }
        self.assertEqual(
            tags, {"ExecutionDiscrepancy", "TrackDivergence", "InfrastructureFault"}
        )

    def test_discrepancy_kinds_cover_the_contract_list(self):
        self.assertEqual(
            {k.value for k in DiscrepancyKind},
            {
                "unexpected_outcome",
                "state_effect_mismatch",
                "execution_failure_of_applicable_skill",
                "duration_anomaly",
            },
        )

    def test_divergence_kinds_cover_the_contract_list(self):
        self.assertEqual(
            {k.value for k in DivergenceKind},
            {
                "contradiction",
                "coverage_gap",
                "translation_residual",
                "confidence_mismatch",
                "benign_abstraction_mismatch",
            },
        )

    def test_fault_kinds_cover_the_contract_list(self):
        for expected in (
            "malformed_backend_result",
            "serialization_failure",
            "backend_api_exception",
            "missing_grounding",
            "executor_monitor_protocol_failure",
            "planner_computation_failure",
        ):
            with self.subTest(kind=expected):
                self.assertIn(expected, {k.value for k in FaultKind})

    def test_state_effect_mismatch_requires_both_keys(self):
        with self.assertRaises(ValueError):
            ExecutionDiscrepancy(
                kind=DiscrepancyKind.STATE_EFFECT_MISMATCH,
                call=_call(),
                predicted_world_key=WorldKey("abc"),
            )

    def test_every_fault_short_circuits_the_cycle(self):
        """:163 admits no exceptions."""
        for kind in FaultKind:
            with self.subTest(kind=kind):
                self.assertTrue(
                    InfrastructureFault(kind=kind, message="x").short_circuits_cycle
                )


class TestReports(unittest.TestCase):
    def test_coverage_residual_drives_completeness(self):
        complete = CoverageReport(covered=("deliver box_1",))
        lossy = CoverageReport(covered=("deliver box_1",), residual=("as fast as possible",))
        self.assertTrue(complete.is_complete)
        self.assertFalse(lossy.is_complete)
        self.assertEqual(lossy.coverage_ratio, 0.5)

    def test_empty_coverage_is_complete(self):
        self.assertTrue(CoverageReport().is_complete)
        self.assertEqual(CoverageReport().coverage_ratio, 1.0)

    def test_confidence_bounds_enforced(self):
        ConfidenceReport(source="symbolic", confidence=0.0)
        ConfidenceReport(source="nl", confidence=1.0)
        with self.assertRaises(ValueError):
            ConfidenceReport(source="nl", confidence=1.5)

    def test_confidence_source_restricted(self):
        with self.assertRaises(ValueError):
            ConfidenceReport(source="backend", confidence=0.5)


if __name__ == "__main__":
    unittest.main()
