"""P2 unit tests: applicability, belief, planner, predictor, monitor — plus the static guards
that keep the symbolic side structurally unable to become a feasibility oracle.

Everything here is offline and steps nothing: pure literal/state manipulation. The live-backend
acceptance suite is `tests/test_p2_acceptance.py`.
"""
import ast
import pathlib
import unittest

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
    TASK_DELIVER_LIGHT,
    initial_state,
    project,
)
from shared.discrepancy import ComparisonBasis, DiscrepancyKind
from shared.execution import (
    ExecutionOutcome,
    ExecutionResult,
    FailureStateClass,
    RawLabel,
    StepAccounting,
)
from shared.planner_result import NoPlan, PlanFound, PlannerFailure
from shared.skills import (
    GroundedSkillCall,
    OutsideSymbolicModel,
    SkillName,
    SymbolicallyInapplicable,
    ValidatedCall,
)
from shared.state_snapshot import AgentSnapshot, BoxSnapshot
from shared.symbolic_state import GroundedLiteral, SymbolicState
from symbolic import (
    ExactSymbolicBelief,
    Universe,
    apply_effects,
    evaluate,
    first_zone_cell_along,
    ground_calls,
    monitor_execution,
    noplan_instance,
    plan,
    predict_symbolic,
    predict_world_candidates,
    push_dir,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

GOTO = GroundedSkillCall(SkillName.GOTO_PUSH_POSE, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE)
PUSH = GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE)
COOP = GroundedSkillCall(
    SkillName.COOPERATIVE_PUSH, (AGENT_0, AGENT_1), BOX_HEAVY, DELIVERY_ZONE
)
IN_POSE_A0_B1 = GroundedLiteral("in_pose", ("agent_0", "box_1"))

GOAL_BOTH = frozenset(
    GroundedLiteral("delivered", (str(b),)) for b in TASK_DELIVER_BOTH.goal_delivered
)
UNIVERSE = Universe.from_snapshot(initial_state(), DELIVERY_ZONE)


def _fresh_belief() -> ExactSymbolicBelief:
    belief = ExactSymbolicBelief(DOMAIN_IR, PROJECTION, project)
    belief.sync(initial_state())
    return belief


def _result(call, outcome, pre, post, failure_class=None, raw=None):
    return ExecutionResult(
        call=call, outcome=outcome, pre_state=pre, post_state=post,
        accounting=StepAccounting(1, 3), raw_label=raw, failure_class=failure_class,
    )


def _moved(state=None):
    s = state or initial_state()
    b = s.box(BOX_LIGHT)
    return s.with_box(BoxSnapshot(b.box_id, (5, 4), b.required_agents, b.is_target, b.delivered))


# ── Applicability ──────────────────────────────────────────────────────────────────

class TestApplicability(unittest.TestCase):
    def test_goto_is_applicable_from_the_initial_projection(self):
        verdict = evaluate(DOMAIN_IR, project(initial_state()), GOTO)
        self.assertIsInstance(verdict, ValidatedCall)

    def test_push_without_in_pose_is_symbolically_inapplicable(self):
        verdict = evaluate(DOMAIN_IR, project(initial_state()), PUSH)
        self.assertIsInstance(verdict, SymbolicallyInapplicable)
        self.assertIn("in_pose(agent_0,box_1)", verdict.unsatisfied)
        self.assertFalse(verdict.is_infrastructure_fault)     # a SYMBOLIC result (Decision 7)

    def test_push_on_the_heavy_box_fails_the_light_guard(self):
        state = SymbolicState.of(
            project(initial_state()).literals
            | {GroundedLiteral("in_pose", ("agent_0", "box_0"))}
        )
        call = GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BOX_HEAVY, DELIVERY_ZONE)
        verdict = evaluate(DOMAIN_IR, state, call)
        self.assertIsInstance(verdict, SymbolicallyInapplicable)
        self.assertIn("light(box_0)", verdict.unsatisfied)

    def test_unsatisfied_lists_every_failing_precondition(self):
        """Mutation X4: truncating the list to one entry survived — both existing cases happened
        to fail exactly one literal. Push on the HEAVY box with no pose fails two."""
        call = GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BOX_HEAVY, DELIVERY_ZONE)
        verdict = evaluate(DOMAIN_IR, project(initial_state()), call)
        self.assertIsInstance(verdict, SymbolicallyInapplicable)
        self.assertGreaterEqual(len(verdict.unsatisfied), 2)
        self.assertIn("in_pose(agent_0,box_0)", verdict.unsatisfied)
        self.assertIn("light(box_0)", verdict.unsatisfied)

    def test_registry_only_skills_resolve_to_outside_symbolic_model(self):
        for name in (SkillName.EXPLORE, SkillName.WAIT):
            with self.subTest(skill=name):
                call = GroundedSkillCall(name, (AGENT_0,))
                verdict = evaluate(DOMAIN_IR, project(initial_state()), call)
                self.assertIsInstance(verdict, OutsideSymbolicModel)
                self.assertTrue(verdict.is_executable)

    def test_geometry_cannot_reach_applicability(self):
        """Two snapshots differing only in geometry PROJECT identically — so applicability,
        which consumes only the projection, cannot depend on geometry. The key equality IS the
        proof (a value-equal input to a pure function settles the rest); the deeper defenses are
        the import guards and the flagship's demanded optimistic failure."""
        self.assertEqual(project(initial_state()).key(), project(_moved()).key())


