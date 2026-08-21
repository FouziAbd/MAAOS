"""P2 acceptance: the symbolic track against the LIVE backend through the P1 adapter.

The supervisor's P2 deliverables, each proven here on the real environment:

  - successful transitions match predictions (BOTH bases — the audit's W-2 obligation landed);
  - a symbolically applicable skill failing in the backend produces a typed
    `ExecutionDiscrepancy` (the flagship: executing the recorded optimistic plan literally);
  - plans use the executive vocabulary (the plan steps ARE the calls the adapter executes);
  - no hidden feasibility oracle (the plan is chosen blind to geometry, and the failures below
    are the designed consequence, observed and reported — never prevented by strengthening).

Offline and deterministic: the backend is local and seed-inert; no LM, no network, no render.
"""
import os
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
from shared.execution import ExecutionOutcome
from shared.planner_result import PlanFound
from shared.skills import GroundedSkillCall, SkillName, SymbolicallyInapplicable, ValidatedCall
from shared.symbolic_state import GroundedLiteral
from symbolic import (
    ExactSymbolicBelief,
    Universe,
    evaluate,
    monitor_execution,
    plan,
    predict_world_candidates,
)

GOAL = frozenset(
    GroundedLiteral("delivered", (str(b),)) for b in TASK_DELIVER_BOTH.goal_delivered
)


class _SymbolicHarness:
    """The minimal plan→validate→execute→sync→record→monitor cycle, scripted for acceptance.

    This is TEST scaffolding, not the P4 orchestrator: no policy, no budgets, no fault handling —
    just the wiring every P2 deliverable needs exercised in order.
    """

    def __init__(self):
        self.adapter = BoxPushV1Adapter()
        snapshot = self.adapter.reset()
        self.belief = ExactSymbolicBelief(DOMAIN_IR, PROJECTION, project)
        self.belief.sync(snapshot)
        self.universe = Universe.from_snapshot(snapshot, DELIVERY_ZONE)

    def plan(self, goal=GOAL):
        return plan(DOMAIN_IR, self.belief.state, goal, self.universe, MODEL_VERSION)

    def execute(self, call):
        verdict = evaluate(DOMAIN_IR, self.belief.state, call)
        pre_symbolic = self.belief.state
        result = self.adapter.execute_skill(call)
        self.belief.sync(self.adapter.export_full_state())
        self.belief.record_outcome(result)
        discrepancies = monitor_execution(
            DOMAIN_IR, PROJECTION, project, pre_symbolic, result, DELIVERY_ZONE, MODEL_VERSION
        )
        return verdict, result, discrepancies


def _teleport(adapter, agent_id, position, direction):
    env = adapter._env
    agent = env.core_env.world.agents[agent_id]
    env.core_env.grid.set(*agent.position, None)
    agent.position = tuple(position)
    agent.direction = int(direction)
    env.agent_positions[agent_id] = tuple(position)
    env.agent_dirs[agent_id] = int(direction)
    env.agent_objects[agent_id].dir = int(direction)
    env.core_env.grid.set(*position, env.agent_objects[agent_id])
    adapter._obs = env._get_all_observations()


class TestSuccessfulTransitionsMatchPredictions(unittest.TestCase):
    """Supervisor deliverable + the consistency audit's W-2 obligation: for every symbolic
    skill, a real successful execution agrees with BOTH prediction bases — zero discrepancies."""

    def test_goto_push_and_coop_all_match_both_bases(self):
        harness = _SymbolicHarness()
        # goto+push here; CooperativePush has its own set-membership test below, and the
        # flagship covers the full plan (all three skills) with accumulated-discrepancy checks.
        script = (
            GroundedSkillCall(SkillName.GOTO_PUSH_POSE, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE),
            GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE),
        )
        for call in script:
            with self.subTest(call=str(call)):
                verdict, result, discrepancies = harness.execute(call)
                self.assertIsInstance(verdict, ValidatedCall)
                self.assertIs(result.outcome, ExecutionOutcome.SUCCESS)
                self.assertEqual(discrepancies, ())

    def test_the_world_basis_membership_check_accepts_the_real_coop_roles(self):
        """CooperativePush's set-valued prediction: the backend picks the roles; the observed
        terminal state must match ONE of the two admissible candidates."""
        harness = _SymbolicHarness()
        harness.execute(
            GroundedSkillCall(SkillName.GOTO_PUSH_POSE, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE))
        harness.execute(GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE))
        coop = GroundedSkillCall(
            SkillName.COOPERATIVE_PUSH, (AGENT_0, AGENT_1), BOX_HEAVY, DELIVERY_ZONE)
        pre = harness.adapter.export_full_state()
        candidates = predict_world_candidates(pre, coop, DELIVERY_ZONE)
        self.assertEqual(len(candidates), 2)
        _, result, discrepancies = harness.execute(coop)
        self.assertIs(result.outcome, ExecutionOutcome.SUCCESS)
        self.assertEqual(discrepancies, ())
        self.assertIn(
            result.post_state.world_key(), {c.world_key() for c in candidates}
        )
        # exactly one candidate matched — the other role assignment did not happen
        self.assertEqual(
            sum(result.post_state.world_key() == c.world_key() for c in candidates), 1
        )