class TestApplyEffects(unittest.TestCase):
    def test_goto_adds_in_pose_and_deletes_nothing(self):
        before = project(initial_state())
        after = apply_effects(before, DOMAIN_IR.skill(SkillName.GOTO_PUSH_POSE), GOTO)
        self.assertTrue(after.holds(IN_POSE_A0_B1))
        self.assertEqual(before.literals - after.literals, frozenset())   # non-exclusive

    def test_push_delivers_and_consumes(self):
        before = SymbolicState.of(project(initial_state()).literals | {IN_POSE_A0_B1})
        after = apply_effects(before, DOMAIN_IR.skill(SkillName.PUSH), PUSH)
        self.assertTrue(after.holds(GroundedLiteral("delivered", ("box_1",))))
        self.assertFalse(after.holds(GroundedLiteral("pending", ("box_1",))))
        self.assertFalse(after.holds(IN_POSE_A0_B1))

    def test_effects_share_one_implementation_with_the_planner(self):
        """The planner's successor and the predictor's symbolic prediction are the SAME function,
        by identity — they cannot drift apart."""
        import symbolic.planner as planner_module
        import symbolic.predictor as predictor_module
        self.assertIs(planner_module.apply_effects, predictor_module.apply_effects)


# ── Belief ─────────────────────────────────────────────────────────────────────────

class TestExactSymbolicBelief(unittest.TestCase):
    def test_projected_part_is_exact_from_the_snapshot(self):
        belief = _fresh_belief()
        self.assertEqual(
            PROJECTION.monitored_key(belief.state),
            PROJECTION.monitored_key(project(initial_state())),
        )

    def test_sync_before_use_is_required(self):
        with self.assertRaises(RuntimeError):
            ExactSymbolicBelief(DOMAIN_IR, PROJECTION, project).state

    def test_tracked_in_pose_survives_a_sync(self):
        """The DESIGNED optimism: a stale `in_pose` persists through world resyncs until an
        execution outcome disturbs it — there is no world counterpart to re-derive it from."""
        belief = _fresh_belief()
        belief.establish(IN_POSE_A0_B1)
        belief.sync(_moved())                                  # world moved; sync happened
        self.assertTrue(belief.state.holds(IN_POSE_A0_B1))     # still believed

    def test_goto_success_establishes_the_literal(self):
        belief = _fresh_belief()
        pre = initial_state()
        belief.record_outcome(_result(GOTO, ExecutionOutcome.SUCCESS, pre, _moved()))
        self.assertTrue(belief.state.holds(IN_POSE_A0_B1))

    def test_goto_failure_with_unmoved_world_preserves_prior_truth(self):
        belief = _fresh_belief()
        belief.establish(IN_POSE_A0_B1)
        pre = initial_state()
        belief.record_outcome(_result(
            GOTO, ExecutionOutcome.FAILURE, pre, pre,
            failure_class=FailureStateClass.BACKEND_REJECTED_BEFORE_TRANSITION,
        ))
        self.assertTrue(belief.state.holds(IN_POSE_A0_B1))     # world did not move

    def test_goto_failure_with_moved_world_invalidates_the_attempted_literal(self):
        belief = _fresh_belief()
        belief.establish(IN_POSE_A0_B1)
        pre = initial_state()
        belief.record_outcome(_result(
            GOTO, ExecutionOutcome.PARTIAL, pre, _moved(),
            failure_class=FailureStateClass.PARTIAL_EXECUTION,
        ))
        self.assertFalse(belief.state.holds(IN_POSE_A0_B1))

    def test_push_success_consumes_in_pose(self):
        belief = _fresh_belief()
        belief.establish(IN_POSE_A0_B1)
        pre = initial_state()
        belief.record_outcome(_result(PUSH, ExecutionOutcome.SUCCESS, pre, _moved()))
        self.assertFalse(belief.state.holds(IN_POSE_A0_B1))

    def test_consuming_skill_failure_retracts_nothing(self):
        """The frozen consuming-skill rule: a failed Push keeps its precondition literals."""
        belief = _fresh_belief()
        belief.establish(IN_POSE_A0_B1)
        pre = initial_state()
        belief.record_outcome(_result(
            PUSH, ExecutionOutcome.PARTIAL, pre, _moved(),
            failure_class=FailureStateClass.PARTIAL_EXECUTION, raw=RawLabel.BLOCKED,
        ))
        self.assertTrue(belief.state.holds(IN_POSE_A0_B1))

    def test_coop_success_consumes_both_in_pose_literals(self):
        belief = _fresh_belief()
        a0 = GroundedLiteral("in_pose", ("agent_0", "box_0"))
        a1 = GroundedLiteral("in_pose", ("agent_1", "box_0"))
        belief.establish(a0)
        belief.establish(a1)
        pre = initial_state()
        belief.record_outcome(_result(COOP, ExecutionOutcome.SUCCESS, pre, _moved()))
        self.assertFalse(belief.state.holds(a0))
        self.assertFalse(belief.state.holds(a1))

    def test_outside_model_outcomes_touch_nothing(self):
        belief = _fresh_belief()
        belief.establish(IN_POSE_A0_B1)
        pre = initial_state()
        wait = GroundedSkillCall(SkillName.WAIT, (AGENT_0,))
        belief.record_outcome(_result(wait, ExecutionOutcome.SUCCESS, pre, pre))
        self.assertTrue(belief.state.holds(IN_POSE_A0_B1))

    def test_projectable_predicates_are_never_patched_from_outcomes(self):
        """delivered/pending come only from sync — a success recorded WITHOUT a sync leaves the
        projected part untouched (the belief never believes its own predictions)."""
        belief = _fresh_belief()
        belief.establish(IN_POSE_A0_B1)
        pre = initial_state()
        belief.record_outcome(_result(PUSH, ExecutionOutcome.SUCCESS, pre, _moved()))
        self.assertTrue(belief.state.holds(GroundedLiteral("pending", ("box_1",))))


# ── Planner ────────────────────────────────────────────────────────────────────────