class TestOptimisticPlanFailsInBackend(unittest.TestCase):
    """THE required acceptance scenario, as the recorded `.soln` itself predicts: execute the
    optimistic 5-step plan literally. Four steps succeed; the final `Push` is symbolically
    applicable under the (stale, non-exclusive) `in_pose` belief but the agent physically left
    that pose — the backend rejects it, and the monitor reports the typed
    `ExecutionDiscrepancy`. The model is NOT strengthened; a replan from the synced belief then
    completes the goal."""

    def test_the_flagship_plan_execute_monitor_replan_story(self):
        harness = _SymbolicHarness()
        result = harness.plan()
        self.assertIsInstance(result, PlanFound)
        self.assertEqual(result.length, 5)

        outcomes, executions, all_discrepancies = [], [], []
        for call in result.plan:
            verdict, execution, discrepancies = harness.execute(call)
            self.assertIsInstance(
                verdict, ValidatedCall,
                f"{call}: the plan step must be symbolically applicable when reached",
            )
            outcomes.append(execution.outcome)
            executions.append(execution)
            all_discrepancies.extend(discrepancies)

        # four successes, then the designed failure on the final Push
        self.assertEqual(outcomes[:4], [ExecutionOutcome.SUCCESS] * 4)
        self.assertIsNot(outcomes[4], ExecutionOutcome.SUCCESS)
        # the acceptance-record rule: classification + step consumption at THIS boundary too
        self.assertIsNotNone(executions[4].failure_class)
        self.assertEqual(executions[4].accounting.executive_steps, 1)
        self.assertIn(str(executions[4].failure_class), all_discrepancies[0].message
                      if all_discrepancies else "")
        kinds = [d.kind for d in all_discrepancies]
        self.assertEqual(
            kinds, [DiscrepancyKind.EXECUTION_FAILURE_OF_APPLICABLE_SKILL],
            "exactly one discrepancy: the applicable-but-infeasible final push",
        )
        self.assertIs(all_discrepancies[0].call.skill, SkillName.PUSH)
        self.assertEqual(all_discrepancies[0].comparison_bases, ())       # clause 7

        # goal incomplete: the light box is still pending
        self.assertFalse(harness.adapter.export_full_state().box(BOX_LIGHT).delivered)
        self.assertTrue(harness.adapter.export_full_state().box(BOX_HEAVY).delivered)

        # REPLAN from the synced belief. The frozen consuming-skill rule means the failed Push
        # retracted NOTHING: the stale in_pose(agent_0, box_1) is still believed, so the replan
        # is a bare [Push] — which fails again. This is the repeated-failure signature that
        # :118's bookkeeping (P4) exists to catch; the symbolic model alone cannot escape it,
        # BY DESIGN (retention is frozen; the model is never silently strengthened).
        self.assertTrue(harness.belief.state.holds(
            GroundedLiteral("in_pose", ("agent_0", "box_1"))
        ))
        replan = harness.plan()
        self.assertIsInstance(replan, PlanFound)
        self.assertEqual([c.skill for c in replan.plan], [SkillName.PUSH])
        _, second_attempt, second_discrepancies = harness.execute(replan.plan[0])
        self.assertIsNot(second_attempt.outcome, ExecutionOutcome.SUCCESS)
        self.assertEqual(
            [d.kind for d in second_discrepancies],
            [DiscrepancyKind.EXECUTION_FAILURE_OF_APPLICABLE_SKILL],
        )
        self.assertEqual(second_attempt.call.key(), all_discrepancies[0].call.key())
        self.assertTrue(harness.belief.state.holds(          # ...and STILL retained
            GroundedLiteral("in_pose", ("agent_0", "box_1"))
        ))

        # RECOVERY is re-establishment, not model surgery: a fresh goto re-earns the literal
        # honestly, and the goal completes with no further discrepancy.
        recovery = GroundedSkillCall(
            SkillName.GOTO_PUSH_POSE, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE)
        _, goto_result, goto_discrepancies = harness.execute(recovery)
        self.assertIs(goto_result.outcome, ExecutionOutcome.SUCCESS)
        self.assertEqual(goto_discrepancies, ())
        final = harness.plan()
        self.assertEqual([c.skill for c in final.plan], [SkillName.PUSH])
        _, push_result, push_discrepancies = harness.execute(final.plan[0])
        self.assertIs(push_result.outcome, ExecutionOutcome.SUCCESS)
        self.assertEqual(push_discrepancies, ())
        self.assertTrue(harness.adapter.is_terminal())

    def test_the_model_was_not_silently_strengthened_by_the_failure(self):
        """The IR object survives the story unmutated (digest + preconditions). This catches
        RUNTIME mutation only — strengthening via new code paths is what the static guards and
        the flagship's demanded 5th-step failure defend against."""
        harness = _SymbolicHarness()
        digest_before = DOMAIN_IR.digest()
        for call in harness.plan().plan:
            harness.execute(call)
        self.assertEqual(DOMAIN_IR.digest(), digest_before)
        self.assertEqual(
            {str(p.name) for p in DOMAIN_IR.skill(SkillName.PUSH).preconditions},
            {"in_pose", "light", "pending"},
        )