class TestPlanner(unittest.TestCase):
    def test_the_frozen_instance_yields_the_recorded_five_step_plan(self):
        result = plan(DOMAIN_IR, project(initial_state()), GOAL_BOTH, UNIVERSE, MODEL_VERSION)
        self.assertIsInstance(result, PlanFound)
        self.assertEqual(
            [f"{c.skill}:{c.key()}" for c in result.plan],
            [f"{c.skill}:{c.key()}" for c in plan(
                DOMAIN_IR, project(initial_state()), GOAL_BOTH, UNIVERSE, MODEL_VERSION
            ).plan],
        )                                                       # deterministic
        self.assertEqual(result.length, 5)
        self.assertEqual(result.model_version, MODEL_VERSION)

    def test_plans_use_the_executive_vocabulary(self):
        """Supervisor P2 deliverable: the plan IS GroundedSkillCalls — nothing to translate."""
        result = plan(DOMAIN_IR, project(initial_state()), GOAL_BOTH, UNIVERSE)
        for call in result.plan:
            self.assertIsInstance(call, GroundedSkillCall)
            self.assertIn(call.skill, DOMAIN_IR.action_set())

    def test_the_plan_simulates_to_the_goal(self):
        result = plan(DOMAIN_IR, project(initial_state()), GOAL_BOTH, UNIVERSE)
        state = project(initial_state())
        for call in result.plan:
            verdict = evaluate(DOMAIN_IR, state, call)
            self.assertIsInstance(verdict, ValidatedCall, f"{call} inapplicable mid-plan")
            state = apply_effects(state, DOMAIN_IR.skill(call.skill), call)
        for literal in GOAL_BOTH:
            self.assertTrue(state.holds(literal))

    def test_the_plan_exhibits_the_designed_non_exclusive_optimism(self):
        """agent_0 is symbolically in pose for BOTH boxes at once mid-plan — §J-3's designed
        abstraction mismatch, now produced by the V1 planner itself and left intact."""
        result = plan(DOMAIN_IR, project(initial_state()), GOAL_BOTH, UNIVERSE)
        gotos = [c for c in result.plan if c.skill is SkillName.GOTO_PUSH_POSE
                 and c.agents[0] == AGENT_0]
        self.assertGreaterEqual(len(gotos), 2)                  # two poses, one agent

    def test_satisfied_goal_yields_an_empty_plan(self):
        state = SymbolicState.of(
            (project(initial_state()).literals
             - {GroundedLiteral("pending", ("box_1",))})
            | {GroundedLiteral("delivered", ("box_1",))}
        )
        goal = frozenset({GroundedLiteral("delivered", ("box_1",))})
        result = plan(DOMAIN_IR, state, goal, UNIVERSE)
        self.assertIsInstance(result, PlanFound)
        self.assertEqual(result.plan, ())

    def test_single_goal_gets_the_two_step_plan(self):
        goal = frozenset(
            GroundedLiteral("delivered", (str(b),)) for b in TASK_DELIVER_LIGHT.goal_delivered
        )
        result = plan(DOMAIN_IR, project(initial_state()), goal, UNIVERSE)
        self.assertEqual([c.skill for c in result.plan],
                         [SkillName.GOTO_PUSH_POSE, SkillName.PUSH])

    def test_synthetic_instance_returns_no_plan(self):
        """Decision 12: the clearly-labelled unsolvable instance exercises NoPlan — a legitimate
        symbolic result, never converted to a fault here."""
        state, goal, universe = noplan_instance()
        result = plan(DOMAIN_IR, state, goal, universe)
        self.assertIsInstance(result, NoPlan)
        self.assertTrue(result.reason)
        self.assertFalse(hasattr(result, "to_infrastructure_fault"))

    def test_node_budget_exhaustion_is_a_planner_failure(self):
        result = plan(DOMAIN_IR, project(initial_state()), GOAL_BOTH, UNIVERSE, node_budget=1)
        self.assertIsInstance(result, PlannerFailure)
        self.assertTrue(result.timed_out)
        self.assertTrue(hasattr(result, "to_infrastructure_fault"))   # runtime converts it

    def test_an_internal_exception_is_a_planner_failure_not_a_crash(self):
        class _Poison:                                          # unhashable-key poison
            def holds(self, _):
                raise RuntimeError("boom")
            literals = property(lambda self: (_ for _ in ()).throw(RuntimeError("boom")))
        result = plan(DOMAIN_IR, _Poison(), GOAL_BOTH, UNIVERSE)
        self.assertIsInstance(result, PlannerFailure)
        self.assertIn("boom", result.error)
        self.assertFalse(result.timed_out)

    def test_grounding_is_exhaustive_and_canonical(self):
        calls = ground_calls(DOMAIN_IR, UNIVERSE)
        self.assertEqual(len(calls), 10)                        # 4 goto + 4 push + 2 coop
        coops = [c for c in calls if c.skill is SkillName.COOPERATIVE_PUSH]
        self.assertEqual(len(coops), 2)                         # pair collapsed canonically
        for c in coops:
            self.assertEqual(c.agents, (AGENT_0, AGENT_1))

    def test_one_agent_universe_grounds_no_cooperative_push(self):
        _, _, universe = noplan_instance()
        calls = ground_calls(DOMAIN_IR, universe)
        self.assertFalse([c for c in calls if c.skill is SkillName.COOPERATIVE_PUSH])


# ── Predictor ──────────────────────────────────────────────────────────────────────

class TestPredictor(unittest.TestCase):
    def test_direction_vector_table_matches_the_backend(self):
        """W-2: the interior-cell sweep below only ever exercises LEFT under the frozen zone
        (the Manhattan-nearest goal cell is always same-row), so the vector TABLE itself needs
        its own pin against the backend constants."""
        import sys
        cst_dir = str(REPO_ROOT / "functional_layer/custom_env/cooperative_search_transport/env")
        if cst_dir not in sys.path:
            sys.path.insert(0, cst_dir)
        from constants import DIRECTION_VECTORS
        import symbolic.predictor as predictor_module
        self.assertEqual(
            predictor_module._DIRECTION_VECTORS,
            {int(d): tuple(v) for d, v in DIRECTION_VECTORS.items()},
        )

    def test_push_dir_matches_the_backend_arithmetic_everywhere(self):
        """The transcription drift-pin: the symbolic `push_dir` equals the backend's
        `_push_dir_toward_goal` on every interior cell. NOTE: under the frozen zone this only
        exercises the LEFT branch (nearest goal cell is always same-row) — the tie and vertical
        branches are pinned by the synthetic-zone tests below, and the vector table by the test
        above."""
        import sys
        env_dir = str(REPO_ROOT / "functional_layer/custom_env/box_push/env")
        if env_dir not in sys.path:
            sys.path.insert(0, env_dir)
        from skill_executor_push import _push_dir_toward_goal
        zone = initial_state().static.delivery_zone
        for x in range(1, 11):
            for y in range(1, 11):
                with self.subTest(cell=(x, y)):
                    self.assertEqual(
                        push_dir((x, y), zone), _push_dir_toward_goal([x, y])
                    )

    def test_push_dir_tie_prefers_horizontal(self):
        """The tie rule ('|dx| >= |dy| and dx != 0 → horizontal') is unreachable against the
        frozen zone (the Manhattan-nearest goal cell is always same-row, dy=0), so the backend
        drift comparison cannot distinguish `>=` from `>`. Pin it on a synthetic zone where the
        tie actually occurs — it is part of the transcription claim."""
        self.assertEqual(push_dir((5, 5), ((7, 7),)), 0)       # dx=2, dy=2 tie → RIGHT
        self.assertEqual(push_dir((9, 5), ((7, 7),)), 2)       # dx=-2, dy=2 tie → LEFT
        self.assertEqual(push_dir((5, 5), ((5, 8),)), 1)       # dx=0 → vertical DOWN

    def test_first_zone_cell_along_finds_the_landing_cell(self):
        zone = initial_state().static.delivery_zone
        self.assertEqual(first_zone_cell_along((8, 4), 2, zone), (1, 4))   # LEFT hits (1,4)

    def test_first_zone_cell_along_takes_the_NEAREST_on_a_multi_cell_ray(self):
        """The frozen zone is a 1-wide column, so a ray never crosses two zone cells and
        'first' was untestable against it (mutation X3: min→max survived). Synthetic zone."""
        self.assertEqual(first_zone_cell_along((5, 5), 0, ((7, 5), (9, 5))), (7, 5))
        self.assertEqual(first_zone_cell_along((10, 5), 2, ((7, 5), (2, 5))), (7, 5))

    def test_first_zone_cell_along_is_partial_by_design(self):
        """§19 D-2: a ray that never crosses the zone has NO landing cell — None, never a guess."""
        zone = initial_state().static.delivery_zone
        self.assertIsNone(first_zone_cell_along((8, 4), 0, zone))          # RIGHT: away
        self.assertIsNone(first_zone_cell_along((8, 4), 3, zone))          # UP: parallel miss

    def test_push_with_a_zone_missing_ray_emits_no_world_prediction(self):
        snap = initial_state()
        turned = snap.__class__(
            agents=(AgentSnapshot(AGENT_0, (8, 5), 3),) + snap.agents[1:],  # facing UP
            boxes=snap.boxes, static=snap.static, episode=snap.episode,
        )
        self.assertEqual(predict_world_candidates(turned, PUSH, DELIVERY_ZONE), ())

    def test_goto_prediction_grounds_the_declared_pose_effect(self):
        candidates = predict_world_candidates(initial_state(), GOTO, DELIVERY_ZONE)
        self.assertEqual(len(candidates), 1)
        agent = candidates[0].agent(AGENT_0)
        self.assertEqual(agent.position, (9, 4))               # box (8,4) - LEFT
        self.assertEqual(agent.direction, 2)
        self.assertEqual(candidates[0].box(BOX_LIGHT), initial_state().box(BOX_LIGHT))  # frame

    def test_push_prediction_grounds_the_terminal_macro_state(self):
        snap = initial_state()
        posed = snap.__class__(
            agents=(AgentSnapshot(AGENT_0, (9, 4), 2),) + snap.agents[1:],
            boxes=snap.boxes, static=snap.static, episode=snap.episode,
        )
        (predicted,) = predict_world_candidates(posed, PUSH, DELIVERY_ZONE)
        self.assertEqual(predicted.box(BOX_LIGHT).position, (1, 4))
        self.assertTrue(predicted.box(BOX_LIGHT).delivered)
        self.assertEqual(predicted.agent(AGENT_0).position, (2, 4))   # box_post - D

    def test_coop_prediction_is_set_valued(self):
        candidates = predict_world_candidates(initial_state(), COOP, DELIVERY_ZONE)
        self.assertEqual(len(candidates), 2)
        for candidate in candidates:
            self.assertEqual(candidate.box(BOX_HEAVY).position, (1, 6))
            self.assertEqual(
                {candidate.agent(AGENT_0).position, candidate.agent(AGENT_1).position},
                {(2, 6), (3, 6)},
            )
        self.assertNotEqual(candidates[0].world_key(), candidates[1].world_key())

    def test_predictions_bind_the_direction_on_a_non_left_zone(self):
        """Mutations X6/X7/X10: every direction in the frozen instance is LEFT, so hardcoding
        `direction = 2` at the goto/coop call sites — or `_with_agent` silently keeping the old
        facing — survived. A snapshot whose zone sits BELOW the boxes forces DOWN everywhere."""
        from shared.state_snapshot import StateSnapshot, StaticWorld
        base = initial_state()
        south_zone = StaticWorld(
            width=12, height=12, walls=base.static.walls,
            delivery_zone=tuple((x, 10) for x in range(1, 11)),
        )
        snap = StateSnapshot(
            agents=base.agents, boxes=base.boxes, static=south_zone, episode=base.episode
        )
        (goto_prediction,) = predict_world_candidates(snap, GOTO, DELIVERY_ZONE)
        agent = goto_prediction.agent(AGENT_0)
        self.assertEqual(agent.direction, 1)                   # DOWN, not the frozen LEFT
        self.assertEqual(agent.position, (8, 3))               # box (8,4) - DOWN = above it
        coop_candidates = predict_world_candidates(snap, COOP, DELIVERY_ZONE)
        self.assertEqual(len(coop_candidates), 2)
        for candidate in coop_candidates:
            self.assertEqual(candidate.box(BOX_HEAVY).position, (6, 10))   # first zone cell DOWN
            self.assertEqual(candidate.agent(AGENT_0).direction, 1)
            self.assertEqual(candidate.agent(AGENT_1).direction, 1)
            self.assertEqual(
                {candidate.agent(AGENT_0).position, candidate.agent(AGENT_1).position},
                {(6, 9), (6, 8)},
            )

    def test_a_zone_identity_mismatch_is_refused_not_silently_predicted(self):
        """W-3: the zone parameter is a CHECKED identity (Decision 11), no longer dead."""
        from shared.ids import ZoneId
        with self.assertRaises(ValueError):
            predict_world_candidates(initial_state(), GOTO, ZoneId("mars"))

    def test_outside_model_skills_have_no_predictions(self):
        for name in (SkillName.EXPLORE, SkillName.WAIT):
            call = GroundedSkillCall(name, (AGENT_0,))
            with self.subTest(skill=name):
                self.assertEqual(predict_world_candidates(initial_state(), call, DELIVERY_ZONE), ())
                self.assertIsNone(predict_symbolic(DOMAIN_IR, project(initial_state()), call))