class TestScenarioTwoRevalidatedAgainstTheAdapter(unittest.TestCase):
    """§18 item 1 / obligation-4 consequence: the goto→blocked navigation discrepancy remains
    REACHABLE under the exact entities view — re-validated live, as the P0 decisions require."""

    def test_applicable_goto_blocked_by_occupied_pose_is_a_discrepancy(self):
        harness = _SymbolicHarness()
        _teleport(harness.adapter, "agent_1", (9, 4), 2)       # partner parked ON the pose
        harness.belief.sync(harness.adapter.export_full_state())
        call = GroundedSkillCall(SkillName.GOTO_PUSH_POSE, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE)
        verdict, result, discrepancies = harness.execute(call)
        self.assertIsInstance(verdict, ValidatedCall)          # symbolically applicable...
        self.assertIsNot(result.outcome, ExecutionOutcome.SUCCESS)   # ...backend-infeasible
        (discrepancy,) = discrepancies
        self.assertIs(discrepancy.kind, DiscrepancyKind.EXECUTION_FAILURE_OF_APPLICABLE_SKILL)

    def test_stale_in_pose_wrong_box_push_is_a_discrepancy(self):
        """The non-exclusive-in_pose case end-to-end: a REAL goto establishes in_pose(a0,box_1);
        the world then moves the agent behind the heavy box; the belief retains the literal (by
        design), Push stays applicable, the backend refuses, the monitor reports."""
        harness = _SymbolicHarness()
        goto = GroundedSkillCall(SkillName.GOTO_PUSH_POSE, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE)
        _, result, _ = harness.execute(goto)
        self.assertIs(result.outcome, ExecutionOutcome.SUCCESS)
        _teleport(harness.adapter, "agent_0", (7, 6), 2)       # now behind heavy box_0
        harness.belief.sync(harness.adapter.export_full_state())
        push = GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE)
        verdict, result, discrepancies = harness.execute(push)
        self.assertIsInstance(verdict, ValidatedCall)          # stale in_pose kept it applicable
        self.assertIs(result.outcome, ExecutionOutcome.FAILURE)
        (discrepancy,) = discrepancies
        self.assertIs(discrepancy.kind, DiscrepancyKind.EXECUTION_FAILURE_OF_APPLICABLE_SKILL)
        self.assertIn("too_heavy", discrepancy.message)        # the raw provenance travels

    def test_inapplicable_calls_are_rejected_before_the_backend(self):
        """Demonstrates the SYMBOLIC verdict path: inapplicability is decided from literals with
        the backend untouched. (The GATING — refusing to execute on this verdict — is P4's loop;
        this test's own choice not to execute stands in for it, and the step_count assertion
        documents that evaluating consulted nothing.)"""
        harness = _SymbolicHarness()
        push = GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE)
        verdict = evaluate(DOMAIN_IR, harness.belief.state, push)
        self.assertIsInstance(verdict, SymbolicallyInapplicable)
        self.assertEqual(
            harness.adapter.export_full_state().episode.step_count, 0
        )                                                       # nothing was executed


if __name__ == "__main__":
    unittest.main()