# ── Monitor (unit level; live in test_p2_acceptance) ──────────────────────────────

class TestMonitorUnit(unittest.TestCase):
    def _monitor(self, pre_symbolic, result):
        return monitor_execution(
            DOMAIN_IR, PROJECTION, project, pre_symbolic, result, DELIVERY_ZONE, MODEL_VERSION
        )

    def test_failure_of_applicable_skill_is_the_designed_signal(self):
        pre = initial_state()
        result = _result(
            PUSH, ExecutionOutcome.FAILURE, pre, pre,
            failure_class=FailureStateClass.UNCHANGED, raw=RawLabel.TOO_HEAVY,
        )
        (discrepancy,) = self._monitor(project(pre), result)
        self.assertIs(discrepancy.kind, DiscrepancyKind.EXECUTION_FAILURE_OF_APPLICABLE_SKILL)
        self.assertEqual(discrepancy.comparison_bases, ())     # clause 7: outcome alone
        self.assertIn("too_heavy", discrepancy.message)        # raw provenance travels
        # ...and so do the classification and authoritative detail (mutation X8): the
        # acceptance-record rule requires the unchanged/partial/rejected class in the report
        self.assertIn("failure_class=unchanged", discrepancy.message)
        self.assertIn("detail=", discrepancy.message)

    def test_success_that_breaks_the_symbolic_declaration_is_a_state_effect_mismatch(self):
        """A SUCCESS whose post-state does not carry the declared delivered flip: the symbolic
        basis catches it with the correctly-typed key pair."""
        pre = initial_state()
        result = _result(PUSH, ExecutionOutcome.SUCCESS, pre, _moved())   # moved, NOT delivered
        discrepancies = self._monitor(
            SymbolicState.of(project(pre).literals | {IN_POSE_A0_B1}), result
        )
        kinds = [d.kind for d in discrepancies]
        self.assertIn(DiscrepancyKind.STATE_EFFECT_MISMATCH, kinds)
        symbolic_hits = [d for d in discrepancies
                         if ComparisonBasis.SYMBOLIC_PROJECTION in d.mismatched_bases]
        self.assertTrue(symbolic_hits)
        hit = symbolic_hits[0]
        # ORIENTATION, both in the keys and in the message — a predicted/observed swap was
        # invisible when only presence was asserted (mutation X1/X2):
        pre_with_pose = SymbolicState.of(project(result.pre_state).literals | {IN_POSE_A0_B1})
        self.assertEqual(
            hit.predicted_symbolic_key,
            PROJECTION.monitored_key(
                predict_symbolic(DOMAIN_IR, pre_with_pose, PUSH)
            ),
        )
        self.assertEqual(
            hit.observed_symbolic_key,
            PROJECTION.monitored_key(project(result.post_state)),
        )
        predicted_part = hit.message.split("observed-only")[0]
        self.assertIn("delivered(box_1)", predicted_part)      # predicted the delivery...
        observed_part = hit.message.split("observed-only")[1]
        self.assertIn("pending(box_1)", observed_part)         # ...observed it still pending

    def test_world_basis_catches_what_the_symbolic_basis_cannot(self):
        """§14.1's story, made concrete: a SUCCESS where the delivered flip happened (symbolic
        basis agrees — its whole vocabulary is satisfied) but the agent did not end one cell
        behind the box. Only the WORLD basis can see it, and the discrepancy must carry the
        typed world-key pair — mutation testing showed a suppressed or key-swapped world check
        was otherwise invisible."""
        pre = initial_state().__class__(
            agents=(AgentSnapshot(AGENT_0, (9, 4), 2),) + initial_state().agents[1:],
            boxes=initial_state().boxes,
            static=initial_state().static, episode=initial_state().episode,
        )
        delivered = pre.with_box(
            BoxSnapshot(BOX_LIGHT, (1, 4), 1, True, True)
        )                                        # box delivered; agent STILL at (9,4) — wrong
        result = _result(PUSH, ExecutionOutcome.SUCCESS, pre, delivered)
        discrepancies = self._monitor(
            SymbolicState.of(project(pre).literals | {IN_POSE_A0_B1}), result
        )
        world_hits = [d for d in discrepancies
                      if ComparisonBasis.WORLD_STATE in d.mismatched_bases]
        self.assertEqual(len(world_hits), 1)
        hit = world_hits[0]
        self.assertIs(hit.kind, DiscrepancyKind.STATE_EFFECT_MISMATCH)
        self.assertIsNotNone(hit.predicted_world_key)
        self.assertIsNotNone(hit.observed_world_key)
        self.assertNotEqual(hit.predicted_world_key, hit.observed_world_key)
        self.assertIsNone(hit.predicted_symbolic_key)    # the symbolic basis AGREED
        symbolic_hits = [d for d in discrepancies
                         if ComparisonBasis.SYMBOLIC_PROJECTION in d.mismatched_bases]
        self.assertEqual(symbolic_hits, [])

    def test_registry_only_failure_is_unexpected_outcome_never_state_mismatch(self):
        pre = initial_state()
        wait = GroundedSkillCall(SkillName.WAIT, (AGENT_0,))
        result = _result(
            wait, ExecutionOutcome.FAILURE, pre, pre,
            failure_class=FailureStateClass.UNCHANGED,
        )
        (discrepancy,) = self._monitor(project(pre), result)
        self.assertIs(discrepancy.kind, DiscrepancyKind.UNEXPECTED_OUTCOME)
        self.assertIn("Wait", discrepancy.message)             # which skill (mutation X9)
        self.assertIn("failure", discrepancy.message)          # and what it did

    def test_registry_only_success_reports_nothing(self):
        pre = initial_state()
        wait = GroundedSkillCall(SkillName.WAIT, (AGENT_0,))
        self.assertEqual(
            self._monitor(project(pre), _result(wait, ExecutionOutcome.SUCCESS, pre, pre)), ()
        )


# ── Static guards (Decision 13 clause 9 / §18 item 6) ─────────────────────────────

def _imports_of(path: pathlib.Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


class TestSymbolicSideGuards(unittest.TestCase):
    def test_the_package_is_discovered_by_the_fail_closed_backend_guard(self):
        """`symbolic/` was covered the day it was created — the guard discovers packages."""
        from tests.test_no_backend_imports import discovered_guarded_packages
        self.assertIn("symbolic", discovered_guarded_packages())

    def test_applicability_belief_and_planner_cannot_reach_the_predictor_or_monitor(self):
        """Decision 13 clause 9: a predictor consulted before choosing IS the forbidden oracle,
        however innocent each part.

        FIVE escape routes closed, not one: direct module imports, ImportFrom ALIAS names
        (`from symbolic.predictor import X`, `from symbolic import X`, and
        `from symbolic import predictor` — the module itself as the alias, and
        `from symbolic import *` — any ImportFrom on the bare package), and the package-root
        import itself (`import symbolic` inside plan() reaches the predictor through the
        package re-exports at runtime, after __init__ has fully initialized — review
        demonstrated that evasion passing the previous guard)."""
        forbidden_names = {
            "predict_world_candidates", "predict_symbolic", "push_dir",
            "first_zone_cell_along", "monitor_execution",
        }
        for module in ("applicability", "belief", "planner", "synthetic"):
            path = REPO_ROOT / "symbolic" / f"{module}.py"
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        with self.subTest(module=module, imported=alias.name):
                            self.assertNotEqual(
                                alias.name, "symbolic",
                                "the bare package-root import reaches the predictor via the "
                                "package re-exports",
                            )
                            self.assertNotIn("predictor", alias.name)
                            self.assertNotIn("monitor", alias.name)
                elif isinstance(node, ast.ImportFrom):
                    source = node.module or ""
                    with self.subTest(module=module, imported=source):
                        self.assertNotIn("predictor", source)
                        self.assertNotIn("monitor", source)
                        # the fifth route: ANY ImportFrom on the bare package
                        # (`from symbolic import *` slips every name check — the alias is
                        # literally "*") reaches the predictor via the package re-exports,
                        # same as the bare package-root import
                        self.assertNotEqual(
                            source, "symbolic",
                            "importing from the package root reaches the predictor via "
                            "the __init__ re-exports",
                        )
                    for alias in node.names:
                        with self.subTest(module=module, name=alias.name):
                            self.assertNotIn(alias.name, forbidden_names)
                            # the fourth route: importing the forbidden MODULE as a name
                            # (`from symbolic import predictor as _p`) — the alias is a
                            # module object, not a function, so the name set misses it
                            self.assertNotIn("predictor", alias.name)
                            self.assertNotIn("monitor", alias.name)

    def test_predictor_inputs_are_bounded(self):
        """Clause 9's input bound, enforced on the AST: the predictor may read positions,
        directions, delivered/required_agents and the zone — never walls, never grid bounds,
        never any occupancy machinery."""
        tree = ast.parse((REPO_ROOT / "symbolic" / "predictor.py").read_text(encoding="utf-8"))
        attributes = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for forbidden in ("walls", "width", "height"):
            with self.subTest(attribute=forbidden):
                self.assertNotIn(forbidden, attributes)
        # Identifier-level, not prose: the docstrings legitimately DISCUSS occupancy and
        # feasibility in order to forbid them (the P1 review already caught a prose scan
        # tripping on exactly that). Names and attributes are what code can act on.
        identifiers = {n.id.lower() for n in ast.walk(tree) if isinstance(n, ast.Name)}
        identifiers |= {a.lower() for a in attributes}
        for token in ("bfs", "reachab", "occupan", "collision", "feasib", "path", "search"):
            with self.subTest(token=token):
                self.assertFalse(
                    [i for i in identifiers if token in i],
                    f"predictor code names an identifier containing {token!r}",
                )

    def test_no_symbolic_module_imports_the_backend_or_runtime(self):
        """Redundant with the package-level guard, but cheap and local."""
        for path in sorted((REPO_ROOT / "symbolic").glob("*.py")):
            for imported in _imports_of(path):
                root = imported.split(".")[0]
                with self.subTest(module=path.name, imported=imported):
                    self.assertNotIn(root, (
                        "functional_layer", "skill_executor_push", "shared_skills",
                        "multi_agent_box_push_env", "box_push_env", "runtime",
                        "minigrid", "pettingzoo", "numpy",
                    ))


if __name__ == "__main__":
    unittest.main()
